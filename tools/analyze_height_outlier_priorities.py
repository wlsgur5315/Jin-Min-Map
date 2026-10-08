#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; OUT=ROOT/"data/height_outlier_priority_analysis.json"

def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
def num(v):
    try:return float(v)
    except:return 0.0
def area_m2(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat)
def rep(g):
    p=g.representative_point();return [round(p.x,7),round(p.y,7)]

cats={
  "likely_normal_industrial":[],
  "high_impossible_low_per_floor":[],
  "high_tiny_highrise":[],
  "high_extreme_height":[],
  "medium_tall_per_floor_nonindustrial":[],
  "other_suspicious":[]
}
for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    fc=load_gz(path)
    for i,f in enumerate(fc.get("features",[])):
        p=f.get("properties") or {}
        try:g=shape(f.get("geometry"))
        except:continue
        if g.is_empty:continue
        h=num(p.get("render_height") or p.get("height_m"));fl=num(p.get("floors_above"));a=area_m2(g)
        if h<=0:continue
        use=str(p.get("use_name") or p.get("register_use") or p.get("building") or "")
        industrial=bool(re.search("공장|창고|산업|industrial|warehouse|factory",use,re.I))
        reasons=[]
        if h>180:reasons.append("height>180m")
        if fl>0 and h/fl>8:reasons.append("층당높이>8m")
        if fl>0 and h/fl<1.8:reasons.append("층당높이<1.8m")
        if h>=45 and a<80:reasons.append("작은 footprint 고층")
        if not reasons:continue
        item={
          "district_id":did,"index":i,
          "name":p.get("building_name") or p.get("register_name"),
          "dong":p.get("building_dong") or p.get("register_dong"),
          "use":use,"height":h,"floors":fl,"area_m2":round(a,1),
          "reasons":reasons,"height_source":p.get("height_source"),
          "height_confidence":p.get("height_confidence"),
          "centroid":rep(g)
        }
        if fl>=2 and h/fl<1.8:
            cats["high_impossible_low_per_floor"].append(item)
        elif h>=45 and a<80:
            cats["high_tiny_highrise"].append(item)
        elif h>180:
            cats["high_extreme_height"].append(item)
        elif fl<=1 and h<=15 and industrial and reasons==["층당높이>8m"]:
            cats["likely_normal_industrial"].append(item)
        elif fl>0 and h/fl>8:
            cats["medium_tall_per_floor_nonindustrial"].append(item)
        else:
            cats["other_suspicious"].append(item)

summary={k:len(v) for k,v in cats.items()}
OUT.write_text(json.dumps({"summary":summary,"categories":cats},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
