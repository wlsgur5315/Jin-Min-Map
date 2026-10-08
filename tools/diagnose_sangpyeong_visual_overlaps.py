#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"data/buildings/38030780.geojson.gz"
OUT=ROOT/"data/sangpyeong_visual_overlap_diagnosis.json"

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
  return {
    "pnu":pnu(p),
    "uid":norm(p.get("building_uid")),
    "source":str(p.get("data_source") or p.get("source") or ""),
    "name":norm(p.get("building_name") or p.get("register_name")),
    "dong":norm(p.get("building_dong") or p.get("register_dong")),
    "height":num(p.get("render_height") or p.get("height_m")),
    "floors":num(p.get("floors_above")),
    "osm_id":str(p.get("osm_id") or p.get("id") or "")
  }

fc=load(PATH); rows=[];geoms=[]
for i,f in enumerate(fc.get("features",[])):
  try:g=safe(shape(f.get("geometry")))
  except:g=None
  if g is None:continue
  rows.append((i,f,g,area_m2(g),center(g),ident(f.get("properties") or {})));geoms.append(g)

tree=STRtree(geoms)
cand=[]
for ri,(idx,f,g,a,c,ia) in enumerate(rows):
  # query bbox expanded roughly 20m
  minx,miny,maxx,maxy=g.bounds
  dx=20/(111320*math.cos(math.radians(c[1])));dy=20/110540
  from shapely.geometry import box
  qbox=box(minx-dx,miny-dy,maxx+dx,maxy+dy)
  for q in tree.query(qbox):
    try:rj=int(q)
    except:rj=geoms.index(q)
    if rj<=ri:continue
    idx2,f2,g2,a2,c2,ib=rows[rj]
    d=mdist(c,c2)
    if d>20:continue
    ar=min(a,a2)/max(a,a2) if a and a2 else 0
    try:
      inter=g.intersection(g2).area
      ov_small=inter/min(g.area,g2.area) if min(g.area,g2.area)>0 else 0
      iou=inter/(g.union(g2).area) if g.union(g2).area>0 else 0
    except:
      ov_small=iou=0
    hclose=(ia["height"]<=0 or ib["height"]<=0 or abs(ia["height"]-ib["height"])<=2)
    fclose=(ia["floors"]<=0 or ib["floors"]<=0 or abs(ia["floors"]-ib["floors"])<=1)
    samep=bool(ia["pnu"] and ia["pnu"]==ib["pnu"])
    # visual duplicate candidate: meaningful overlap OR very close similar size
    visual=((ov_small>=.20 and ar>=.45) or (d<=5 and ar>=.55))
    if not visual:continue
    score=(ov_small*45)+(iou*25)+(ar*10)+(10 if samep else 0)+(5 if hclose else 0)+(5 if fclose else 0)-min(d,20)
    cand.append({
      "a_index":idx,"b_index":idx2,"centroid_distance_m":round(d,2),
      "overlap_small":round(ov_small,4),"iou":round(iou,4),"area_ratio":round(ar,4),
      "same_pnu":samep,"height_close":hclose,"floors_close":fclose,
      "score":round(score,2),"a":ia,"b":ib
    })
cand.sort(key=lambda x:-x["score"])
OUT.write_text(json.dumps({"count":len(cand),"candidates":cand[:300]},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"count":len(cand),"top":cand[:80]},ensure_ascii=False,indent=2))
