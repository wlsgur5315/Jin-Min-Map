#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; MANIFEST=ROOT/"data/manifest.json"; OUT=ROOT/"data/visual_overlap_cleanup_report.json"

def load(path):
  with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def save(path,obj):
  raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode()
  with gzip.open(path,"wb",compresslevel=9) as f:f.write(raw)
  return path.stat().st_size
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
def ident(p):
  src=str(p.get("data_source") or p.get("source") or "")
  return {
    "pnu":pnu(p),"uid":norm(p.get("building_uid")),
    "name":norm(p.get("building_name") or p.get("register_name")),
    "dong":norm(p.get("building_dong") or p.get("register_dong")),
    "height":num(p.get("render_height") or p.get("height_m")),
    "floors":num(p.get("floors_above")),
    "source":src,"overture":"Overture" in src,
    "verified":bool(p.get("verified_override"))
  }
def uid_year(uid):
  m=re.match(r"((?:19|20)\d{2})",str(uid or ""))
  return int(m.group(1)) if m else 0
def center(g):
  c=g.representative_point();return c.x,c.y
def distm(a,b):
  lat=(a[1]+b[1])/2
  x=(b[0]-a[0])*111320*math.cos(math.radians(lat));y=(b[1]-a[1])*110540
  return math.hypot(x,y)
def compatible(a,b):
  if a["dong"] and b["dong"] and a["dong"]!=b["dong"]:return False
  if a["name"] and b["name"] and a["name"]!=b["name"]:return False
  if a["height"]>0 and b["height"]>0 and abs(a["height"]-b["height"])>.35:return False
  if a["floors"]>0 and b["floors"]>0 and a["floors"]!=b["floors"]:return False
  return True
def choose_native(a,b,aa,bb):
  if a["verified"]!=b["verified"]:return 0 if a["verified"] else 1
  ay,by=uid_year(a["uid"]),uid_year(b["uid"])
  if ay!=by:
    if ay==0:return 1
    if by==0:return 0
    return 0 if ay>by else 1
  return 0 if aa>=bb else 1

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
report={"removed":0,"overture_removed":0,"native_removed":0,"districts":{},"items":[]}

for did,meta in manifest["buildings"].items():
  path=ROOT/meta["file"];fc=load(path);fs=fc.get("features",[])
  rows=[]; geoms=[]
  for i,f in enumerate(fs):
    try:g=safe(shape(f.get("geometry")))
    except:g=None
    if g is None:continue
    rows.append((i,g,g.area,center(g),ident(f.get("properties") or {}))); geoms.append(g)
  tree=STRtree(geoms) if geoms else None
  remove=set();items=[]

  # 1) Overture is supplement only: remove whenever it meaningfully overlaps a native GIS building.
  for ri,(idx,g,aa,ca,a) in enumerate(rows):
    if idx in remove or not a["overture"]:continue
    for q in tree.query(g):
      try:rj=int(q)
      except:rj=geoms.index(q)
      if rj==ri:continue
      idx2,g2,bb,cb,b=rows[rj]
      if idx2 in remove or b["overture"]:continue
      try:
        inter=g.intersection(g2).area
        ov=inter/min(aa,bb) if min(aa,bb)>0 else 0
        ar=min(aa,bb)/max(aa,bb) if max(aa,bb)>0 else 0
      except:continue
      d=distm(ca,cb)
      if ov>=.15 or (d<=3 and ar>=.45):
        remove.add(idx)
        items.append({"type":"overture_vs_gis","district_id":did,"drop":idx,"keep":idx2,
          "overlap":round(ov,4),"area_ratio":round(ar,4),"distance_m":round(d,2),
          "drop_pnu":a["pnu"],"keep_pnu":b["pnu"],"drop_source":a["source"],"keep_source":b["source"]})
        report["overture_removed"]+=1
        break

  # 2) Native GIS old/new geometry duplicates: same parcel + same building attributes.
  for ri,(idx,g,aa,ca,a) in enumerate(rows):
    if idx in remove or a["overture"] or not a["pnu"]:continue
    for q in tree.query(g):
      try:rj=int(q)
      except:rj=geoms.index(q)
      if rj<=ri:continue
      idx2,g2,bb,cb,b=rows[rj]
      if idx2 in remove or b["overture"] or a["pnu"]!=b["pnu"]:continue
      if not compatible(a,b):continue
      try:
        inter=g.intersection(g2).area
        ov=inter/min(aa,bb) if min(aa,bb)>0 else 0
        ar=min(aa,bb)/max(aa,bb) if max(aa,bb)>0 else 0
      except:continue
      d=distm(ca,cb)
      if ov<=0:continue
      same_label=(a["dong"] and a["dong"]==b["dong"]) or (a["name"] and a["name"]==b["name"])
      ay,by=uid_year(a["uid"]),uid_year(b["uid"])
      old_new=(ay and by and max(ay,by)-min(ay,by)>=5)
      duplicate=False
      if same_label and ov>=.20 and ar>=.45 and d<=15:duplicate=True
      elif old_new and ov>=.35 and ar>=.50 and d<=10:duplicate=True
      elif not a["dong"] and not b["dong"] and not a["name"] and not b["name"] and ov>=.45 and ar>=.55 and d<=8:duplicate=True
      if not duplicate:continue
      keep_side=choose_native(a,b,aa,bb)
      keep,drop=(idx,idx2) if keep_side==0 else (idx2,idx)
      ka,kb=(a,b) if keep_side==0 else (b,a)
      remove.add(drop);report["native_removed"]+=1
      items.append({"type":"native_old_new","district_id":did,"keep":keep,"drop":drop,
        "overlap":round(ov,4),"area_ratio":round(ar,4),"distance_m":round(d,2),
        "pnu":a["pnu"],"keep_uid":ka["uid"],"drop_uid":kb["uid"],
        "keep_year":uid_year(ka["uid"]),"drop_year":uid_year(kb["uid"]),
        "name":ka["name"] or kb["name"],"dong":ka["dong"] or kb["dong"],
        "height":ka["height"],"floors":ka["floors"]})

  if remove:
    fc["features"]=[f for i,f in enumerate(fs) if i not in remove]
    meta["count"]=len(fc["features"]);meta["bytes"]=save(path,fc);meta["static_version"]="2026-10-08-06"
  report["districts"][did]=len(remove);report["removed"]+=len(remove);report["items"].extend(items)

manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
manifest.setdefault("notes",{})["visual_overlap_cleanup"]="2026-10-08: Overture 보완이 GIS와 15% 이상 겹치면 제거. 같은 PNU의 구형/신형 GIS가 속성 일치하고 시각적으로 겹치면 최신 레코드 우선."
MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"removed":report["removed"],"overture":report["overture_removed"],"native":report["native_removed"],
"districts":{k:v for k,v in report["districts"].items() if v},
"sangpyeong":[x for x in report["items"] if x["district_id"]=="38030780"]},ensure_ascii=False,indent=2))
