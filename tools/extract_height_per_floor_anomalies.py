#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
src=ROOT/"data/building_integrity_audit.json"
out=ROOT/"data/height_per_floor_over_8m.json"
d=json.loads(src.read_text(encoding="utf-8"))
rows=[]
for rec in d.get("top_suspects",[]):
    if "height_per_floor_over_8m" in rec.get("reasons",[]):
        rows.append(rec)
if len(rows)<9:
    seen={(r.get("district_id"),r.get("index")) for r in rows}
    for did,dd in d.get("districts",{}).items():
        for rec in dd.get("top_suspects",[]):
            k=(rec.get("district_id"),rec.get("index"))
            if k in seen: continue
            if "height_per_floor_over_8m" in rec.get("reasons",[]):
                rows.append(rec);seen.add(k)
out.write_text(json.dumps({"count":len(rows),"features":rows},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"count":len(rows)},ensure_ascii=False))
