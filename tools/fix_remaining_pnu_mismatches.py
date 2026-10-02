#!/usr/bin/env python3
import gzip, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings/38030110.geojson.gz"
MANIFEST=ROOT/"data/manifest.json"
TARGET_UIDS={
"0000306429481840910200000000",
"0000306440001840895700000000",
"0000306418391840904500000000",
}
OLD="4817025024111060006"
NEW="4817025024111060005"

with gzip.open(BUILD,"rt",encoding="utf-8") as f:
    fc=json.load(f)

changed=[]
for feat in fc.get("features",[]):
    p=feat.get("properties") or {}
    uid=str(p.get("building_uid") or "")
    if uid in TARGET_UIDS:
        prev=str(p.get("pnu") or "")
        p["source_pnu_before_manual_fix"]=prev
        p["pnu"]=NEW
        p["pnu_spatial_corrected"]=True
        p["pnu_spatial_fix_basis"]="실제 필지 100% 중첩 검증"
        changed.append({"uid":uid,"before":prev,"after":NEW})

raw=json.dumps(fc,ensure_ascii=False,separators=(",",":")).encode("utf-8")
BUILD.write_bytes(gzip.compress(raw,compresslevel=9,mtime=0))

m=json.loads(MANIFEST.read_text(encoding="utf-8"))
bm=m["buildings"]["38030110"]
bm["bytes"]=BUILD.stat().st_size
bm["static_version"]="2026-10-02-02"
m.setdefault("notes",{})["pnu_manual_fix"]="2026-10-02: 문산읍 잔여 PNU 불일치 3건을 실제 필지 100% 중첩 기준으로 보정."
MANIFEST.write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding="utf-8")

print(json.dumps({"changed_count":len(changed),"changed":changed},ensure_ascii=False,indent=2))
if len(changed)!=3:
    raise SystemExit(f"Expected 3 changes, got {len(changed)}")
