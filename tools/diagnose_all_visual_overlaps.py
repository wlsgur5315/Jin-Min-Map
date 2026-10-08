#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape, box
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"
OUT=ROOT/"data/all_district_visual_overlap_diagnosis.json"

def load(path):
  with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def safe(g):
  try:
    if not g.is_valid:g=g.buffer(0)
  except:return None
  return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def num(v):
  try:return float(v)
  except:return 0.0
def norm(x):return re.sub(r"\s+","",str(x or "")).strip()
def pnu(p):
  d=re.sub(r"\D","",str(p.get("pnu") or p.get("PNU") or ""))
  return d if len(d)==19 else ""
def center(g):
  c=g.representative_point();return c.x,c.y
def mdist(a,b):
  lat=(a[1]+b[1])/2
  x=(b[0]-a[0])*111320*math.cos(math.radians(lat));y=(b[1]-a[1])*110540
  return math.hypot(x,y)
def area_m2(g):
  lat=35.18
  return g.area*(111320**2)*math.cos(math.radians(lat))
def ident(p):
  src=str(p.get("data_source") or p.get("source") or "")
  return {
    "pnu":pnu(p),
    "uid":norm(p.get("building_uid")),
    "source":src,
    "name":norm(p.get("building_name") or p.get("register_name")),
    "dong":norm(p.get("building_dong") or p.get("register_dong")),
    "height":num(p.get("render_height") or p.get("height_m")),
    "floors":num(p.get("floors_above")),
    "overture":"Overture" in src
  }

summary={};examples={}
for path in sorted(BUILD.glob("*.geojson.gz")):
  did=path.stem.split(".")[0];fc=load(path);rows=[];geoms=[]
  for i,f in enumerate(fc.get("features",[])):
    try:g=safe(shape(f.get("geometry")))
    except:g=None
    if g is None:continue
    rows.append((i,g,area_m2(g),center(g),ident(f.get("properties") or {})));geoms.append(g)
  tree=STRtree(geoms) if geoms else None
  counts={"meaningful":0,"overture_vs_gis":0,"same_pnu_native":0,"cross_pnu":0}
  cand=[]
  for ri,(idx,g,a,c,ia) in enumerate(rows):
    minx,miny,maxx,maxy=g.bounds
    dx=20/(111320*math.cos(math.radians(c[1])));dy=20/110540
    qbox=box(minx-dx,miny-dy,maxx+dx,maxy+dy)
    for q in (tree.query(qbox) if tree else []):
      try:rj=int(q)
      except:rj=geoms.index(q)
      if rj<=ri:continue
      idx2,g2,a2,c2,ib=rows[rj]
      d=mdist(c,c2)
      if d>20:continue
      ar=min(a,a2)/max(a,a2) if a and a2 else 0
      try:
        inter=g.intersection(g2).area
        ov=inter/min(g.area,g2.area) if min(g.area,g2.area)>0 else 0
        iou=inter/(g.union(g2).area) if g.union(g2).area>0 else 0
      except:ov=iou=0
      if ov<.15:continue
      counts["meaningful"]+=1
      typ="cross_pnu"
      if ia["overture"]!=ib["overture"]:
        typ="overture_vs_gis";counts[typ]+=1
      elif ia["pnu"] and ia["pnu"]==ib["pnu"]:
        typ="same_pnu_native";counts[typ]+=1
      else:counts["cross_pnu"]+=1
      cand.append({"a_index":idx,"b_index":idx2,"type":typ,"overlap_small":round(ov,4),
                   "iou":round(iou,4),"area_ratio":round(ar,4),"distance_m":round(d,2),
                   "a":ia,"b":ib})
  cand.sort(key=lambda x:(-x["overlap_small"],-x["area_ratio"]))
  summary[did]=counts
  if cand:examples[did]=cand[:80]

OUT.write_text(json.dumps({"summary":summary,"examples":examples},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"districts_with_overlap":{k:v for k,v in summary.items() if v["meaningful"]>0}},ensure_ascii=False,indent=2))
