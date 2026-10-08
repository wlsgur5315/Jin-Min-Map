#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; OUT=ROOT/"data/render_overlap_diagnosis.json"

def load(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def norm(x):return re.sub(r"\s+","",str(x or "")).strip()
def pnu(p):
    d=re.sub(r"\D","",str(p.get("pnu") or p.get("PNU") or ""))
    return d if len(d)==19 else ""
def num(v):
    try:return float(v)
    except:return 0.0
def area(g):
    lat=35.18*math.pi/180
    return g.area*(111320**2)*math.cos(lat)
def safe(g):
    try:
        if not g.is_valid:g=g.buffer(0)
    except:return None
    return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def ident(p):
    return {
      "pnu":pnu(p),
      "uid":norm(p.get("building_uid")),
      "name":norm(p.get("building_name") or p.get("register_name")),
      "dong":norm(p.get("building_dong") or p.get("register_dong")),
      "source":str(p.get("data_source") or p.get("source") or "GIS"),
      "height":num(p.get("render_height") or p.get("height_m")),
      "floors":num(p.get("floors_above"))
    }

summary={}
examples=[]
for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    fc=load(path); rows=[]; geoms=[]
    for i,f in enumerate(fc.get("features",[])):
        try:g=safe(shape(f.get("geometry")))
        except:g=None
        if g is None:continue
        rows.append((i,f,g,area(g),ident(f.get("properties") or {})));geoms.append(g)
    tree=STRtree(geoms) if geoms else None
    counts={"pairs80":0,"pairs90":0,"same_pnu":0,"cross_source":0,"same_height_floor":0}
    local=[]
    for i,(idx,f,g,a,ia) in enumerate(rows):
        for item in (tree.query(g) if tree else []):
            try:j=int(item)
            except:j=geoms.index(item)
            if j<=i:continue
            idx2,f2,g2,a2,ib=rows[j]
            ar=min(a,a2)/max(a,a2) if a and a2 else 0
            if ar<.70:continue
            try:ov=g.intersection(g2).area/min(g.area,g2.area)
            except:ov=0
            if ov<.80:continue
            counts["pairs80"]+=1
            if ov>=.90:counts["pairs90"]+=1
            sp=bool(ia["pnu"] and ia["pnu"]==ib["pnu"])
            if sp:counts["same_pnu"]+=1
            if ia["source"]!=ib["source"]:counts["cross_source"]+=1
            sh=(ia["height"]<=0 or ib["height"]<=0 or abs(ia["height"]-ib["height"])<=1.5) and (ia["floors"]<=0 or ib["floors"]<=0 or abs(ia["floors"]-ib["floors"])<=1)
            if sh:counts["same_height_floor"]+=1
            if did=="38030780" or ov>=.95:
                local.append({"a_index":idx,"b_index":idx2,"overlap":round(ov,4),"area_ratio":round(ar,4),"a":ia,"b":ib})
    summary[did]=counts
    if did=="38030780":
        examples=sorted(local,key=lambda x:-x["overlap"])[:120]

OUT.write_text(json.dumps({"summary":summary,"sangpyeong":examples},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"sangpyeong":summary.get("38030780"),"top":examples[:30]},ensure_ascii=False,indent=2))
