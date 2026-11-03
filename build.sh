#!/usr/bin/env bash
# Builds every map of regions.json, the light world map and catalogue.json into OUTPUT_DIR.
#
# Requires `pmtiles` (https://github.com/protomaps/go-pmtiles/releases), `jq` and `curl`.
# Data: OpenStreetMap via the Protomaps daily build, © OpenStreetMap contributors, ODbL.
#
# Usage: build.sh OUTPUT_DIR BASE_URL [YYYYMMDD]
#   BASE_URL = where the files will be downloadable, e.g. https://github.com/OWNER/REPO/releases/download/TAG
set -euo pipefail

OUT="$1"
BASE_URL="$2"
BUILD="${3:-}"
WORLD_MAXZOOM=5
mkdir -p "$OUT"

# Without a date, take the most recent daily build: today's may not be published yet.
if [ -z "$BUILD" ]; then
  for days_ago in 0 1 2 3 4 5 6 7; do
    candidate="$(date -u -d "-${days_ago} day" +%Y%m%d)"
    if curl -sfI "https://build.protomaps.com/${candidate}.pmtiles" > /dev/null; then
      BUILD="$candidate"
      break
    fi
  done
  [ -n "$BUILD" ] || { echo "No Protomaps build found in the last 8 days" >&2; exit 1; }
fi
SOURCE="https://build.protomaps.com/${BUILD}.pmtiles"
echo "Protomaps build: $BUILD"

# One catalogue entry for a built file: id, name, file, size, checksum, bounding box, max zoom.
entry() {
  local id="$1" name="$2" file="$3" maxzoom="$4" bbox="$5"
  jq -n --arg id "$id" --arg name "$name" --arg file "$file" --arg url "$BASE_URL/$file" \
    --argjson bytes "$(stat -c %s "$OUT/$file")" --arg sha256 "$(sha256sum "$OUT/$file" | cut -d' ' -f1)" \
    --argjson maxzoom "$maxzoom" --argjson bbox "$bbox" \
    '{id: $id, name: $name, file: $file, url: $url, bytes: $bytes, sha256: $sha256, bbox: $bbox, maxzoom: $maxzoom}'
}

: > "$OUT/regions.jsonl"
count=$(jq '.regions | length' regions.json)
for i in $(seq 0 $((count - 1))); do
  region=$(jq ".regions[$i]" regions.json)
  id=$(jq -r .id <<< "$region")
  name=$(jq -r .name <<< "$region")
  maxzoom=$(jq -r .maxzoom <<< "$region")
  jq '{type: "Polygon", coordinates: [.polygon]}' <<< "$region" > "$OUT/$id.geojson"
  bbox=$(jq -c '[(.polygon | map(.[0]) | min), (.polygon | map(.[1]) | min), (.polygon | map(.[0]) | max), (.polygon | map(.[1]) | max)]' <<< "$region")
  pmtiles extract "$SOURCE" "$OUT/$id.pmtiles" --region="$OUT/$id.geojson" --maxzoom="$maxzoom"
  rm "$OUT/$id.geojson"
  entry "$id" "$name" "$id.pmtiles" "$maxzoom" "$bbox" >> "$OUT/regions.jsonl"
done

pmtiles extract "$SOURCE" "$OUT/world.pmtiles" --bbox=-180,-85,180,85 --maxzoom="$WORLD_MAXZOOM"
world=$(entry world World world.pmtiles "$WORLD_MAXZOOM" '[-180,-85,180,85]')

jq -n --arg build "$BUILD" --slurpfile regions "$OUT/regions.jsonl" --argjson world "$world" \
  '{format: "ostie-map-catalogue", version: "1", build: $build,
    attribution: "© OpenStreetMap contributors, ODbL", regions: $regions, world: $world}' > "$OUT/catalogue.json"
rm "$OUT/regions.jsonl"
echo "$BUILD" > "$OUT/BUILD"
cat "$OUT/catalogue.json"
