#!/usr/bin/env python3
"""Builds places.json: the towns, villages, hamlets and neighbourhoods of Euskal Herria, for the "from / to" search
of the journey planner. Run it from the repository root when you want fresh data:

    python3 tools/make_places.py

It asks the Overpass API of OpenStreetMap for every `place=*` node in the bounding box of Euskal Herria and keeps the
ones inside the territory outline (region.py). The result is written next to the code, so the app never needs a
third-party geocoder while it runs. Data (c) OpenStreetMap contributors, ODbL.

places.json is a list of [name, lat, lon, type, population, {lang: name}, [other names]].
"""
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import region  # noqa: E402

BBOX = "41.95,-3.45,43.6,-0.7"
TYPES = "city|town|village|suburb|quarter|neighbourhood|hamlet|borough"
QUERY = '[out:json][timeout:180];node["place"~"^(%s)$"](%s);out tags center qt;' % (TYPES, BBOX)
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
LANGS = ("eu", "es", "fr", "en")


def fetch():
    last = None
    for url in ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": QUERY}).encode(),
                                         headers={"User-Agent": "mugitu-tools/1.0 (https://github.com/josuloo99/mugitu)"})
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.loads(r.read())["elements"]
        except Exception as e:  # try the next mirror
            last = e
            print("  %s failed: %s" % (url, e), file=sys.stderr)
    raise SystemExit("Overpass is not reachable: %s" % last)


def main():
    print("asking Overpass for place nodes ...")
    seen, out = set(), []
    for e in fetch():
        tags = e.get("tags") or {}
        name = (tags.get("name") or "").strip()
        lat, lon = e.get("lat"), e.get("lon")
        if not name or lat is None or not region.contains(lat, lon):
            continue
        names = {l: tags["name:" + l].strip() for l in LANGS if tags.get("name:" + l) and tags["name:" + l].strip() != name}
        others = []
        for key in ("alt_name", "official_name", "old_name", "name:br"):
            for part in (tags.get(key) or "").split(";"):
                part = part.strip()
                if part and part != name and part not in names.values() and part not in others:
                    others.append(part)
        try:
            pop = int(tags.get("population", "0").replace(".", "").replace(",", "").split()[0])
        except (ValueError, IndexError):
            pop = 0
        key = (name, round(lat, 3), round(lon, 3))
        if key in seen:
            continue
        seen.add(key)
        out.append([name, round(lat, 5), round(lon, 5), tags["place"], pop, names, others[:4]])
    out.sort(key=lambda p: (-p[4], p[0]))
    path = os.path.join(ROOT, "places.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    kinds = {}
    for p in out:
        kinds[p[3]] = kinds.get(p[3], 0) + 1
    print("wrote %d places to %s (%d KB)  %s" % (len(out), path, os.path.getsize(path) // 1024, kinds))


if __name__ == "__main__":
    main()
