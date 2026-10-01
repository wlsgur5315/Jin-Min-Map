#!/usr/bin/env python3
import gzip, json, math
from pathlib import Path
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"data/buildings/38030720.geojson.gz"
OUT=ROOT/"data/chilam_campus_candidates.json"
# 칠암캠퍼스 중심부를 넉넉히 포함
BBOX=(128.0905,35.1780,128.0970,35.1832)

def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat)

with gzip.open(SRC,"rt",encoding="utf-8") as f:
    fc=json.load(f)

rows=[]
for i,feat in enumerate(fc.get("features",[])):
    try:
        g=shape(feat["geometry"])
        c=g.representative_point()
    except Exception:
        continue
    if not (BBOX[0] <= c.x <= BBOX[2] and BBOX[1] <= c.y <= BBOX[3]):
        continue
    p=feat.get("properties") or {}
    rows.append({
        "index":i,
        "centroid":[round(c.x,7),round(c.y,7)],
        "geom_area_m2":round(metric_area(g),1),
        "building_uid":p.get("building_uid"),
        "data_source":p.get("data_source"),
        "pnu":p.get("pnu"),
        "jibun":p.get("jibun"),
        "building_name":p.get("building_name"),
        "building_dong":p.get("building_dong"),
        "register_name":p.get("register_name"),
        "register_dong":p.get("register_dong"),
        "render_height":p.get("render_height"),
        "floors_above":p.get("floors_above"),
        "building_area":p.get("building_area"),
        "approval_date":p.get("approval_date"),
        "height_source":p.get("height_source"),
        "register_match_basis":p.get("register_match_basis"),
        "osm_id":p.get("osm_id"),
        "overture_id":p.get("overture_id"),
    })

rows.sort(key=lambda x:(-(x.get("render_height") or 0),-(x.get("geom_area_m2") or 0)))
OUT.write_text(json.dumps({"bbox":BBOX,"count":len(rows),"features":rows},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"count":len(rows),"output":str(OUT)},ensure_ascii=False))
