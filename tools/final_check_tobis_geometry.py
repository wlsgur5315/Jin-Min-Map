#!/usr/bin/env python3
import gzip,json,re,math
from pathlib import Path
from shapely.geometry import shape
from shapely.ops import transform

ROOT=Path(__file__).resolve().parents[1]
B=ROOT/"data/buildings/38030770.geojson.gz"
P=ROOT/"data/parcels/38030770.geojson.gz"
OUT=ROOT/"data/tobis_final_geometry_check.json"
TARGET="4817011900100330015"
lat=35.1822
mx=111320*math.cos(math.radians(lat)); my=110540
def metric(g): return transform(lambda x,y,z=None:(x*mx,y*my),g)
def loadgz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
def pnu(pr):
    d=re.sub(r"\D","",str(pr.get("pnu") or pr.get("PNU") or ""))
    return d if len(d)==19 else ""

bfc=loadgz(B);pfc=loadgz(P)
rows=[]
for i,f in enumerate(bfc.get("features",[])):
    pr=f.get("properties") or {}
    if pnu(pr)==TARGET or "토비스유압" in str(pr.get("building_name") or pr.get("register_name") or ""):
        g=metric(shape(f["geometry"]))
        rows.append((i,pr,g))
road=[]
for f in pfc.get("features",[]):
    pr=f.get("properties") or {}
    raw=str(pr.get("jibun") or pr.get("JIBUN") or "")
    if raw.endswith("도"):
        try: road.append(metric(shape(f["geometry"])))
        except: pass
from shapely.ops import unary_union
ru=unary_union(road) if road else None
records=[]
for i,pr,g in rows:
    records.append({
      "index":i,"uid":pr.get("building_uid"),"name":pr.get("building_name") or pr.get("register_name"),
      "dong":pr.get("building_dong") or pr.get("register_dong"),
      "height":pr.get("render_height") or pr.get("height_m"),"floors":pr.get("floors_above"),
      "area_m2":round(g.area,1),
      "road_overlap_ratio":round((g.intersection(ru).area/g.area if ru and g.area else 0),4)
    })
pairs=[]
for a in range(len(rows)):
    ia,pa,ga=rows[a]
    for b in range(a+1,len(rows)):
        ib,pb,gb=rows[b]
        inter=ga.intersection(gb).area
        if inter<=0:continue
        ov=inter/min(ga.area,gb.area)
        iou=inter/ga.union(gb).area
        pairs.append({"a":ia,"b":ib,"overlap_smaller":round(ov,4),"iou":round(iou,4)})
pairs.sort(key=lambda x:-x["overlap_smaller"])
out={"record_count":len(records),"records":records,"pairwise_overlaps":pairs}
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out,ensure_ascii=False,indent=2))
