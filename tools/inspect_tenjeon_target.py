#!/usr/bin/env python3
import gzip, json
from pathlib import Path
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"data/buildings/38030720.geojson.gz"
OUT=ROOT/"data/tenjeon_target_report.json"

with gzip.open(SRC,"rt",encoding="utf-8") as f:
    fc=json.load(f)

rows=[]
for i,feat in enumerate(fc.get("features",[])):
    p=feat.get("properties") or {}
    txt=" ".join(str(p.get(k) or "") for k in [
        "building_name","name","register_name","register_dong",
        "legal_name","jibun","use_name","height_source"
    ])
    if ("진주남중학교" in txt or "남중학교" in txt or "종합교육관" in txt
        or "칠암동150-1" in txt.replace(" ","") or str(p.get("pnu") or "")=="4817010400001500001"):
        try:
            g=shape(feat["geometry"])
            c=g.representative_point()
            centroid=[round(c.x,7),round(c.y,7)]
            area_deg=g.area
        except Exception:
            centroid=None;area_deg=None
        rows.append({
            "index":i,
            "centroid":centroid,
            "area_deg2":area_deg,
            "properties":p
        })

OUT.write_text(json.dumps({"count":len(rows),"matches":rows},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"count":len(rows),"output":str(OUT)},ensure_ascii=False))
