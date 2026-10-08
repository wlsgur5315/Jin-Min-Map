#!/usr/bin/env python3
import gzip,json,math,re
from collections import defaultdict
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"
OUT=ROOT/"data/building_geometry_height_audit.json"

def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)

def safe_geom(g):
    try:
        if g is None or g.is_empty:return None
        if not g.is_valid:g=g.buffer(0)
    except:return None
    if g is None or g.is_empty:return None
    return g if g.geom_type in ("Polygon","MultiPolygon") else None

def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0

def centroid(g):
    p=g.representative_point();return (p.x,p.y)

def dist_m(a,b):
    x=(b[0]-a[0])*111320*math.cos(math.radians((a[1]+b[1])/2))
    y=(b[1]-a[1])*110540
    return math.hypot(x,y)

def num(v):
    try:return float(v)
    except:return 0.0

def norm(s): return re.sub(r"\s+","",str(s or "")).strip()

summary={"duplicates":0,"height_outliers":0,"tiny_highrise":0,"missing_like":0}
examples={"duplicates":[],"height_outliers":[],"tiny_highrise":[],"missing_like":[]}
districts={}

for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    fc=load_gz(path)
    feats=fc.get("features",[])
    rows=[]; geoms=[]
    for i,f in enumerate(feats):
        g=safe_geom(shape(f.get("geometry")))
        if g is None:continue
        p=f.get("properties") or {}
        a=metric_area(g); c=centroid(g)
        h=num(p.get("render_height") or p.get("height_m"))
        fl=num(p.get("floors_above"))
        rows.append({"i":i,"g":g,"p":p,"area":a,"c":c,"h":h,"fl":fl})
        geoms.append(g)
    tree=STRtree(geoms) if geoms else None
    dc={"duplicates":0,"height_outliers":0,"tiny_highrise":0,"missing_like":0}

    # 1) 중복 geometry 후보: 중심 3m 이내 + 면적 유사 + 교차비율 매우 큼
    seen=set()
    for idx,r in enumerate(rows):
        if not tree:break
        for item in tree.query(r["g"]):
            try:j=int(item)
            except:j=geoms.index(item)
            if j<=idx:continue
            s=rows[j]
            if dist_m(r["c"],s["c"])>8:continue
            if r["area"]<=0 or s["area"]<=0:continue
            ar=min(r["area"],s["area"])/max(r["area"],s["area"])
            if ar<0.75:continue
            try:ov=r["g"].intersection(s["g"]).area/min(r["g"].area,s["g"].area)
            except:ov=0
            if ov<0.80:continue
            key=(r["i"],s["i"])
            if key in seen:continue
            seen.add(key);summary["duplicates"]+=1;dc["duplicates"]+=1
            if len(examples["duplicates"])<40:
                examples["duplicates"].append({
                    "district_id":did,
                    "a_index":r["i"],"b_index":s["i"],
                    "a_name":r["p"].get("building_name") or r["p"].get("register_name"),
                    "b_name":s["p"].get("building_name") or s["p"].get("register_name"),
                    "overlap_ratio":round(ov,3),"area_ratio":round(ar,3),
                    "centroid":[round(r["c"][0],7),round(r["c"][1],7)]
                })

    # 2) 비정상 높이
    for r in rows:
        h,fl,a=r["h"],r["fl"],r["area"];p=r["p"]
        bad=False;reason=[]
        if h>180:bad=True;reason.append("height>180m")
        if fl>0 and h>0 and h/fl>8:bad=True;reason.append("층당높이>8m")
        if fl>0 and h>0 and h/fl<1.8:bad=True;reason.append("층당높이<1.8m")
        if h>=45 and a<80:bad=True;reason.append("작은 footprint 고층")
        if bad:
            summary["height_outliers"]+=1;dc["height_outliers"]+=1
            if len(examples["height_outliers"])<60:
                examples["height_outliers"].append({
                    "district_id":did,"index":r["i"],
                    "name":p.get("building_name") or p.get("register_name"),
                    "dong":p.get("building_dong") or p.get("register_dong"),
                    "height":h,"floors":fl,"area_m2":round(a,1),
                    "reason":reason,"centroid":[round(r["c"][0],7),round(r["c"][1],7)]
                })
        if h>=30 and a<50:
            summary["tiny_highrise"]+=1;dc["tiny_highrise"]+=1
            if len(examples["tiny_highrise"])<40:
                examples["tiny_highrise"].append({
                    "district_id":did,"index":r["i"],
                    "name":p.get("building_name") or p.get("register_name"),
                    "height":h,"floors":fl,"area_m2":round(a,1),
                    "centroid":[round(r["c"][0],7),round(r["c"][1],7)]
                })

    # 3) 누락 의심: 큰 대장 건축면적/고층정보가 있는데 현재 footprint가 지나치게 작음
    for r in rows:
        p=r["p"]; ra=num(p.get("register_building_area_m2")); a=r["area"]
        if not p.get("register_matched") or ra<=0 or a<=0:continue
        ratio=min(a,ra)/max(a,ra)
        if ratio<0.08 and (num(p.get("floors_above"))>=8 or num(p.get("render_height"))>=30):
            summary["missing_like"]+=1;dc["missing_like"]+=1
            if len(examples["missing_like"])<50:
                examples["missing_like"].append({
                    "district_id":did,"index":r["i"],
                    "name":p.get("building_name") or p.get("register_name"),
                    "dong":p.get("building_dong") or p.get("register_dong"),
                    "footprint_area_m2":round(a,1),
                    "register_area_m2":ra,"ratio":round(ratio,4),
                    "height":num(p.get("render_height")),"floors":num(p.get("floors_above")),
                    "centroid":[round(r["c"][0],7),round(r["c"][1],7)]
                })
    districts[did]=dc

report={
    "summary":summary,
    "criteria":{
        "duplicates":"중심 8m 이내 + 면적비>=0.75 + 상호중첩>=0.80",
        "height_outliers":"height>180m 또는 층당높이>8m/1.8m미만 또는 80㎡미만 footprint에 45m 이상",
        "tiny_highrise":"50㎡ 미만 footprint에 30m 이상",
        "missing_like":"대장 매칭 건물 중 footprint/대장면적비<0.08이고 8층 이상 또는 30m 이상"
    },
    "districts":districts,
    "examples":examples
}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report["summary"],ensure_ascii=False,indent=2))
