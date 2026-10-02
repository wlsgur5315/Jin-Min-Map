#!/usr/bin/env python3
import gzip, json, math
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
MANIFEST=DATA/"manifest.json"
OUT=DATA/"pnu_mismatch_remaining.json"

def load_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def pnu(p):
    s=str((p or {}).get("pnu") or (p or {}).get("PNU") or "")
    d="".join(ch for ch in s if ch.isdigit())
    return d if len(d)==19 else ""
def parcel_index(fc):
    geoms=[];props=[]
    for f in fc.get("features",[]):
        try:g=shape(f["geometry"])
        except:continue
        if g.is_empty:continue
        geoms.append(g);props.append(f.get("properties") or {})
    return geoms,props,STRtree(geoms) if geoms else None
def best_parcel(g,geoms,props,tree):
    if not tree:return None,None,0.0
    ba=0.0;bp=None;bg=None
    for item in tree.query(g):
        try:i=int(item)
        except:i=geoms.index(item)
        try:a=g.intersection(geoms[i]).area
        except:a=0.0
        if a>ba:ba=a;bp=props[i];bg=geoms[i]
    return bp,bg,ba/max(g.area,1e-15)

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
rows=[]
for did,bm in manifest.get("buildings",{}).items():
    pm=manifest.get("parcels",{}).get(did)
    if not pm:continue
    bfc=load_gz(ROOT/bm["file"]); pfc=load_gz(ROOT/pm["file"])
    pgs,pps,ptree=parcel_index(pfc)
    for idx,f in enumerate(bfc.get("features",[])):
        p=f.get("properties") or {}
        try:g=shape(f["geometry"])
        except:continue
        bp,bg,overlap=best_parcel(g,pgs,pps,ptree)
        fp=pnu(p); pp=pnu(bp or {})
        if bool(p.get("register_matched")) and overlap>=0.55 and fp and pp and fp!=pp:
            rp=g.representative_point()
            rows.append({
                "district_id":did,"district_name":bm.get("name"),"index":idx,
                "centroid":[round(rp.x,7),round(rp.y,7)],
                "feature_pnu":fp,"parcel_pnu":pp,"overlap_ratio":round(overlap,4),
                "building_name":p.get("building_name"),"building_dong":p.get("building_dong"),
                "register_name":p.get("register_name"),"register_dong":p.get("register_dong"),
                "height":p.get("render_height"),"floors":p.get("floors_above"),
                "building_uid":p.get("building_uid"),
                "source_pnu_before_spatial_fix":p.get("source_pnu_before_spatial_fix"),
                "pnu_spatial_corrected":p.get("pnu_spatial_corrected"),
                "data_source":p.get("data_source"),
                "height_source":p.get("height_source"),
                "match_basis":p.get("register_match_basis")
            })
OUT.write_text(json.dumps({"count":len(rows),"features":rows},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"count":len(rows),"features":rows},ensure_ascii=False,indent=2))
