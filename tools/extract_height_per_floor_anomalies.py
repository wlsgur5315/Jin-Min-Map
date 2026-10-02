#!/usr/bin/env python3
import gzip, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"
MANIFEST=ROOT/"data/manifest.json"
OUT=ROOT/"data/height_per_floor_over_8m.json"

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
name_by_id={k:v.get("name") for k,v in manifest.get("buildings",{}).items()}
rows=[]
for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        fc=json.load(fh)
    for idx,feat in enumerate(fc.get("features",[])):
        p=feat.get("properties") or {}
        try:h=float(p.get("render_height") or p.get("height_m") or 0)
        except:h=0
        try:fl=float(p.get("floors_above") or 0)
        except:fl=0
        if fl>0 and h>0 and h/fl>8:
            try:
                from shapely.geometry import shape
                g=shape(feat["geometry"]); rp=g.representative_point()
                centroid=[round(rp.x,7),round(rp.y,7)]
            except Exception:
                centroid=None
            rows.append({
                "district_id":did,
                "district_name":name_by_id.get(did),
                "index":idx,
                "building_name":p.get("building_name"),
                "building_dong":p.get("building_dong"),
                "register_name":p.get("register_name"),
                "register_dong":p.get("register_dong"),
                "pnu":p.get("pnu"),
                "jibun":p.get("jibun"),
                "render_height":h,
                "floors_above":fl,
                "height_per_floor":round(h/fl,3),
                "height_source":p.get("height_source"),
                "register_match_basis":p.get("register_match_basis"),
                "building_uid":p.get("building_uid"),
                "centroid":centroid
            })
rows.sort(key=lambda x:-x["height_per_floor"])
OUT.write_text(json.dumps({"count":len(rows),"features":rows},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"count":len(rows),"features":rows},ensure_ascii=False,indent=2))
