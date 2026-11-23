"""Journey planner: from a point, stop, station or town to another, by walking and by every operator's services.

How it works
  * Every operator's timetable is read once into memory (class Net): trips with the same stops are grouped into
    patterns, and each pattern keeps its departure and arrival times in columns, so "the first trip after 08:15 at this
    stop" is a binary search.
  * A journey is found with RAPTOR (Delling, Pajor, Werneck): rounds of "ride one more vehicle", each round scanning only
    the patterns that serve a stop improved in the previous one. It gives the fastest journey for 1, 2, 3... vehicles.
  * Searching backwards in time (arrive by) is the same search over a mirrored copy of the timetable.
  * Walking: the stops worth walking to, from the start and to the end, are timed by the walking router (walk.py,
    Valhalla); changes between stops are first estimated from the straight line and then checked with the router.
    A change that turns out too tight is forbidden and the search runs again.
  * "Now" uses the live data the rest of the application uses (delays, cancellations, skipped stops, Lurraldebus
    arrivals); a chosen date and time uses the published timetables only.
Only the Python standard library is used.
"""
import array
import bisect
import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import core
import walk
from store import TZ, service_midnight

log = logging.getLogger("mugitu.planner")

INF = 1 << 60
BUF = 60                # seconds needed to change vehicle at the same stop
XFER_M = 450            # a change of stop on foot is considered up to this straight-line distance
XFER_BASE = 25          # seconds added to every walk between two stops
XFER_K = 1.15           # seconds per metre of straight line between two stops (measured: real walks are 1.26x the
                        # straight line on median, 2x at the 90th percentile; the router checks the ones that are used)
MAX_ROUNDS = 5          # up to four changes
HORIZON = 12 * 3600     # the search never looks further than this past the start (or before the deadline)
CELL_LAT, CELL_LON, COS = 0.0054, 0.0074, 0.73     # ~600 m grid cells
SPEED = walk.WALK_KMH / 3.6
AREA = (41.80, -3.60, 43.75, -0.40)                # a point outside this box is not in Euskal Herria
MAX_ACCESS = 70         # at most this many stops are timed by the walking router for each end of the journey
RAIL = ("train", "metro", "tram", "funicular")
SEARCHES = 3            # a request looks for the best journey, then the next ones after it
MIN_WALK_LEG_M = 25     # a walk shorter than this is not shown


def _d(lat1, lon1, lat2, lon2):
    return math.hypot((lat2 - lat1) * 111320.0, (lon2 - lon1) * 111320.0 * COS)


class PlanError(Exception):
    def __init__(self, code, **extra):
        super().__init__(code)
        self.code, self.extra = code, extra


# --------------------------------------------------------------------------- the timetable in memory

class Pattern:
    """Trips of one operator that call at the same stops in the same order and never overtake each other.
    arr[j][k] / dep[j][k]: seconds after the service day's midnight at position j for trip k (k ordered by time)."""
    __slots__ = ("pid", "si", "stops", "n", "nt", "arr", "dep", "svc", "tix", "orig", "mode")


class RTTrip:
    """A trip with live times (absolute epoch seconds per position, None where the vehicle does not stop)."""
    __slots__ = ("pid", "k", "di", "arr", "dep")


def _fifo(prev, cur):
    pa, pd, ca, cd = prev[3], prev[4], cur[3], cur[4]
    for j in range(len(pa)):
        if pa[j] > ca[j] or pd[j] > cd[j]:
            return False
    return True


class Net:
    def __init__(self):
        self.sig = None
        self.slugs = []
        self.svc_ids = []          # per operator: service id -> small int
        self.stops = []            # gid -> (slug, stop_id, lat, lon, name, station_id)
        self.gid = {}              # slug -> {stop_id: gid}
        self.patterns = []
        self.by_stop = []          # gid -> [(pid, position)]
        self.loc = []              # per operator: {tix: (pid, k)}
        self.grid = {}
        self.rail = set()          # stops that a train, metro, tram or funicular calls at
        self._nbr = {}
        self._active = {}
        self.mirror = None         # (patterns, by_stop) of the time-reversed timetable

    # ---- building
    def _build_slug(self, si, slug, db):
        conn = db.conn
        routes = db.routes()
        svc, tsvc, trt = {}, {}, {}
        for tix, sid, rid in conn.execute("SELECT tix, service_id, route_id FROM trips"):
            tsvc[tix] = svc.setdefault(sid, len(svc))
            trt[tix] = rid
        self.svc_ids.append(svc)
        gmap = {}
        for stop_id, name, lat, lon, st in conn.execute(
                "SELECT s.stop_id, s.name, s.lat, s.lon, ss.station_id FROM stops s "
                "LEFT JOIN stop_station ss ON ss.stop_id=s.stop_id"):
            if lat is None or lon is None or (not lat and not lon):
                continue
            gmap[stop_id] = len(self.stops)
            self.stops.append((slug, stop_id, lat, lon, name or "", st))
        self.gid[slug] = gmap
        groups = {}
        cur, stops_, arr, dep = None, [], [], []
        for tix, stop_id, a, d in conn.execute("SELECT tix, stop_id, arr, dep FROM stop_times ORDER BY tix, seq"):
            if tix != cur:
                if cur is not None and len(stops_) >= 2:
                    groups.setdefault(tuple(stops_), []).append((dep[0], cur, tsvc.get(cur, -1), arr, dep))
                cur, stops_, arr, dep = tix, [], [], []
            g = gmap.get(stop_id)
            if g is None:
                continue
            if dep and a < dep[-1]:
                a = dep[-1]
            if d < a:
                d = a
            stops_.append(g)
            arr.append(a)
            dep.append(d)
        if cur is not None and len(stops_) >= 2:
            groups.setdefault(tuple(stops_), []).append((dep[0], cur, tsvc.get(cur, -1), arr, dep))
        loc = {}
        for stops_t, trips in groups.items():
            trips.sort(key=lambda x: (x[0], x[4][-1]))
            subs = []
            for tr in trips:                       # split so that no trip overtakes another inside a pattern
                for sub in subs:
                    if _fifo(sub[-1], tr):
                        sub.append(tr)
                        break
                else:
                    subs.append([tr])
            for sub in subs:
                p = Pattern()
                p.pid, p.si, p.stops, p.n, p.nt, p.orig = len(self.patterns), si, stops_t, len(stops_t), len(sub), None
                p.arr = [array.array("i", c) for c in zip(*[t[3] for t in sub])]
                p.dep = [array.array("i", c) for c in zip(*[t[4] for t in sub])]
                p.svc = [t[2] for t in sub]
                p.tix = [t[1] for t in sub]
                r = routes.get(trt.get(sub[0][1]))
                p.mode = r["mode"] if r else "bus"
                for k, t in enumerate(sub):
                    loc[t[1]] = (p.pid, k)
                self.patterns.append(p)
        self.loc.append(loc)

    def build(self, agencies):
        t0 = time.time()
        for si, (slug, db) in enumerate(agencies):
            self.slugs.append(slug)
            self._build_slug(si, slug, db)
        self.by_stop = [[] for _ in self.stops]
        for p in self.patterns:
            for j, g in enumerate(p.stops):
                self.by_stop[g].append((p.pid, j))
                if p.mode in RAIL:
                    self.rail.add(g)
        for g, row in enumerate(self.by_stop):
            if row:
                self.grid.setdefault((int(self.stops[g][2] // CELL_LAT), int(self.stops[g][3] // CELL_LON)), []).append(g)
        log.info("planner: %d operators, %d stops, %d patterns, %d trips in %.1fs", len(self.slugs), len(self.stops),
                 len(self.patterns), sum(p.nt for p in self.patterns), time.time() - t0)

    def build_mirror(self):
        """The timetable run backwards: positions reversed, times negated, so the same forward search finds the
        latest departure that still arrives on time."""
        t0 = time.time()
        pats = []
        for p in self.patterns:
            m = Pattern()
            n = p.n
            m.pid, m.si, m.stops, m.n, m.nt, m.orig, m.mode = p.pid, p.si, p.stops[::-1], n, p.nt, p, p.mode
            m.arr = [array.array("i", [-x for x in reversed(p.dep[n - 1 - j])]) for j in range(n)]
            m.dep = [array.array("i", [-x for x in reversed(p.arr[n - 1 - j])]) for j in range(n)]
            m.svc, m.tix = p.svc[::-1], p.tix[::-1]
            pats.append(m)
        by_stop = [[] for _ in self.stops]
        for m in pats:
            for j, g in enumerate(m.stops):
                by_stop[g].append((m.pid, j))
        self.mirror = (pats, by_stop)
        log.info("planner: mirrored timetable in %.1fs", time.time() - t0)

    # ---- space
    def stops_within(self, lat, lon, radius):
        ring = int(radius / 590) + 1
        ci, cj = int(lat // CELL_LAT), int(lon // CELL_LON)
        out = []
        for a in range(ci - ring, ci + ring + 1):
            for b in range(cj - ring, cj + ring + 1):
                for g in self.grid.get((a, b), ()):
                    s = self.stops[g]
                    d = _d(lat, lon, s[2], s[3])
                    if d <= radius:
                        out.append((d, g))
        out.sort()
        return out

    def neighbors(self, g):
        """[(stop, seconds)] reachable on foot from a stop (straight-line estimate, checked later by the router)."""
        r = self._nbr.get(g)
        if r is None:
            s = self.stops[g]
            r = [(g2, XFER_BASE + int(d * XFER_K)) for d, g2 in self.stops_within(s[2], s[3], XFER_M) if g2 != g]
            if len(self._nbr) > 60000:
                self._nbr.clear()
            self._nbr[g] = r
        return r

    # ---- time
    def day_info(self, days, reverse=False):
        """Per operator: [(day index, midnight, active service ids)] for the days the search can touch."""
        out = []
        for si, slug in enumerate(self.slugs):
            db = core.DBS[slug]
            svc = self.svc_ids[si]
            lst = []
            for di, d in enumerate(days):
                key = (si, db.version, d)
                act = self._active.get(key)
                if act is None:
                    act = frozenset(svc[s] for s in db.active_services(d) if s in svc)
                    if len(self._active) > 4000:
                        self._active.clear()
                    self._active[key] = act
                if act:
                    m = service_midnight(d)
                    lst.append((di, -m if reverse else m, act))
            out.append(lst)
        return out


# --------------------------------------------------------------------------- RAPTOR

def _earliest(p, j, t, dinfo, blocked, rts):
    """First trip of pattern p leaving position j at or after t: (dep, k, day index, midnight, live trip) or None."""
    best = None
    col = p.dep[j]
    nt, svc = p.nt, p.svc
    for di, m, act in dinfo:
        rel = t - m
        if rel > col[-1]:
            continue
        k = bisect.bisect_left(col, rel)
        while k < nt and (svc[k] not in act or (blocked and (p.pid, k, di) in blocked)):
            k += 1
        if k < nt:
            d = m + col[k]
            if best is None or d < best[0]:
                best = (d, k, di, m, None)
    if rts:
        for r in rts:
            d = r.dep[j]
            if d is not None and d >= t and (best is None or d < best[0]):
                best = (d, r.k, r.di, 0, r)
    return best


def raptor(net, pats, by_stop, src, tgt, dinfo, blocked, rtp, bound, ov):
    """src {stop: (time, walk seconds)}, tgt {stop: walk seconds}. Returns the results (round, stop, final arrival,
    label) that beat every result with fewer vehicles. A label says how a stop was reached and carries the label
    of the stop it came from, so a journey is read off it without any lookup:
      ("a", walk seconds)                                    walked from the starting point
      ("w", from stop, label of from stop)                   walked from another stop
      ("r", pattern, trip, day, board pos, alight pos, live trip, label of the boarding stop)   rode a vehicle"""
    n_stops = len(net.stops)
    best = [INF] * n_stops
    tau, lab = [INF] * n_stops, [None] * n_stops      # label of the previous round
    marked = set()
    tget = tgt.get
    for g, (tm, secs) in src.items():
        if tm < best[g]:
            best[g] = tau[g] = tm
            lab[g] = ("a", secs)
            marked.add(g)
    results, best_final = [], bound
    for k in range(1, MAX_ROUNDS + 1):
        if not marked:
            break
        queue = {}
        for s in marked:
            for pid, pos in by_stop[s]:
                q = queue.get(pid)
                if q is None or pos < q:
                    queue[pid] = pos
        cur, curlab = {}, {}
        for pid, pos0 in queue.items():
            p = pats[pid]
            dpi = dinfo[p.si]
            rts = rtp.get(pid) if rtp else None
            if not dpi and not rts:
                continue
            stops, parr, pdep, n = p.stops, p.arr, p.dep, p.n
            ck, cm, crt, cdi, bj, cdep, boardlab = -1, 0, None, 0, 0, 0, None
            for j in range(pos0, n):
                s = stops[j]
                if ck >= 0:
                    a = crt.arr[j] if crt is not None else cm + parr[j][ck]
                    if a is not None:
                        if a >= bound:
                            break
                        if a < best[s]:
                            best[s] = a
                            cur[s] = a
                            curlab[s] = ("r", pid, ck, cdi, bj, j, crt, boardlab)
                            e = tget(s)
                            if e is not None and a + e < bound:
                                bound = a + e
                ts = tau[s]
                if ts < INF:
                    ready = ts + (BUF if lab[s][0] == "r" else 0)
                    if ck < 0:
                        c = _earliest(p, j, ready, dpi, blocked, rts)
                    else:
                        cdep = crt.dep[j] if crt is not None else cm + pdep[j][ck]
                        c = _earliest(p, j, ready, dpi, blocked, rts) if (cdep is None or ready < cdep) else None
                    if c is not None and (ck < 0 or cdep is None or c[0] < cdep):
                        ck, cdi, cm, crt = c[1], c[2], c[3], c[4]
                        bj, boardlab = j, lab[s]
        # on foot from every stop a vehicle just brought us to (one walk only: never walk through several stops)
        for s, a in list(cur.items()):
            ride = curlab[s]
            for g2, w in net.neighbors(s):
                if ov:
                    w = ov.get((s, g2), w)
                t2 = a + w
                if t2 < best[g2] and t2 < bound:
                    best[g2] = t2
                    cur[g2] = t2
                    curlab[g2] = ("w", s, ride)
        top = None
        for s, a in cur.items():
            e = tget(s)
            if e is not None and curlab[s][0] == "r" and (top is None or a + e < top[2]):    # a journey ends on a vehicle
                top = (k, s, a + e, curlab[s])
        if top and top[2] < best_final:
            results.append(top)
            best_final = top[2]
        for s, a in cur.items():
            tau[s] = a
            lab[s] = curlab[s]
        marked = set(cur)
    return results


def _trace(pats, label, s):
    """Read a journey off the label of stop s: (first stop, access seconds, items in search order)."""
    items = []
    while True:
        kind = label[0]
        if kind == "a":
            return s, label[1], items[::-1]
        if kind == "w":
            items.append(("w", label[1], s))
            s, label = label[1], label[2]
            continue
        items.append(label)
        s, label = pats[label[1]].stops[label[4]], label[7]


def _to_forward(pats, items):
    """Items of a search over the mirrored timetable, as they happen in time."""
    out = []
    for it in reversed(items):
        if it[0] == "w":
            out.append(("w", it[2], it[1]))
        else:
            _, pid, ck, di, bj, aj, _, _ = it
            m = pats[pid]
            out.append(("r", m.orig, m.nt - 1 - ck, di, m.n - 1 - aj, m.n - 1 - bj, None))
    return out


# --------------------------------------------------------------------------- live data

_ov_cache = {}


def _overlay(net, days, now):
    """Live times of the trips that have a trip update, for the days of the search: (blocked, live trips by pattern).
    A trip with an update replaces its timetable entry; a cancelled one disappears."""
    key = (id(net), tuple(days), now // 20)
    hit = _ov_cache.get(key)
    if hit:
        return hit
    blocked, rtp = set(), {}
    blocked_m, rtp_m = set(), {}
    dset = {d: di for di, d in enumerate(days)}
    slugs = [s for s in net.slugs if core.AGENCIES[s]["rt"].get("trips") or core.is_lb(s)]
    core.refresh([s for s in slugs if core.AGENCIES[s]["rt"].get("trips")], ["trips"])
    for slug in slugs:
        si = net.slugs.index(slug)
        db, gm, loc = core.DBS[slug], net.gid[slug], net.loc[si]
        try:
            tus = core.tu_index(slug)
        except Exception:
            log.exception("planner: no trip updates for %s", slug)
            continue
        for tid, lst in tus.items():
            trip = core._trip(db, slug, tid)
            at = loc.get(trip["tix"]) if trip else None
            if not at:
                continue
            rows = db.trip_stop_times(trip["tix"])
            for tu in lst:
                d = core.resolve_service_date(db, trip, rows, now, tu["trip"].get("start_date"))
                di = dset.get(d)
                if di is None:
                    continue
                eff, cancelled = core.effective_times(slug, rows, d, tu)
                pid, k = at
                blocked.add((pid, k, di))
                if cancelled:
                    continue
                eff = [e for e in eff if e["stop_id"] in gm]
                if len(eff) != net.patterns[pid].n:
                    continue
                r = RTTrip()
                r.pid, r.k, r.di = pid, k, di
                r.arr = [None if e.get("skipped") else e["arr"] for e in eff]
                r.dep = [None if e.get("skipped") else e["dep"] for e in eff]
                rtp.setdefault(pid, []).append(r)
                # the same trip in the mirrored timetable: reversed, with negated times and swapped arrival / departure
                nt = net.patterns[pid].nt
                m = RTTrip()
                m.pid, m.k, m.di = pid, nt - 1 - k, di
                m.arr = [None if x is None else -x for x in reversed(r.dep)]
                m.dep = [None if x is None else -x for x in reversed(r.arr)]
                blocked_m.add((pid, nt - 1 - k, di))
                rtp_m.setdefault(pid, []).append(m)
        # (cancelled trips are blocked in the mirrored timetable too)
    for pid, k, di in list(blocked):
        blocked_m.add((pid, net.patterns[pid].nt - 1 - k, di))
    if len(_ov_cache) > 8:
        _ov_cache.clear()
    _ov_cache[key] = (blocked, rtp, blocked_m, rtp_m)
    return _ov_cache[key]


# --------------------------------------------------------------------------- the two ends of a journey

class Endpoint:
    __slots__ = ("lat", "lon", "label", "zero", "station")

    def __init__(self, lat, lon, label, zero=(), station=None):
        self.lat, self.lon, self.label, self.zero, self.station = lat, lon, label, set(zero), station

    @property
    def ll(self):
        return (self.lat, self.lon)


def _endpoint(net, spec, label):
    spec = (spec or "").strip()
    label = (label or "").strip()[:80]
    try:
        if spec.startswith("st:"):
            slug, _, sid = spec[3:].partition("|")
            st = core.DBS[slug].station(sid) if slug in net.gid else None
            if not st:
                raise PlanError("bad_endpoint")
            zero = set()
            for peer in core.lb_peers(slug, sid):
                gm = net.gid.get(peer, {})
                zero.update(gm[x] for x in core.DBS[peer].station_stops(sid) if x in gm)
            return Endpoint(st["lat"], st["lon"], st["name"], zero, (slug, sid))
        if spec.startswith("ll:"):
            lat, lon = (float(x) for x in spec[3:].split(","))
            if not (AREA[0] <= lat <= AREA[2] and AREA[1] <= lon <= AREA[3]):
                raise PlanError("out_of_area")
            return Endpoint(lat, lon, label)
    except (ValueError, KeyError):
        pass
    raise PlanError("bad_endpoint")


def _candidates(net, ep, max_walk, ctx, which):
    """Stops reachable on foot from a point: {stop: (seconds, metres)}, the real walking times when the router is up."""
    cand = {g: (0, 0) for g in ep.zero}
    near = [(d, g) for d, g in net.stops_within(ep.lat, ep.lon, max_walk) if g not in ep.zero]
    # walking to a farther stop of a line that has a nearer one is never better, so only the nearest stop of every
    # line (pattern) is worth timing; with the stations (they have many lines) that is a few dozen stops
    seen, pick = set(), []
    for d, g in near:
        new = [pid for pid, _ in net.by_stop[g] if pid not in seen]
        if new and len(pick) < MAX_ACCESS:
            pick.append((d, g))
            seen.update(pid for pid, _ in net.by_stop[g])
    extra = 0
    chosen = {g for _, g in pick}
    for d, g in near:                                # a station is worth a longer walk than one more bus stop
        if extra < 12 and g in net.rail and g not in chosen:
            pick.append((d, g))
            extra += 1
    if pick:
        res, eng = walk.matrix(ep.ll, [net.stops[g][2:4] for _, g in pick])
        ctx.engines.add(eng)
        for (d, g), r in zip(pick, res):
            if r is not None and r[1] <= max_walk * 1.4:
                cand[g] = r
    if not cand:
        raise PlanError("no_stops_near", end=which)
    return cand


# --------------------------------------------------------------------------- searching

class Ctx:
    pass


def _search(net, ctx, anchor, reverse):
    """Journeys leaving at or after `anchor` (or arriving at or before it, when reverse): a list of
    (access (stop, secs), items in time order, egress (stop, secs)), fewest vehicles first."""
    if reverse:
        if net.mirror is None:
            raise PlanError("warming_up")
        pats, by_stop = net.mirror
        src = {g: (-anchor + secs, secs) for g, (secs, _) in ctx.d_cand.items()}
        tgt = {g: secs for g, (secs, _) in ctx.o_cand.items()}
        results = raptor(net, pats, by_stop, src, tgt, ctx.dinfo_rev, ctx.blocked_m, ctx.rtp_m, -anchor + HORIZON, ctx.ov)
    else:
        pats = net.patterns
        src = {g: (anchor + secs, secs) for g, (secs, _) in ctx.o_cand.items()}
        tgt = {g: secs for g, (secs, _) in ctx.d_cand.items()}
        results = raptor(net, pats, net.by_stop, src, tgt, ctx.dinfo, ctx.blocked, ctx.rtp, anchor + HORIZON, ctx.ov)
    specs = []
    for _, s, _, label in results:
        start, secs0, items = _trace(pats, label, s)
        if reverse:
            specs.append(((s, tgt[s]), _to_forward(pats, items), (start, secs0)))
        else:
            specs.append(((start, secs0), [("w", i[1], i[2]) if i[0] == "w" else
                                           ("r", pats[i[1]], i[2], i[3], i[4], i[5], i[6]) for i in items], (s, tgt[s])))
    return specs


# --------------------------------------------------------------------------- turning a search result into a journey

_wcache = {}
_wpool = ThreadPoolExecutor(max_workers=6)


def _walk_route(a, b):
    key = (round(a[0], 5), round(a[1], 5), round(b[0], 5), round(b[1], 5))
    r = _wcache.get(key)
    if r is None:
        r = walk.route(a, b)
        if r["engine"] == "valhalla":
            if len(_wcache) > 3000:
                _wcache.clear()
            _wcache[key] = r
    return r


def _ride_times(ctx, it):
    _, p, k, di, bpos, apos, rt = it
    if rt is not None:
        return rt.dep[bpos], rt.arr[apos]
    m = ctx.mids[di]
    return m + p.dep[bpos][k], m + p.arr[apos][k]


def _assemble(net, ctx, spec):
    """(journey, conflicts). conflicts = {(stop, stop): seconds} for changes on foot that take longer than the time
    the timetable leaves, so the search can be run again without them."""
    try:
        return _assemble_(net, ctx, spec)
    except Exception:
        (a, _), items, (e, _) = spec
        log.exception("planner: cannot assemble a journey: access %s, egress %s, items %s", a, e,
                      [(i[0], i[1] if i[0] == "w" else getattr(i[1], "pid", None), i[2] if i[0] == "w" else i[2:6]) for i in items])
        return None, {}


def _assemble_(net, ctx, spec):
    (acc_g, _), items, (egr_g, _) = spec
    items = list(items)
    o, d = ctx.o_ep, ctx.d_ep
    nodes = []                                      # ("ride", item) | ("walk", from, to)   from/to: "o", "d" or a stop
    links = []                                      # changes of stop on foot that were merged into the walk at either end
    if items and items[0][0] == "w":                # the walk from a starting stop to the next one: one walk from the point
        first = items.pop(0)
        links.append((first[1], first[2]))
        nodes.append(("walk", "o", first[2]))
    elif items and acc_g not in o.zero:
        nodes.append(("walk", "o", items[0][1].stops[items[0][4]]))
    for it in items:
        nodes.append(("ride", it) if it[0] == "r" else ("walk", it[1], it[2]))
    if nodes and egr_g not in d.zero:               # walk the last stretch to the destination point
        if nodes[-1][0] == "walk":                   # ... in one go, from the last vehicle (no stop in between)
            links.append((nodes[-1][1], nodes[-1][2]))
            nodes[-1] = ("walk", nodes[-1][1], "d")
        else:
            last = nodes[-1][1]
            nodes.append(("walk", last[1].stops[last[5]], "d"))
    rides = [n for n in nodes if n[0] == "ride"]
    if not rides:
        return None, {}
    # a change of stop on foot was estimated from the straight line; when it is really much longer (a river, a railway)
    # the search must not use it: forbid it and look again
    bad = {}
    for a, b in links:
        est = ctx.ov.get((a, b), _link_est(net, a, b))
        real = _walk_route(net.stops[a][2:4], net.stops[b][2:4])
        if real["secs"] > est + 30:
            bad[(a, b)] = bad[(b, a)] = real["secs"]
    if bad:
        return None, bad

    def ll(x):
        return o.ll if x == "o" else d.ll if x == "d" else net.stops[x][2:4]

    walks = [n for n in nodes if n[0] == "walk"]
    futs = {id(n): _wpool.submit(_walk_route, ll(n[1]), ll(n[2])) for n in walks}
    wr = {k: f.result() for k, f in futs.items()}
    legs, conflicts, t_prev = [], {}, None
    # times: rides are fixed; a walk starts when the previous ride ends (or ends when the next ride starts)
    for i, n in enumerate(nodes):
        if n[0] == "ride":
            continue
        w = wr[id(n)]
        nxt = nodes[i + 1] if i + 1 < len(nodes) else None
        prv = nodes[i - 1] if i > 0 else None
        if prv is not None and prv[0] == "ride":
            dep = _ride_times(ctx, prv[1])[1]
        else:
            dep = _ride_times(ctx, nxt[1])[0] - w["secs"]
        arr = dep + w["secs"]
        if nxt is not None and nxt[0] == "ride" and prv is not None and arr > _ride_times(ctx, nxt[1])[0]:
            if isinstance(n[1], int) and isinstance(n[2], int):
                conflicts[(n[1], n[2])] = conflicts[(n[2], n[1])] = w["secs"]
        wr[id(n)] = dict(w, dep=dep, arr=arr)
    if conflicts:
        return None, conflicts
    secs_walk = m_walk = 0
    for n in nodes:
        if n[0] == "walk":
            w = wr[id(n)]
            secs_walk += w["secs"]
            m_walk += w["m"]
            if w["m"] < MIN_WALK_LEG_M:
                continue
            legs.append({"type": "walk", "from": _place(net, o, d, n[1]), "to": _place(net, o, d, n[2]), "dep": w["dep"],
                         "arr": w["arr"], "secs": w["secs"], "m": w["m"], "shape": w["shape"], "steps": w["steps"],
                         "estimated": w["engine"] != "valhalla"})
        else:
            legs.append(_ride_leg(net, ctx, n[1]))
    legs.sort(key=lambda l: l["dep"])
    leave, arrive = legs[0]["dep"], max(l["arr"] for l in legs)
    nrides = len(rides)
    return {"leave": leave, "arrive": arrive, "dur": arrive - leave, "transfers": nrides - 1, "walk_s": secs_walk,
            "walk_m": m_walk, "live": any(l.get("rt") for l in legs), "estimated": any(l.get("estimated") for l in legs),
            "legs": legs, "sig": [(l["agency"], l["trip_id"], l["date"]) for l in legs if l["type"] == "ride"]}, {}


def _link_est(net, a, b):
    sa, sb = net.stops[a], net.stops[b]
    return XFER_BASE + int(_d(sa[2], sa[3], sb[2], sb[3]) * XFER_K)


def _place(net, o, d, x):
    if x == "o":
        return {"name": o.label, "lat": o.lat, "lon": o.lon, "point": True}
    if x == "d":
        return {"name": d.label, "lat": d.lat, "lon": d.lon, "point": True}
    s = net.stops[x]
    return {"name": s[4], "lat": s[2], "lon": s[3], "agency": s[0], "station_id": s[5], "stop_id": s[1]}


def _ride_leg(net, ctx, it):
    _, p, k, di, bpos, apos, rt = it
    slug = net.slugs[p.si]
    db = core.DBS[slug]
    tix = p.tix[k]
    trip = dict(db.q("SELECT * FROM trips WHERE tix=?", (tix,))[0])
    li = core.line_info(db, trip["route_id"])
    rows = db.trip_stop_times(tix)
    gm = net.gid[slug]
    idx = [i for i, r in enumerate(rows) if r["stop_id"] in gm]           # rows that are positions of the pattern
    m = ctx.mids[di]
    dep_t, arr_t = _ride_times(ctx, it)
    stops = []
    for j in range(bpos, apos + 1):
        r = rows[idx[j]]
        a = rt.arr[j] if rt is not None else m + p.arr[j][k]
        d_ = rt.dep[j] if rt is not None else m + p.dep[j][k]
        stops.append({"name": r["name"], "lat": r["lat"], "lon": r["lon"], "arr": a, "dep": d_})
    return {"type": "ride", "agency": slug, "agency_name": core.AGENCIES[slug]["name"], "route_id": trip["route_id"],
            "line": li["line"], "color": li["color"], "text_color": li["text_color"], "mode": li["mode"],
            "headsign": trip["headsign"] or core.lb_headsign(slug, tix) or li["long"], "trip_id": trip["trip_id"],
            "date": ctx.days[di].strftime("%Y%m%d"), "dep": dep_t, "arr": arr_t, "dep_s": m + p.dep[bpos][k],
            "arr_s": m + p.arr[apos][k], "rt": rt is not None, "from": _place(net, ctx.o_ep, ctx.d_ep, p.stops[bpos]),
            "to": _place(net, ctx.o_ep, ctx.d_ep, p.stops[apos]), "stops": stops, "n": apos - bpos,
            "shape": _leg_shape(db, trip, rows, idx[bpos], idx[apos])}


def _leg_shape(db, trip, rows, i0, i1):
    """The track between two stops of a trip: the published shape when it can be followed, else the stops joined."""
    try:
        geom = core.shape_geom(db, trip.get("shape_id"))
        if geom:
            dists = core.stop_distances(db, trip, rows)
            d0, d1 = dists[i0], dists[i1]
            if d0 is not None and d1 is not None and d1 > d0:
                cum, pts = geom[2], geom[3]
                a, b = bisect.bisect_right(cum, d0), bisect.bisect_left(cum, d1)
                seg = [core._point_at(geom, d0)[:2]] + [pts[i] for i in range(a, b)] + [core._point_at(geom, d1)[:2]]
                return [[round(x, 5), round(y, 5)] for x, y in seg]
    except Exception:
        log.exception("planner: shape of %s", trip.get("trip_id"))
    return [[r["lat"], r["lon"]] for r in rows[i0:i1 + 1] if r["lat"] and r["lon"]]


def _find(net, ctx, anchor, reverse):
    """Journeys from one search, verified with the walking router (the search runs again, forbidding any change
    on foot that takes longer than estimated)."""
    for _ in range(6):
        built, bad = [], False
        for spec in _search(net, ctx, anchor, reverse):
            j, conf = _assemble(net, ctx, spec)
            if conf:
                ctx.ov.update(conf)
                bad = True
            elif j and not (j["arrive"] > anchor + 30 if reverse else j["leave"] < anchor - 30):
                built.append(j)
        if not bad:
            break
    if reverse:
        built.sort(key=lambda j: (-j["leave"], j["transfers"]))
    else:
        built.sort(key=lambda j: (j["arrive"], j["transfers"]))
    return built


def _push_late(net, ctx, j):
    """The same arrival with the latest possible departure: the earliest-arrival search leaves as soon as it can and
    waits at the first stop, which is neither what a person wants nor a good place to start the next search."""
    try:
        # a minute of slack: the search chains two estimated walks (stop to stop, then to the end) that the router
        # then replaces by one shorter direct walk, so the exact deadline is a little tighter than it needs to be
        for b in _find(net, ctx, j["arrive"] + 30, True):    # latest departure first
            if b["arrive"] <= j["arrive"] + 30 and b["transfers"] <= j["transfers"]:
                return b if b["leave"] >= j["leave"] else j
    except PlanError:
        pass
    return j


def _attach_alerts(journeys):
    """Service alerts that are active now on the lines of a journey, as the alerts tab shows them."""
    cache = {}
    for j in journeys:
        for l in j["legs"]:
            if l["type"] != "ride":
                continue
            if l["agency"] not in cache:
                try:
                    cache[l["agency"]] = core.alerts(l["agency"])
                except Exception:
                    log.exception("planner: alerts of %s", l["agency"])
                    cache[l["agency"]] = []
            mine = [a for a in cache[l["agency"]]
                    if l["route_id"] in a["route_ids"] or any(e.get("trip_id") == l["trip_id"] for e in a["entities"])]
            if mine:
                l["alerts"] = [{k: a[k] for k in ("id", "agency", "agency_name", "lines", "header", "description", "url", "end")}
                               for a in mine[:3]]


def _walk_journey(ctx, anchor, reverse):
    a, b = ctx.o_ep, ctx.d_ep
    straight = _d(a.lat, a.lon, b.lat, b.lon)
    if straight > 5000:
        return None
    w = _walk_route(a.ll, b.ll)
    leave = anchor - w["secs"] if reverse else anchor
    leg = {"type": "walk", "from": {"name": a.label, "lat": a.lat, "lon": a.lon, "point": True},
           "to": {"name": b.label, "lat": b.lat, "lon": b.lon, "point": True}, "dep": leave, "arr": leave + w["secs"],
           "secs": w["secs"], "m": w["m"], "shape": w["shape"], "steps": w["steps"], "estimated": w["engine"] != "valhalla"}
    return {"leave": leave, "arrive": leave + w["secs"], "dur": w["secs"], "transfers": 0, "walk_s": w["secs"],
            "walk_m": w["m"], "live": False, "estimated": leg["estimated"], "legs": [leg], "sig": [("walk",)], "walk_only": True}


def _dominated(j, others):
    for o in others:
        if o is j:
            continue
        if o["leave"] >= j["leave"] and o["arrive"] <= j["arrive"] and o["transfers"] <= j["transfers"] and \
                (o["leave"] > j["leave"] or o["arrive"] < j["arrive"] or o["transfers"] < j["transfers"]):
            return True
    return False


# --------------------------------------------------------------------------- public API

_net = None
_building = threading.Lock()
_sem = threading.BoundedSemaphore(2)
_cache = {}


def _signature():
    return tuple(sorted((s, core.DBS[s].version) for s, i in core.AGENCIES.items() if i["ready"]))


def current():
    return _net


def start():
    """Background thread: (re)build the timetable index whenever the operators' databases change."""
    threading.Thread(target=_loop, name="planner", daemon=True).start()


def _loop():
    global _net
    last = None
    while True:
        try:
            sig = _signature()
            # wait until the set of databases has stopped changing (first start imports them one after another)
            if sig and sig == last and (_net is None or _net.sig != sig):
                with _building:
                    agencies = [(s, core.DBS[s]) for s, _ in sig]
                    net = Net()
                    net.build(agencies)
                    net.sig = sig
                    net.build_mirror()
                    _net = net
                    _cache.clear()
            last = sig
        except Exception:
            log.exception("planner: build failed")
        time.sleep(15)


def status():
    n = _net
    return {"ready": n is not None, "operators": len(n.slugs) if n else 0, "stops": len(n.stops) if n else 0,
            "patterns": len(n.patterns) if n else 0, "walking": walk.engine() if walk.enabled() else "estimate"}


def _local_epoch(date_s, time_s):
    d = datetime.strptime(date_s, "%Y%m%d").date()
    h, m = (int(x) for x in (time_s or "00:00").split(":")[:2])
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).timestamp())


def plan(q, lang="eu"):
    """q: from, to ("ll:lat,lon" or "st:operator|station"), from_name, to_name, mode (now|dep|arr), date, time (HH:MM),
    t (epoch, overrides date and time), live (1 to use live data), max_walk (metres)."""
    try:
        if _net is None:
            raise PlanError("warming_up")
        return _plan(_net, q, lang)
    except PlanError as e:
        return {"error": e.code, **e.extra}


def _plan(net, q, lang):
    def g(k, default=""):
        v = q.get(k, default)
        return (v[0] if v else default) if isinstance(v, list) else v
    mode = g("mode", "now")
    mode = mode if mode in ("dep", "arr") else "now"
    now = int(time.time())
    try:
        max_walk = max(300, min(3000, int(g("max_walk", "1000") or 1000)))
    except ValueError:
        max_walk = 1000
    if g("t"):
        try:
            anchor = int(g("t"))
        except ValueError:
            raise PlanError("bad_time")
    elif mode == "now":
        anchor = now
    else:
        try:
            anchor = _local_epoch(g("date"), g("time"))
        except (ValueError, TypeError):
            raise PlanError("bad_time")
    live = g("live") == "1" or mode == "now"
    if mode == "now":
        anchor = now
    lim = core.limits_payload(net.slugs)
    day0 = datetime.fromtimestamp(anchor, TZ).date()
    if not (lim["min"] <= day0.strftime("%Y%m%d") <= lim["max"]):
        raise PlanError("date_out_of_range", range=lim)
    key = json.dumps([g("from"), g("to"), mode, anchor // (30 if live else 60), live, max_walk, g("from_name"), g("to_name")])
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    o_ep, d_ep = _endpoint(net, g("from"), g("from_name")), _endpoint(net, g("to"), g("to_name"))
    if (o_ep.lat, o_ep.lon) == (d_ep.lat, d_ep.lon):
        raise PlanError("same_place")
    reverse = mode == "arr"
    with _sem:
        ctx = Ctx()
        ctx.o_ep, ctx.d_ep, ctx.engines, ctx.ov = o_ep, d_ep, set(), {}
        ctx.days = [day0 - timedelta(days=1), day0, day0 + timedelta(days=1)]
        ctx.mids = [service_midnight(d) for d in ctx.days]
        ctx.o_cand = _candidates(net, o_ep, max_walk, ctx, "from")
        ctx.d_cand = _candidates(net, d_ep, max_walk, ctx, "to")
        ctx.dinfo = net.day_info(ctx.days)
        ctx.dinfo_rev = net.day_info(ctx.days, reverse=True)
        ctx.blocked, ctx.rtp, ctx.blocked_m, ctx.rtp_m = _overlay(net, ctx.days, now) if live else (set(), None, set(), None)
        journeys, seen, t = [], set(), anchor
        for _ in range(SEARCHES):
            found = _find(net, ctx, t, reverse)
            if not reverse:
                found = [_push_late(net, ctx, j) if i < 2 else j for i, j in enumerate(found)]
                found.sort(key=lambda j: (j["arrive"], j["transfers"]))
            found = [j for j in found if tuple(j["sig"]) not in seen]
            if not found:
                break
            for j in found:
                seen.add(tuple(j["sig"]))
            journeys += found
            t = found[0]["arrive"] - 60 if reverse else found[0]["leave"] + 60
        wj = _walk_journey(ctx, anchor, reverse)
        if wj:
            best = min((j["dur"] for j in journeys), default=None)
            if best is None or wj["dur"] <= 25 * 60 or wj["dur"] <= best:
                journeys.append(wj)
    journeys = [j for j in journeys if j.get("walk_only") or not _dominated(j, journeys)]
    best = min((j["dur"] for j in journeys if not j.get("walk_only")), default=None)
    if best is not None:        # not the 03:00 bus with a three hour wait, next to a journey of an hour and a half
        journeys = [j for j in journeys if j.get("walk_only") or j["dur"] <= max(best * 1.8, best + 2700)]
    if live or day0 == datetime.fromtimestamp(now, TZ).date():
        _attach_alerts(journeys)
    journeys.sort(key=lambda j: (j["leave"], j["arrive"]))
    fast = min(journeys, key=lambda j: j["dur"]) if journeys else None
    for j in journeys:
        j["fastest"] = j is fast
    out = {"mode": mode, "live": live, "time": anchor, "now": now, "walking": "valhalla" if "valhalla" in ctx.engines and "estimate" not in ctx.engines
           else "estimate", "range": lim, "from": {"name": o_ep.label, "lat": o_ep.lat, "lon": o_ep.lon},
           "to": {"name": d_ep.label, "lat": d_ep.lat, "lon": d_ep.lon}, "journeys": journeys,
           "earlier": min((j["arrive"] for j in journeys), default=anchor) - 60,
           "later": max((j["leave"] for j in journeys), default=anchor) + 60}
    if not journeys:
        out["error"] = "no_route"
    _cache[key] = (now + (20 if live else 300), out)
    if len(_cache) > 200:
        _cache.clear()
    return out
