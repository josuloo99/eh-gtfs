"""Operators that are not listed in the Basque Government's MovEuskadi index.

Euskal Herria is served by feeds of several administrations. The Basque Government (Euskadi) is read through
its data-index in core.py. Everything else is configured here, one entry per operator, and is treated exactly
like an Euskadi operator once its URLs are known: same importer, same real-time pipeline, same UI.

Today: Ipar Euskal Herria (French Basque Country) from https://transport.data.gouv.fr, Renfe straight from
renfe.com, and Nafarroa from the Spanish Ministry's National Access Point (NAP, https://nap.transportes.gob.es).
Adding an operator is one more entry in SOURCES.

Static feeds (static_feed). Operators that publish no GTFS at all, only PDFs (La Baztanesa), are typed once into
feeds/<name>.json and turned into a GTFS at import time (see staticfeeds.py). Nothing is downloaded or resolved.

NAP (nap_dataset). Its API needs a personal key, sent in the `ApiKey` header. The key is read from the
environment variable NAP_API_KEY and is never written in the code, the logs, data/sources.json or the repository.
The API gives the current file of a dataset and, on request, a pre-signed download link that expires in 15
minutes, so the link is asked for only when the file is downloaded (and is fetched without the key). Without the
key, operators already imported keep working and nothing new is downloaded.

API keys. Some feeds (Txik Txak, hosted by Mecatran) need `?apiKey=...` in the URL, and the key may change.
Nothing is hard-coded: the URLs are resolved at run time from the portal, in this order:

  1. the dataset API of transport.data.gouv.fr lists every resource with a permanent link
     (https://www.data.gouv.fr/api/1/datasets/r/<uuid>) and the publisher's current `original_url`;
  2. the permanent link answers 302 to the publisher's current keyed URL: that Location is used (it is what
     the publisher registered most recently, so it is the first to show a rotated key);
  3. the dataset API's original_url, then the last URLs that worked (kept in data/sources.json), so the app
     still starts when the portal is down.

A 401/403 from a feed makes the caller ask for a fresh resolution (`refresh_soon`).
Only the Python standard library is used.
"""
import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.request

import staticfeeds
import store

log = logging.getLogger("moveuskadi.sources")

UA = {"User-Agent": "mugitu/1.0 (personal use)"}

# Python 3.13 turned on VERIFY_X509_STRICT by default, which rejects the certificate of app.mecatran.com
# (Txik Txak) because it has no Authority Key Identifier. The chain and the host name are still verified;
# only that extra RFC 5280 strictness is switched off.
SSL_CTX = ssl.create_default_context()
SSL_CTX.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
TDG_DATASET = "https://transport.data.gouv.fr/api/datasets/%s"
NAP_API = "https://nap.transportes.gob.es/api/v2/"
NAP_KEY_ENV = "NAP_API_KEY"
CACHE_FILE = os.path.join(store.DATA_DIR, "sources.json")
MIN_REFRESH = 300      # seconds between two forced resolutions of the same operator

# region ids: "eus" Euskadi (Basque Autonomous Community), "nav" Nafarroa, "ipar" Ipar Euskal Herria.
# quirks: see core.py (zero_delay_untracked) and store.import_gtfs (city_in_name).
SOURCES = [
    {
        "slug": "txiktxak",
        "name": "Txik Txak",
        "region": "ipar",
        "tdg_dataset": "64106d7aad276449cf02fb0a",                # Réseau interurbain TXIK TXAK
        "resources": {"gtfs": 80701, "trips": 80703, "alerts": 80702},   # transport.data.gouv.fr resource ids
        "quirks": {"zero_delay_untracked": True, "city_in_name": True},
    },
    {
        # Renfe Cercanias, straight from Renfe. Replaces the copy of the same GTFS in the MovEuskadi index
        # (same slug, so it takes that entry's place). It is one national feed for every Cercanias network in
        # Spain: the importer and the real-time filters keep only the lines that touch Euskal Herria
        # (see region.py and store.import_gtfs, core.region_items). The real-time ids match this GTFS.
        "slug": "renfe_cercanias",
        "name": "RENFE Cercanias",
        "region": "eh",
        "gtfs_url": "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip",
        "rt": {
            "vehicles": "https://gtfsrt.renfe.com/vehicle_positions.pb",
            "trips": "https://gtfsrt.renfe.com/trip_updates.pb",
            "alerts": "https://gtfsrt.renfe.com/alerts.pb",
        },
        "replaces_index": True,       # ignore the operator of the same slug in the MovEuskadi index
    },
    {
        # Renfe long and medium distance (Alvia, Intercity, Media Distancia, Avant; no high speed reaches Euskal
        # Herria), straight from Renfe. Replaces the MovEuskadi copy. Timetable only: Renfe publishes no
        # real-time feed for these trains.
        "slug": "renfe_media",
        "name": "RENFE Larga y Media Distancia",
        "region": "eh",
        "gtfs_url": "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip",
        "replaces_index": True,
    },
    {
        # Nafarroa, from the Spanish Ministry's National Access Point (dataset ids = ConjuntoDato/Detail/<id>).
        "slug": "navarra_interurbano",
        "name": "Interurbano de Navarra",
        "region": "nav",
        "nap_dataset": 963,           # Autobus interurbano de Navarra (Gobierno de Navarra)
        "quirks": {"headsign_town": True},   # the feed has no trip_headsign
    },
    {
        "slug": "villavesas",
        "name": "Villavesas (Comarca de Pamplona)",
        "region": "nav",
        "nap_dataset": 976,           # Autobus Comarca de Pamplona (Infotuc)
        # GPS from the operator's web map (SIRI-VM), no GTFS-RT exists; see villavesa.py
        "rt_static": {"vehicles": "siri://villavesa"},
    },
    {
        # La Baztanesa (Elizondo - Pamplona - Donostia) publishes only PDF timetables, no GTFS: transcribed by hand
        # into feeds/labaztanesa.json. Stop positions come from OpenStreetMap; see the file and the README.
        "slug": "labaztanesa",
        "name": "La Baztanesa",
        "region": "nav",
        "static_feed": "labaztanesa",
    },
    {
        # ALSA publishes one national GTFS: the importer keeps only the trips that call inside Euskal Herria.
        "slug": "alsa",
        "name": "ALSA",
        "region": "eh",
        "nap_dataset": 932,           # ALSA autobuses
    },
]


def replaced_in_index(slug):
    return any(s["slug"] == slug and s.get("replaces_index") for s in SOURCES)

_lock = threading.Lock()          # one resolution at a time (it touches the cache file)
_force_lock = threading.Lock()
_last_forced = {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read())


def _location(permalink, timeout=20):
    """The URL a data.gouv.fr permanent link currently redirects to (not followed, never downloaded)."""
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=SSL_CTX))
    try:
        opener.open(urllib.request.Request(permalink, headers=UA), timeout=timeout)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "") if e.code in (301, 302, 303, 307, 308) else ""
        if loc.startswith("https://"):
            return loc
    return None


def _load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1)
        os.replace(CACHE_FILE + ".tmp", CACHE_FILE)
    except OSError as e:
        log.warning("cannot save %s: %s", CACHE_FILE, e)


def source_label(src):
    """Where an operator's data comes from (shown nowhere secret; used by core for 'is this the MovEuskadi index')."""
    if src.get("static_feed"):
        return "transcribed timetable"
    if src.get("nap_dataset"):
        return "nap.transportes.gob.es"
    return "renfe.com" if src.get("gtfs_url") else "transport.data.gouv.fr"


def resolve(src):
    res = _resolve(src)
    if res and src.get("rt_static"):
        res = dict(res, rt=dict(res["rt"], **src["rt_static"]))     # pseudo URLs handled inside core.get_feed
    return res


def _resolve(src):
    """Current URLs of one operator: {"gtfs": url, "stamp": str, "rt": {"trips": url, "alerts": url}} or None.

    `stamp` changes when the publisher updates the timetable (the importer re-imports on change)."""
    if src.get("static_feed"):
        return {"gtfs": STATIC_SCHEME + src["static_feed"], "stamp": staticfeeds.stamp(src["static_feed"]), "rt": {}}
    if src.get("nap_dataset"):
        return _resolve_nap(src)
    if src.get("gtfs_url"):
        return _resolve_direct(src)
    with _lock:
        cache = _load_cache()
        found = {}
        try:
            ds = _get_json(TDG_DATASET % src["tdg_dataset"])
            by_id = {r.get("id"): r for r in ds.get("resources", [])}
            for kind, rid in src["resources"].items():
                r = by_id.get(rid)
                if not r:
                    log.warning("%s: resource %s is no longer in the dataset", src["slug"], rid)
                    continue
                url = None
                if r.get("url"):
                    url = _location(r["url"])           # live answer of the permanent link
                url = url or r.get("original_url") or r.get("url")
                if url and url.startswith("https://"):
                    found[kind] = {"url": url, "stamp": r.get("updated") or ""}
        except Exception as e:
            log.warning("%s: transport.data.gouv.fr unreachable (%s); using the last known URLs", src["slug"], e)
        old = cache.get(src["slug"], {})
        merged = dict(old)
        merged.update(found)
        if found:
            cache[src["slug"]] = merged
            _save_cache(cache)
        if "gtfs" not in merged:
            return None
        return {"gtfs": merged["gtfs"]["url"], "stamp": merged["gtfs"].get("stamp", ""),
                "rt": {k: merged[k]["url"] for k in ("trips", "alerts") if k in merged}}


# ---- National Access Point (Spanish Ministry of Transport)

NAP_SCHEME = "nap://fichero/"
STATIC_SCHEME = "static://"


def nap_key():
    return os.environ.get(NAP_KEY_ENV, "").strip()


def _nap_get(path):
    """GET on the NAP API; returns the 'data' of the answer. Raises when there is no key (the key is not logged)."""
    key = nap_key()
    if not key:
        raise RuntimeError("%s is not set" % NAP_KEY_ENV)
    req = urllib.request.Request(NAP_API + path, headers=dict(UA, ApiKey=key, Accept="application/json"))
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        body = json.loads(r.read())
    if body.get("success") is False:
        raise RuntimeError("NAP: %s" % (body.get("message") or "request failed"))
    return body.get("data")


def _resolve_nap(src):
    """Timetable file of a NAP dataset: pseudo URL 'nap://fichero/<id>' and the file's update date as stamp.

    Falls back to what the last successful run saw (data/sources.json) when the API cannot be asked, e.g. no key
    or the portal is down, so an operator that was already imported stays available."""
    found = None
    try:
        ds = _nap_get("conjunto-dato/%d" % src["nap_dataset"]) or {}
        files = [f for f in ds.get("ficheros", []) if "zip" in (f.get("nombreTipoFichero") or "").lower()]
        if files:
            # a valid file first, then the most recently updated one
            f = max(files, key=lambda f: (bool(f.get("esValido")), f.get("fechaActualizacion") or ""))
            found = {"file": f["id"], "stamp": f.get("fechaActualizacion") or ""}
        else:
            log.warning("%s: NAP dataset %s has no GTFS file", src["slug"], src["nap_dataset"])
    except Exception as e:
        log.warning("%s: NAP not available (%s); using the last known file", src["slug"], e)
    with _lock:
        cache = _load_cache()
        if found:
            if cache.get(src["slug"]) != found:
                cache[src["slug"]] = found
                _save_cache(cache)
        else:
            found = cache.get(src["slug"])
    if not found or not found.get("file"):
        return None
    return {"gtfs": NAP_SCHEME + str(found["file"]), "stamp": found.get("stamp", ""), "rt": {}}


def nap_download_url(pseudo_url):
    """Fresh pre-signed download link (valid 15 minutes) for a 'nap://fichero/<id>' file."""
    fid = int(pseudo_url[len(NAP_SCHEME):])
    data = _nap_get("fichero/%d/descarga" % fid) or {}
    url = data.get("enlaceDescarga")
    if not url or not url.startswith("https://"):
        raise RuntimeError("NAP gave no download link for file %d" % fid)
    return url


def _resolve_direct(src):
    """Operator with fixed URLs: the timetable 'stamp' is the file's Last-Modified (or ETag) from a HEAD request,
    so the importer re-imports when the publisher uploads a new file."""
    url = src["gtfs_url"]
    stamp = ""
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            stamp = r.headers.get("Last-Modified") or r.headers.get("ETag") or ""
    except Exception as e:
        log.warning("%s: cannot read the headers of %s (%s)", src["slug"], url, e)
    with _lock:
        cache = _load_cache()
        if stamp:
            if cache.get(src["slug"], {}).get("stamp") != stamp:
                cache[src["slug"]] = {"stamp": stamp}
                _save_cache(cache)
        else:
            stamp = cache.get(src["slug"], {}).get("stamp", "")   # keep the last known one: no needless re-import
    return {"gtfs": url, "stamp": stamp, "rt": dict(src.get("rt") or {})}


def should_force(slug):
    """True at most once every MIN_REFRESH seconds per operator (callers hit 401/403 in bursts)."""
    now = time.time()
    with _force_lock:
        if now - _last_forced.get(slug, 0) < MIN_REFRESH:
            return False
        _last_forced[slug] = now
        return True


def by_slug(slug):
    return next((s for s in SOURCES if s["slug"] == slug), None)
