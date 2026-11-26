"""Live GPS positions of the Villavesas buses (TUC, Comarca de Pamplona), read from the operator's web map.

Villavesas publishes no GTFS-RT, but its public interactive map (https://tuvillavesa.es/eu/interactive-map) gets
the position of every bus of a line from a SIRI-VM service:

    GET /eu/api/cit/siri/siri-vm/GetVehicleMonitoring?LineRef=<line>&NetworkRef=1

It needs one request per line and a short-lived bearer token (a JWT valid for 5 minutes). The web page obtains
that token, without any user login, from a Next.js server action, so this module does the same: nothing is
configured or stored, the token is asked for when needed and again when it expires.

The server action is identified by a hash that changes when the web page is rebuilt. When the known one stops
answering, the page's own scripts are scanned for hashes and each candidate is tried until one returns a JWT.

Each SIRI VehicleJourneyRef is exactly the GTFS trip_id of the NAP dataset (e.g. 202611261415000010031442), so a
position is tied to its scheduled trip. Lines that are not in that GTFS (R1..R5 on match days, A to the airport)
are still drawn, labelled with the name and colour the service itself publishes.

The result has the shape core.py expects of a decoded GTFS-RT feed ("vehicles" list) and is served through the
pseudo URL `siri://villavesa`, so every other part of the app treats it as any other operator with GPS.

Being polite: nothing is requested while nobody uses the app (the feed is fetched when a client asks for the
vehicles, and shared), only the lines that have a trip scheduled now are asked for (plus the ones the GTFS
lacks, rarely and with back-off), a few requests run at once, and an answer is reused for TTL seconds.

Environment: VILLAVESA_LIVE=0 switches it off; VILLAVESA_TTL (seconds, default 30) is the refresh period.
"""
import gzip
import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import sources

log = logging.getLogger("moveuskadi")

SCHEME = "siri://villavesa"
ENABLED = os.environ.get("VILLAVESA_LIVE", "1") != "0"
try:
    TTL = max(10, int(os.environ.get("VILLAVESA_TTL", "30")))
except ValueError:
    TTL = 30

SITE = "https://tuvillavesa.es"
PAGE = SITE + "/eu/interactive-map"
API = SITE + "/eu/api/cit/siri/"
NETWORK = "1"
# Next.js server action that hands out the token (found in the page's scripts; rediscovered when it changes)
ACTION_ID = os.environ.get("VILLAVESA_TOKEN_ACTION", "364dea1665ce131c2e0d388c81f8166602011a2d")
HEADERS = {"User-Agent": "mugitu/1.0 (personal use)", "Accept-Encoding": "gzip", "Referer": PAGE}
NS = "{http://www.siri.org.uk/siri}"

TOKEN_MARGIN = 30          # a token is renewed this long before it expires (s)
LINES_TTL = 6 * 3600       # the list of lines hardly ever changes
IDLE_BACKOFF = 180         # a line the GTFS does not know, found empty, is not asked again for this long (s)
KEEP_LINE = 90             # when a line's request fails, its last positions are still shown this long (s)
DISCOVER_EVERY = 600       # at most one scan of the page's scripts per this many seconds
WORKERS = 3
RETRY_CODES = (429, 502, 503, 504)
_HEX40 = re.compile(r'\("([0-9a-f]{40})"\)')
_JWT = re.compile(r"^eyJ[\w-]+\.[\w-]+\.[\w-]+$")

_lock = threading.Lock()            # token + action id
_tok = {"value": None, "exp": 0}
_action = {"id": ACTION_ID, "tried": 0}
_lines = {"t": 0, "data": {}}       # LineRef -> {"name", "line", "color", "text_color"}
_idle = {}                          # LineRef -> time it was found empty
_last = {}                          # VehicleRef -> (lat, lon, bearing, time): to derive a heading
_prev = {}                          # LineRef -> (time, [vehicle dicts]) of the last good answer


class Unavailable(Exception):
    """The service could not be read (the caller keeps what it had)."""


# --------------------------------------------------------------------------- http

def _open(req, timeout=12):
    with urllib.request.urlopen(req, timeout=timeout, context=sources.SSL_CTX) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw


def _safe_xml(raw):
    head = raw[:2048].lower()
    if b"<!doctype" in head or b"<!entity" in head:      # nothing we read needs a DTD
        raise ValueError("unexpected DTD in XML")
    return ET.fromstring(raw)


# --------------------------------------------------------------------------- token

def _parse_action(text):
    """The JWT inside a server action's response (React flight format), or None.

    A long string comes as a row `<n>:T<hex length>,<text>`, a short one as JSON `<n>:"<text>"`."""
    for m in re.finditer(r"(?:^|\n)\d+:T([0-9a-f]+),", text):
        body = text[m.end():m.end() + int(m.group(1), 16)]
        if _JWT.match(body):
            return body
    for m in re.finditer(r'"(eyJ[\w-]+\.[\w-]+\.[\w-]+)"', text):
        return m.group(1)
    return None


def _jwt_exp(tok):
    try:
        import base64
        p = tok.split(".")[1]
        return int(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["exp"])
    except Exception:
        return int(time.time()) + 240


def _call_action(action_id):
    req = urllib.request.Request(PAGE, data=b"[]", method="POST", headers=dict(HEADERS, **{
        "Next-Action": action_id, "Content-Type": "text/plain;charset=UTF-8", "Accept": "text/x-component"}))
    return _parse_action(_open(req).decode("utf-8", "replace"))


def _discover():
    """Find the token action among the hashes in the page's scripts (they change when the site is rebuilt)."""
    now = time.time()
    if now - _action["tried"] < DISCOVER_EVERY:
        return None
    _action["tried"] = now
    log.warning("villavesa: token action not answering, scanning the page for the new one")
    page = _open(urllib.request.Request(PAGE, headers=HEADERS)).decode("utf-8", "replace")
    seen = {_action["id"]}
    for path in dict.fromkeys(re.findall(r'/_next/static/chunks/[^"\'\\ ]+\.js', page)):
        try:
            js = _open(urllib.request.Request(SITE + path, headers=HEADERS), timeout=20).decode("utf-8", "replace")
        except Exception:
            continue
        for cand in _HEX40.findall(js):
            if cand in seen:
                continue
            seen.add(cand)
            try:
                tok = _call_action(cand)
            except Exception:
                continue
            if tok:
                _action["id"] = cand
                log.info("villavesa: new token action found")
                return tok
    return None


def _token(force=False):
    with _lock:
        if not force and _tok["value"] and time.time() < _tok["exp"] - TOKEN_MARGIN:
            return _tok["value"]
        tok = None
        try:
            tok = _call_action(_action["id"])
        except Exception as e:
            log.warning("villavesa: token request failed: %s", e)
        if not tok:
            try:
                tok = _discover()
            except Exception as e:
                log.warning("villavesa: token discovery failed: %s", e)
        if not tok:
            raise Unavailable("no token")
        _tok.update(value=tok, exp=_jwt_exp(tok))
        return tok


def _get(path, params):
    """GET a SIRI service with the bearer token; one retry with a fresh token when it is refused."""
    url = API + path + "?" + "&".join("%s=%s" % kv for kv in params.items())
    for attempt in (0, 1):
        req = urllib.request.Request(url, headers=dict(HEADERS, Authorization="Bearer " + _token(force=attempt == 1)))
        try:
            try:
                return _open(req)
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_CODES:
                    raise
                time.sleep(1.5)                       # overloaded for a moment: one more try
                return _open(req)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and attempt == 0:
                continue
            raise
    raise Unavailable("refused")


# --------------------------------------------------------------------------- lines and positions

def lines():
    """{LineRef: {name, line, color, text_color}} as published by the service (cached for hours)."""
    if time.time() - _lines["t"] < LINES_TTL and _lines["data"]:
        return _lines["data"]
    try:
        root = _safe_xml(_get("siri-discovery/GetLinesDiscovery", {"NetworkRef": NETWORK}))
        data = {}
        for a in root.iter(NS + "AnnotatedLineRef"):
            ref = (a.findtext(NS + "LineRef") or "").strip()
            if not ref:
                continue
            ext = a.find(".//" + NS + "LineExtension")
            g = (lambda k: (ext.findtext(NS + k) or "").strip()) if ext is not None else (lambda k: "")
            data[ref] = {"name": (a.findtext(NS + "LineName") or "").strip(), "line": g("PublishedLineName") or ref,
                         "color": g("LineColor").lstrip("#").upper(), "text_color": g("LineTextColor").lstrip("#").upper()}
        if data:
            _lines.update(t=time.time(), data=data)
    except Exception as e:
        log.warning("villavesa: lines list unavailable: %s", e)
        _lines["t"] = time.time() - LINES_TTL + 300       # try again in 5 minutes, meanwhile use what we have
    return _lines["data"]


def _epoch(s):
    """SIRI timestamp (ISO 8601 with offset) -> epoch seconds."""
    try:
        return int(datetime.fromisoformat(s.strip().replace("Z", "+00:00")).timestamp())
    except Exception:
        return int(time.time())


def _bearing(a_lat, a_lon, b_lat, b_lon):
    return math.degrees(math.atan2((b_lon - a_lon) * math.cos(math.radians(a_lat)), b_lat - a_lat)) % 360


def _metres(a_lat, a_lon, b_lat, b_lon):
    return math.hypot((b_lon - a_lon) * math.cos(math.radians(a_lat)) * 111320.0, (b_lat - a_lat) * 110540.0)


def _line_positions(line, meta):
    """Vehicles of one line, as GTFS-RT style dicts."""
    root = _safe_xml(_get("siri-vm/GetVehicleMonitoring", {"LineRef": line, "NetworkRef": NETWORK}))
    out = []
    for act in root.iter(NS + "VehicleActivity"):
        j = act.find(NS + "MonitoredVehicleJourney")
        if j is None:
            continue
        try:
            lat = float(j.findtext(NS + "VehicleLocation/" + NS + "Latitude"))
            lon = float(j.findtext(NS + "VehicleLocation/" + NS + "Longitude"))
        except (TypeError, ValueError):
            continue
        ref = (j.findtext(NS + "VehicleJourneyRef") or "").strip()
        veh = (j.findtext(NS + "VehicleRef") or "").strip()
        if not veh or not (-90 < lat < 90):
            continue
        out.append({"id": veh, "lat": lat, "lon": lon, "bearing": None, "speed": None,
                    "timestamp": _epoch(act.findtext(NS + "RecordedAtTime") or ""),
                    "trip": {"trip_id": ref, "route_id": line, "start_date": ref[:8] if ref[:8].isdigit() else None},
                    "vehicle": {"id": veh, "label": veh}, "shape_heading": True,
                    "line_meta": dict(meta) if meta else None})
    return out


def _with_heading(vehicles, now):
    """SIRI gives no heading: derive it from the distance the bus moved since the last time it was seen."""
    for v in vehicles:
        k = v["id"]
        prev = _last.get(k)
        if prev and now - prev[3] < 180:
            if _metres(prev[0], prev[1], v["lat"], v["lon"]) >= 15:
                v["bearing"] = round(_bearing(prev[0], prev[1], v["lat"], v["lon"]))
                _last[k] = (v["lat"], v["lon"], v["bearing"], now)
            else:
                v["bearing"] = prev[2]
        else:
            _last[k] = (v["lat"], v["lon"], None, now)
    if len(_last) > 2000:
        for k in [k for k, p in _last.items() if now - p[3] > 600]:
            del _last[k]


def fetch(scheduled_lines, gtfs_lines):
    """Positions of all buses now, as a decoded-feed dict.

    scheduled_lines: LineRefs with a trip running now according to the timetable (always asked for);
    gtfs_lines: every route id of the GTFS (the other lines the service knows are asked for from time to time).
    Raises Unavailable when nothing could be read."""
    now = time.time()
    meta = lines()
    todo = set(scheduled_lines)
    for ref in meta:
        if ref not in gtfs_lines and now - _idle.get(ref, 0) > IDLE_BACKOFF:
            todo.add(ref)
    if not todo:
        return {"timestamp": int(now), "trip_updates": [], "vehicles": [], "alerts": []}

    def one(line):
        try:
            return line, _line_positions(line, None if line in gtfs_lines else meta.get(line)), None
        except Exception as e:
            return line, None, e

    ok, errors, vehicles = 0, [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for line, res, err in ex.map(one, sorted(todo)):
            if err is not None:
                errors.append(err)
                old = _prev.get(line)
                if old and now - old[0] < KEEP_LINE:
                    vehicles.extend(old[1])
                continue
            ok += 1
            _prev[line] = (now, res)
            if not res and line not in scheduled_lines:
                _idle[line] = now
            vehicles.extend(res)
    if errors and not ok:
        raise Unavailable("%d line requests failed (%s)" % (len(errors), errors[0]))
    if errors:
        log.info("villavesa: %d of %d line requests failed (%s)", len(errors), len(todo), errors[0])
    _with_heading(vehicles, now)
    ts = max([v["timestamp"] for v in vehicles] or [int(now)])
    return {"timestamp": ts, "trip_updates": [], "vehicles": vehicles, "alerts": []}
