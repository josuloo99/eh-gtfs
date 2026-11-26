"""Live stop arrivals of Bizkaibus, from the Diputacion Foral de Bizkaia's own web service.

The vehicle feed Bizkaibus publishes is one snapshot of all its buses, rebuilt about every two minutes, so a position
is 130-215 s old by the time it reaches the app (and its vehicle ids change with every snapshot). The service behind
bizkaia.eus' "next buses at this stop" box answers, for one stop:

    for every line that calls there, the next two buses: minutes to arrive AND metres still to travel.

The metres are what makes it useful: they place the bus on its route right now. Measured against the snapshots
(buses 0-15 minutes from a stop), the distance to the stop was off by about 100 m (90th percentile 250-380 m), against
330-500 m (1.3-2.5 km) for the snapshot advanced along the timetable.

    POST https://apli.bizkaia.net/apps/danok/tqws/tq.asmx/GetPasoParadaMobile_JSON
         callback=&strLinea=*&strParada=<stop code, 4 digits, zero padded>

The code is the GTFS stop_id padded to four digits ("307" is unknown, "0307" works; five digits are other stops).
The answer is JSONP whose 'Resultado' is XML. No key, no cookie; CORS is open (the site calls it from the browser).

Being polite: a stop is asked for at most every TTL_OK seconds whoever needs it, requests are rate limited (RATE per
second for everybody together, 2 at a time), repeated failures pause the client (circuit breaker), and the tracker
in core.py asks only while somebody is looking at a map area with Bizkaibus buses, and only for the stops that
cover the buses in view.

Environment: BIZKAIBUS_LIVE=0 switches it off; BIZKAIBUS_RATE sets requests per second (default 1.5).
"""
import gzip
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque

from lurraldebus import _Bucket          # the same token bucket

log = logging.getLogger("moveuskadi")

URL = "https://apli.bizkaia.net/apps/danok/tqws/tq.asmx/GetPasoParadaMobile_JSON"
UA = "mugitu/1.0 (personal use; low-rate, cached)"
ENABLED = os.environ.get("BIZKAIBUS_LIVE", "1") != "0"


def _env_float(name, default):
    try:
        return max(0.05, float(os.environ.get(name, default)))
    except ValueError:
        return default


RATE = _env_float("BIZKAIBUS_RATE", 1.5)
BURST = 4
MAX_PARALLEL = 2
TIMEOUT = 10
TTL_OK = 25            # an answer with buses is reused for this long (s)
TTL_EMPTY = 90         # a stop with no buses is not asked again for this long
STALE_MAX = 180        # while the service fails, answers up to this old are still served
MAX_BYTES = 1 << 20
_STOP_RE = re.compile(r"^\d{1,4}$")
_RESULT = re.compile(r"'Resultado':\s*'(.*?)'\s*,\s*'Info'", re.S)
_STATUS = re.compile(r"'STATUS':\s*'(\w+)'")


def code(stop_id):
    """The service's stop code for a GTFS stop_id, or None when it cannot be one."""
    if not stop_id or not _STOP_RE.match(str(stop_id)):
        return None
    return "%04d" % int(stop_id)


def _unescape(s):
    return re.sub(r"\\(['\"\\/])", r"\1", s)


def parse(text):
    """-> (status, arrivals). status: 'ok' (arrivals is not empty), 'empty' (a valid answer without buses: unknown stop
    or none coming) or 'unparsed' (the answer is not what we know: treated as a failure by the caller).

    arrivals: [{"line": "A3912", "dest": "EIBAR", "buses": [{"minutes": 19, "metres": 11173}, ...]}]  (1-2 buses)."""
    st = _STATUS.search(text)
    if not st:
        return "unparsed", []
    if st.group(1) != "OK":
        return "empty", []
    m = _RESULT.search(text)
    if not m or b"<!DOCTYPE" in m.group(1).encode("utf-8", "ignore")[:200].upper() or "<!ENTITY" in m.group(1).upper():
        return "unparsed", []
    try:
        root = ET.fromstring(_unescape(m.group(1)))
    except ET.ParseError:
        return "unparsed", []
    out = []
    for p in root.iter("PasoParada"):
        line = (p.findtext("linea") or "").strip()
        if not line:
            continue
        buses = []
        for tag in ("e1", "e2"):
            mins, metres = (p.findtext(tag + "/minutos") or "").strip(), (p.findtext(tag + "/metros") or "").strip()
            if mins.isdigit() and metres.isdigit():
                buses.append({"minutes": int(mins), "metres": int(metres)})
        if buses:
            out.append({"line": line, "dest": (p.findtext("ruta") or "").strip(), "buses": buses})
    return ("ok" if out else "empty"), out


class Client:
    def __init__(self, rate=None, fetch=None):
        self.bucket = _Bucket(RATE if rate is None else rate, BURST)
        self.slots = threading.BoundedSemaphore(MAX_PARALLEL)
        self.cache = {}                      # code -> result dict
        self.locks = {}
        self.meta = threading.Lock()
        self.fail = 0
        self.open_until = 0.0
        self.last_ok = 0.0
        self.last_error = ""
        self.sent = deque(maxlen=4000)
        self.errors = deque(maxlen=200)
        self._fetch = fetch or self._http

    def _http(self, stop_code):
        data = urllib.parse.urlencode({"callback": "", "strLinea": "*", "strParada": stop_code}).encode()
        req = urllib.request.Request(URL, data=data, headers={
            "User-Agent": UA, "Accept-Encoding": "gzip", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read(MAX_BYTES)
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")

    def _failed(self, why, retry_after=0):
        with self.meta:
            self.fail += 1
            self.last_error = why[:120]
            self.errors.append(time.time())
            if self.fail >= 3 or retry_after:
                delay = max(retry_after, min(30 * 2 ** (self.fail - 3), 600))
                self.open_until = time.time() + delay
                log.warning("bizkaia.net stop service failing (%s); pausing requests for %ds", why, delay)

    def _succeeded(self):
        with self.meta:
            self.fail, self.open_until, self.last_ok = 0, 0.0, time.time()

    def _lock(self, key):
        with self.meta:
            return self.locks.setdefault(key, threading.Lock())

    def peek(self, stop_id):
        c = code(stop_id)
        return self.cache.get(c) if c else None

    def get(self, stop_id, max_age=TTL_OK, wait=5.0):
        """Answer for a stop: {stop_id, status, arrivals, fetched, ms, stale} or None (disabled, invalid code, paused,
        throttled and nothing cached). A fresh enough cached answer is returned without a request."""
        c = code(stop_id)
        if not ENABLED or not c:
            return None
        now = time.time()

        def fresh(h, t):
            return h and t - h["fetched"] <= (max(max_age, TTL_EMPTY) if h["status"] == "empty" else max_age)
        hit = self.cache.get(c)
        if fresh(hit, now):
            return hit
        with self._lock(c):
            hit = self.cache.get(c)
            now = time.time()
            if fresh(hit, now):
                return hit
            stale = hit if hit and now - hit["fetched"] <= STALE_MAX else None
            if now < self.open_until:
                return dict(stale, stale=True) if stale else None
            if not self.bucket.take(wait):
                return dict(stale, stale=True) if stale else None
            with self.slots:
                t0 = time.time()
                self.sent.append(t0)
                try:
                    text = self._fetch(c)
                except urllib.error.HTTPError as e:
                    ra = e.headers.get("Retry-After", "") if e.headers else ""
                    self._failed("HTTP %s" % e.code, int(ra) if ra.isdigit() and e.code in (429, 503) else 0)
                    return dict(stale, stale=True) if stale else None
                except Exception as e:
                    self._failed(type(e).__name__)
                    return dict(stale, stale=True) if stale else None
            fetched = time.time()
            status, arrivals = parse(text)
            if status == "unparsed":
                self._failed("unrecognised answer")
                return dict(stale, stale=True) if stale else None
            self._succeeded()
            res = {"stop_id": str(stop_id), "status": status, "arrivals": arrivals, "fetched": fetched,
                   "t_asked": t0, "stale": False, "ms": int((fetched - t0) * 1000)}
            self.cache[c] = res
            return res

    def stats(self):
        now = time.time()
        state = "off" if not ENABLED else "paused" if now < self.open_until else \
            "live" if self.last_ok and now - self.last_ok < 600 else "idle"
        return {"state": state, "requests_hour": sum(1 for t in self.sent if now - t < 3600),
                "errors_hour": sum(1 for t in self.errors if now - t < 3600), "cached": len(self.cache),
                "last_ok": int(self.last_ok) or None, "last_error": self.last_error,
                "paused_for": max(0, int(self.open_until - now))}


client = Client()
