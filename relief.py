#!/usr/bin/env python3
"""Builds the relief file of one region: elevation tiles in one PMTiles file.

The app draws the hillshade from it and reads altitudes in it (elevation profile, line of sight).
Format: docs/formats/relief-file.md in the OSTIE repository. Requires `pip install pmtiles pillow numpy`.
Data: Terrain Tiles on AWS Open Data (terrarium PNG), see ATTRIBUTION below.

Usage: relief.py REGION_ID OUT.pmtiles
"""
import io
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

SOURCE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
ATTRIBUTION = "Terrain Tiles: SRTM, EU-DEM (Copernicus) and others, github.com/tilezen/joerd/blob/master/docs/attribution.md"
# Below zoom 7 a region is a few pixels wide: no relief worth drawing.
MIN_ZOOM = 7
# Zoom 12 is about 25 m per pixel at our latitudes, the real fineness of the source.
DEFAULT_MAX_ZOOM = 12
# Altitudes are rounded to a quarter of a metre: the source is no finer, and the file is half the size.
ROUND_BITS = 6  # a terrarium unit is 1/256 m; 2**6 units = 0.25 m
SEA_LEVEL = 32768 << 8  # 0 m in terrarium units


def rounded(png):
    rgb = numpy.array(Image.open(io.BytesIO(png)).convert("RGB")).astype(numpy.uint32)
    units = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
    units = ((units + (1 << (ROUND_BITS - 1))) >> ROUND_BITS) << ROUND_BITS
    # The source also has the sea bed: flattened, or the sea would be shaded like hills.
    # shortcut: land below sea level (polders) becomes 0 m too; keep it if a region needs it.
    units = numpy.maximum(units, SEA_LEVEL)
    out = numpy.stack([(units >> 16) & 255, (units >> 8) & 255, units & 255], axis=-1).astype(numpy.uint8)
    buffer = io.BytesIO()
    Image.fromarray(out).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def tile_of(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def fetch(zxy):
    url = SOURCE.format(z=zxy[0], x=zxy[1], y=zxy[2])
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return zxy, rounded(response.read())
        except OSError:
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"Could not download {url}")


def build(region, out):
    lons = [p[0] for p in region["polygon"]]
    lats = [p[1] for p in region["polygon"]]
    west, south, east, north = min(lons), min(lats), max(lons), max(lats)
    max_zoom = region.get("relief_maxzoom", DEFAULT_MAX_ZOOM)

    # shortcut: every tile of the bounding box, also outside a slanted polygon; clip if a region gets heavy.
    wanted = []
    for z in range(MIN_ZOOM, max_zoom + 1):
        x0, y0 = tile_of(west, north, z)
        x1, y1 = tile_of(east, south, z)
        wanted += [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    with ThreadPoolExecutor(16) as pool:
        tiles = dict(pool.map(fetch, wanted))

    with open(out, "wb") as f:
        writer = Writer(f)
        for zxy in sorted(tiles, key=lambda t: zxy_to_tileid(*t)):
            writer.write_tile(zxy_to_tileid(*zxy), tiles[zxy])
        writer.finalize(
            {
                "tile_type": TileType.PNG,
                "tile_compression": Compression.NONE,
                "min_lon_e7": int(west * 1e7),
                "min_lat_e7": int(south * 1e7),
                "max_lon_e7": int(east * 1e7),
                "max_lat_e7": int(north * 1e7),
                "center_zoom": MIN_ZOOM + 2,
                "center_lon_e7": int((west + east) / 2 * 1e7),
                "center_lat_e7": int((south + north) / 2 * 1e7),
            },
            {"name": region["name"], "format": "png", "encoding": "terrarium", "attribution": ATTRIBUTION},
        )
    print(f"{region['id']}: {len(tiles)} relief tiles, zoom {MIN_ZOOM} to {max_zoom}, {os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    region_id, out = sys.argv[1:3]
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "regions.json"), encoding="utf-8") as f:
        build(next(r for r in json.load(f)["regions"] if r["id"] == region_id), out)
