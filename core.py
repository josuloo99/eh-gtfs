"""Core logic: agency registry, GTFS updater, GTFS-RT cache and real-time merging."""
import bisect
import gzip
import json
import logging
import math
import os
import re
import threading
import time
import zlib
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_cls, datetime, timedelta

import gtfsrt
import lurraldebus
import bizkaibus
import region
import sources
import staticfeeds
import store
import villavesa
from store import TZ, AgencyDB, candidate_days, haversine, norm, service_midnight

log = logging.getLogger("moveuskadi")

INDEX_URL = "https://opendata.euskadi.eus/transport/moveuskadi/data-index.json"
GTFS_DIR = os.path.join(store.DATA_DIR, "gtfs")
UA = {"User-Agent": "mugitu/1.0 (personal use)"}
# Theoretical timetables for another date are limited to this window around today (and to the
# period the operator's published GTFS actually covers).
SCHEDULE_PAST_DAYS = int(os.environ.get("SCHEDULE_PAST_DAYS", "7"))
SCHEDULE_FUTURE_DAYS = int(os.environ.get("SCHEDULE_FUTURE_DAYS", "60"))
SCHEDULE_MAX_ROWS = 2500
RT_TTL = 15            # seconds a decoded RT feed stays cached
RT_MAX_AGE = 600       # a feed whose header timestamp is older than this is considered stale
# AlavaBus publishes timestamps as "local time encoded as UTC"
LOCAL_EPOCH = {"alavabus"}

AGENCIES = {}          # slug -> info dict
DBS = {}               # slug -> AgencyDB
_state_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=16)


def quote_url(u):
    return urllib.parse.quote(u, safe=":/?&=%")


def http_get(url, timeout=20):
    req = urllib.request.Request(quote_url(url), headers=dict(UA, **{"Accept-Encoding": "gzip"}))
    with urllib.request.urlopen(req, timeout=timeout, context=sources.SSL_CTX) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw


# --------------------------------------------------------------------------- registry

def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", norm(name)).strip("_")


def load_index():
    path = os.path.join(store.DATA_DIR, "data-index.json")
    try:
        raw = http_get(INDEX_URL)
        idx = json.loads(raw)
        with open(path, "wb") as f:
            f.write(raw)
    except Exception as e:  # network down: use cache
        log.warning("index fetch failed: %s", e)
        if not os.path.exists(path):
            return False
        idx = json.load(open(path, "rb"))
    new = {}
    for name, files in idx.get("data", {}).items():
        info = {"name": name, "gtfs": None, "gtfs_stamp": "", "rt": {}, "slug": None, "region": "eus",
                "quirks": {}, "source": "movEuskadi"}
        for f in files:
            fmt, url, fn = f.get("format"), f.get("url", ""), f.get("name", "")
            low = fn.lower()
            if fmt == "GTFS":
                info["gtfs"] = url
                info["gtfs_stamp"] = f.get("last-update", "")
                m = re.match(r"gtfs_(.+)\.zip$", fn)
                info["slug"] = m.group(1) if m else slugify(name)
            elif fmt == "GTFS-RT":
                if "alert" in low:
                    kind = "alerts"
                elif "trip" in low:
                    kind = "trips"
                elif "position" in low or "vehicle" in low:
                    kind = "vehicles"
                else:
                    continue
                info["rt"][kind] = url
        if info["gtfs"] and info["slug"]:
            if sources.replaced_in_index(info["slug"]):
                continue                    # that operator is read straight from its publisher (sources.py)
            if info["slug"] in store.BBOX_AGENCIES:
                info["region"] = "eh"
            new[info["slug"]] = info
    _merge_agencies(new)
    return True


def _merge_agencies(new):
    """Add or refresh operators keeping their import state."""
    with _state_lock:
        for slug, info in new.items():
            # the stamp also says how the importer cut the feed, so a change of that re-imports every operator
            info["gtfs_stamp"] = (info.get("gtfs_stamp") or "") + store.IMPORT_TAG
            old = AGENCIES.get(slug)
            info["ready"] = old["ready"] if old else False
            info["error"] = old.get("error") if old else None
            info["importing"] = old.get("importing", False) if old else False
            info["imported_stamp"] = old.get("imported_stamp", "") if old else ""
            AGENCIES[slug] = info
            DBS.setdefault(slug, AgencyDB(slug))


def load_extra_sources(only=None):
    """Operators outside the MovEuskadi index (see sources.py): resolve their current, possibly keyed, URLs."""
    new = {}
    for src in sources.SOURCES:
        if only and src["slug"] != only:
            continue
        res = sources.resolve(src)
        if not res:
            log.warning("%s: no URLs available yet", src["slug"])
            continue
        rt = {k: v for k, v in res["rt"].items()
              if villavesa.ENABLED or not v.startswith(villavesa.SCHEME)}
        new[src["slug"]] = {"name": src["name"], "gtfs": res["gtfs"], "gtfs_stamp": res["stamp"], "rt": rt,
                            "slug": src["slug"], "region": src["region"], "quirks": dict(src.get("quirks") or {}),
                            "source": sources.source_label(src)}
    if new:
        _merge_agencies(new)
    return bool(new)


def refresh_source_soon(slug):
    """A feed answered 401/403 (rotated API key?): resolve its URLs again in the background, rate limited."""
    if slug in AGENCIES and AGENCIES[slug].get("source") != "movEuskadi" and sources.should_force(slug):
        log.warning("%s: access denied, resolving its URLs again", slug)
        threading.Thread(target=load_extra_sources, args=(slug,), daemon=True).start()


def _db_stamp(slug):
    p = os.path.join(store.DB_DIR, slug + ".sqlite")
    if not os.path.exists(p):
        return None
    try:
        import sqlite3
        c = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
        meta = dict(c.execute("SELECT k, v FROM meta").fetchall())
        c.close()
        if meta.get("schema") != str(store.SCHEMA_VERSION):
            return None
        return meta.get("stamp", "")
    except Exception:
        return None


def _download(url, dest):
    if url.startswith(sources.STATIC_SCHEME):
        staticfeeds.build_zip(url[len(sources.STATIC_SCHEME):], dest)      # a hand-transcribed timetable: built, not fetched
        return
    if url.startswith(sources.NAP_SCHEME):
        # a pre-signed, short-lived link: asked for now, and used as it is (re-quoting would break its signature)
        url = sources.nap_download_url(url)
        req = urllib.request.Request(url, headers=UA)
    else:
        req = urllib.request.Request(quote_url(url), headers=UA)
    with urllib.request.urlopen(req, timeout=120, context=sources.SSL_CTX) as r, open(dest + ".part", "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(dest + ".part", dest)


def update_agency(slug):
    info = AGENCIES[slug]
    if info.get("importing"):
        return
    stamp = _db_stamp(slug)
    if stamp is not None and not info["ready"]:
        info["ready"] = True
        info["imported_stamp"] = stamp
    if stamp is not None and stamp == info["gtfs_stamp"]:
        return
    info["importing"] = True
    try:
        os.makedirs(GTFS_DIR, exist_ok=True)
        zp = os.path.join(GTFS_DIR, slug + ".zip")
        log.info("downloading GTFS %s", slug)
        try:
            _download(info["gtfs"], zp)
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403) or info.get("source") == "movEuskadi":
                raise
            # the API key probably rotated: resolve the URL again once and retry
            log.warning("%s: GTFS download denied (HTTP %s), resolving the URL again", slug, e.code)
            load_extra_sources(slug)
            info = AGENCIES[slug]
            _download(info["gtfs"], zp)
        log.info("importing GTFS %s", slug)
        t0 = time.time()
        ok = store.import_gtfs(zp, os.path.join(store.DB_DIR, slug + ".sqlite"), slug, info["gtfs_stamp"],
                               info.get("quirks"))
        if ok:
            DBS[slug].reload()
            info["ready"] = True
            info["imported_stamp"] = info["gtfs_stamp"]
            info["error"] = None
            log.info("imported %s in %.1fs", slug, time.time() - t0)
        else:
            info["error"] = "no stops inside Euskal Herria"
        os.remove(zp)
    except Exception as e:
        log.exception("update of %s failed", slug)
        info["error"] = str(e)
    finally:
        info["importing"] = False


def updater_loop():
    os.makedirs(store.DB_DIR, exist_ok=True)
    first = True
    while True:
        try:
            # each registry is independent: one being unreachable never blocks the other
            for loader in (load_index, load_extra_sources):
                try:
                    loader()
                except Exception:
                    log.exception("%s failed", loader.__name__)
            if AGENCIES:
                slugs = sorted(AGENCIES, key=lambda s: (_db_stamp(s) is not None, s))
                # mark already-imported ones ready right away so the UI works while others download
                for s in slugs:
                    st = _db_stamp(s)
                    if st is not None and not AGENCIES[s]["ready"]:
                        AGENCIES[s]["ready"] = True
                        AGENCIES[s]["imported_stamp"] = st
                with ThreadPoolExecutor(max_workers=3) as ex:
                    list(ex.map(update_agency, slugs))
        except Exception:
            log.exception("updater loop")
        first = False
        time.sleep(1800)


# --------------------------------------------------------------------------- RT feeds

class Feed:
    def __init__(self, url):
        self.url = url
        self.lock = threading.Lock()
        self.fetched = 0
        self.data = None
        self.error = None


_feeds = {}


def get_feed(url, ttl=RT_TTL, slug=None):
    f = _feeds.get(url)
    if f is None:
        f = _feeds.setdefault(url, Feed(url))
    if url.startswith(villavesa.SCHEME):
        return _villavesa_get(f, slug)
    if time.time() - f.fetched < ttl:
        return f
    with f.lock:
        if time.time() - f.fetched < ttl:
            return f
        try:
            raw = http_get(url, timeout=10)
            f.data = gtfsrt.decode(raw) if len(raw) > 20 else {"timestamp": 0, "trip_updates": [], "vehicles": [], "alerts": []}
            f.error = None
        except Exception as e:
            f.error = str(e)[:120]
            if slug and isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
                refresh_source_soon(slug)      # the API key may have rotated
            if f.data is None:
                f.data = {"timestamp": 0, "trip_updates": [], "vehicles": [], "alerts": []}
        f.fetched = time.time()
    return f


def _villavesa_get(f, slug):
    """Villavesas needs one request per line (several seconds), so it refreshes in the background: callers always
    get the last result at once, and only one refresh runs at a time (nothing runs while nobody asks)."""
    if f.data is None:
        f.data = {"timestamp": 0, "trip_updates": [], "vehicles": [], "alerts": []}
    if time.time() - f.fetched >= villavesa.TTL and f.lock.acquire(blocking=False):
        def work():
            try:
                f.data = _villavesa_feed(slug)
                f.error = None
            except Exception as e:
                f.error = str(e)[:120]
                log.warning("villavesa: %s", f.error)
            finally:
                f.fetched = time.time()
                f.lock.release()
        threading.Thread(target=work, daemon=True).start()
    return f


def _villavesa_feed(slug):
    """GPS positions of Villavesas (see villavesa.py): the lines asked for are those with a trip running now."""
    db = DBS.get(slug)
    if db is None:
        return {"timestamp": 0, "trip_updates": [], "vehicles": [], "alerts": []}
    now = int(time.time())
    running = set()
    spans = _trip_spans(slug, db)
    for d in candidate_days(now):
        active = db.active_services(d)
        if not active:
            continue
        rel = now - service_midnight(d)
        running.update(r for _, _, r, sv, _, _, first, last in spans if sv in active and first - 900 <= rel <= last + 900)
    return villavesa.fetch(running, set(db.routes()))


def fix_ts(slug, t):
    if t and slug in LOCAL_EPOCH:
        off = datetime.fromtimestamp(t, TZ).utcoffset().total_seconds()
        return int(t - off)
    return t


def feed_for(slug, kind, ttl=RT_TTL):
    url = AGENCIES[slug]["rt"].get(kind)
    return get_feed(url, ttl, slug) if url else None


def refresh(slugs, kinds):
    jobs = [(s, k) for s in slugs for k in kinds if s in AGENCIES and AGENCIES[s]["rt"].get(k)]
    list(_pool.map(lambda a: feed_for(*a), jobs))


# ---- real-time entities of operators the importer cut to Euskal Herria

_region_cache = {}


def is_national(slug):
    return slug in store.BBOX_AGENCIES


def is_cut(slug):
    """True when the importer left trips out of this operator (every stop outside Euskal Herria)."""
    try:
        return is_national(slug) or DBS[slug].dropped() > 0
    except Exception:
        return False


def region_ids(slug):
    """(trip ids, route ids, stop ids) kept in the operator's database."""
    db = DBS[slug]
    key = (slug, db.version)
    if key not in _region_cache:
        ids = ({r[0] for r in db.q("SELECT trip_id FROM trips")}, {r[0] for r in db.q("SELECT route_id FROM routes")},
               {r[0] for r in db.q("SELECT stop_id FROM stops")})
        for k in [k for k in _region_cache if k[0] == slug]:
            del _region_cache[k]
        _region_cache[key] = ids
    return _region_cache[key]


def region_items(slug, kind, items):
    """Entities of a real-time feed that belong to the lines kept for Euskal Herria. Regional operators are
    untouched unless some of their trips were cut; national ones (Renfe) lose everything outside."""
    if not items or slug not in DBS or not is_cut(slug):
        return items
    national = is_national(slug)
    try:
        trips, routes, stops = region_ids(slug)
        if kind == "vehicles":
            return [v for v in items if ((v.get("trip") or {}).get("trip_id") in trips
                                         if (v.get("trip") or {}).get("trip_id") else not national)]
        if kind == "trips":
            return [t for t in items if (t.get("trip") or {}).get("trip_id") in trips]
        out = []
        for a in items:
            ents = [e for e in a.get("entities") or [] if e.get("route_id") or e.get("stop_id")]
            if (any(e.get("route_id") in routes or e.get("stop_id") in stops for e in ents) if ents else not national):
                out.append(a)
        return out
    except Exception:
        log.exception("region filter failed for %s", slug)
        return items


def feed_stats(slug, kind):
    """Return dict(n, age, status) for an agency feed (already cached)."""
    url = AGENCIES[slug]["rt"].get(kind)
    if not url:
        return {"status": "none", "n": 0}
    f = _feeds.get(url)
    if not f or not f.data:
        return {"status": "unknown", "n": 0}
    key = {"vehicles": "vehicles", "trips": "trip_updates", "alerts": "alerts"}[kind]
    n = len(region_items(slug, kind, f.data[key]))
    ts = f.data["timestamp"]  # header timestamps are true UTC even for skewed feeds
    age = int(time.time() - ts) if ts else None
    if f.error and n == 0:
        st = "error"
    elif n == 0:
        st = "empty"
    elif kind != "alerts" and age is not None and age > RT_MAX_AGE:
        st = "stale"
    else:
        st = "live"
    return {"status": st, "n": n, "age": age}


# --------------------------------------------------------------------------- real-time merge

def nid(s):
    return s[:-2] if s and s.endswith(".0") else s


def tu_index(slug):
    """trip_id -> list of trip updates: the GTFS-RT feed, plus updates derived from Lurraldebus live arrivals.

    The feed wins when it has an update for the same trip (all Lurraldebus feeds are empty today)."""
    base = _feed_tu_index(slug)
    if not is_lb(slug):
        return base
    live = lb_tus(slug)
    if not live:
        return base
    merged = dict(live)
    merged.update(base)
    return merged


def _feed_tu_index(slug):
    """trip_id -> list of trip updates (fresh feed only)."""
    f = feed_for(slug, "trips")
    if not f or not f.data:
        return {}
    ts = f.data["timestamp"]
    if ts and time.time() - ts > RT_MAX_AGE * 3:
        return {}
    idx = _tu_cache.get(slug)
    if idx and idx[0] is f.data:
        return idx[1]
    out = {}
    drop_zero = AGENCIES[slug].get("quirks", {}).get("zero_delay_untracked")
    for tu in f.data["trip_updates"]:
        tid = (tu.get("trip") or {}).get("trip_id")
        if tid and drop_zero:
            tu = _drop_untracked(tu)
        if tid and tu:
            out.setdefault(tid, []).append(tu)
    _tu_cache[slug] = (f.data, out)
    return out


def _drop_untracked(tu):
    """Txik Txak style feeds publish an update for every trip of the day, tracked or not.

    A bus that is really followed has a delay that is never exactly 0 s and is carried along the whole trip
    (measured on the live feed: 7.1 min on every stop of a late bus). A trip whose every delay is exactly 0 is
    just the timetable echoed back: it must not be shown as "live" nor produce a vehicle on the map.
    What such a trip can still carry is real information: stops flagged SKIPPED (roadworks and detours
    announced in the alerts feed), so those are kept, stripped of their fake times."""
    if (tu.get("trip") or {}).get("rel") == 3:
        return tu                      # a cancellation is always information
    events = [e for s in tu["stus"] for e in (s.get("arr"), s.get("dep")) if e and e.get("delay") is not None]
    if not events or any(e["delay"] != 0 for e in events):
        return tu
    skipped = [{"seq": s.get("seq"), "stop_id": s.get("stop_id"), "rel": 1} for s in tu["stus"] if s.get("rel") == 1]
    return dict(tu, stus=skipped) if skipped else None


_tu_cache = {}


def pick_tu(tus, sdate):
    if not tus:
        return None
    key = sdate.strftime("%Y%m%d")
    for tu in tus:
        sd = tu["trip"].get("start_date")
        if sd and sd == key:
            return tu
    for tu in tus:
        if not tu["trip"].get("start_date"):
            return tu
    return None


def effective_times(slug, rows, sdate, tu):
    """Merge scheduled stop_times rows with a trip update.

    Returns list of dicts with scheduled and expected epoch times and the source:
    'rt' (reported by feed), 'est' (delay propagated), 'sched' (no real-time data).
    """
    mid = service_midnight(sdate)
    out = []
    by_seq, by_stop = {}, {}
    cancelled = False
    if tu:
        cancelled = tu["trip"].get("rel") == 3
        for s in tu["stus"]:
            if s.get("seq") is not None:
                by_seq[s["seq"]] = s
            if s.get("stop_id"):
                by_stop.setdefault(nid(s["stop_id"]), s)
    cur = None
    first_delay = None
    # first pass to find the initial delay (used for stops before the first update)
    def ev_time(ev, sched):
        if not ev:
            return None
        if ev.get("time"):
            return fix_ts(slug, ev["time"])
        if ev.get("delay") is not None:
            return sched + ev["delay"]
        return None

    for r in rows:
        sa, sd = mid + r["arr"], mid + r["dep"]
        stu = None
        if tu:
            stu = by_seq.get(r["seq"])
            if stu is None:
                cand = by_stop.get(nid(r["stop_id"]))
                if cand is not None and cand.get("seq") in (None, r["seq"]):
                    stu = cand
        item = {"seq": r["seq"], "stop_id": r["stop_id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
                "station_id": r["station_id"], "sched_arr": sa, "sched_dep": sd, "arr": sa, "dep": sd,
                "src": "sched", "skipped": False}
        if stu is not None:
            if stu.get("rel") == 1:
                item["skipped"] = True
            a = ev_time(stu.get("arr"), sa)
            d = ev_time(stu.get("dep"), sd)
            if a is None and d is None:
                stu = None
            else:
                if a is None:
                    a = d if d >= sa else sa + (d - sd)
                if d is None:
                    d = a if a >= sd else sd + (a - sa)
                # one of the two events is wildly off while the other is sane (seen: arrival 3.8 h early,
                # departure on time): trust the sane one
                if abs(a - sa) > 3 * 3600 >= abs(d - sd):
                    a = d
                elif abs(d - sd) > 3 * 3600 >= abs(a - sa):
                    d = a
                if abs(a - sa) > 4 * 3600 and abs(d - sd) > 4 * 3600:
                    return [dict(i, arr=i["sched_arr"], dep=i["sched_dep"], src="sched") for i in
                            _plain(rows, mid)], cancelled
                item.update(arr=a, dep=max(d, a), src="rt")
                cur = d - sd if stu.get("dep") else a - sa
                if first_delay is None:
                    first_delay = cur
        if stu is None and cur is not None and tu:
            item.update(arr=sa + cur, dep=sd + cur, src="est")
        out.append(item)
    if tu and first_delay is not None:
        # stops before the first update: assume the same delay
        for it in out:
            if it["src"] != "sched":
                break
            it.update(arr=it["sched_arr"] + first_delay, dep=it["sched_dep"] + first_delay, src="est")
    return out, cancelled


def _plain(rows, mid):
    return [{"seq": r["seq"], "stop_id": r["stop_id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
             "station_id": r["station_id"], "sched_arr": mid + r["arr"], "sched_dep": mid + r["dep"],
             "skipped": False} for r in rows]


def resolve_service_date(db, trip, rows, now, start_date=None):
    """Pick the service day on which this trip is currently running (or runs next)."""
    from datetime import datetime as dt
    if start_date:
        try:
            return dt.strptime(start_date, "%Y%m%d").date()
        except ValueError:
            pass
    if not rows:
        return candidate_days(now)[1]
    first, last = rows[0]["dep"], rows[-1]["arr"]
    best = None
    for d in candidate_days(now)[:2]:
        if trip["service_id"] not in db.active_services(d):
            continue
        mid = service_midnight(d)
        if mid + first - 3600 <= now <= mid + last + 4 * 3600:
            return d
        best = best or d
    return best or candidate_days(now)[1]


_WHITES = {"", "FFFFFF", "F2F5F5", "000000"}
_color_policy = {}


def _official_colors_usable(db):
    """Do this operator's route colours actually tell lines apart? (several distinct non-white colours,
    or a single-line operator). Many feeds use one colour (or white) for every line."""
    key = (db.slug, db.version)
    if key not in _color_policy:
        routes = db.routes().values()
        distinct = {r["color"].upper() for r in routes if r["color"].upper() not in _WHITES}
        _color_policy[key] = len(distinct) >= 3 or (len(distinct) >= 1 and len(routes) <= 2)
    return _color_policy[key]


def auto_color(label):
    """Stable, readable colour derived from the line label (used when the operator publishes none)."""
    h = zlib.crc32((label or "").encode()) % 360
    # HSL(h, 62%, 40%) -> hex
    sat, lig = 0.62, 0.40
    c = (1 - abs(2 * lig - 1)) * sat
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = lig - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return "%02X%02X%02X" % tuple(round((v + m) * 255) for v in (r, g, b))


def route_style(db, r):
    """(color, text_color, is_auto) for a route row."""
    col = r["color"].upper()
    if _official_colors_usable(db) and col not in ("", "FFFFFF", "F2F5F5"):
        return r["color"], r["text_color"], False
    label = r["short"] or r["long"] or r["route_id"]
    return auto_color(label), "FFFFFF", True


def line_info(db, route_id):
    r = db.routes().get(route_id)
    if not r:
        return {"line": route_id or "", "color": "", "text_color": "", "mode": "bus", "long": ""}
    color, text, _ = route_style(db, r)
    long_ = r["long"] or route_long(db.slug, r)         # national feeds: "first stop → last stop" when unnamed
    return {"line": r["short"] or long_ or r["route_id"], "color": color, "text_color": text,
            "mode": r["mode"], "long": long_}


# --------------------------------------------------------------------------- Lurraldebus live arrivals
#
# lurraldebus.eus publishes, per stop, the minutes until the next bus of every line (no trip ids, no GPS).
# Each prediction is matched to the scheduled trip it most plausibly belongs to (same line, scheduled time
# close to the predicted one, same direction) and stored as a synthetic GTFS-RT style trip update. From there
# the existing machinery does the rest: departures show live times, trip pages show the delay propagated to
# the other stops, and the estimated-vehicle code places the bus on the map like it does for Euskotren trains.

LB_EARLY, LB_LATE = 25 * 60, 60 * 60  # search window (predicted - scheduled); the cost below decides, not this edge
LB_MAX_COST = 30                      # a match whose base cost (see lb_match) exceeds this is rejected
LB_OBS_TTL = 240                      # an observation keeps feeding trip updates for this long (s)
LB_USER_AGE = 30                      # a stop opened by a user is refreshed when older than this (s)
LB_TRACK_AGE = 100                    # the tracker refreshes a stop when older than this (s)
LB_TRACK_AHEAD = 25 * 60              # it watches stops that each active trip reaches within this time (s)
LB_CYCLE = 120                        # target seconds per tracker cycle
LB_SPACING = 1.2                      # minimum seconds between two tracker requests
LB_IDLE_AFTER = 120                   # a map view counts as "somebody is watching" for this long (s)
LB_VIEW_PAD = 0.02                    # degrees (~2 km) added around the visible map area
LB_TRACK = os.environ.get("LURRALDEBUS_TRACK", "1") != "0"
try:
    LB_MAX_POLL = int(os.environ.get("LURRALDEBUS_MAX_STOPS", "60"))   # stops per cycle
except ValueError:
    LB_MAX_POLL = 60

LB = lurraldebus.client
_lb_obs = {}        # (slug, trip_id, date) -> {"stus": {seq: obs}, "ts": float, "occ": int|None}
_lb_lock = threading.Lock()
_lb_ver = [0]       # bumped whenever observations change
_lb_tus_cache = {}  # slug -> (version, built_at, {trip_id: [tu]})
_lb_views = []      # [(time, s, w, n, e)] map areas that clients are looking at
_lb_town = {}       # (slug, db.version, tix) -> town of the trip's last stop
_lb_wake = threading.Event()   # set when a new area needs covering
_lb_stopset = {}    # (slug, db.version) -> {stop_id: (lat, lon)}
_lb_routes = {}     # (slug, db.version) -> {short: [route_id]}
_lb_dest = {}       # (slug, db.version, tix) -> tokens of the terminal stop name
_lb_spans = {}      # (slug, db.version) -> [(tix, service_id, first_dep, last_arr)]


def is_lb(slug):
    i = AGENCIES.get(slug)
    return bool(i and i["name"].endswith("(Lurraldebus)"))


def lb_slugs():
    return [s for s in AGENCIES if is_lb(s) and AGENCIES[s]["ready"]]


def lb_note_view(s, w, n, e):
    """A client is looking at this map area with buses visible: the tracker should cover it."""
    now = time.time()
    pad = LB_VIEW_PAD
    with _lb_lock:
        covered = any(now - v[0] < LB_IDLE_AFTER and v[1] - pad <= s and v[2] - pad <= w and n <= v[3] + pad
                      and e <= v[4] + pad for v in _lb_views)
        _lb_views[:] = [v for v in _lb_views if now - v[0] < LB_IDLE_AFTER and v[1:] != (s, w, n, e)][-30:]
        _lb_views.append((now, s, w, n, e))
    if not covered:
        _lb_wake.set()     # a new area: do not wait for the end of the current tracker cycle
        _bz_wake.set()


def _lb_active_views(now):
    with _lb_lock:
        return [v[1:] for v in _lb_views if now - v[0] < LB_IDLE_AFTER]


def _lb_stops(slug):
    db = DBS[slug]
    k = (slug, db.version)
    if k not in _lb_stopset:
        if len(_lb_stopset) > 20:
            _lb_stopset.clear()
        _lb_stopset[k] = {r[0]: (r[1], r[2]) for r in db.q("SELECT stop_id, lat, lon FROM stops")}
    return _lb_stopset[k]


def _lb_has_stop(slug, stop_id):
    return stop_id in _lb_stops(slug)


def _lb_route_ids(slug, line):
    db = DBS[slug]
    k = (slug, db.version)
    if k not in _lb_routes:
        m = {}
        for r in db.routes().values():
            m.setdefault(r["short"], []).append(r["route_id"])
        _lb_routes[k] = m
    return _lb_routes[k].get(line, [])


def _tokens(s):
    return set(re.findall(r"[a-z0-9]{4,}", norm(s)))


def _lb_dest_tokens(slug, db, tix):
    k = (slug, db.version, tix)
    if k not in _lb_dest:
        if len(_lb_dest) > 50000:
            _lb_dest.clear()
        r = db.q("SELECT s.name FROM stop_times st JOIN stops s ON s.stop_id=st.stop_id "
                 "WHERE st.tix=? ORDER BY st.seq DESC LIMIT 1", (tix,))
        _lb_dest[k] = _tokens(r[0][0] if r else "")
    return _lb_dest[k]


def _lb_candidates(slug, stop_id, line, exp):
    """Scheduled calls of `line` at the stop whose time is plausible for a predicted arrival `exp`."""
    rids = _lb_route_ids(slug, line)
    if not rids:
        return []
    db = DBS[slug]
    ph = ",".join("?" * len(rids))
    out = []
    for d in candidate_days(exp):
        active = db.active_services(d)
        if not active:
            continue
        mid = service_midnight(d)
        for r in db.q("SELECT st.tix, st.seq, st.arr, t.trip_id, t.service_id, t.route_id, t.direction FROM stop_times st "
                      "JOIN trips t ON t.tix=st.tix WHERE st.stop_id=? AND t.route_id IN (%s) "
                      "AND st.arr BETWEEN ? AND ?" % ph, (stop_id, *rids, exp - mid - LB_LATE, exp - mid + LB_EARLY)):
            if r["service_id"] in active:
                out.append({"slug": slug, "tix": r["tix"], "seq": r["seq"], "trip_id": r["trip_id"],
                            "route_id": r["route_id"], "direction": r["direction"],
                            "date": d.strftime("%Y%m%d"), "sched": mid + r["arr"]})
    return out


def lb_match(stop_id, arrivals, fetched, prev=None, known=None):
    """Assign every live arrival of a stop to one scheduled trip. Returns [(arrival, candidate)] (matched only).

    The page gives no trip id, so the trip is inferred. cost = minutes between prediction and schedule (a bus
    ahead of its timetable is penalised double: they rarely run early), then adjusted:
      +6   the destination does not look like the trip's terminal stop while another candidate's does;
      -6   this arrival was assigned to the same trip in the previous poll of this stop (no flip-flopping);
      -12  the trip already has a fresh prediction at another stop with a similar delay (so the same bus is
           not matched to different trips at different stops, which would draw it twice).
    Candidates whose base cost exceeds LB_MAX_COST are rejected (an implausible delay is worse than no data)."""
    prev, known = prev or {}, known or {}
    slugs = [s for s in lb_slugs() if _lb_has_stop(s, stop_id)]
    used, out = set(), []
    for a in sorted(arrivals, key=lambda x: x["minutes"]):
        exp = fetched + a["minutes"] * 60
        cands = []
        for s in slugs:
            cands += _lb_candidates(s, stop_id, a["line"], exp)
        cands = [c for c in cands if (c["slug"], c["trip_id"], c["date"]) not in used]
        for c in cands:
            delay = (exp - c["sched"]) / 60.0
            c["base"] = delay if delay >= 0 else -2 * delay
        cands = [c for c in cands if c["base"] <= LB_MAX_COST]
        if not cands:
            continue
        want = _tokens(a["headsign"])
        for c in cands:
            c["dest"] = len(want & _lb_dest_tokens(c["slug"], DBS[c["slug"]], c["tix"])) if want else 0
        any_dest = any(c["dest"] for c in cands)

        def cost(c):
            v = c["base"]
            if any_dest and not c["dest"]:
                v += 6
            p = prev.get((c["slug"], c["trip_id"], c["date"], c["seq"]))
            if p is not None and abs(p - exp) <= 240:
                v -= 6
            k = known.get((c["slug"], c["trip_id"], c["date"]))
            if k is not None and abs((exp - c["sched"]) - k) <= 300:
                v -= 12
            return v
        best = min(cands, key=cost)
        used.add((best["slug"], best["trip_id"], best["date"]))
        out.append((a, dict(best, exp=exp)))
    return out


def lb_ingest(res):
    """Store the live arrivals of a stop result as observations. Returns the number of matched arrivals."""
    if not res or res["status"] != "ok":
        return 0
    stop_id, ts = res["stop_id"], res["fetched"]
    with _lb_lock:
        prev, known = {}, {}
        for k, rec in _lb_obs.items():
            for seq, ob in rec["stus"].items():
                if ob["stop_id"] == stop_id:
                    prev[(k[0], k[1], k[2], seq)] = ob["E"]
                elif ts - ob["ts"] <= LB_OBS_TTL:
                    known[k] = ob["delay"]
    matches = lb_match(stop_id, res["arrivals"], ts, prev, known)
    lines = {a["line"] for a in res["arrivals"]}
    with _lb_lock:
        # a bus predicted earlier for this stop that this poll no longer reports at the same place was
        # (probably) assigned to another trip now: forget it. Buses that already passed are kept.
        for rec in _lb_obs.values():
            for seq, ob in list(rec["stus"].items()):
                if ob["stop_id"] == stop_id and ob["line"] in lines and ob["ts"] < ts and ob["E"] > ts - 30:
                    del rec["stus"][seq]
        for a, c in matches:
            rec = _lb_obs.setdefault((c["slug"], c["trip_id"], c["date"]), {"stus": {}, "ts": 0, "occ": None})
            rec["stus"][c["seq"]] = {"stop_id": stop_id, "line": a["line"], "E": int(c["exp"]), "ts": ts,
                                     "flags": a["flags"], "delay": int(c["exp"] - c["sched"])}
            rec["ts"] = max(rec["ts"], ts)
            if a["occupancy"] is not None:
                rec["occ"] = a["occupancy"]
        _lb_ver[0] += 1
    unmatched = len(res["arrivals"]) - len(matches)
    if unmatched:
        log.debug("lurraldebus stop %s: %d of %d arrivals not matched to a scheduled trip",
                  stop_id, unmatched, len(res["arrivals"]))
    return len(matches)


def lb_fetch(stop_id, max_age=LB_USER_AGE, background=False):
    """Cached live result for a stop (ingesting it once). Returns (result or None, freshly_ingested)."""
    res = LB.get(stop_id, max_age=max_age, background=background)
    if res and not res.get("stale") and not res.get("_ing"):
        res["_ing"] = True
        return res, lb_ingest(res) > 0
    return res, False


def lb_gc(now=None):
    now = now or time.time()
    with _lb_lock:
        for k, rec in list(_lb_obs.items()):
            for seq, ob in list(rec["stus"].items()):
                if now - ob["ts"] > LB_OBS_TTL * 2:
                    del rec["stus"][seq]
            if not rec["stus"]:
                del _lb_obs[k]
        _lb_ver[0] += 1


def lb_tus(slug):
    """trip_id -> [trip update] built from the observations that are still fresh."""
    now = time.time()
    with _lb_lock:
        hit = _lb_tus_cache.get(slug)
        if hit and hit[0] == _lb_ver[0] and now - hit[1] < 5:
            return hit[2]
        out = {}
        for (s, tid, date), rec in _lb_obs.items():
            if s != slug:
                continue
            stus = [{"seq": seq, "stop_id": ob["stop_id"], "arr": {"time": ob["E"]}, "dep": {"time": ob["E"]},
                     "flags": ob["flags"]} for seq, ob in sorted(rec["stus"].items()) if now - ob["ts"] <= LB_OBS_TTL]
            if stus:
                out.setdefault(tid, []).append({"trip": {"trip_id": tid, "start_date": date}, "stus": stus,
                                                "timestamp": int(rec["ts"]), "lb": True, "occupancy": rec["occ"]})
        _lb_tus_cache[slug] = (_lb_ver[0], now, out)
        return out


def lb_refresh_station(stop_ids, now=None):
    """Fetch live arrivals for the stops of a station (interactive request). True when new data was stored."""
    changed = False
    for sid in stop_ids[:4]:
        if any(_lb_has_stop(s, sid) for s in lb_slugs()):
            changed |= lb_fetch(sid)[1]
    return changed


def lb_headsign(slug, tix):
    """Destination of one trip for Lurraldebus operators (their GTFS has no headsign): the town of its last stop,
    e.g. "Orio - Aita Lertxundi 28" -> "Orio". Short-turn trips (Donostia-Zumaia line ending in Orio) differ."""
    if not is_lb(slug):
        return None
    db = DBS[slug]
    k = (slug, db.version, tix)
    if k not in _lb_town:
        if len(_lb_town) > 50000:
            _lb_town.clear()
        r = db.q("SELECT s.name FROM stop_times st JOIN stops s ON s.stop_id=st.stop_id "
                 "WHERE st.tix=? ORDER BY st.seq DESC LIMIT 1", (tix,))
        _lb_town[k] = r[0][0].split(" - ")[0].strip() if r and r[0][0] else None
    return _lb_town[k]


def lb_status(items):
    """Real-time banner state for a Lurraldebus station: 'live' when any row has live data."""
    if any(i.get("rt") for i in items):
        return "live"
    return "error" if LB.stats()["state"] == "paused" else "lb_none"


def lb_agency_status(slug):
    """Status of the live-arrivals source for the Info table: n = trips currently tracked for this operator."""
    st = LB.stats()["state"]
    with _lb_lock:
        n = sum(1 for k in _lb_obs if k[0] == slug)
    status = {"live": "live", "paused": "error", "idle": "idle", "off": "none"}[st]
    return {"status": status, "n": n if status == "live" else 0}


def _lb_trip_spans(slug):
    db = DBS[slug]
    k = (slug, db.version)
    if k not in _lb_spans:
        _lb_spans.clear()
        _lb_spans[k] = [(r[0], r[1], r[2], r[3]) for r in db.q(
            "SELECT st.tix, t.service_id, MIN(st.dep), MAX(st.arr) FROM stop_times st "
            "JOIN trips t ON t.tix=st.tix GROUP BY st.tix")]
    return _lb_spans[k]


def lb_plan(now=None, limit=None, views=None):
    """Smallest practical set of stops to poll so that every running (or about to start) trip is seen.

    Only trips that reach a stop inside one of the watched map areas (`views`, default: what clients are
    looking at right now) are considered. Each trip can be seen from any such stop it reaches within
    LB_TRACK_AHEAD; a greedy set cover picks the stops that serve the most uncovered trips. Stops that
    recently answered "no information" are skipped while that answer is fresh.
    Returns [(stop_id, trips_covered)] in poll order."""
    now = now or time.time()
    views = _lb_active_views(now) if views is None else views
    if not views:
        return []

    def watched(pos):
        return any(s - LB_VIEW_PAD <= pos[0] <= n + LB_VIEW_PAD and w - LB_VIEW_PAD <= pos[1] <= e + LB_VIEW_PAD
                   for s, w, n, e in views)
    trips = []
    for slug in lb_slugs():
        db = DBS[slug]
        spans = _lb_trip_spans(slug)
        pos = _lb_stops(slug)
        for d in candidate_days(now):
            active = db.active_services(d)
            if not active:
                continue
            mid = service_midnight(d)
            for tix, sid, lo, hi in spans:
                if sid in active and mid + lo <= now + 600 and mid + hi >= now - 180:
                    cands = {r[0] for r in db.q("SELECT stop_id FROM stop_times WHERE tix=? AND arr BETWEEN ? AND ?",
                                                (tix, now - 180 - mid, now + LB_TRACK_AHEAD - mid))}
                    cands = {c for c in cands if c in pos and watched(pos[c]) and not _lb_known_empty(c, now)}
                    if cands:
                        trips.append(cands)
    by_stop = {}
    for i, c in enumerate(trips):
        for s in c:
            by_stop.setdefault(s, set()).add(i)
    uncovered, plan = set(range(len(trips))), []
    while uncovered and len(plan) < (limit or LB_MAX_POLL):
        stop, covers = max(((s, v & uncovered) for s, v in by_stop.items()), key=lambda x: (len(x[1]), x[0]))
        if not covers:
            break
        plan.append((stop, len(covers)))
        uncovered -= covers
    return plan


def _lb_known_empty(stop_id, now):
    r = LB.peek(stop_id)
    return bool(r and r["status"] == "empty" and now - r["fetched"] < lurraldebus.TTL_EMPTY)


def lb_tracker_loop():
    """Background poller: only active while a client is looking at a map area with buses, always rate limited."""
    log.info("lurraldebus tracker %s", "enabled" if lurraldebus.ENABLED and LB_TRACK else "disabled")
    while True:
        try:
            if not (lurraldebus.ENABLED and LB_TRACK):
                time.sleep(30)
                continue
            _lb_wake.clear()
            t0 = time.time()
            plan = lb_plan(t0)
            if not plan:
                _lb_wake.wait(5)
                continue
            for stop_id, _ in plan:
                t_call = time.time()
                res, _ing = lb_fetch(stop_id, LB_TRACK_AGE, background=True)
                if res and res["fetched"] >= t_call - 0.01:   # a request was really sent
                    time.sleep(LB_SPACING)
            lb_gc()
            _lb_wake.wait(max(2.0, LB_CYCLE - (time.time() - t0)))
        except Exception:
            log.exception("lurraldebus tracker")
            time.sleep(10)


# --------------------------------------------------------------------------- departures

def lb_peers(slug, station_id):
    """[slug] plus the other Lurraldebus operators that serve the same physical stop (same id, same place).

    The seven operators share one stop id space, so a stop like 1713 (Tolosa, Zezen Plaza) exists in
    Tolosaldea, Tbh and Guipuzkoana; it is one station for the user."""
    if not is_lb(slug):
        return [slug]
    st = DBS[slug].station(station_id)
    out = [slug]
    for s in lb_slugs():
        if s != slug and st:
            o = DBS[s].station(station_id)
            if o and haversine(st["lat"], st["lon"], o["lat"], o["lon"]) < 100:
                out.append(s)
    return out


# --------------------------------------------------------------------------- theoretical timetable for a date

def today_local():
    return datetime.now(TZ).date()


def date_limits(slugs):
    """Selectable (min, max) dates for these operators: the window around today, narrowed to the
    period their published timetables cover (union when several operators share a stop)."""
    today = today_local()
    lo, hi = today - timedelta(days=SCHEDULE_PAST_DAYS), today + timedelta(days=SCHEDULE_FUTURE_DAYS)
    ranges = []
    for s in slugs:
        try:
            r = DBS[s].feed_range()
        except Exception:
            r = None
        if r:
            ranges.append((datetime.strptime(r[0], "%Y%m%d").date(), datetime.strptime(r[1], "%Y%m%d").date()))
    if ranges:
        flo, fhi = min(r[0] for r in ranges), max(r[1] for r in ranges)
        lo, hi = max(lo, flo), min(hi, fhi)
    if lo > hi:                      # feed expired or not started: keep a one-day window so the UI stays usable
        lo = hi = today
    return lo, hi


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def limits_payload(slugs):
    lo, hi = date_limits(slugs)
    return {"min": lo.strftime("%Y%m%d"), "max": hi.strftime("%Y%m%d"), "today": today_local().strftime("%Y%m%d")}


def schedule_departures(slugs, station_id, d, kind="dep"):
    """Every scheduled call at a station during calendar day d (00:00-24:00), purely from the timetable.

    Includes after-midnight trips of the previous service day (GTFS times >= 24:00). No real-time data."""
    col = "dep" if kind == "dep" else "arr"
    cmp_ = "s2.seq>st.seq" if kind == "dep" else "s2.seq<st.seq"
    out, found = [], False
    for slug in slugs:
        db = DBS[slug]
        stops = db.station_stops(station_id)
        if not stops:
            continue
        found = True
        ph = ",".join("?" * len(stops))
        for sd, lo, hi in ((d - timedelta(days=1), 86400, 2 * 86400), (d, 0, 86400)):
            active = db.active_services(sd)
            if not active:
                continue
            mid = service_midnight(sd)
            sql = ("SELECT st.seq, st.stop_id, st.%s AS tm, t.tix, t.trip_id, t.route_id, t.service_id, t.headsign "
                   "FROM stop_times st JOIN trips t ON t.tix=st.tix "
                   "WHERE st.stop_id IN (%s) AND st.%s >= ? AND st.%s < ? "
                   "AND EXISTS (SELECT 1 FROM stop_times s2 WHERE s2.tix=st.tix AND %s)" % (col, ph, col, col, cmp_))
            for r in db.q(sql, (*stops, lo, hi)):
                if r["service_id"] not in active:
                    continue
                li = line_info(db, r["route_id"])
                sched = mid + r["tm"]
                out.append({"agency": slug, "trip_id": r["trip_id"], "route_id": r["route_id"], "line": li["line"],
                            "color": li["color"], "text_color": li["text_color"], "mode": li["mode"],
                            "headsign": r["headsign"] or lb_headsign(slug, r["tix"]) or li["long"],
                            "sched": sched, "expected": sched, "delay": 0, "rt": None, "cancelled": False,
                            "date": sd.strftime("%Y%m%d"), "stop_id": r["stop_id"]})
    if not found:
        return None
    out.sort(key=lambda x: (x["sched"], _natkey(x["line"])))
    return out[:SCHEDULE_MAX_ROWS]


_lines_cache = {}


def station_lines(slugs, station_id):
    """Lines that call at a station today (for the line filter), one entry per line. Cached for ten minutes."""
    today = today_local()
    key = (tuple(slugs), station_id, today)
    hit = _lines_cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    seen = {}
    for it in schedule_departures(slugs, station_id, today) or []:
        k = it["agency"] + "|" + it["route_id"]
        if k not in seen:
            seen[k] = {f: it[f] for f in ("agency", "route_id", "line", "color", "text_color", "mode")}
    out = sorted(seen.values(), key=lambda x: _natkey(x["line"]))
    if len(_lines_cache) > 500:
        _lines_cache.clear()
    _lines_cache[key] = (time.time(), out)
    return out


def route_schedule(slug, route_id, d):
    """Trips of a line running on calendar day d, grouped by direction (timetable only)."""
    db = DBS[slug]
    groups = {}
    for sd, lo, hi in ((d - timedelta(days=1), 86400, 2 * 86400), (d, 0, 86400)):
        active = db.active_services(sd)
        if not active:
            continue
        mid = service_midnight(sd)
        sql = ("SELECT t.tix, t.trip_id, t.service_id, t.headsign, t.direction, "
               "(SELECT s.dep FROM stop_times s WHERE s.tix=t.tix ORDER BY s.seq LIMIT 1) AS first_dep, "
               "(SELECT s.arr FROM stop_times s WHERE s.tix=t.tix ORDER BY s.seq DESC LIMIT 1) AS last_arr, "
               "(SELECT n.name FROM stop_times s JOIN stops n ON n.stop_id=s.stop_id WHERE s.tix=t.tix ORDER BY s.seq LIMIT 1) AS from_name "
               "FROM trips t WHERE t.route_id=?")
        for r in db.q(sql, (route_id,)):
            if r["service_id"] not in active or r["first_dep"] is None or not (lo <= r["first_dep"] < hi):
                continue
            groups.setdefault(r["direction"], []).append({
                "trip_id": r["trip_id"], "dep": mid + r["first_dep"], "arr": mid + (r["last_arr"] or r["first_dep"]),
                "from": r["from_name"], "headsign": r["headsign"] or lb_headsign(slug, r["tix"]) or "",
                "date": sd.strftime("%Y%m%d")})
    out = []
    for direction, trips in sorted(groups.items(), key=lambda kv: (kv[0] if kv[0] is not None else 9)):
        trips.sort(key=lambda x: x["dep"])
        heads = {}
        for x in trips:
            heads[x["headsign"]] = heads.get(x["headsign"], 0) + 1
        main = max(heads, key=heads.get) if heads else ""
        out.append({"direction": direction, "headsign": main, "trips": trips[:SCHEDULE_MAX_ROWS]})
    return out


def departures(slug, station_id, kind="dep", limit=15, now=None, line=None):
    """Next calls at a station, with real-time data merged in. Lurraldebus stops are refreshed from
    lurraldebus.eus first (cached, shared and rate limited) when something is due in the next hour or so,
    and include the services of every Lurraldebus operator calling at the same stop."""
    peers = lb_peers(slug, station_id)
    res = _departures_merged(peers, station_id, kind, limit, now, line)
    if res and is_lb(slug) and not now:
        t = time.time()
        if res[0]["expected"] - t < 75 * 60 and lb_refresh_station(DBS[slug].station_stops(station_id)):
            res = _departures_merged(peers, station_id, kind, limit, now, line)
    return res


def _departures_merged(slugs, station_id, kind, limit, now, line=None):
    """line = set of (operator slug, route id): only the services of those lines."""
    out, found = [], False
    for s in slugs:
        routes = {rid for ag, rid in line if ag == s} if line else None
        if line and not routes:
            continue
        r = _departures(s, station_id, kind, limit, now, routes)
        if r is not None:
            found = True
        for it in r or []:
            it["agency"] = s
            out.append(it)
    if not found:
        return None
    out.sort(key=lambda x: x["expected"])
    return out[:limit]


def _departures(slug, station_id, kind="dep", limit=15, now=None, route_ids=None):
    now = int(now or time.time())
    db = DBS[slug]
    stops = db.station_stops(station_id)
    if not stops:
        return None
    refresh([slug], ["trips"])
    tus = tu_index(slug)
    col = "dep" if kind == "dep" else "arr"
    cmp_ = "s2.seq>st.seq" if kind == "dep" else "s2.seq<st.seq"
    ph = ",".join("?" * len(stops))
    results = []
    seen = set()
    for window_h in (4, 12, 30):
        results = []
        for d in candidate_days(now):
            active = db.active_services(d)
            if not active:
                continue
            mid = service_midnight(d)
            lo, hi = now - mid - 2400, now - mid + window_h * 3600
            sql = ("SELECT st.tix, st.seq, st.stop_id, st.arr, st.dep, t.trip_id, t.route_id, t.service_id, t.headsign, t.direction "
                   "FROM stop_times st JOIN trips t ON t.tix=st.tix "
                   "WHERE st.stop_id IN (%s) AND st.%s BETWEEN ? AND ? "
                   "AND EXISTS (SELECT 1 FROM stop_times s2 WHERE s2.tix=st.tix AND %s)" % (ph, col, cmp_))
            for r in db.q(sql, (*stops, lo, hi)):
                if r["service_id"] not in active or (route_ids and r["route_id"] not in route_ids):
                    continue
                sched = mid + r[col]
                tu = pick_tu(tus.get(r["trip_id"]), d) if tus else None
                exp, src, cancelled, skipped = sched, "sched", False, False
                occ, flags = None, []
                if tu:
                    rows = db.trip_stop_times(r["tix"])
                    eff, cancelled = effective_times(slug, rows, d, tu)
                    for e in eff:
                        if e["seq"] == r["seq"]:
                            exp = e[col]
                            src = e["src"]
                            skipped = e.get("skipped", False)
                            break
                    if tu.get("lb"):
                        occ = tu.get("occupancy")
                        flags = next((s.get("flags") or [] for s in tu["stus"] if s.get("seq") == r["seq"]), [])
                if exp < now - 45:
                    continue
                # a zero-delay update for a trip that is far away is just the timetable echoed back
                # (not for Lurraldebus: there an on-time prediction is real data)
                if src != "sched" and exp - now > 1200 and abs(exp - sched) < 60 and not (tu and tu.get("lb")):
                    src = "sched"
                li = line_info(db, r["route_id"])
                hs = r["headsign"] or lb_headsign(slug, r["tix"]) or li["long"]
                results.append({
                    "trip_id": r["trip_id"], "route_id": r["route_id"], "line": li["line"], "color": li["color"],
                    "text_color": li["text_color"], "mode": li["mode"], "headsign": hs, "sched": sched,
                    "expected": exp, "delay": exp - sched, "rt": src if src != "sched" else None,
                    "cancelled": cancelled or skipped, "skipped": skipped and not cancelled,
                    "date": d.strftime("%Y%m%d"), "stop_id": r["stop_id"], "occupancy": occ, "flags": flags})
        if len(results) >= limit:
            break
    results.sort(key=lambda x: x["expected"])
    return results[:limit]


# --------------------------------------------------------------------------- vehicles

_veh_cache = {"t": 0, "data": None}
_veh_lock = threading.Lock()
_trip_cache = {}


def _trip(db, slug, trip_id):
    k = (slug, db.version, trip_id)
    if k not in _trip_cache:
        if len(_trip_cache) > 20000:
            _trip_cache.clear()
        _trip_cache[k] = db.trip_by_id(trip_id)
    return _trip_cache[k]


def _stop_name(db, stop_id):
    r = db.q("SELECT name FROM stops WHERE stop_id=?", (stop_id,))
    if not r and stop_id and not stop_id.endswith(".0"):
        r = db.q("SELECT name FROM stops WHERE stop_id=?", (stop_id + ".0",))
    return r[0][0] if r else None


# ---- geometry helpers: follow the real track (GTFS shape) instead of a straight line

_shape_cache = {}
_dist_cache = {}
MAX_SNAP_M = 250      # a stop further than this from the shape is not snapped


def shape_geom(db, shape_id):
    """Planar (metre) version of a shape: (xs, ys, cumulative_length, lat0, cos0) or None."""
    key = (db.slug, db.version, shape_id)
    if key in _shape_cache:
        return _shape_cache[key]
    geom = None
    pts = db.shape(shape_id) if shape_id else None
    if pts and len(pts) >= 2:
        lat0 = pts[0][0]
        cos0 = math.cos(math.radians(lat0))
        xs = [p[1] * cos0 * 111320.0 for p in pts]
        ys = [p[0] * 110540.0 for p in pts]
        cum = [0.0]
        for i in range(1, len(xs)):
            cum.append(cum[-1] + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))
        geom = (xs, ys, cum, pts, cos0)
    if len(_shape_cache) > 400:
        _shape_cache.clear()
    _shape_cache[key] = geom
    return geom


def _project(geom, lat, lon, dmin, dmax):
    """Closest point of the shape to (lat, lon) searching only between along-track distances dmin..dmax."""
    xs, ys, cum, _, cos0 = geom
    px, py = lon * cos0 * 111320.0, lat * 110540.0
    n = len(xs)
    lo = max(bisect.bisect_right(cum, dmin) - 1, 0)
    hi = min(bisect.bisect_left(cum, dmax), n - 2)
    best = None
    for i in range(lo, hi + 1):
        ax, ay, bx, by = xs[i], ys[i], xs[i + 1], ys[i + 1]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
        ex, ey = ax + t * dx, ay + t * dy
        d2 = (px - ex) ** 2 + (py - ey) ** 2
        if best is None or d2 < best[0]:
            best = (d2, cum[i] + t * math.sqrt(l2))
    return (best[1], math.sqrt(best[0])) if best else None


def stop_distances(db, trip, rows):
    """Along-shape distance (m) of every stop of a trip, in stop order (None when it cannot be snapped)."""
    key = (db.slug, db.version, trip["tix"])
    if key in _dist_cache:
        return _dist_cache[key]
    geom = shape_geom(db, trip.get("shape_id"))
    out = [None] * len(rows)
    if geom:
        total = geom[2][-1]
        prev, prev_ll = 0.0, None
        for i, r in enumerate(rows):
            if not r["lat"] or not r["lon"]:
                continue
            # search window: forward from the previous stop, within a generous multiple of the straight distance
            if prev_ll is None:
                lo, hi = 0.0, total
            else:
                straight = haversine(prev_ll[0], prev_ll[1], r["lat"], r["lon"])
                lo, hi = max(prev - 30, 0.0), prev + max(4 * straight, 1500.0)
            res = _project(geom, r["lat"], r["lon"], lo, hi)
            if res and res[1] <= MAX_SNAP_M:
                out[i] = res[0]
                prev, prev_ll = res[0], (r["lat"], r["lon"])
        # stops that could not be snapped (e.g. in tunnels): place them between their snapped neighbours
        known = [i for i, v in enumerate(out) if v is not None]
        for i0, i1 in zip(known, known[1:]):
            gap = [i for i in range(i0 + 1, i1) if rows[i]["lat"] and rows[i]["lon"]]
            if not gap or out[i1] < out[i0]:
                continue
            chain = [i0] + gap + [i1]
            seg = [haversine(rows[a]["lat"], rows[a]["lon"], rows[b]["lat"], rows[b]["lon"]) for a, b in zip(chain, chain[1:])]
            tot = sum(seg) or 1.0
            acc = 0.0
            for k, i in enumerate(gap):
                acc += seg[k]
                out[i] = out[i0] + (out[i1] - out[i0]) * acc / tot
    if len(_dist_cache) > 20000:
        _dist_cache.clear()
    _dist_cache[key] = out
    return out


def _point_at(geom, d):
    """(lat, lon, bearing) at along-track distance d."""
    xs, ys, cum, pts, _ = geom
    i = min(max(bisect.bisect_right(cum, d) - 1, 0), len(xs) - 2)
    seg = cum[i + 1] - cum[i]
    f = 0.0 if seg <= 0 else min(max((d - cum[i]) / seg, 0.0), 1.0)
    la = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f
    lo = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f
    brg = math.degrees(math.atan2(xs[i + 1] - xs[i], ys[i + 1] - ys[i])) % 360
    return la, lo, brg


def _interp(eff, now, dists=None, geom=None):
    """Estimate a position from effective times.

    Follows the shape when stops could be snapped to it, otherwise a straight line.
    Returns (lat, lon, next_stop_name, status, bearing, on_track) or None.
    """
    pts = [(e, (dists[i] if dists else None)) for i, e in enumerate(eff) if e["lat"] and e["lon"]]
    if len(pts) < 2:
        return None
    if now < pts[0][0]["dep"] or now > pts[-1][0]["arr"]:
        return None
    for (a, da), (b, db) in zip(pts, pts[1:]):
        if a["arr"] <= now <= a["dep"]:
            return a["lat"], a["lon"], a["name"], "stopped", None, False
        if a["dep"] < now < b["arr"]:
            f = (now - a["dep"]) / max(b["arr"] - a["dep"], 1)
            if geom and da is not None and db is not None and db > da:
                la, lo, brg = _point_at(geom, da + f * (db - da))
                return la, lo, b["name"], "moving", brg, True
            brg = math.degrees(math.atan2((b["lon"] - a["lon"]) * math.cos(math.radians(a["lat"])), b["lat"] - a["lat"])) % 360
            return (a["lat"] + (b["lat"] - a["lat"]) * f, a["lon"] + (b["lon"] - a["lon"]) * f,
                    b["name"], "moving", brg, False)
    return None


# ---- GPS fixes that are already old when they are published
#
# Some operators (Dbus) publish positions that are 1-2 minutes old when the feed is written, and the app adds its own
# polling on top. In a city a bus covers hundreds of metres in that time, so the marker lags behind the real bus.
# The fix is moved forward along the bus's route by its age, following the timetable: the point of the route where the
# bus was seen is turned into a scheduled time, that time is advanced by the age of the fix, and the position of the
# schedule at that time is where the bus should be now. Nothing is guessed about speed: it is the scheduled speed of
# each stretch. Measured on 339 pairs of real Dbus fixes (a fix predicted from the one before it), the displayed bus
# was a median 409 m behind the real one along its route; with this it is within 13 m on average, and the median error
# drops from 344 m to about 100 m (90th percentile from 654 m to 300 m).

ADVANCE_MAX_S = 240        # never move a fix by more than this (a bus that stopped reporting is not extrapolated for ever)
ADVANCE_MIN_S = 5          # younger fixes are used as they are
ADVANCE_MAX_OFF_M = 120    # a fix further than this from its route is off route: left alone
# Operators whose positions are advanced: those whose feed is written well after the fixes (Dbus: about 2.5 minutes
# on average, the feed is rebuilt once a minute and each bus reports about every 90 s; Bizkaibus: 130-215 s, one
# snapshot about every two minutes). ADVANCE_FIXES=<slug,slug> changes the list and ADVANCE_FIXES=none turns the
# correction off.
ADVANCE_OPERATORS = {s.strip() for s in os.environ.get("ADVANCE_FIXES", "dbus,bizkaibus").split(",")} - {"", "none", "0"}


def _time_knots(rows, dists):
    """[(distance along the shape, scheduled arrival, scheduled departure)] of the stops snapped to the shape."""
    knots = []
    for r, d in zip(rows, dists):
        if d is None or (knots and d < knots[-1][0]):
            continue
        knots.append((d, r["arr"], r["dep"]))
    return knots


def _time_at_dist(knots, d):
    """Scheduled time at which a bus that follows the timetable is d metres along the shape."""
    if d <= knots[0][0]:
        return knots[0][1]
    for (da, _, pa), (db_, ab, _) in zip(knots, knots[1:]):
        if d <= db_:
            return pa + (ab - pa) * (d - da) / max(db_ - da, 1e-6)
    return knots[-1][2]


def _dist_at_time(knots, tau):
    """Distance along the shape of a bus that follows the timetable at scheduled time tau."""
    if tau <= knots[0][1]:
        return knots[0][0]
    for (da, _, pa), (db_, ab, _) in zip(knots, knots[1:]):
        if tau <= pa:
            return da                                    # dwelling at the stop
        if tau < ab:
            return da + (db_ - da) * (tau - pa) / max(ab - pa, 1)
    return knots[-1][0]


def fix_on_route(db, trip, rows, lat, lon, stop_id):
    """Put a fix on its trip's route: {"geom", "dists", "knots", "d"} (d = metres along the shape), or None when it
    cannot be (no shape, too few stops snapped to it, further than ADVANCE_MAX_OFF_M from the route).

    The bus is searched between the stop before the one it is heading to and a little past that one."""
    geom = shape_geom(db, trip.get("shape_id"))
    if not geom:
        return None
    dists = stop_distances(db, trip, rows)
    knots = _time_knots(rows, dists)
    if len(knots) < 2:
        return None
    total = geom[2][-1]
    lo, hi = 0.0, total
    for i, r in enumerate(rows):
        if r["stop_id"] == stop_id and dists[i] is not None:
            prev = [d for d in dists[:i] if d is not None]
            lo = max((prev[-1] if prev else 0.0) - 100.0, 0.0)
            hi = min(dists[i] + 150.0, total)
            break
    res = _project(geom, lat, lon, lo, hi)
    if not res or res[1] > ADVANCE_MAX_OFF_M:
        return None
    return {"geom": geom, "dists": dists, "knots": knots, "d": res[0]}


def advance_distance(fx, d0, dt):
    """A bus d0 metres along its route dt seconds ago, following the timetable: (lat, lon, bearing, metres moved, d now)."""
    knots = fx["knots"]
    d1 = max(_dist_at_time(knots, _time_at_dist(knots, d0) + min(max(dt, 0), ADVANCE_MAX_S)), d0)
    la, lo, brg = _point_at(fx["geom"], d1)
    return la, lo, brg, d1 - d0, d1


def advance_fix(db, trip, rows, lat, lon, stop_id, dt):
    """Where a bus seen at (lat, lon) dt seconds ago, heading to stop_id, should be now.

    Returns (lat, lon, bearing, metres_moved, distance_along_route), or None when the fix should be used as it is
    (too young, no shape, not on its route...)."""
    if dt < ADVANCE_MIN_S:
        return None
    fx = fix_on_route(db, trip, rows, lat, lon, stop_id)
    return advance_distance(fx, fx["d"], dt) if fx else None


# ---- Bizkaibus: positions from the stop arrival service
#
# The Bizkaibus feed is one snapshot of every bus, rebuilt about every two minutes (130-215 s old when it arrives), and
# even advanced along the timetable it is off by about 450 m (1.4 km for one bus in ten). bizkaia.eus' stop service
# (bizkaibus.py) says, for every line at a stop, how many METRES the next two buses still have to travel, which places
# them on their route right now (within about 100 m, measured). The answer has no bus id, so each one is matched to the
# snapshot: the first bus of a line before the stop is the first one listed, and so on; a bus that the snapshot puts
# closer to the stop than the service does has already passed it (a bus cannot move backwards), and one that would have
# had to travel faster than a bus can since its snapshot is somebody else. Each match becomes an observation (trip,
# metres along its route, time) that the vehicle list advances along the timetable by its age.
#
# Who is asked: only while a client is looking at a map area with buses (the same views the Lurraldebus tracker
# uses), only for buses in view, and the fewest stops that show them: stops a little ahead of the bus, chosen greedily
# by how many buses (two per line) they would reveal. Everything is rate limited in bizkaibus.py.

BZ_SLUG = "bizkaibus"
BZ_OBS_MAX = 90           # an observation is used for this long (s): older than that it is no better than the snapshot
BZ_REFRESH = 40           # a bus whose observation is older than this is asked about again (s)
BZ_MARGIN = 350           # ask about stops at least this far ahead of the bus (m): it must not have passed them
BZ_AHEAD = 8000           # ... and at most this far (m)
BZ_TOL = 250              # slack when comparing a distance from the service with one from a snapshot (m)
BZ_VMAX = 28              # m/s: the fastest a bus can have moved since its snapshot (rejects wrong matches)
BZ_MAX_STOPS = 80         # stops asked about per tracker cycle
BZ_CYCLE = 25             # shortest tracker cycle (s)
BZ_MAX_BUSES = 400        # views covering more buses than this are not tracked (too much to ask for)
_bz_obs = {}              # trip_id -> {"t", "d", "stop", "metres", "minutes"}
_bz_lock = threading.Lock()
_bz_wake = threading.Event()
_bz_fetched = {}          # stop -> time of the answer already used
_bz_snap = {"key": None, "data": []}


def _bz_enabled():
    return bizkaibus.ENABLED and BZ_SLUG in AGENCIES and AGENCIES[BZ_SLUG]["ready"] and BZ_SLUG in DBS


def bz_build_snapshot(slug, vehicles):
    """The buses of a snapshot that can be placed on their route: [{trip, trip_id, route_id, head, fx, d, ts, sd}]
    where sd = {stop_id: metres along the route} of the stops still ahead of the bus."""
    db, out = DBS[slug], []
    for v in vehicles:
        tid = (v.get("trip") or {}).get("trip_id")
        trip = _trip(db, slug, tid) if tid else None
        if not trip or not v.get("lat") or not v.get("lon"):
            continue
        rows = db.trip_stop_times(trip["tix"])
        fx = fix_on_route(db, trip, rows, v["lat"], v["lon"], v.get("stop_id"))
        if not fx:
            continue
        sd = {}
        for r, d in zip(rows, fx["dists"]):
            if d is not None and d >= fx["d"] - BZ_TOL and r["stop_id"] not in sd:
                sd[r["stop_id"]] = d
        out.append({"trip": trip, "trip_id": tid, "route_id": trip["route_id"], "head": norm(trip.get("headsign") or ""),
                    "fx": fx, "d": fx["d"], "ts": fix_ts(slug, v.get("timestamp")) or 0, "sd": sd})
    return out


def _bz_snapshot(slug=BZ_SLUG):
    """The latest snapshot of the feed, built once per snapshot."""
    f = feed_for(slug, "vehicles")
    if not f or not f.data:
        return []
    key = (slug, f.data.get("timestamp"), len(f.data["vehicles"]), DBS[slug].version)
    if _bz_snap["key"] != key:
        _bz_snap.update(key=key, data=bz_build_snapshot(slug, region_items(slug, "vehicles", f.data["vehicles"])))
    return _bz_snap["data"]


def bz_observation(trip_id, fix_time, now):
    """The fresh observation of a bus, if there is one newer than its snapshot position."""
    o = _bz_obs.get(trip_id)
    return o if o and o["t"] > fix_time and now - o["t"] <= BZ_OBS_MAX else None


def bz_ingest(res, slug=BZ_SLUG):
    """Match the buses an answer lists for one stop to the snapshot and keep what they say. Returns how many."""
    if not res or res["status"] != "ok":
        return 0
    stop_id = res["stop_id"]
    t_obs = res["t_asked"] + (res["fetched"] - res["t_asked"]) / 2
    snap = _bz_snapshot(slug)
    n = 0
    for a in res["arrivals"]:
        rids = _lb_route_ids(slug, a["line"])
        head = norm(a["dest"])
        cands = []
        for b in snap:
            if b["route_id"] not in rids or stop_id not in b["sd"]:
                continue
            cands.append((b["sd"][stop_id] - b["d"], b))        # metres to go according to the snapshot
        same_dest = [c for c in cands if c[1]["head"] == head]
        cands = sorted(same_dest or cands, key=lambda c: c[0])
        i = 0
        for bus in a["buses"]:
            m = bus["metres"]
            while i < len(cands) and cands[i][0] < m - BZ_TOL:   # it was closer than the service says: it has gone by
                i += 1
            if i >= len(cands):
                break
            rem, b = cands[i]
            if rem - m > (t_obs - b["ts"]) * BZ_VMAX + BZ_TOL:      # it would have had to fly: another bus
                break
            d_obs = b["sd"][stop_id] - m
            with _bz_lock:
                old = _bz_obs.get(b["trip_id"])
                if not old or old["t"] <= t_obs:
                    _bz_obs[b["trip_id"]] = {"t": t_obs, "d": d_obs, "stop": stop_id, "metres": m, "minutes": bus["minutes"]}
            n += 1
            i += 1
    return n


def bz_plan(now, views, limit=BZ_MAX_STOPS):
    """The stops to ask about now: [(stop_id, buses it should reveal)], best first."""
    snap = _bz_snapshot()
    if not snap or not views:
        return []
    pad = LB_VIEW_PAD
    est = {}
    for b in snap:
        obs = bz_observation(b["trip_id"], b["ts"], now)
        a = advance_distance(b["fx"], obs["d"] if obs else b["d"], now - (obs["t"] if obs else b["ts"]))
        est[b["trip_id"]] = (a[0], a[1], a[4], now - obs["t"] if obs else None)

    def in_view(lat, lon):
        return any(s - pad <= lat <= n + pad and w - pad <= lon <= e + pad for s, w, n, e in views)
    need = {b["trip_id"] for b in snap if in_view(*est[b["trip_id"]][:2])
            and (est[b["trip_id"]][3] is None or est[b["trip_id"]][3] > BZ_REFRESH)}
    if not need or len(need) > BZ_MAX_BUSES:
        return []
    # every stop ahead of every bus, with how far: the first two buses of a line before a stop are the ones it lists
    by_stop = {}
    for b in snap:
        d1 = est[b["trip_id"]][2]
        for sid, ds in b["sd"].items():
            rem = ds - d1
            if -BZ_TOL <= rem <= BZ_AHEAD + BZ_MARGIN:
                by_stop.setdefault(sid, {}).setdefault((b["route_id"], b["head"]), []).append((rem, b["trip_id"]))
    cover = {}
    for sid, groups in by_stop.items():
        r = bizkaibus.client.peek(sid)
        if bizkaibus.code(sid) is None or (r and r["status"] == "empty" and now - r["fetched"] < bizkaibus.TTL_EMPTY):
            continue
        seen = set()
        for items in groups.values():
            items.sort()
            seen.update(t for rem, t in items[:2] if rem >= BZ_MARGIN and t in need)
        if seen:
            cover[sid] = seen
    plan, left = [], set(need)
    while left and len(plan) < limit:
        sid, gain = max(((k, len(v & left)) for k, v in cover.items()), key=lambda x: x[1], default=(None, 0))
        if not gain:
            break
        plan.append((sid, gain))
        left -= cover.pop(sid)
    return plan


def bz_gc(now=None):
    now = now or time.time()
    with _bz_lock:
        for k in [k for k, o in _bz_obs.items() if now - o["t"] > BZ_OBS_MAX * 2]:
            del _bz_obs[k]
    for k in [k for k, t in _bz_fetched.items() if now - t > 3600]:
        del _bz_fetched[k]


def bz_agency_status():
    st = bizkaibus.client.stats()["state"]
    now = time.time()
    with _bz_lock:
        n = sum(1 for o in _bz_obs.values() if now - o["t"] <= BZ_OBS_MAX)
    status = {"live": "live", "paused": "error", "idle": "idle", "off": "none"}[st]
    return {"status": status, "n": n if status == "live" else 0}


def bz_tracker_loop():
    """Background poller for Bizkaibus: only while a client is looking at a map area with buses, always rate limited."""
    log.info("bizkaibus tracker %s", "enabled" if bizkaibus.ENABLED else "disabled")
    while True:
        try:
            if not bizkaibus.ENABLED or not _bz_enabled():
                time.sleep(20)
                continue
            now = time.time()
            views = _lb_active_views(now)
            if not views:
                _bz_wake.wait(10)
                _bz_wake.clear()
                continue
            _bz_wake.clear()
            for stop_id, _gain in bz_plan(now, views):
                if not _lb_active_views(time.time()):
                    break
                res = bizkaibus.client.get(stop_id)
                if res and not res.get("stale") and _bz_fetched.get(stop_id) != res["fetched"]:
                    _bz_fetched[stop_id] = res["fetched"]
                    bz_ingest(res)
            bz_gc()
            _bz_wake.wait(max(2.0, BZ_CYCLE - (time.time() - now)))
        except Exception:
            log.exception("bizkaibus tracker")
            time.sleep(10)


def vehicles(max_age=10):
    with _veh_lock:
        if _veh_cache["data"] is not None and time.time() - _veh_cache["t"] < max_age:
            return _veh_cache["data"]
        data = _build_vehicles()
        _veh_cache.update(t=time.time(), data=data)
        return data


def _build_vehicles():
    now = int(time.time())
    slugs = [s for s, i in AGENCIES.items() if i["ready"] and s in DBS]
    refresh([s for s in slugs if AGENCIES[s]["rt"].get("vehicles") or AGENCIES[s]["rt"].get("trips") or is_lb(s)],
            ["vehicles", "trips"])
    out = []
    feeds = {}
    for slug in slugs:
        info = AGENCIES[slug]
        db = DBS[slug]
        vs, ts = feed_stats(slug, "vehicles"), feed_stats(slug, "trips")
        feeds[slug] = {"name": info["name"], "vehicles": vs, "trips": ts}
        tus = tu_index(slug) if ts["status"] in ("live", "stale") or is_lb(slug) else {}
        vf = feed_for(slug, "vehicles")
        vlist = region_items(slug, "vehicles", vf.data["vehicles"]) if vf and vf.data and vs["status"] in ("live", "stale") else []
        try:
            for v in vlist:
                if not v.get("lat") or not v.get("lon") or abs(v["lat"]) < 1:
                    continue
                tinfo = v.get("trip") or {}
                trip = _trip(db, slug, tinfo.get("trip_id")) if tinfo.get("trip_id") else None
                route_id = tinfo.get("route_id") or (trip or {}).get("route_id")
                li = line_info(db, route_id)
                meta = v.get("line_meta")
                if meta and route_id not in db.routes():     # a line the timetable lacks: use what the service publishes
                    li = {"line": meta["line"], "color": meta["color"], "text_color": meta["text_color"],
                          "mode": "bus", "long": meta["name"]}
                brg = v.get("bearing")
                if brg is None and trip and v.get("shape_heading"):       # no heading sent: that of the route here
                    brg = _shape_heading(db, trip, v["lat"], v["lon"])
                delay, hs = None, (trip or {}).get("headsign") or ""
                if trip and tus.get(trip["trip_id"]):
                    rows = db.trip_stop_times(trip["tix"])
                    d = resolve_service_date(db, trip, rows, now, tinfo.get("start_date"))
                    tu = pick_tu(tus[trip["trip_id"]], d)
                    if tu:
                        eff, canc = effective_times(slug, rows, d, tu)
                        nxt = next((e for e in eff if e["src"] == "rt" and e["dep"] >= now - 120), None) \
                            or next((e for e in eff if e["src"] == "rt"), None)
                        if nxt:
                            delay = nxt["dep"] - nxt["sched_dep"]
                vid = (v.get("vehicle") or {})
                lat, lon, adv, obs_age = v["lat"], v["lon"], None, None
                fix_time = fix_ts(slug, v.get("timestamp"))
                want_obs = slug == BZ_SLUG and bizkaibus.ENABLED
                if (slug in ADVANCE_OPERATORS or want_obs) and trip and fix_time:
                    # the fix is old by the time it is published: where should the bus be by now?
                    fx = fix_on_route(db, trip, db.trip_stop_times(trip["tix"]), lat, lon, v.get("stop_id"))
                    obs = bz_observation(trip["trip_id"], fix_time, now) if want_obs and fx else None
                    if fx and obs:       # the stop service placed it more recently: from there, along the timetable
                        adv, obs_age = advance_distance(fx, obs["d"], now - obs["t"]), int(now - obs["t"])
                    elif fx and slug in ADVANCE_OPERATORS and now - fix_time >= ADVANCE_MIN_S:
                        adv = advance_distance(fx, fx["d"], now - fix_time)
                    if adv:
                        lat, lon, brg = adv[0], adv[1], round(adv[2])
                        adv = adv[:3] + (max(adv[4] - fx["d"], 0.0),)       # metres along the route from the raw fix
                # some feeds (Bizkaibus) number the vehicles of every snapshot afresh ("<snapshot time>_<n>"): such an
                # id is neither stable nor meaningful, the trip identifies the bus
                raw_id = str(vid.get("id") or v["id"])
                snapshot_id = re.match(r"^\d{8,}_\d+$", raw_id) is not None and bool(tinfo.get("trip_id"))
                out.append({
                    "id": "%s:%s" % (slug, tinfo["trip_id"] if snapshot_id else raw_id), "agency": slug, "agency_name": info["name"],
                    "label": "" if snapshot_id else re.sub(r"-PLATF\.\(\d+\)$", "", vid.get("label") or vid.get("id") or ""),
                    "lat": round(lat, 6),
                    "lon": round(lon, 6), "bearing": brg, "advanced": round(adv[3]) if adv else None, "obs_age": obs_age,
                    "speed": round(v["speed"] * 3.6) if v.get("speed") is not None else None,
                    "route_id": route_id, "line": li["line"], "color": li["color"], "text_color": li["text_color"],
                    "mode": li["mode"], "headsign": hs or li["long"], "trip_id": tinfo.get("trip_id") if trip else None,
                    "date": tinfo.get("start_date"),
                    "stop": _stop_name(db, v.get("stop_id")) if v.get("stop_id") else None,
                    "status": v.get("status"), "ts": fix_time, "delay": delay, "est": False,
                    "sched": False, "kind": "gps",
                })
            if not vlist and tus:
                out.extend(_estimated_vehicles(slug, info, db, tus, now))
            # no GPS and no live arrival data for this operator: draw where the timetable says its vehicles are
            mine = [o for o in out if o["agency"] == slug]
            if not mine and not is_lb(slug):
                out.extend(_scheduled_vehicles(slug, info, db, now))
            elif mine and not vlist and (info.get("quirks") or {}).get("zero_delay_untracked"):
                # a feed that reports only the trips with a delay (SNCF, Txik Txak): the others have no live data,
                # so they are drawn from the timetable, except those the feed does talk about (delayed, cancelled)
                out.extend(_scheduled_vehicles(slug, info, db, now, skip=_reported_trips(tus) | {o["trip_id"] for o in mine}))
        except Exception:
            log.exception("vehicle build failed for %s", slug)
    data = {"time": now, "vehicles": out, "feeds": feeds}
    return data


def _shape_heading(db, trip, lat, lon):
    """Direction of travel of a trip's route at the point nearest to (lat, lon), or None when it is not on it."""
    geom = shape_geom(db, trip.get("shape_id"))
    if not geom:
        return None
    res = _project(geom, lat, lon, 0.0, geom[2][-1])
    if not res or res[1] > MAX_SNAP_M:
        return None
    return round(_point_at(geom, res[0])[2])


def _estimated_vehicles(slug, info, db, tus, now):
    out = []
    for tid, lst in tus.items():
        trip = _trip(db, slug, tid)
        if not trip:
            continue
        tu = lst[0]
        if tu["trip"].get("rel") == 3:
            continue
        # quick reject: trips whose first reported stop is in the future and seq==1 are not running yet
        rows = db.trip_stop_times(trip["tix"])
        if len(rows) < 2:
            continue
        for tu in lst:
            d = resolve_service_date(db, trip, rows, now, tu["trip"].get("start_date"))
            eff, canc = effective_times(slug, rows, d, tu)
            if not any(e["src"] == "rt" for e in eff):
                continue
            geom = shape_geom(db, trip.get("shape_id"))
            pos = _interp(eff, now, stop_distances(db, trip, rows) if geom else None, geom)
            if not pos or (is_national(slug) and not region.contains(pos[0], pos[1])):
                continue                     # a national feed: only the part of the journey inside Euskal Herria
            li = line_info(db, trip["route_id"])
            rt = next((e for e in eff if e["src"] == "rt"), None)
            delay = (rt["dep"] - rt["sched_dep"]) if rt else None
            vid = (tu.get("vehicle") or {}).get("id") or tid
            out.append({
                "id": "%s:%s" % (slug, vid), "agency": slug, "agency_name": info["name"],
                "label": (tu.get("vehicle") or {}).get("label") or "", "lat": round(pos[0], 6),
                "lon": round(pos[1], 6), "bearing": round(pos[4]) if pos[4] is not None else None, "on_track": pos[5],
                "speed": None, "route_id": trip["route_id"],
                "line": li["line"], "color": li["color"], "text_color": li["text_color"], "mode": li["mode"],
                "headsign": trip["headsign"] or lb_headsign(slug, trip["tix"]) or li["long"],
                "trip_id": tid, "date": d.strftime("%Y%m%d"),
                "stop": pos[2], "status": 1 if pos[3] == "stopped" else 2, "ts": fix_ts(slug, tu.get("timestamp")),
                "delay": delay, "est": True, "sched": False, "kind": "est", "occupancy": tu.get("occupancy")})
            break
    return out


_span_cache = {}


def _trip_spans(slug, db):
    """[(tix, trip_id, route_id, service_id, headsign, shape_id, first departure, last arrival)] of every trip."""
    key = (slug, db.version)
    if key not in _span_cache:
        for k in [k for k in _span_cache if k[0] == slug]:
            del _span_cache[k]
        _span_cache[key] = [tuple(r) for r in db.q(
            "SELECT t.tix, t.trip_id, t.route_id, t.service_id, t.headsign, t.shape_id, MIN(st.dep), MAX(st.arr) "
            "FROM trips t JOIN stop_times st ON st.tix=t.tix GROUP BY t.tix") if r[6] is not None and r[7] is not None]
    return _span_cache[key]


def _reported_trips(tus):
    """Trips a trip-update feed says something about: cancelled, or with a delay at some stop."""
    out = set()
    for tid, lst in tus.items():
        for tu in lst:
            if tu["trip"].get("rel") == 3 or any((st.get(k) or {}).get("delay") for st in tu["stus"] for k in ("arr", "dep")):
                out.add(tid)
                break
    return out


def _scheduled_vehicles(slug, info, db, now, skip=()):
    """Theoretical vehicles: trips that should be running now according to the timetable alone."""
    out = []
    spans = _trip_spans(slug, db)
    for d in candidate_days(now):
        active = db.active_services(d)
        if not active:
            continue
        rel = now - service_midnight(d)
        for tix, tid, route_id, service_id, headsign, shape_id, first, last in spans:
            if service_id not in active or not first <= rel <= last or tid in skip:
                continue
            rows = db.trip_stop_times(tix)
            eff, _ = effective_times(slug, rows, d, None)
            trip = {"tix": tix, "shape_id": shape_id}
            geom = shape_geom(db, shape_id)
            pos = _interp(eff, now, stop_distances(db, trip, rows) if geom else None, geom)
            # long-distance lines (Alsa, Renfe) run far outside: only draw the part inside Euskal Herria
            if not pos or not region.contains(pos[0], pos[1]):
                continue
            li = line_info(db, route_id)
            out.append({
                "id": "%s:sched:%s:%s" % (slug, tid, d.strftime("%Y%m%d")), "agency": slug, "agency_name": info["name"],
                "label": "", "lat": round(pos[0], 6), "lon": round(pos[1], 6),
                "bearing": round(pos[4]) if pos[4] is not None else None, "on_track": pos[5], "speed": None,
                "route_id": route_id, "line": li["line"], "color": li["color"], "text_color": li["text_color"],
                "mode": li["mode"], "headsign": headsign or lb_headsign(slug, tix) or li["long"],
                "trip_id": tid, "date": d.strftime("%Y%m%d"), "stop": pos[2],
                "status": 1 if pos[3] == "stopped" else 2, "ts": None, "delay": None,
                "est": False, "sched": True, "kind": "sched", "occupancy": None})
    return out


# --------------------------------------------------------------------------- trip / route / stations

def trip_detail(slug, trip_id, date_str=None, now=None, sched_only=False):
    """Stops of a trip. sched_only=True gives the pure timetable of service day date_str (no real-time)."""
    now = int(now or time.time())
    db = DBS[slug]
    trip = db.trip_by_id(trip_id)
    if not trip:
        return None
    rows = db.trip_stop_times(trip["tix"])
    if sched_only:
        d = parse_date(date_str)
        if d is None:
            return {"error": "bad_date"}
        lo, hi = date_limits([slug])
        # the service day may start the day before the selected calendar day (after-midnight trips)
        if not (lo - timedelta(days=1) <= d <= hi):
            return {"error": "date_out_of_range"}
        tu, tus = None, {}
    else:
        d = resolve_service_date(db, trip, rows, now, date_str)
        refresh([slug], ["trips"])
        tus = tu_index(slug)
        tu = pick_tu(tus.get(trip_id), d) if tus else None
    eff, canc = effective_times(slug, rows, d, tu)
    li = line_info(db, trip["route_id"])
    stops = [{"seq": e["seq"], "stop_id": e["stop_id"], "station_id": e["station_id"], "name": e["name"],
              "lat": e["lat"], "lon": e["lon"], "sched": e["sched_dep"], "sched_arr": e["sched_arr"],
              "expected": e["dep"], "expected_arr": e["arr"], "rt": e["src"] if e["src"] != "sched" else None,
              "skipped": e.get("skipped", False)} for e in eff]
    return {"trip_id": trip_id, "agency": slug, "route_id": trip["route_id"], "line": li["line"], "color": li["color"],
            "text_color": li["text_color"], "mode": li["mode"],
            "headsign": trip["headsign"] or lb_headsign(slug, trip["tix"]) or li["long"],
            "cancelled": canc, "has_rt": tu is not None, "date": d.strftime("%Y%m%d"), "stops": stops,
            "sched_only": sched_only, "runs": trip["service_id"] in db.active_services(d),
            "occupancy": tu.get("occupancy") if tu else None,
            "shape": db.shape(trip["shape_id"])}


def route_detail(slug, route_id):
    db = DBS[slug]
    li = line_info(db, route_id)
    shapes, stops = [], []
    seen_dirs = set()
    for r in db.q("SELECT shape_id, direction, headsign, COUNT(*) c, MIN(tix) tix FROM trips WHERE route_id=? "
                  "GROUP BY shape_id, direction ORDER BY c DESC", (route_id,)):
        key = r["direction"]
        if key in seen_dirs and len(seen_dirs) >= 2:
            continue
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        rows = db.trip_stop_times(r["tix"])
        st = [{"station_id": x["station_id"], "name": x["name"], "lat": x["lat"], "lon": x["lon"]} for x in rows]
        shapes.append({"direction": r["direction"], "headsign": r["headsign"], "pts": db.shape(r["shape_id"]),
                       "stops": st})
        if len(seen_dirs) >= 2:
            break
    r = db.routes().get(route_id)
    if r and not li["long"]:
        li["long"] = route_long(slug, r)
    return dict(li, route_id=route_id, agency=slug, shapes=shapes)


_route_names = {}


def route_long(slug, r):
    """Long name of a route. National operators (Renfe) leave it empty for long distance: use
    'first stop → last stop' of one of its trips (all its stops are stored)."""
    if r["long"] or not is_national(slug):
        return r["long"]
    db = DBS[slug]
    key = (slug, db.version)
    m = _route_names.get(key)
    if m is None:
        m = {}
        for row in db.q("SELECT t.route_id, MIN(t.tix) tix FROM trips t "
                        "WHERE EXISTS (SELECT 1 FROM stop_times s WHERE s.tix=t.tix) GROUP BY t.route_id"):
            rows = db.trip_stop_times(row["tix"])
            if len(rows) >= 2:
                m[row["route_id"]] = "%s → %s" % (rows[0]["name"], rows[-1]["name"])
        _route_names.clear()
        _route_names[key] = m
    return m.get(r["route_id"], "")


def shown_routes(slug):
    """Routes worth listing: the importer already kept only those with a stop inside Euskal Herria."""
    return DBS[slug].routes().values()


def routes_of(slug):
    db = DBS[slug]
    out = []
    for r in shown_routes(slug):
        color, text, _ = route_style(db, r)
        long_ = route_long(slug, r)
        out.append({"route_id": r["route_id"], "line": r["short"] or long_ or r["route_id"], "long": long_,
                    "color": color, "text_color": text, "mode": r["mode"]})
    return sorted(out, key=lambda r: _natkey(r["line"]))


def _natkey(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s or "")]


def _like(q):
    return "%" + q.replace("%", "").replace("_", "") + "%"


def search_stations(q, limit=40, lat=None, lon=None):
    qn = norm(q)
    if len(qn) < 2:
        return []
    res = []
    shared = set()      # a Lurraldebus stop served by several operators is one result
    for slug, info in AGENCIES.items():
        if not info["ready"]:
            continue
        try:
            for r in DBS[slug].q("SELECT station_id, name, lat, lon, modes FROM stations WHERE name_norm LIKE ? LIMIT 60",
                                 (_like(qn),)):
                if is_lb(slug):
                    if r["station_id"] in shared:
                        continue
                    shared.add(r["station_id"])
                n = norm(r["name"])
                rank = 0 if n == qn else 1 if n.startswith(qn) else 2
                res.append({"agency": slug, "agency_name": info["name"], "station_id": r["station_id"],
                            "name": r["name"], "lat": r["lat"], "lon": r["lon"], "modes": r["modes"], "_r": rank})
        except Exception:
            log.exception("search failed in %s", slug)
    mode_rank = {"train": 0, "metro": 0, "tram": 1, "funicular": 1}
    res.sort(key=lambda r: (r["_r"], mode_rank.get((r["modes"] or "").split(",")[0], 2), len(r["name"]), r["name"]))
    for r in res:
        r.pop("_r")
    return res[:limit]


def stations_in_bbox(s, w, n, e, limit=1500, rail_only=False):
    res = []
    shared = {}         # Lurraldebus stops are listed once, however many operators serve them
    for slug, info in AGENCIES.items():
        if not info["ready"]:
            continue
        lb = is_lb(slug)
        for r in DBS[slug].q("SELECT station_id, name, lat, lon, modes FROM stations WHERE lat BETWEEN ? AND ? "
                             "AND lon BETWEEN ? AND ?", (s, n, w, e)):
            if rail_only and not (set((r["modes"] or "").split(",")) - {"bus", ""}):
                continue
            if lb:
                if r["station_id"] in shared:
                    shared[r["station_id"]]["agencies"].append(slug)      # the same stop, served by several operators
                    continue
            entry = {"agency": slug, "agencies": [slug], "station_id": r["station_id"], "name": r["name"],
                     "lat": r["lat"], "lon": r["lon"], "modes": r["modes"]}
            if lb:
                shared[r["station_id"]] = entry
            res.append(entry)
    return res[:limit * 3]


def nearby(lat, lon, radius=600, limit=15):
    dlat = radius / 111000.0
    dlon = radius / (111000.0 * max(0.2, abs(__import__("math").cos(__import__("math").radians(lat)))))
    out = []
    for r in stations_in_bbox(lat - dlat, lon - dlon, lat + dlat, lon + dlon, 5000):
        r["dist"] = int(haversine(lat, lon, r["lat"], r["lon"]))
        if r["dist"] <= radius:
            r["agency_name"] = AGENCIES[r["agency"]]["name"]
            out.append(r)
    out.sort(key=lambda r: r["dist"])
    return out[:limit]


# --------------------------------------------------------------------------- alerts

def alerts(slug_filter=None):
    now = time.time()
    slugs = [s for s, i in AGENCIES.items() if i["rt"].get("alerts") and i["ready"] and (not slug_filter or s == slug_filter)]
    refresh(slugs, ["alerts"])
    out = []
    for slug in slugs:
        f = feed_for(slug, "alerts")
        if not f or not f.data:
            continue
        for a in region_items(slug, "alerts", f.data["alerts"]):
            per = a.get("periods") or []
            if per:
                ok = any((not p.get("start") or fix_ts(slug, p["start"]) <= now) and
                         (not p.get("end") or now <= fix_ts(slug, p["end"])) for p in per)
                if not ok:
                    continue
            routes = DBS[slug].routes()
            rids = [e["route_id"] for e in (a.get("entities") or []) if e.get("route_id")]
            modes = sorted({routes[r]["mode"] for r in rids if r in routes})
            lines = sorted({(routes[r]["short"] or routes[r]["long"]) for r in rids if r in routes})
            out.append({"agency": slug, "agency_name": AGENCIES[slug]["name"], "id": a["id"],
                        "route_ids": rids, "modes": modes, "lines": lines,
                        "header": a.get("header") or {}, "description": a.get("description") or {},
                        "url": a.get("url") or {}, "effect": a.get("effect"), "cause": a.get("cause"),
                        "entities": a.get("entities") or [],
                        "end": fix_ts(slug, per[0]["end"]) if per and per[0].get("end") else None})
    return out


def agencies_summary():
    out = []
    for slug, info in sorted(AGENCIES.items(), key=lambda kv: kv[1]["name"].lower()):
        rt = {}
        for k in ("vehicles", "trips", "alerts"):
            if info["rt"].get(k):
                rt[k] = feed_stats(slug, k)
        if is_lb(slug):
            rt["arrivals"] = lb_agency_status(slug)
        elif slug == BZ_SLUG and bizkaibus.ENABLED:
            rt["arrivals"] = bz_agency_status()
        modes = []
        if info["ready"]:
            try:
                modes = sorted({r["mode"] for r in DBS[slug].routes().values()})
            except Exception:
                pass
        out.append({"id": slug, "name": info["name"], "ready": info["ready"], "importing": info.get("importing"),
                    "error": info.get("error"), "modes": modes, "rt": rt, "gtfs_updated": info["gtfs_stamp"],
                    "region": info.get("region", "eus")})
    return out


def search_all(q, limit=25):
    """Stations + lines + operators matching q (accent/case-insensitive)."""
    qn = norm(q)
    res = {"stations": search_stations(q, limit), "routes": [], "operators": []}
    if len(qn) < 1:
        return res
    for slug, info in AGENCIES.items():
        if not info["ready"]:
            continue
        if len(qn) >= 3 and qn in norm(info["name"]):
            res["operators"].append({"agency": slug, "name": info["name"]})
        try:
            db = DBS[slug]
            for r in shown_routes(slug):
                long_text = route_long(slug, r)
                short, long_ = norm(r["short"]), norm(long_text)
                rank = 0 if short == qn else 1 if short.startswith(qn) else 2 if (len(qn) >= 3 and qn in long_) else None
                if rank is None:
                    continue
                color, text, _ = route_style(db, r)
                res["routes"].append({"agency": slug, "agency_name": info["name"], "route_id": r["route_id"],
                                      "line": r["short"] or long_text or r["route_id"], "long": long_text,
                                      "color": color, "text_color": text, "mode": r["mode"], "_r": rank})
        except Exception:
            log.exception("route search failed in %s", slug)
    res["routes"].sort(key=lambda r: (r["_r"], _natkey(r["line"])))
    for r in res["routes"]:
        r.pop("_r")
    res["routes"] = res["routes"][:limit]
    return res
