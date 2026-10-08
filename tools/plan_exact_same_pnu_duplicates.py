#!/usr/bin/env python3
import gzip,json,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; OUT=ROOT/"data/exact_same_pnu_duplicate_plan.json"

def load(path):
  with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def safe(g):
  try:
    if not g.is_valid:g=g.buffer(0)
  except:return None
  return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def norm(x):return re.sub(r"\s+","",str(x or "")).strip()
def num(v):
  try:return float(v)
  except:return 0.0
def pnu(p):
  d=re.sub(r"\D","",str(p.get("pnu") or p.get("PNU") or ""))
  return d if len(d)==19 else ""
def ident(p):
  return {
    "pnu":pnu(p),
    "uid":norm(p.get("building_uid")),
    "name":norm(p.get("building_name") or p.get("register_name")),
    "dong":norm(p.get("building_dong") or p.get("register_dong")),
    "height":num(p.get("render_height") or p.get("height_m")),
    "floors":num(p.get("floors_above")),
    "verified":bool(p.get("verified_override"))
  }

items=[];counts={}
for path in sorted(BUILD.glob("*.geojson.gz")):
  did=path.stem.split(".")[0];fc=load(path);rows=[];geoms=[]
  for i,f in enumerate(fc.get("features",[])):
    try:g=safe(shape(f.get("geometry")))
    except:g=None
    if g is None:continue
    rows.append((i,g,ident(f.get("properties") or {})));geoms.append(g)
  tree=STRtree(geoms) if geoms else None
  drops=set();local=[]
  for ri,(idx,g,a) in enumerate(rows):
    if idx in drops or not a["pnu"]:continue
    for q in (tree.query(g) if tree else []):
      try:rj=int(q)
      except:rj=geoms.index(q)
      if rj<=ri:continue
      idx2,g2,b=rows[rj]
      if idx2 in drops or a["pnu"]!=b["pnu"]:continue
      if a["dong"] and b["dong"] and a["dong"]!=b["dong"]:continue
      if a["name"] and b["name"] and a["name"]!=b["name"]:continue
      if a["height"]>0 and b["height"]>0 and abs(a["height"]-b["height"])>.35:continue
      if a["floors"]>0 and b["floors"]>0 and a["floors"]!=b["floors"]:continue
      try:
        aa=g.area;bb=g2.area;inter=g.intersection(g2).area
        ov=inter/min(aa,bb) if min(aa,bb)>0 else 0
        ar=min(aa,bb)/max(aa,bb) if max(aa,bb)>0 else 0
      except:continue
      if ov<.80 or ar<.70:continue
      # verified wins; otherwise larger footprint wins to retain fuller geometry
      if a["verified"]!=b["verified"]:keep,drop=(idx,idx2) if a["verified"] else (idx2,idx)
      else:keep,drop=(idx,idx2) if aa>=bb else (idx2,idx)
      drops.add(drop)
      local.append({"district_id":did,"keep":keep,"drop":drop,"pnu":a["pnu"],
        "overlap":round(ov,4),"area_ratio":round(ar,4),"a":a,"b":b})
      if drop==idx:break
  counts[did]=len(drops);items.extend(local)

OUT.write_text(json.dumps({"remove_count":len(items),"districts":counts,"items":items},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"remove_count":len(items),"districts":{k:v for k,v in counts.items() if v}},ensure_ascii=False,indent=2))
