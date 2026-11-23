"""Walking times and paths, from a Valhalla router (pedestrian profile).

The journey planner needs two things from a walking router:
  * a matrix: how long it takes to walk from one point to many stops (to pick the stops worth walking to), and
  * a route: the path, distance and turn-by-turn steps of one walk (to draw it and to check a transfer).

Valhalla is a separate service (see docker-compose.yml) that builds its graph from the OpenStreetMap extracts of
Euskal Herria. If it is not running, or is still building its graph, every function falls back to a straight-line
estimate and says so ("engine": "estimate"), so the planner keeps working with rougher walking times.
Only the Python standard library is used.
"""
import json
import logging
import math
import os
import threading
import time
import urllib.error
import urllib.request

from store import haversine

log = logging.getLogger("mugitu.walk")

# '' disables the router. Inside docker compose the service is called "valhalla".
URL = os.environ.get("VALHALLA_URL", "http://127.0.0.1:8002").rstrip("/")
WALK_KMH = float(os.environ.get("WALK_SPEED_KMH", "4.8"))   # also what the planner assumes for estimates
DETOUR = 1.3                 # a real path is about 30 % longer than the straight line, in a town
DOWN_FOR = 30                # seconds to leave a router that failed alone before asking it again
MATRIX_MAX = 50              # targets per matrix request (Valhalla's default limit is 50 for pedestrians)

_down_until = 0.0
_lock = threading.Lock()
_state = {"checked": 0.0, "ok": False}


def enabled():
    return bool(URL)


def _post(path, payload, timeout=10):
    req = urllib.request.Request(URL + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _mark_down(e):
    global _down_until
    _down_until = time.time() + DOWN_FOR
    log.warning("walking router unavailable (%s); using estimates for %ds", e, DOWN_FOR)


def available():
    """True when the router answers. Checked at most every 20 s; a failure also pauses requests for DOWN_FOR s."""
    if not URL:
        return False
    now = time.time()
    if now < _down_until:
        return False
    with _lock:
        if now - _state["checked"] < 20:
            return _state["ok"]
        _state["checked"] = now
    try:
        with urllib.request.urlopen(URL + "/status", timeout=2) as r:
            ok = r.status == 200
    except Exception:            # not running, or still building its graph
        ok = False
    _state["ok"] = ok
    return ok


def engine():
    return "valhalla" if available() else "estimate"


# --------------------------------------------------------------------------- estimates

def est_secs(meters):
    """Walking time over a straight-line distance when no router is available."""
    return int(10 + meters * DETOUR / (WALK_KMH / 3.6))


def _opts():
    return {"pedestrian": {"walking_speed": WALK_KMH}}


# --------------------------------------------------------------------------- matrix

def matrix(origin, targets):
    """Walk from origin (lat, lon) to every target (lat, lon): list of (secs, metres) or None when it cannot be
    walked. Second value: the engine that answered. Targets are sent in chunks of MATRIX_MAX."""
    out = [None] * len(targets)
    if not targets:
        return out, engine()
    if available():
        try:
            for i in range(0, len(targets), MATRIX_MAX):
                chunk = targets[i:i + MATRIX_MAX]
                r = _post("/sources_to_targets", {
                    "sources": [{"lat": origin[0], "lon": origin[1]}],
                    "targets": [{"lat": t[0], "lon": t[1]} for t in chunk],
                    "costing": "pedestrian", "costing_options": _opts()})
                for cell in r["sources_to_targets"][0]:
                    if cell.get("time") is None:
                        continue
                    m = (cell.get("distance") or 0) * 1000.0
                    straight = haversine(origin[0], origin[1], *chunk[cell["to_index"]])
                    # Valhalla snaps a point it cannot reach (sea, a fenced area) to the nearest path, however far:
                    # a walk much longer than the straight line is not that place
                    if m > straight * 3 + 400:
                        continue
                    out[i + cell["to_index"]] = (int(cell["time"]), int(m))
            return out, "valhalla"
        except Exception as e:
            _mark_down(e)
    for i, t in enumerate(targets):
        d = haversine(origin[0], origin[1], t[0], t[1])
        out[i] = (est_secs(d), int(d * DETOUR))
    return out, "estimate"


# --------------------------------------------------------------------------- route

def decode_polyline(s, precision=6):
    """Valhalla encodes paths as a Google polyline with 6 decimals."""
    f = 10.0 ** precision
    out, i, lat, lon = [], 0, 0, 0
    while i < len(s):
        for k in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if k == 0:
                lat += d
            else:
                lon += d
        out.append([round(lat / f, 5), round(lon / f, 5)])
    return out


# Valhalla maneuver types -> the few kinds the interface speaks about
_KIND = {1: "start", 2: "start", 3: "start", 4: "dest", 5: "dest", 6: "dest", 7: "straight", 8: "straight",
         9: "slight_right", 10: "right", 11: "sharp_right", 12: "uturn", 13: "uturn", 14: "sharp_left", 15: "left",
         16: "slight_left", 17: "straight", 18: "slight_right", 19: "slight_left", 20: "right", 21: "left",
         22: "straight", 23: "slight_right", 24: "slight_left", 25: "straight", 26: "roundabout", 27: "straight"}


def _steps(maneuvers):
    steps = []
    for m in maneuvers:
        kind = _KIND.get(m.get("type"))
        if not kind:
            continue
        names = m.get("street_names") or []
        step = {"k": kind, "m": int(round((m.get("length") or 0) * 1000)), "s": int(round(m.get("time") or 0))}
        if names:
            step["street"] = names[0]
        if kind == "roundabout" and m.get("roundabout_exit_count"):
            step["exit"] = m["roundabout_exit_count"]
        steps.append(step)
    return steps


def route(a, b):
    """Walk from a to b (lat, lon): {secs, m, shape [[lat, lon]], steps, engine}."""
    if available():
        try:
            r = _post("/route", {"locations": [{"lat": a[0], "lon": a[1]}, {"lat": b[0], "lon": b[1]}],
                                 "costing": "pedestrian", "costing_options": _opts(),
                                 "directions_options": {"units": "kilometers", "language": "en-US"}})
            leg = r["trip"]["legs"][0]
            return {"secs": int(round(r["trip"]["summary"]["time"])), "m": int(round(r["trip"]["summary"]["length"] * 1000)),
                    "shape": decode_polyline(leg["shape"]), "steps": _steps(leg.get("maneuvers") or []), "engine": "valhalla"}
        except urllib.error.HTTPError as e:
            if e.code != 400:                 # 400: no path between the points; that is not an outage
                _mark_down(e)
        except Exception as e:
            _mark_down(e)
    d = haversine(a[0], a[1], b[0], b[1])
    return {"secs": est_secs(d), "m": int(d * DETOUR), "shape": [[round(a[0], 5), round(a[1], 5)], [round(b[0], 5), round(b[1], 5)]],
            "steps": [], "engine": "estimate"}
