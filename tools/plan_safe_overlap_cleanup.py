#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; OUT=ROOT/"data/safe_overlap_cleanup_plan.json"

def load(path):
  with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def norm(x):return re.sub(r"\s+","",str(x or "")).strip()
def pnu(p):
  d=re.sub(r"\D","",str(p.get("pnu") or p.get("PNU") or ""))
  return d if len(d)==19 else ""
def num(v):
  try:return float(v)
  except:return 0.0
def safe(g):
  try:
    if not g.is_valid:g=g.buffer(0)
  except:return None
  return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def year(uid):
  m=re.match(r"((?:19|20)\d{2})",str(uid or ""))
  return int(m.group(1)) if m else 0
def richness(p):
  n=sum(1 for k in ("building_uid","pnu","building_name","building_dong","register_name","register_dong","use_name","height_source") if p.get(k))
  if p.get("verified_override"):n+=20
  if p.get("register_matched"):n+=3
  return n
def ident(p):
  return dict(
    pnu=pnu(p),uid=norm(p.get("building_uid")),
    name=norm(p.get("building_name") or p.get("register_name")),
    dong=norm(p.get("building_dong") or p.get("register_dong")),
    height=num(p.get("render_height") or p.get("height_m")),
    floors=num(p.get("floors_above")),
    verified=bool(p.get("verified_override")),richness=richness(p)
  )

plan=[];by={}
for path in sorted(BUILD.glob("*.geojson.gz")):
  did=path.stem.split(".")[0];fc=load(path);rows=[];geoms=[]
  for i,f in enumerate(fc.get("features",[])):
    try:g=safe(shape(f.get("geometry")))
    except:g=None
    if g is None:continue
    rows.append((i,f,g,ident(f.get("properties") or {})));geoms.append(g)
  tree=STRtree(geoms) if geoms else None
  remove=set();items=[]
  for i,(idx,f,g,a) in enumerate(rows):
    if idx in remove:continue
    for q in (tree.query(g) if tree else []):
      try:j=int(q)
      except:j=geoms.index(q)
      if j<=i:continue
      idx2,f2,g2,b=rows[j]
      if idx2 in remove:continue
      if not a["pnu"] or a["pnu"]!=b["pnu"]:continue
      if a["dong"] and b["dong"] and a["dong"]!=b["dong"]:continue
      if a["name"] and b["name"] and a["name"]!=b["name"]:continue
      if a["floors"]>0 and b["floors"]>0 and a["floors"]!=b["floors"]:continue
      if a["height"]>0 and b["height"]>0 and abs(a["height"]-b["height"])>.35:continue
      try:
        aa=g.area;bb=g2.area
        ar=min(aa,bb)/max(aa,bb)
        ov=g.intersection(g2).area/min(aa,bb)
      except:continue
      if ar<.70 or ov<.80:continue
      # verified override always wins, otherwise richer, then newer UID year, then larger geometry
      ay,byr=year(a["uid"]),year(b["uid"])
      sa=(100 if a["verified"] else 0)+a["richness"]*3+(ay/1000)+(aa>=bb)*.2
      sb=(100 if b["verified"] else 0)+b["richness"]*3+(byr/1000)+(bb>aa)*.2
      keep,drop=(idx,idx2) if sa>=sb else (idx2,idx)
      ka,kb=(a,b) if keep==idx else (b,a)
      remove.add(drop)
      items.append({"keep":keep,"drop":drop,"pnu":a["pnu"],"overlap":round(ov,4),"area_ratio":round(ar,4),
                    "keep_uid":ka["uid"],"drop_uid":kb["uid"],"keep_year":year(ka["uid"]),"drop_year":year(kb["uid"]),
                    "name":ka["name"] or kb["name"],"dong":ka["dong"] or kb["dong"],"height":ka["height"],"floors":ka["floors"]})
      if drop==idx:break
  if items:
    by[did]=len(items);plan.extend([{"district_id":did,**x} for x in items])

OUT.write_text(json.dumps({"summary":{"remove_count":len(plan),"districts":by},"items":plan},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"remove_count":len(plan),"districts":by,"sangpyeong":[x for x in plan if x["district_id"]=="38030780"]},ensure_ascii=False,indent=2))
