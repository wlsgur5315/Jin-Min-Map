#!/usr/bin/env python3
import gzip,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"data/buildings/38030770.geojson.gz"
MANIFEST=ROOT/"data/manifest.json"
REPORT=ROOT/"data/tobis_bad_footprint_cleanup_report.json"
BAD={
"2015120088201873547100000000",
"2015120091181873549400000000",
"2015120089601873554400000000",
"2015120084301873581200000000",
}
with gzip.open(PATH,"rt",encoding="utf-8") as f:fc=json.load(f)
before=len(fc.get("features",[]));removed=[]
kept=[]
for f in fc.get("features",[]):
    p=f.get("properties") or {}
    uid=str(p.get("building_uid") or "")
    if uid in BAD:
        removed.append({
          "uid":uid,
          "name":p.get("building_name") or p.get("register_name"),
          "dong":p.get("building_dong") or p.get("register_dong"),
          "pnu":p.get("pnu"),
          "height":p.get("render_height") or p.get("height_m"),
          "floors":p.get("floors_above")
        })
    else:kept.append(f)
fc["features"]=kept
raw=json.dumps(fc,ensure_ascii=False,separators=(",",":")).encode("utf-8")
with gzip.open(PATH,"wb",compresslevel=9) as f:f.write(raw)
manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
m=manifest["buildings"]["38030770"]
m["count"]=len(kept);m["bytes"]=PATH.stat().st_size;m["static_version"]="2026-10-08-10"
manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
manifest.setdefault("notes",{})["tobis_bad_footprint_cleanup"]="2026-10-08: 상대동 토비스유압 부지 중앙에 중첩되고 도로 필지를 침범하던 2015년 대형 오류 footprint 4개 제거. 실제 소형 제1~4동 건물은 유지."
MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
REPORT.write_text(json.dumps({"before":before,"after":len(kept),"removed_count":len(removed),"removed":removed},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(json.loads(REPORT.read_text(encoding="utf-8")),ensure_ascii=False,indent=2))
