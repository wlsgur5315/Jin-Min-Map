#!/usr/bin/env python3
import gzip,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"data/buildings/38030770.geojson.gz"
OUT=ROOT/"data/tobis_current_records.json"
TARGET="4817011900100330015"
with gzip.open(P,"rt",encoding="utf-8") as f: fc=json.load(f)
rows=[]
for i,feat in enumerate(fc.get("features",[])):
    p=feat.get("properties") or {}
    d=re.sub(r"\D","",str(p.get("pnu") or p.get("PNU") or ""))
    name=str(p.get("building_name") or p.get("register_name") or "")
    if d==TARGET or "토비스유압" in name:
        rows.append({
          "index":i,
          "uid":p.get("building_uid"),
          "pnu":d,
          "name":p.get("building_name") or p.get("register_name"),
          "dong":p.get("building_dong") or p.get("register_dong"),
          "height":p.get("render_height") or p.get("height_m"),
          "floors":p.get("floors_above"),
          "source":p.get("data_source") or p.get("source"),
          "verified":p.get("verified_override"),
          "geometry_type":(feat.get("geometry") or {}).get("type")
        })
OUT.write_text(json.dumps({"count":len(rows),"records":rows},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"count":len(rows),"records":rows},ensure_ascii=False,indent=2))
