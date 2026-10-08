#!/usr/bin/env python3
import gzip,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/"data/same_pnu_multidong_duplicate_plan.json"
MANIFEST=ROOT/"data/manifest.json"
REPORT=ROOT/"data/same_pnu_multidong_duplicate_cleanup_report.json"

def load_gz(path):
  with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def save_gz(path,obj):
  raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode("utf-8")
  with gzip.open(path,"wb",compresslevel=9) as f:f.write(raw)
  return path.stat().st_size

plan=json.loads(PLAN.read_text(encoding="utf-8"))
manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
by={}
for g in plan["groups"]:
  by.setdefault(g["district_id"],set()).update(int(x) for x in g["drops"])

report={"removed":0,"districts":{},"groups":plan["groups"]}
for did,drops in by.items():
  meta=manifest["buildings"][did]
  path=ROOT/meta["file"]
  fc=load_gz(path);fs=fc.get("features",[])
  valid={i for i in drops if 0<=i<len(fs)}
  fc["features"]=[f for i,f in enumerate(fs) if i not in valid]
  meta["count"]=len(fc["features"]);meta["bytes"]=save_gz(path,fc);meta["static_version"]="2026-10-08-08"
  report["districts"][did]=len(valid);report["removed"]+=len(valid)

manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
manifest.setdefault("notes",{})["same_pnu_multidong_cleanup"]="2026-10-08: 같은 PNU에서 서로 다른 동명이지만 footprint 80%+, 면적비 90%+, IoU 65%+, 높이/층수 일치인 거의 동일 형상 그룹은 대표 1개만 유지."
MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
