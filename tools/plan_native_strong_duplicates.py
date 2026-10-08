#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; OUT=ROOT/"data/native_strong_duplicate_plan.json"

def load(path):
  with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def safe(g):
  try:
    if not g.is_valid:g=g.buffer(0)
  except:return None
  return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def norm(x):return re.sub(r"\s+","",str(x or "")).strip()
def pnu(p):
  d=re.sub(r"\D","",str(p.get("pnu") or p.get("PNU") or ""))
  return d if len(d)==19 else ""
def num(v):
  try:return float(v)
  except:return 0.0
def src(p):return str(p.get("data_source") or p.get("source") or "")
def supp(p):return "정적 보완" in src(p)
def year(uid):
  m=re.match(r"((?:19|20)\d{2})",str(uid or ""))
  return int(m.group(1)) if m else 0
def ident(p):
  return {"pnu":pnu(p),"uid":norm(p.get("building_uid")),
    "name":norm(p.get("building_name") or p.get("register_name")),
    "dong":norm(p.get("building_dong") or p.get("register_dong")),
    "height":num(p.get("render_height") or p.get("height_m")),
    "floors":num(p.get("floors_above")),"source":src(p)}

summary={};items=[]
for path in sorted(BUILD.glob("*.geojson.gz")):
  did=path.stem.split(".")[0];fc=load(path);rows=[];geoms=[]
  for i,f in enumerate(fc.get("features",[])):
    p=f.get("properties") or {}
    if supp(p):continue
    try:g=safe(shape(f.get("geometry")))
    except:g=None
    if g is None:continue
    rows.append((i,g,g.area,ident(p)));geoms.append(g)
  tree=STRtree(geoms) if geoms else None
  drops=set();local=[]
  for ri,(idx,g,aa,a) in enumerate(rows):
    if idx in drops or not a["pnu"]:continue
    for q in (tree.query(g) if tree else []):
      try:rj=int(q)
      except:rj=geoms.index(q)
      if rj<=ri:continue
      idx2,g2,bb,b=rows[rj]
      if idx2 in drops or a["pnu"]!=b["pnu"]:continue
      if a["dong"] and b["dong"] and a["dong"]!=b["dong"]:continue
      if a["name"] and b["name"] and a["name"]!=b["name"]:continue
      if a["floors"]>0 and b["floors"]>0 and a["floors"]!=b["floors"]:continue
      if a["height"]>0 and b["height"]>0 and abs(a["height"]-b["height"])>.35:continue
      try:
        inter=g.intersection(g2).area
        ov=inter/min(aa,bb) if min(aa,bb)>0 else 0
        union=g.union(g2).area
        iou=inter/union if union>0 else 0
        ar=min(aa,bb)/max(aa,bb) if max(aa,bb)>0 else 0
      except:continue
      if ov<.20:continue
      ay,by=year(a["uid"]),year(b["uid"])
      same_label=bool((a["dong"] and a["dong"]==b["dong"]) or (a["name"] and a["name"]==b["name"]))
      both_blank=not a["dong"] and not b["dong"] and not a["name"] and not b["name"]
      old_new=(ay and by and abs(ay-by)>=5) or ((ay==0)!=(by==0) and max(ay,by)>=2000)
      strong=False
      reason=""
      if old_new and (same_label or both_blank) and ov>=.35 and ar>=.12:
        strong=True;reason="old_new_same_identity"
      elif same_label and iou>=.75 and ar>=.80:
        strong=True;reason="near_exact_same_label"
      elif both_blank and iou>=.82 and ar>=.85:
        strong=True;reason="near_exact_blank_label"
      if not strong:continue
      # newest dated UID wins; otherwise larger geometry
      if ay!=by:
        if ay==0:keep,drop=idx2,idx
        elif by==0:keep,drop=idx,idx2
        elif ay>by:keep,drop=idx,idx2
        else:keep,drop=idx2,idx
      else:
        keep,drop=(idx,idx2) if aa>=bb else (idx2,idx)
      drops.add(drop)
      local.append({"district_id":did,"keep":keep,"drop":drop,"reason":reason,
        "pnu":a["pnu"],"overlap":round(ov,4),"iou":round(iou,4),"area_ratio":round(ar,4),
        "a":a,"b":b})
      if drop==idx:break
  summary[did]=len(drops);items.extend(local)

OUT.write_text(json.dumps({"remove_count":len(items),"districts":summary,"items":items},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"remove_count":len(items),"districts":{k:v for k,v in summary.items() if v}},ensure_ascii=False,indent=2))
