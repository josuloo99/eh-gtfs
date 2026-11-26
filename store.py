"""GTFS static data: import into per-agency SQLite databases and query helpers."""
import csv
import io
import json
import math
import os
import re
import sqlite3
import threading
import unicodedata
import zipfile

import region
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_DIR = os.path.join(DATA_DIR, "db")

# National feeds (Renfe, all of Spain). Every operator is cut to Euskal Herria at import (see import_gtfs): a trip is
# kept only if one of its stops is inside the territory (region.py). These are also the feeds whose real-time data
# is national, and whose trips get a destination derived from their last stop.
BBOX_AGENCIES = {"renfe_media", "renfe_cercanias", "sncf"}
# Bump when the importer changes what it stores: the operators are re-imported (the old database serves meanwhile).
IMPORT_TAG = "|eh3"

SCHEMA_VERSION = 3


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def mode_of(route_type):
    """Map a GTFS route_type (basic or extended) to a UI mode."""
    try:
        t = int(route_type)
    except (TypeError, ValueError):
        return "bus"
    if t == 1 or 400 <= t < 500 or t == 12:
        return "metro"
    if t == 0 or 900 <= t < 1000:
        return "tram"
    if t == 2 or 100 <= t < 200:
        return "train"
    if t in (5, 6, 7) or 1300 <= t < 1500 or t == 1400:
        return "funicular"
    if t == 4 or 1000 <= t < 1100:
        return "ferry"
    return "bus"


def parse_hms(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        h, m, sec = s.split(":")
        return int(h) * 3600 + int(m) * 60 + int(sec)
    except ValueError:
        return None


def service_midnight(d):
    """Epoch seconds for the GTFS 'time zero' of a service day (noon minus 12h)."""
    noon = datetime.combine(d, time(12, 0), tzinfo=TZ)
    return int((noon - timedelta(hours=12)).timestamp())


def haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- import

SCHEMA = """
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE stops(stop_id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, parent TEXT, code TEXT, platform TEXT);
CREATE TABLE routes(route_id TEXT PRIMARY KEY, short TEXT, long TEXT, rtype INTEGER, mode TEXT, color TEXT, text_color TEXT);
CREATE TABLE trips(tix INTEGER PRIMARY KEY, trip_id TEXT UNIQUE, route_id TEXT, service_id TEXT, headsign TEXT, direction INTEGER, shape_id TEXT);
CREATE TABLE stop_times(tix INTEGER, seq INTEGER, stop_id TEXT, arr INTEGER, dep INTEGER, PRIMARY KEY(tix, seq)) WITHOUT ROWID;
CREATE TABLE calendar(service_id TEXT PRIMARY KEY, days TEXT, start TEXT, end TEXT);
CREATE TABLE calendar_dates(service_id TEXT, date TEXT, type INTEGER);
CREATE TABLE shapes(shape_id TEXT PRIMARY KEY, pts TEXT);
CREATE TABLE stations(station_id TEXT PRIMARY KEY, name TEXT, name_norm TEXT, lat REAL, lon REAL, modes TEXT);
CREATE TABLE stop_station(stop_id TEXT PRIMARY KEY, station_id TEXT);
"""


def _reader(z, name):
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    f = io.TextIOWrapper(z.open(info), encoding="utf-8-sig", newline="")
    rd = csv.DictReader(f)
    # some feeds pad fields with spaces (RENFE)
    rd.fieldnames = [h.strip() for h in rd.fieldnames or []]
    return rd


def _fnum(s):
    try:
        return float((s or "").strip())
    except ValueError:
        return None


def _tidy(s):
    """Trim and remove the column padding some feeds (Renfe) put inside names: 'Abando      -Muskiz'."""
    s = re.sub(r"\s{2,}-", "-", (s or "").strip())
    return re.sub(r"\s{2,}", " ", s)


def _unknown(s):
    """Placeholders some feeds use for a missing name (SNCF: 'INCONNU' and '-') are no name at all."""
    s = (s or "").strip()
    return "" if s.upper() in ("INCONNU", "UNKNOWN", "-") else s


def import_gtfs(zip_path, db_path, slug, source_stamp="", opts=None):
    """Import a GTFS zip into a SQLite database. opts (per-source quirks):
    city_in_name: prefix stop names with the town from stops.txt city_name ("Tarnos - 11 novembre 1918"),
    which is how the other operators of the area name their stops.
    headsign_town: trips without a headsign get the town of their last stop ("Pamplona/Iruña. Estación Bus" ->
    "Pamplona/Iruña").
    headsign_last_stop: the feed's trip_headsign is not a destination (SNCF gives the train number): every trip gets
    the name of its last stop instead."""
    opts = opts or {}
    tmp = db_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.executescript(SCHEMA)
    z = zipfile.ZipFile(zip_path)
    national = slug in BBOX_AGENCIES

    # stops: which ones are inside Euskal Herria?
    stops, inside, outside_any = {}, set(), False
    for r in _reader(z, "stops.txt"):
        sid = (r.get("stop_id") or "").strip()
        if not sid:
            continue
        lat, lon = _fnum(r.get("stop_lat")), _fnum(r.get("stop_lon"))
        name = (r.get("stop_name") or "").strip()
        city = (r.get("city_name") or "").strip()
        if opts.get("city_in_name") and city and not norm(name).startswith(norm(city)):
            name = "%s - %s" % (city, name)
        stops[sid] = (
            sid, name, lat, lon,
            (r.get("parent_station") or "").strip(), (r.get("stop_code") or "").strip(),
            (r.get("platform_code") or "").strip(),
        )
        if region.contains(lat, lon):
            inside.add(sid)
        else:
            outside_any = True
    if not inside:
        db.close()
        os.remove(tmp)
        return False

    # trips
    tix_of = {}
    trip_rows = []
    for i, r in enumerate(_reader(z, "trips.txt"), 1):
        tid = (r.get("trip_id") or "").strip()
        tix_of[tid] = i
        d = (r.get("direction_id") or "").strip()
        trip_rows.append((i, tid, (r.get("route_id") or "").strip(), (r.get("service_id") or "").strip(),
                          (r.get("trip_headsign") or "").strip(), int(d) if d.isdigit() else None,
                          (r.get("shape_id") or "").strip()))

    # a trip belongs to the app only if one of its stops is inside Euskal Herria (all its stops are then kept,
    # so a line that leaves the territory still shows where it goes). A feed whose stops are all inside needs
    # no filtering; otherwise stop_times are read twice: first to find the trips, then to store them.
    keep = None
    if outside_any:
        keep = set()
        for r in _reader(z, "stop_times.txt"):
            if (r.get("stop_id") or "").strip() in inside:
                tix = tix_of.get((r.get("trip_id") or "").strip())
                if tix is not None:
                    keep.add(tix)
        if not keep:
            db.close()
            os.remove(tmp)
            return False
    kept_rows = [t for t in trip_rows if keep is None or t[0] in keep]
    dropped = len(trip_rows) - len(kept_rows)
    db.executemany("INSERT OR REPLACE INTO trips VALUES(?,?,?,?,?,?,?)", kept_rows)
    route_ids = {t[2] for t in kept_rows}
    service_ids = {t[3] for t in kept_rows}
    shape_ids = {t[6] for t in kept_rows if t[6]}
    trip_rows = kept_rows = None

    # stop_times
    used = set()
    batch = []
    for r in _reader(z, "stop_times.txt"):
        tix = tix_of.get((r.get("trip_id") or "").strip())
        if tix is None or (keep is not None and tix not in keep):
            continue
        sid = (r.get("stop_id") or "").strip()
        if sid not in stops:
            continue
        arr = parse_hms(r.get("arrival_time"))
        dep = parse_hms(r.get("departure_time"))
        if arr is None:
            arr = dep
        if dep is None:
            dep = arr
        if arr is None:
            continue
        try:
            seq = int(r["stop_sequence"])
        except (ValueError, KeyError):
            continue
        used.add(sid)
        batch.append((tix, seq, sid, arr, dep))
        if len(batch) >= 50000:
            db.executemany("INSERT OR REPLACE INTO stop_times VALUES(?,?,?,?,?)", batch)
            batch = []
    if batch:
        db.executemany("INSERT OR REPLACE INTO stop_times VALUES(?,?,?,?,?)", batch)
    keep = None

    # only the stops these trips call at (and their parent stations) are stored
    needed = set(used)
    for sid in used:
        p = stops[sid][4]
        while p and p in stops and p not in needed:
            needed.add(p)
            p = stops[p][4]
    db.executemany("INSERT INTO stops VALUES(?,?,?,?,?,?,?)", (stops[sid] for sid in needed))

    # routes (only those with a kept trip)
    for r in _reader(z, "routes.txt"):
        rid = (r.get("route_id") or "").strip()
        if rid not in route_ids:
            continue
        rtype = (r.get("route_type") or "3").strip()
        db.execute(
            "INSERT OR REPLACE INTO routes VALUES(?,?,?,?,?,?,?)",
            (rid, _unknown(r.get("route_short_name")), _unknown(_tidy(r.get("route_long_name"))),
             int(rtype) if rtype.isdigit() else 3, mode_of(rtype),
             (r.get("route_color") or "").strip(), (r.get("route_text_color") or "").strip()))

    db.execute("CREATE INDEX st_stop ON stop_times(stop_id, dep)")
    db.execute("CREATE INDEX trips_route ON trips(route_id)")
    if opts.get("headsign_town"):
        # no trip_headsign in the feed and stops named "Town. street": the destination is the town of the last stop
        last = db.execute("SELECT t.tix, (SELECT s.name FROM stop_times st JOIN stops s ON s.stop_id=st.stop_id "
                          "WHERE st.tix=t.tix ORDER BY st.seq DESC LIMIT 1) FROM trips t WHERE t.headsign=''").fetchall()
        db.executemany("UPDATE trips SET headsign=? WHERE tix=?",
                       ((re.split(r"\.\s|\s-\s", n or "")[0].strip(), tix) for tix, n in last if n))
    if national or opts.get("headsign_last_stop"):
        # Renfe leaves trip_headsign empty: use the name of the last stop the trip calls at
        # (headsign_last_stop: for every trip, whatever the feed says; "Paris Montparnasse Hall 1 - 2" -> "Paris Montparnasse")
        last = db.execute("SELECT t.tix, (SELECT s.name FROM stop_times st JOIN stops s ON s.stop_id=st.stop_id "
                          "WHERE st.tix=t.tix ORDER BY st.seq DESC LIMIT 1) FROM trips t %s"
                          % ("" if opts.get("headsign_last_stop") else "WHERE t.headsign=''")).fetchall()
        db.executemany("UPDATE trips SET headsign=? WHERE tix=?",
                       ((re.sub(r"\s+Hall\s*\d[\d\s-]*$", "", n or ""), tix) for tix, n in last))

    # calendar (only the services of the kept trips)
    rd = _reader(z, "calendar.txt")
    if rd:
        for r in rd:
            sv = (r.get("service_id") or "").strip()
            if sv not in service_ids:
                continue
            days = "".join((r.get(d) or "0").strip() for d in
                           ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))
            db.execute("INSERT OR REPLACE INTO calendar VALUES(?,?,?,?)",
                       (sv, days, (r.get("start_date") or "").strip(), (r.get("end_date") or "").strip()))
    rd = _reader(z, "calendar_dates.txt")
    if rd:
        db.executemany("INSERT INTO calendar_dates VALUES(?,?,?)",
                       (((r.get("service_id") or "").strip(), (r.get("date") or "").strip(),
                         int((r.get("exception_type") or "1").strip() or 1))
                        for r in rd if (r.get("service_id") or "").strip() in service_ids))
    db.execute("CREATE INDEX cd_svc ON calendar_dates(service_id)")

    # shapes (only those of the kept trips)
    shp = {}
    rd = _reader(z, "shapes.txt")
    if rd and shape_ids:
        for r in rd:
            shid = (r.get("shape_id") or "").strip()
            if shid not in shape_ids:
                continue
            lat, lon = _fnum(r.get("shape_pt_lat")), _fnum(r.get("shape_pt_lon"))
            try:
                sq = int(r["shape_pt_sequence"])
            except (ValueError, KeyError):
                continue
            if lat is None or lon is None:
                continue
            shp.setdefault(shid, []).append((sq, round(lat, 5), round(lon, 5)))
        db.executemany(
            "INSERT INTO shapes VALUES(?,?)",
            ((k, json.dumps([[a, b] for _, a, b in sorted(v)], separators=(",", ":")))
             for k, v in shp.items()))
        shp = None

    # stations: group platforms under their parent station
    stations = {}
    stop_station = {}
    for sid in used:
        s = stops[sid]
        parent = s[4] if s[4] in stops else None
        if parent and stops[parent][4] in stops:
            parent = stops[parent][4]
        stid = parent or sid
        stop_station[sid] = stid
        stations.setdefault(stid, []).append(s)
    out = []
    for stid, children in stations.items():
        base = stops.get(stid) or children[0]
        lat, lon = base[2], base[3]
        if not lat or not lon:
            vals = [(c[2], c[3]) for c in children if c[2] and c[3]]
            if not vals:
                continue
            lat = sum(v[0] for v in vals) / len(vals)
            lon = sum(v[1] for v in vals) / len(vals)
        name = base[1] or children[0][1]
        out.append((stid, name, norm(name), lat, lon, ""))
    db.executemany("INSERT INTO stations VALUES(?,?,?,?,?,?)", out)
    db.executemany("INSERT INTO stop_station VALUES(?,?)", stop_station.items())
    # modes per station
    modes = {}
    q = ("SELECT st.stop_id, r.mode FROM stop_times st JOIN trips t ON t.tix=st.tix "
         "JOIN routes r ON r.route_id=t.route_id GROUP BY st.stop_id, r.mode")
    for sid, m in db.execute(q).fetchall():
        modes.setdefault(stop_station.get(sid), set()).add(m)
    db.executemany("UPDATE stations SET modes=? WHERE station_id=?",
                   [(",".join(sorted(v)), k) for k, v in modes.items() if k])
    db.execute("CREATE INDEX stations_lat ON stations(lat)")
    db.execute("CREATE INDEX ss_station ON stop_station(station_id)")

    db.execute("INSERT INTO meta VALUES('schema',?)", (str(SCHEMA_VERSION),))
    db.execute("INSERT INTO meta VALUES('stamp',?)", (source_stamp,))
    db.execute("INSERT INTO meta VALUES('dropped',?)", (str(dropped),))
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(tmp, db_path)
    return True


# --------------------------------------------------------------------------- queries

class AgencyDB:
    """Read-only access to one agency database (thread-local connections)."""

    def __init__(self, slug):
        self.slug = slug
        self.path = os.path.join(DB_DIR, slug + ".sqlite")
        self.local = threading.local()
        self.version = 0
        self._svc_cache = {}
        self._lock = threading.Lock()
        self._routes = None
        self._range = None
        self._dropped = None

    def reload(self):
        with self._lock:
            self.version += 1
            self._svc_cache = {}
            self._routes = None
            self._range = None
            self._dropped = None

    def dropped(self):
        """Number of trips left out because every stop is outside Euskal Herria (0: nothing was cut)."""
        if self._dropped is None:
            r = self.q("SELECT v FROM meta WHERE k='dropped'")
            self._dropped = int(r[0][0]) if r and str(r[0][0]).isdigit() else 0
        return self._dropped

    def feed_range(self):
        """(first, last) dates (YYYYMMDD strings) with any published service, or None.

        From calendar start/end dates and the 'service added' exceptions. Open-ended calendar rows
        (empty end) are ignored here; callers clamp to their own window anyway."""
        if self._range is None:
            lo, hi = [], []
            for r in self.q("SELECT MIN(start) a, MAX(end) b FROM calendar WHERE start<>'' AND end<>''"):
                if r["a"]:
                    lo.append(r["a"])
                if r["b"]:
                    hi.append(r["b"])
            for r in self.q("SELECT MIN(date) a, MAX(date) b FROM calendar_dates WHERE type=1"):
                if r["a"]:
                    lo.append(r["a"])
                if r["b"]:
                    hi.append(r["b"])
            self._range = (min(lo), max(hi)) if lo and hi else False
        return self._range or None

    @property
    def conn(self):
        c = getattr(self.local, "conn", None)
        if c is None or getattr(self.local, "ver", None) != self.version:
            if c is not None:
                c.close()
            c = sqlite3.connect("file:%s?mode=ro" % self.path, uri=True, check_same_thread=False)
            c.row_factory = sqlite3.Row
            self.local.conn = c
            self.local.ver = self.version
        return c

    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def routes(self):
        if self._routes is None:
            self._routes = {r["route_id"]: dict(r) for r in self.q("SELECT * FROM routes")}
        return self._routes

    def active_services(self, d):
        key = d.strftime("%Y%m%d")
        with self._lock:
            hit = self._svc_cache.get(key)
        if hit is not None:
            return hit
        wd = d.weekday()
        active = set()
        for r in self.q("SELECT service_id, days, start, end FROM calendar"):
            if r["days"][wd] == "1" and (not r["start"] or r["start"] <= key) and (not r["end"] or key <= r["end"]):
                active.add(r["service_id"])
        for r in self.q("SELECT service_id, type FROM calendar_dates WHERE date=?", (key,)):
            if r["type"] == 1:
                active.add(r["service_id"])
            elif r["type"] == 2:
                active.discard(r["service_id"])
        with self._lock:
            self._svc_cache[key] = active
        return active

    def station(self, station_id):
        r = self.q("SELECT * FROM stations WHERE station_id=?", (station_id,))
        return dict(r[0]) if r else None

    def station_stops(self, station_id):
        return [r[0] for r in self.q("SELECT stop_id FROM stop_station WHERE station_id=?", (station_id,))]

    def trip_by_id(self, trip_id):
        r = self.q("SELECT * FROM trips WHERE trip_id=?", (trip_id,))
        return dict(r[0]) if r else None

    def trip_stop_times(self, tix):
        return self.q(
            "SELECT st.seq, st.stop_id, st.arr, st.dep, s.name, s.lat, s.lon, ss.station_id "
            "FROM stop_times st LEFT JOIN stops s ON s.stop_id=st.stop_id "
            "LEFT JOIN stop_station ss ON ss.stop_id=st.stop_id WHERE st.tix=? ORDER BY st.seq", (tix,))

    def shape(self, shape_id):
        if not shape_id:
            return None
        r = self.q("SELECT pts FROM shapes WHERE shape_id=?", (shape_id,))
        return json.loads(r[0][0]) if r else None


def candidate_days(now_ts):
    """Service days that can have trips running around now (yesterday for >24h times)."""
    now = datetime.fromtimestamp(now_ts, TZ)
    today = now.date()
    return [today - timedelta(days=1), today, today + timedelta(days=1)]
