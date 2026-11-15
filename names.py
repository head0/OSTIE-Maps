#!/usr/bin/env python3
"""Builds the names file of one region: places, streets and house numbers, for the offline search.

Format: docs/formats/names-file.md in the OSTIE repository. Requires `pip install osmium`.
Data: OpenStreetMap extracts (.osm.pbf, e.g. from download.geofabrik.de), © OpenStreetMap contributors, ODbL.

Usage: names.py REGION_ID OUT.db BUILD FILE.osm.pbf [FILE.osm.pbf ...]
"""
import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

import osmium

# Same table as the app (ostie.core.search.Names): both sides must cut a text into the same words.
ACCENTS = str.maketrans({
    **{c: "a" for c in "àáâãäå"}, **{c: "e" for c in "èéêë"}, **{c: "i" for c in "ìíîï"},
    **{c: "o" for c in "òóôõö"}, **{c: "u" for c in "ùúûü"}, **{c: "y" for c in "ýÿ"},
    "ç": "c", "ñ": "n", "ß": "ss", "œ": "oe", "æ": "ae",
})
PLACE_KINDS = {"city": 0, "town": 1, "village": 2}
SMALL_PLACES = {"hamlet", "suburb", "quarter", "neighbourhood", "locality", "isolated_dwelling"}
SMALL, PEAK, STREET = 3, 4, 5
NOT_STREETS = {"platform", "proposed", "construction", "bus_stop", "rest_area", "services", "elevator"}
OTHER_NAMES = ("name:fr", "name:de", "name:en", "name:lb")
# A town draws streets from further away than a village: distances are divided by this.
PULL = {0: 3.0, 1: 1.5, 2: 1.0}
MAX_TOWN_KM = 15.0
MAX_STREET_KM = 3.0


def words(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower().translate(ACCENTS)).split()


def km(a, b):
    """Good enough under 50 km: flat earth around the first point."""
    dx = (b[1] - a[1]) * 111.32 * math.cos(math.radians(a[0]))
    return math.hypot(dx, (b[0] - a[0]) * 110.57)


def inside(lat, lon, polygon):
    hit = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def read(files, polygon):
    places, ways, houses = [], [], []
    seen = set()
    for path in files:
        reader = osmium.FileProcessor(path).with_locations().with_filter(
            osmium.filter.KeyFilter("place", "highway", "addr:housenumber", "natural"))
        for o in reader:
            if o.is_node():
                if not o.location.valid():
                    continue
                at = (o.lat, o.lon)
            elif o.is_way():
                pts = [(n.lat, n.lon) for n in o.nodes if n.location.valid()]
                if not pts:
                    continue
                # A street is placed at its middle point; a building at the middle of its outline.
                at = pts[len(pts) // 2] if "highway" in o.tags else (
                    sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            else:
                # shortcut: addresses carried by relations (large buildings) are skipped, add them if they are missed.
                continue
            key = ("n" if o.is_node() else "w", o.id)
            if key in seen or not inside(at[0], at[1], polygon):
                continue
            seen.add(key)  # the same object is in two overlapping extracts
            tags = o.tags
            name = tags.get("name")
            if "addr:housenumber" in tags and "addr:street" in tags:
                houses.append((tags["addr:street"], tags["addr:housenumber"], at))
            if not name:
                continue
            if o.is_node():
                place = tags.get("place")
                kind = PLACE_KINDS.get(place, SMALL if place in SMALL_PLACES else None)
                if kind is None and tags.get("natural") == "peak":
                    kind = PEAK
                if kind is not None:
                    other = " ".join(tags[k] for k in OTHER_NAMES if k in tags)
                    places.append((kind, name, other, at))
            elif "highway" in tags and tags["highway"] not in NOT_STREETS:
                ways.append((name, at))
    return places, ways, houses


def build(region, out, build_date, files):
    polygon = region["polygon"]
    places, ways, houses = read(files, polygon)

    # Towns on a 0.1° grid, to find the one a street belongs to.
    # shortcut: nearest town centre, not the commune's boundary; use admin boundaries if streets land in the wrong town.
    grid = defaultdict(list)
    for kind, name, _, at in places:
        if kind in PULL:
            grid[(int(at[0] * 10), int(at[1] * 10))].append((kind, name, at))

    def town(at):
        best, best_d = "", MAX_TOWN_KM
        cy, cx = int(at[0] * 10), int(at[1] * 10)
        for y in range(cy - 2, cy + 3):
            for x in range(cx - 3, cx + 4):
                for kind, name, p in grid.get((y, x), ()):
                    d = km(at, p) / PULL[kind]
                    if d < best_d:
                        best, best_d = name, d
        return best

    # One street per (name, town): its pieces in OpenStreetMap are many short ways.
    pieces = defaultdict(list)
    names = {}
    for name, at in ways:
        key = (" ".join(words(name)), town(at))
        if key[0]:
            pieces[key].append(at)
            names.setdefault(key, Counter())[name] += 1

    os.path.exists(out) and os.remove(out)
    db = sqlite3.connect(out)
    db.executescript("""
        PRAGMA page_size = 4096;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
        CREATE TABLE place(id INTEGER PRIMARY KEY, kind INTEGER, name TEXT, town TEXT, lat INTEGER, lon INTEGER);
        CREATE VIRTUAL TABLE words USING fts4(content='', text, tokenize=simple, matchinfo=fts3);
        CREATE TABLE house(street INTEGER, number TEXT, lat INTEGER, lon INTEGER,
                           PRIMARY KEY(street, number)) WITHOUT ROWID;
    """)
    db.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("format", "ostie-names"), ("version", "1"), ("region", region["id"]), ("build", build_date),
        ("attribution", "© OpenStreetMap contributors, ODbL")])

    def micro(at):
        return round(at[0] * 1e6), round(at[1] * 1e6)

    next_id = 0

    def add(kind, name, in_town, at, text):
        nonlocal next_id
        next_id += 1
        db.execute("INSERT INTO place VALUES (?, ?, ?, ?, ?, ?)", (next_id, kind, name, in_town, *micro(at)))
        db.execute("INSERT INTO words(docid, text) VALUES (?, ?)", (next_id, " ".join(words(text))))
        return next_id

    for kind, name, other, at in sorted(places, key=lambda p: (p[0], p[1])):
        add(kind, name, "", at, f"{name} {other}")

    by_name = defaultdict(list)  # normalised street name -> [(id, position)]
    for key in sorted(pieces):
        pts = pieces[key]
        mean = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        at = min(pts, key=lambda p: km(mean, p))
        name = names[key].most_common(1)[0][0]
        by_name[key[0]].append((add(STREET, name, key[1], at, f"{name} {key[1]}"), at))

    count = 0
    for street, number, at in houses:
        near = min(by_name.get(" ".join(words(street)), ()), key=lambda s: km(at, s[1]), default=None)
        number = "".join(words(number))
        if near and number and km(at, near[1]) < MAX_STREET_KM:
            count += db.execute("INSERT OR IGNORE INTO house VALUES (?, ?, ?, ?)", (near[0], number, *micro(at))).rowcount
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"{region['id']}: {len(places)} places, {len(pieces)} streets, {count} house numbers "
          f"(of {len(houses)} in the data), {os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    region_id, out, build_date, *pbf = sys.argv[1:]
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "regions.json"), encoding="utf-8") as f:
        region = next(r for r in json.load(f)["regions"] if r["id"] == region_id)
    build(region, out, build_date, pbf)
