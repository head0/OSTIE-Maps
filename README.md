# OSTIE maps

Ready-made offline maps for [OSTIE](https://github.com/head0/OSTIE), the open source tactical map app. The app offers them at first launch and downloads the one you choose; once on the phone, a map never expires and needs no network.

## What is published

Every month (and on demand), the *Publish maps* workflow builds:

- one **region map** per entry of [`regions.json`](regions.json), with full detail (zoom 15);
- one **names file** per region (`<id>.names`): its places, streets and house numbers, for the app's offline search ("marseille", "31 route de Peppange à Bettembourg"). Format: `docs/formats/names-file.md` in the OSTIE repository;
- one **relief file** per region (`<id>.relief.pmtiles`): its elevation, about 25 m per pixel, for the hillshade, the altitude, the elevation profile and the line of sight. Format: `docs/formats/relief-file.md` in the OSTIE repository;
- a **light world map** (zoom 5, about 15 MB);
- **`catalogue.json`**, the list the app reads: name, file, download address, size, SHA-256 checksum, bounding box. Format: `docs/formats/map-catalogue.md` in the OSTIE repository.

They are attached to a GitHub release. The latest catalogue is always at:

```
https://github.com/head0/ostie-maps/releases/latest/download/catalogue.json
```

Only the two most recent releases are kept.

## Regions

| Id | Area |
| --- | --- |
| `luxembourg` | Luxembourg and its immediate surroundings |
| `metz-luxembourg` | A band from Metz to Luxembourg City |
| `provence` | Gap, Arles, Marseille, Toulon |
| `normandie` | Normandy, Cotentin included |

To add a region, add an entry to `regions.json`: an `id` (lowercase, dashes), a `name`, a `maxzoom` (15 = full detail) and a `polygon` of `[longitude, latitude]` points, closed (last point = first point), and `osm`, the [Geofabrik](https://download.geofabrik.de) extracts that cover it (their path without `-latest.osm.pbf`; names outside these extracts are not searchable). An optional `relief_maxzoom` sets the finest zoom of the relief file (12 by default, about 25 m per pixel; each step more is four times the size). Then run *Actions* → *Publish maps* → *Run workflow*.

## Build locally

Requires [`pmtiles`](https://github.com/protomaps/go-pmtiles/releases), `jq`, `curl`, and Python 3 with `pip install osmium pmtiles pillow numpy`:

```bash
./build.sh out https://example.org/maps        # latest Protomaps build
./build.sh out https://example.org/maps 20261101
```

## Licences

- **Map data:** © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, available under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/). Tiles produced with [Protomaps](https://protomaps.com); names read from the [Geofabrik](https://download.geofabrik.de) extracts. Anyone showing these maps must credit OpenStreetMap; the OSTIE app does so on the map.
- **Elevation:** [Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) on AWS Open Data (SRTM, EU-DEM and others); credits in their [attribution list](https://github.com/tilezen/joerd/blob/master/docs/attribution.md).
- **Scripts and workflow:** GPL-3.0, like OSTIE. See [LICENSE](LICENSE).
