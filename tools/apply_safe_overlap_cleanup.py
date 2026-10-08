#!/usr/bin/env python3
import gzip,json,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; MANIFEST=ROOT/"data/manifest.json"; OUT=ROOT/"data/safe_overlap_cleanup_report.json"

def load(path):
  with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def save(path,obj):
  raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode("utf-8")
  with gzip.open(path,"wb",compresslevel=9) as f:f.write(raw)
  return path.stat().st_size
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
  if p.get("register_matched"):n+=2
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
def pick_keep(a,b,aa,bb):
  if a["verified"]!=b["verified"]:return 0 if a["verified"] else 1
  ay,by=year(a["uid"]),year(b["uid"])
  # 연도가 있으면 최신 건물 레코드를 우선한다.
  if ay!=by:
    if ay==0:return 1
    if by==0:return 0
    return 0 if ay>by else 1
  if a["richness"]!=b["richness"]:return 0 if a["richness"]>b["richness"] else 1
  return 0 if aa>=bb else 1

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
report={"removed":0,"districts":{},"items":[]}

for did,meta in manifest["buildings"].items():
  path=ROOT/meta["file"];fc=load(path);fs=fc.get("features",[])
  rows=[];geoms=[]
  for i,f in enumerate(fs):
    try:g=safe(shape(f.get("geometry")))
    except:g=None
    if g is None:continue
    rows.append((i,f,g,ident(f.get("properties") or {})));geoms.append(g)
  tree=STRtree(geoms) if geoms else None
  remove=set();items=[]
  for ri,(idx,f,g,a) in enumerate(rows):
    if idx in remove:continue
    for q in (tree.query(g) if tree else []):
      try:rj=int(q)
      except:rj=geoms.index(q)
      if rj<=ri:continue
      idx2,f2,g2,b=rows[rj]
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
      keep_side=pick_keep(a,b,aa,bb)
      keep,drop=(idx,idx2) if keep_side==0 else (idx2,idx)
      ka,kb=(a,b) if keep_side==0 else (b,a)
      remove.add(drop)
      items.append({"district_id":did,"keep":keep,"drop":drop,"pnu":a["pnu"],
                    "overlap":round(ov,4),"area_ratio":round(ar,4),
                    "keep_uid":ka["uid"],"drop_uid":kb["uid"],
                    "keep_year":year(ka["uid"]),"drop_year":year(kb["uid"]),
                    "name":ka["name"] or kb["name"],"dong":ka["dong"] or kb["dong"],
                    "height":ka["height"],"floors":ka["floors"]})
      if drop==idx:break
  if remove:
    fc["features"]=[f for i,f in enumerate(fs) if i not in remove]
    meta["count"]=len(fc["features"]);meta["bytes"]=save(path,fc);meta["static_version"]="2026-10-08-05"
  report["districts"][did]=len(remove);report["removed"]+=len(remove);report["items"].extend(items)

manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
manifest.setdefault("notes",{})["safe_overlap_cleanup"]="2026-10-08: 같은 PNU·높이·층수이고 80% 이상 중첩하며 동/건물명 충돌이 없는 중복 GIS 레코드만 제거. verified override 및 최신 UID 우선."
MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"removed":report["removed"],"districts":{k:v for k,v in report["districts"].items() if v},"sangpyeong":[x for x in report["items"] if x["district_id"]=="38030780"]},ensure_ascii=False,indent=2))
