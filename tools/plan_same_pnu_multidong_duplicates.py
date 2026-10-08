#!/usr/bin/env python3
import gzip,json,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; OUT=ROOT/"data/same_pnu_multidong_duplicate_plan.json"

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

groups=[]
for path in sorted(BUILD.glob("*.geojson.gz")):
  did=path.stem.split(".")[0];fc=load(path)
  feats=fc.get("features",[])
  rows=[];geoms=[]
  for i,f in enumerate(feats):
    try:g=safe(shape(f.get("geometry")))
    except:g=None
    if g is None:continue
    rows.append((i,g,ident(f.get("properties") or {})));geoms.append(g)
  tree=STRtree(geoms) if geoms else None
  edges=[]
  for ri,(idx,g,a) in enumerate(rows):
    if not a["pnu"]:continue
    for q in (tree.query(g) if tree else []):
      try:rj=int(q)
      except:rj=geoms.index(q)
      if rj<=ri:continue
      idx2,g2,b=rows[rj]
      if a["pnu"]!=b["pnu"]:continue
      if not a["dong"] or not b["dong"] or a["dong"]==b["dong"]:continue
      if a["height"]>0 and b["height"]>0 and abs(a["height"]-b["height"])>.35:continue
      if a["floors"]>0 and b["floors"]>0 and a["floors"]!=b["floors"]:continue
      try:
        aa=g.area;bb=g2.area;inter=g.intersection(g2).area
        ov=inter/min(aa,bb) if min(aa,bb)>0 else 0
        ar=min(aa,bb)/max(aa,bb) if max(aa,bb)>0 else 0
        iou=inter/g.union(g2).area if g.union(g2).area>0 else 0
      except:continue
      if ov>=.80 and ar>=.90 and iou>=.65:
        edges.append({"a":idx,"b":idx2,"pnu":a["pnu"],"overlap":round(ov,4),"area_ratio":round(ar,4),"iou":round(iou,4),"ia":a,"ib":b})
  # connected components
  adj={}
  for e in edges:
    adj.setdefault(e["a"],set()).add(e["b"]);adj.setdefault(e["b"],set()).add(e["a"])
  seen=set()
  for node in adj:
    if node in seen:continue
    stack=[node];comp=[]
    while stack:
      x=stack.pop()
      if x in seen:continue
      seen.add(x);comp.append(x);stack.extend(adj.get(x,[])-seen)
    if len(comp)<2:continue
    members=[]
    for idx in comp:
      row=next(r for r in rows if r[0]==idx)
      members.append({"index":idx,"area":row[1].area,**row[2]})
    # choose keep: verified first, then normalized building name present, then smallest dong number, then largest area
    def dongnum(d):
      m=re.search(r"(\d+)",d or "")
      return int(m.group(1)) if m else 9999
    keep=sorted(members,key=lambda m:(not m["verified"], not bool(m["name"]), dongnum(m["dong"]), -m["area"]))[0]
    groups.append({"district_id":did,"pnu":keep["pnu"],"keep":keep["index"],"members":members,
                   "drops":[m["index"] for m in members if m["index"]!=keep["index"]]})
OUT.write_text(json.dumps({"group_count":len(groups),"remove_count":sum(len(g["drops"]) for g in groups),"groups":groups},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"group_count":len(groups),"remove_count":sum(len(g["drops"]) for g in groups),
 "tobis":[g for g in groups if g["pnu"]=="4817011900100330015"]},ensure_ascii=False,indent=2))
