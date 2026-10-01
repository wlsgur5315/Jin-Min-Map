#!/usr/bin/env python3
import gzip, json, math
from pathlib import Path
from collections import defaultdict
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
MANIFEST=DATA/"manifest.json"
OUT=DATA/"building_integrity_audit.json"

def load_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)

def pnu(p):
    s=str((p or {}).get("pnu") or (p or {}).get("PNU") or "")
    d="".join(ch for ch in s if ch.isdigit())
    return d if len(d)==19 else ""

def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0

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
    ratio=ba/max(g.area,1e-15)
    return bp,bg,ratio

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
summary=defaultdict(int)
districts={}
top=[]

for did,bm in manifest.get("buildings",{}).items():
    pm=manifest.get("parcels",{}).get(did)
    if not pm:continue
    bfc=load_gz(ROOT/bm["file"])
    pfc=load_gz(ROOT/pm["file"])
    pgs,pps,ptree=parcel_index(pfc)
    dsum=defaultdict(int)
    suspects=[]
    for idx,f in enumerate(bfc.get("features",[])):
        p=f.get("properties") or {}
        try:g=shape(f["geometry"])
        except:continue
        if g.is_empty:continue
        area=metric_area(g)
        bp,bg,overlap=best_parcel(g,pgs,pps,ptree)
        fpnu=pnu(p);ppnu=pnu(bp or {})
        h=float(p.get("render_height") or p.get("height_m") or 0)
        fl=float(p.get("floors_above") or 0)
        rarea=float(p.get("register_building_area_m2") or 0)
        ar=(min(area,rarea)/max(area,rarea)) if area>0 and rarea>0 else None
        score=p.get("register_match_score")
        margin=p.get("register_match_margin")
        matched=bool(p.get("register_matched"))
        reasons=[];sev=0

        if h>200:
            reasons.append("height_over_200m");sev+=5
        if fl>0 and h>0 and h/fl>8:
            reasons.append("height_per_floor_over_8m");sev+=5
        if matched and overlap>=0.55 and fpnu and ppnu and fpnu!=ppnu:
            reasons.append("feature_pnu_differs_from_actual_parcel");sev+=8
        if matched and ar is not None and ar<0.35:
            reasons.append("register_area_vs_footprint_low");sev+=6
        if matched and isinstance(margin,(int,float)) and margin<3:
            reasons.append("low_register_match_margin");sev+=4
        if matched and isinstance(score,(int,float)) and score<8:
            reasons.append("low_register_match_score");sev+=4
        if matched and float(p.get("building_area") or 0)<=0 and area>150:
            reasons.append("zero_source_area_but_large_polygon");sev+=5

        if reasons:
            for r in reasons:
                summary[r]+=1;dsum[r]+=1
            dsum["suspect_features"]+=1;summary["suspect_features"]+=1
            rec={
                "district_id":did,
                "district_name":bm.get("name"),
                "index":idx,
                "severity":sev,
                "reasons":reasons,
                "centroid":[round(g.representative_point().x,7),round(g.representative_point().y,7)],
                "feature_pnu":fpnu,
                "parcel_pnu":ppnu,
                "parcel_overlap_ratio":round(overlap,4),
                "building_name":p.get("building_name"),
                "building_dong":p.get("building_dong"),
                "register_name":p.get("register_name"),
                "register_dong":p.get("register_dong"),
                "render_height":h,
                "floors_above":fl,
                "footprint_area_m2":round(area,1),
                "register_building_area_m2":rarea,
                "area_ratio":round(ar,4) if ar is not None else None,
                "match_score":score,
                "match_margin":margin,
                "height_source":p.get("height_source"),
                "building_uid":p.get("building_uid"),
                "data_source":p.get("data_source")
            }
            suspects.append(rec)
    suspects.sort(key=lambda x:(-x["severity"], x["index"]))
    districts[did]={
        "name":bm.get("name"),
        "building_count":len(bfc.get("features",[])),
        "summary":dict(dsum),
        "top_suspects":suspects[:50]
    }
    top.extend(suspects[:50])

top.sort(key=lambda x:-x["severity"])
report={
    "generated_for_static_versions":sorted(set(str(v.get("static_version")) for v in manifest.get("buildings",{}).values())),
    "building_count":manifest.get("building_count"),
    "summary":dict(summary),
    "districts":districts,
    "top_suspects":top[:300]
}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"output":str(OUT),"summary":dict(summary)},ensure_ascii=False,indent=2))
