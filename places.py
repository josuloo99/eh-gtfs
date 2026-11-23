"""Towns, villages and neighbourhoods of Euskal Herria (places.json, made by tools/make_places.py).

Used by the journey planner to turn "Hendaia" or "Deusto" into a point, and a tapped point into "near Deusto".
Everything is in memory and offline. Only the Python standard library is used.
"""
import json
import logging
import math
import os
import re
import unicodedata

log = logging.getLogger("mugitu.places")

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "places.json")
# how much a kind of place weighs when several match (lower = more important)
KIND_RANK = {"city": 0, "town": 1, "borough": 2, "suburb": 2, "quarter": 2, "village": 2, "neighbourhood": 3, "hamlet": 3}
# a tapped point is described by the nearest of these, if it is close enough (metres)
NEAR_M = {"city": 6000, "town": 4000, "borough": 3000, "suburb": 2000, "quarter": 1500, "village": 2500,
          "neighbourhood": 1200, "hamlet": 1500}

_places = None        # [{id, name, names, lat, lon, kind, pop}]
_variants = None      # [(normalised variant, place id)]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _load():
    global _places, _variants
    if _places is not None:
        return
    places, variants = [], []
    try:
        with open(PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        log.warning("places.json not available (%s): place search is off", e)
        raw = []
    for i, (name, lat, lon, kind, pop, names, others) in enumerate(raw):
        places.append({"id": i, "name": name, "names": names, "lat": lat, "lon": lon, "kind": kind, "pop": pop})
        seen = set()
        for v in [name, *names.values(), *others]:
            n = norm(v)
            if n and n not in seen:
                seen.add(n)
                variants.append((n, i))
    _places, _variants = places, variants


def label(p, lang):
    """Name of a place in the interface language when OpenStreetMap has one; otherwise the local name."""
    return p["names"].get(lang) or p["name"]


def search(q, lang="eu", limit=6):
    """Places whose name (in any language) matches q: exact, then starting with q, then a word starting with q."""
    _load()
    qn = norm(q)
    if len(qn) < 2:
        return []
    best = {}
    for n, i in _variants:
        if n == qn:
            rank = 0
        elif n.startswith(qn):
            rank = 1
        elif (" " + qn) in (" " + n) and qn in n.split() or any(w.startswith(qn) for w in n.split()):
            rank = 2
        else:
            continue
        if i not in best or rank < best[i]:
            best[i] = rank
    out = sorted(best.items(), key=lambda kv: (kv[1], KIND_RANK.get(_places[kv[0]]["kind"], 4), -_places[kv[0]]["pop"],
                                               len(_places[kv[0]]["name"])))
    return [dict(_places[i], label=label(_places[i], lang), rank=r) for i, r in out[:limit]]


def nearest(lat, lon, lang="eu"):
    """The closest place that is near enough to describe the point (None when it is far from everything)."""
    _load()
    dlat = 0.06
    dlon = dlat / max(0.2, math.cos(math.radians(lat)))
    best = None
    for p in _places:
        if abs(p["lat"] - lat) > dlat or abs(p["lon"] - lon) > dlon:
            continue
        d = math.hypot((p["lat"] - lat) * 111320.0, (p["lon"] - lon) * 111320.0 * math.cos(math.radians(lat)))
        if d > NEAR_M.get(p["kind"], 1500):
            continue
        # a small place right next to the point is a better description than a city far away
        score = d + KIND_RANK.get(p["kind"], 4) * 150
        if best is None or score < best[0]:
            best = (score, d, p)
    if not best:
        return None
    return dict(best[2], label=label(best[2], lang), dist=int(best[1]))
