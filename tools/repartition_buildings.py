#!/usr/bin/env python3
import gzip
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BUILD_DIR = DATA / "buildings"
DISTRICT_FILE = DATA / "jinju_districts.geojson"
MANIFEST_FILE = DATA / "manifest.json"
ADDITIONS_FILE = ROOT / "tools" / "building_additions.geojson"
REPORT_FILE = DATA / "building_repartition_report.json"


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_gzip_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_gzip_json(path, obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))


district_fc = read_json(DISTRICT_FILE)
districts = []
for f in district_fc["features"]:
    p = f.get("properties", {})
    districts.append({
        "code": str(p["district_id"]),
        "name": p["district_name"],
        "geom": shape(f["geometry"]),
    })

geoms = [d["geom"] for d in districts]
tree = STRtree(geoms)


def choose_district(geom):
    # First use an interior point so ordinary buildings are assigned quickly.
    rp = geom.representative_point()
    idxs = list(tree.query(rp, predicate="within"))
    if len(idxs) == 1:
        return int(idxs[0]), "representative_point"

    # Buildings touching more than one boundary are assigned to the district
    # containing the largest actual footprint area.
    idxs = list(tree.query(geom, predicate="intersects"))
    if idxs:
        best_idx = None
        best_area = -1.0
        for i in idxs:
            area = geom.intersection(geoms[int(i)]).area
            if area > best_area:
                best_area = area
                best_idx = int(i)
        return best_idx, "max_intersection"

    # Very small gaps in administrative boundary geometry are resolved by
    # the nearest district. This keeps legally Jinju-coded buildings from
    # disappearing due to sub-meter boundary gaps.
    i = int(tree.nearest(rp))
    return i, "nearest"


# Read every currently published building exactly once.
features = []
seen = set()
old_count = 0
for path in sorted(BUILD_DIR.glob("*.geojson.gz")):
    fc = read_gzip_json(path)
    for feat in fc.get("features", []):
        old_count += 1
        uid = str(feat.get("properties", {}).get("building_uid") or "")
        key = uid if uid else json.dumps(feat.get("geometry"), sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        features.append(feat)

# Four valid source features were omitted by the former exporter. Add them.
added_count = 0
if ADDITIONS_FILE.exists():
    additions = read_json(ADDITIONS_FILE)
    for feat in additions.get("features", []):
        uid = str(feat.get("properties", {}).get("building_uid") or "")
        key = uid if uid else json.dumps(feat.get("geometry"), sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        features.append(feat)
        added_count += 1

buckets = defaultdict(list)
moved = 0
method_counts = defaultdict(int)
for feat in features:
    geom = shape(feat["geometry"])
    idx, method = choose_district(geom)
    method_counts[method] += 1
    d = districts[idx]
    props = feat.setdefault("properties", {})
    old_district = str(props.get("district_id") or "")
    if old_district != d["code"]:
        moved += 1
    props["district_id"] = d["code"]
    props["district_name"] = d["name"]
    buckets[d["code"]].append(feat)

manifest = read_json(MANIFEST_FILE)
per_district = {}
for d in districts:
    code = d["code"]
    out = {"type": "FeatureCollection", "features": buckets[code]}
    path = BUILD_DIR / f"{code}.geojson.gz"
    write_gzip_json(path, out)
    count = len(buckets[code])
    per_district[code] = {"name": d["name"], "count": count}
    if code in manifest.get("buildings", {}):
        manifest["buildings"][code]["count"] = count
        manifest["buildings"][code]["bytes"] = path.stat().st_size
        manifest["buildings"][code]["file"] = f"data/buildings/{code}.geojson.gz"

manifest["building_count"] = len(features)
notes = manifest.setdefault("notes", {})
notes["building_assignment"] = (
    "2026-09-15 재처리: 건물 실제 도형과 진주시 30개 행정동 경계를 공간교차. "
    "복수 경계 교차 시 최대 중첩면적, 미세 경계 공백은 최단거리로 보정."
)
notes["building_repartition_moved"] = moved
notes["building_repartition_added"] = added_count
with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

# Verification targets reported by the project owner.
central_high = 0
chojang_names = defaultdict(int)
watch_names = {
    "진주초전 푸르지오 2단지",
    "청구타운",
    "초전흥한황토방아파트",
    "초전 대림아파트",
    "현대아파트",
}
for feat in buckets.get("38030780", []):
    if feat.get("properties", {}).get("building_name") == "진주중앙고등학교":
        central_high += 1
for feat in buckets.get("38030660", []):
    name = feat.get("properties", {}).get("building_name")
    if name in watch_names:
        chojang_names[name] += 1

report = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "old_feature_count": old_count,
    "deduplicated_plus_additions": len(features),
    "moved_to_correct_district": moved,
    "added_from_source": added_count,
    "assignment_methods": dict(method_counts),
    "per_district": per_district,
    "verification": {
        "hadae_jinju_central_high_school_buildings": central_high,
        "chojang_apartment_buildings": dict(sorted(chojang_names.items())),
    },
}
with open(REPORT_FILE, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(json.dumps(report, ensure_ascii=False, indent=2))
