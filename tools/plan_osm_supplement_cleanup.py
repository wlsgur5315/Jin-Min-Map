#!/usr/bin/env python3
import gzip,json,math
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; OUT=ROOT/"data/osm_supplement_overlap_plan.json"

def load(path):
  with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def safe(g):
  try:
    if not g.is_valid:g=g.buffer(0)
  except:return None
  return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def center(g):
  c=g.representative_point();return c.x,c.y
def distm(a,b):
  lat=(a[1]+b[1])/2
  x=(b[0]-a[0])*111320*math.cos(math.radians(lat));y=(b[1]-a[1])*110540
  return math.hypot(x,y)
def source(p): return str(p.get("data_source") or p.get("source") or "")
def is_supp(p):
  s=source(p)
  return "OSM 정적 보완" in s or "Overture 정적 보완" in s

summary={};items=[]
for path in sorted(BUILD.glob("*.geojson.gz")):
  did=path.stem.split(".")[0];fc=load(path);rows=[];geoms=[]
  for i,f in enumerate(fc.get("features",[])):
    try:g=safe(shape(f.get("geometry")))
    except:g=None
    if g is None:continue
    rows.append((i,g,g.area,center(g),f.get("properties") or {})); geoms.append(g)
  tree=STRtree(geoms) if geoms else None
  drops=set(); local=[]
  for ri,(idx,g,aa,ca,p) in enumerate(rows):
    if idx in drops or not is_supp(p):continue
    for q in tree.query(g):
      try:rj=int(q)
      except:rj=geoms.index(q)
      if rj==ri:continue
      idx2,g2,bb,cb,p2=rows[rj]
      if idx2 in drops or is_supp(p2):continue
      try:
        inter=g.intersection(g2).area
        ov=inter/min(aa,bb) if min(aa,bb)>0 else 0
        ar=min(aa,bb)/max(aa,bb) if max(aa,bb)>0 else 0
      except:continue
      d=distm(ca,cb)
      if ov>=.15 or (d<=3 and ar>=.45):
        drops.add(idx)
        local.append({"district_id":did,"drop":idx,"keep":idx2,"source":source(p),
          "overlap":round(ov,4),"area_ratio":round(ar,4),"distance_m":round(d,2)})
        break
  summary[did]=len(drops); items.extend(local)
OUT.write_text(json.dumps({"remove_count":len(items),"districts":summary,"items":items},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"remove_count":len(items),"districts":{k:v for k,v in summary.items() if v}},ensure_ascii=False,indent=2))
