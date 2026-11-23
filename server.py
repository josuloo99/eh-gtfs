#!/usr/bin/env python3
"""Mugitu - local web server (static UI + JSON API over GTFS / GTFS-RT).

Run:  python3 server.py [--port 8000] [--host 127.0.0.1]
Only the Python 3.9+ standard library is required.
"""
import argparse
import gzip
import hashlib
import json
import logging
import mimetypes
import os
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import core
import places
import planner
import walk

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")


def _f(q, k, default=None):
    try:
        return float(q[k][0])
    except (KeyError, ValueError, IndexError):
        return default


def _s(q, k, default=""):
    return q.get(k, [default])[0]


def api(path, q):
    if path == "/api/agencies":
        core.refresh(list(core.AGENCIES), ["vehicles", "trips", "alerts"]) if _s(q, "probe") else None
        return {"time": int(time.time()), "agencies": core.agencies_summary()}
    if path == "/api/vehicles":
        # optional s,w,n,e = map area currently showing buses: tells the Lurraldebus tracker what to cover
        view = [_f(q, k) for k in ("s", "w", "n", "e")]
        if None not in view:
            core.lb_note_view(*view)
        return core.vehicles()
    if path == "/api/search":
        r = core.search_all(_s(q, "q"))
        return {"results": r["stations"], "routes": r["routes"], "operators": r["operators"]}
    if path == "/api/nearby":
        lat, lon = _f(q, "lat"), _f(q, "lon")
        if lat is None or lon is None:
            return {"results": []}
        return {"results": core.nearby(lat, lon, _f(q, "radius", 600))}
    if path == "/api/stations":
        s, w, n, e = (_f(q, k) for k in ("s", "w", "n", "e"))
        if None in (s, w, n, e):
            return {"stations": []}
        return {"stations": core.stations_in_bbox(s, w, n, e, rail_only=_s(q, "rail") == "1")}
    if path == "/api/departures":
        slug, sid = _s(q, "agency"), _s(q, "station")
        if slug not in core.DBS or not core.AGENCIES[slug]["ready"]:
            return {"error": "unknown agency"}
        st = core.DBS[slug].station(sid)
        if not st:
            return {"error": "unknown station"}
        kind = "arr" if _s(q, "kind") == "arr" else "dep"
        info = core.AGENCIES[slug]
        peers = core.lb_peers(slug, sid)
        modes = ",".join(sorted({m for p in peers for m in (core.DBS[p].station(sid)["modes"] or "").split(",") if m}))
        names = " · ".join(core.AGENCIES[p]["name"] for p in peers)
        lim = core.limits_payload(peers)
        if _s(q, "date"):    # theoretical timetable of a whole day, no real-time data
            d = core.parse_date(_s(q, "date"))
            lo, hi = core.date_limits(peers)
            if d is None or not (lo <= d <= hi):
                return {"error": "date_out_of_range", "range": lim}
            items = core.schedule_departures(peers, sid, d, kind) or []
            return {"station": dict(st, agency=slug, agency_name=names, modes=modes or st["modes"]), "kind": kind,
                    "time": int(time.time()), "items": items, "rt_status": "sched", "date": d.strftime("%Y%m%d"),
                    "range": lim, "alerts": []}
        line = {tuple(x.split("|", 1)) for x in q.get("line", []) if "|" in x} or None
        res = core.departures(slug, sid, kind, int(_f(q, "limit", 15)), line=line)
        trips_stat = core.feed_stats(slug, "trips") if info["rt"].get("trips") else {"status": "none"}
        rt_status = core.lb_status(res or []) if core.is_lb(slug) else trips_stat["status"]
        extra = {"lines": core.station_lines(peers, sid)} if _s(q, "lines") == "1" else {}
        return {**extra, "station": dict(st, agency=slug, agency_name=names, modes=modes or st["modes"]), "kind": kind,
                "time": int(time.time()), "items": res or [], "rt_status": rt_status, "range": lim,
                "alerts": [a for p in peers for a in core.alerts(p) if _alert_applies(a, p, sid, [i for i in (res or []) if i["agency"] == p])]}
    if path == "/api/trip":
        slug = _s(q, "agency")
        if slug not in core.DBS:
            return {"error": "unknown agency"}
        res = core.trip_detail(slug, _s(q, "trip"), _s(q, "date") or None, sched_only=_s(q, "sched") == "1")
        return res or {"error": "unknown trip"}
    if path == "/api/route_schedule":
        slug = _s(q, "agency")
        if slug not in core.DBS:
            return {"error": "unknown agency"}
        lim = core.limits_payload([slug])
        d = core.parse_date(_s(q, "date"))
        lo, hi = core.date_limits([slug])
        if d is None or not (lo <= d <= hi):
            return {"error": "date_out_of_range", "range": lim}
        return {"date": d.strftime("%Y%m%d"), "range": lim, "directions": core.route_schedule(slug, _s(q, "route"), d)}
    if path == "/api/route":
        slug = _s(q, "agency")
        if slug not in core.DBS:
            return {"error": "unknown agency"}
        res = core.route_detail(slug, _s(q, "route"))
        res["range"] = core.limits_payload([slug])
        return res
    if path == "/api/routes":
        slug = _s(q, "agency")
        if slug not in core.DBS:
            return {"error": "unknown agency"}
        return {"routes": core.routes_of(slug)}
    if path == "/api/alerts":
        return {"alerts": core.alerts(_s(q, "agency") or None)}
    if path == "/api/plan":
        return planner.plan(q, _s(q, "lang", "eu"))
    if path == "/api/plan_status":
        return planner.status()
    if path == "/api/geocode":
        return _geocode(q)
    return None


def _geocode(q):
    """Places for the "from / to" boxes of the journey planner. ?q= text: towns, neighbourhoods and stations that
    match. ?lat=&lon= a point: the place it is near (for a spot tapped on the map)."""
    lang = _s(q, "lang", "eu")
    lat, lon = _f(q, "lat"), _f(q, "lon")
    if lat is not None and lon is not None:
        p = places.nearest(lat, lon, lang)
        return {"place": {"label": p["label"], "kind": p["kind"], "dist": p["dist"]} if p else None}
    text = _s(q, "q").strip()
    out = []
    for p in places.search(text, lang, 6):
        out.append({"type": "place", "name": p["label"], "kind": p["kind"], "lat": p["lat"], "lon": p["lon"],
                    "_k": (p["rank"], 0, places.KIND_RANK.get(p["kind"], 4))})
    qn = places.norm(text)
    for s in core.search_stations(text, 8):
        n = places.norm(s["name"])
        rank = 0 if n == qn else 1 if n.startswith(qn) else 2
        out.append({"type": "station", "name": s["name"], "agency": s["agency"], "agency_name": s["agency_name"],
                    "station_id": s["station_id"], "lat": s["lat"], "lon": s["lon"], "modes": s["modes"], "_k": (rank, 1, 2)})
    out.sort(key=lambda x: x["_k"])
    for x in out:
        del x["_k"]
    return {"results": out[:9]}


def _alert_applies(a, slug, station_id, items):
    routes = {i["route_id"] for i in items}
    stops = set(core.DBS[slug].station_stops(station_id))
    for e in a["entities"]:
        if e.get("route_id") in routes or (e.get("stop_id") and e["stop_id"] in stops):
            return True
    return False


# ---- static files and cache busting
#
# index.html is rendered on the fly: every local css / js / image / manifest it points to gets "?v=<hash of the
# file's content>". A versioned URL never changes meaning, so browsers may keep it for a year (immutable); when a
# file changes its hash changes, the URL changes, and browsers fetch it again. index.html itself is always
# revalidated (ETag, so an unchanged page costs a 304). Anything fetched without a matching ?v= is revalidated too.
_hash_cache = {}                 # path -> (mtime_ns, size, hash)
_LOCAL_REF = re.compile(r'(href|src)="([^"?#:]+\.(?:css|js|png|svg|webmanifest|ico))"')


def file_hash(fp):
    st = os.stat(fp)
    hit = _hash_cache.get(fp)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    with open(fp, "rb") as f:
        h = hashlib.sha1(f.read()).hexdigest()[:10]
    _hash_cache[fp] = (st.st_mtime_ns, st.st_size, h)
    return h


def render_index(fp):
    with open(fp, encoding="utf-8") as f:
        html = f.read()

    def version(m):
        ref = m.group(2)
        if ref.startswith("//"):
            return m.group(0)
        target = os.path.normpath(os.path.join(STATIC, ref.lstrip("/")))
        if target.startswith(STATIC + os.sep) and os.path.isfile(target):
            return '%s="%s?v=%s"' % (m.group(1), ref, file_hash(target))
        return m.group(0)
    return _LOCAL_REF.sub(version, html).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Mugitu/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("DEBUG_HTTP"):
            super().log_message(fmt, *args)

    def _send(self, code, body, ctype, extra=None):
        accept = self.headers.get("Accept-Encoding", "")
        if len(body) > 1024 and "gzip" in accept:
            body = gzip.compress(body, 5)
            enc = True
        else:
            enc = False
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if enc:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _not_modified(self, extra):
        self.send_response(304)
        for k, val in extra.items():
            self.send_header(k, val)
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/"):
            try:
                res = api(u.path, parse_qs(u.query))
            except Exception as e:
                logging.getLogger("moveuskadi").error("API error %s: %s", self.path, traceback.format_exc())
                return self._send(500, json.dumps({"error": str(e)}).encode(), "application/json",
                                  {"Cache-Control": "no-store"})
            if res is None:
                return self._send(404, b'{"error":"not found"}', "application/json")
            return self._send(200, json.dumps(res, separators=(",", ":")).encode(), "application/json",
                              {"Cache-Control": "no-store"})
        rel = "index.html" if u.path in ("", "/") else u.path.lstrip("/")
        fp = os.path.normpath(os.path.join(STATIC, rel))
        if not fp.startswith(STATIC + os.sep) or not os.path.isfile(fp):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        if fp.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "application/manifest+json"):
            ctype += "; charset=utf-8"
        if os.path.basename(fp) == "index.html":
            body = render_index(fp)
            tag = hashlib.sha1(body).hexdigest()[:16]
            cache = "no-cache"
        else:
            body = None
            tag = file_hash(fp)
            # a URL carrying the file's current hash is immutable; anything else must be revalidated
            cache = "public, max-age=31536000, immutable" if parse_qs(u.query).get("v") == [tag[:10]] else "no-cache"
        etag = 'W/"%s"' % tag
        headers = {"Cache-Control": cache, "ETag": etag}
        if self.headers.get("If-None-Match") == etag:
            return self._not_modified(headers)
        if body is None:
            with open(fp, "rb") as f:
                body = f.read()
        self._send(200, body, ctype, headers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    threading.Thread(target=core.updater_loop, daemon=True).start()
    threading.Thread(target=core.lb_tracker_loop, daemon=True).start()
    planner.start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print("Serving on http://%s:%d" % (a.host, a.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
