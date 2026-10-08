#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; MANIFEST=ROOT/"data/manifest.json"
OUT=ROOT/"data/exact_duplicate_fix_report.json"

def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
def save_gz(p,obj):
    raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode()
    with gzip.open(p,"wb",compresslevel=9) as f:f.write(raw)
    return p.stat().st_size
def norm(s):return re.sub(r"\s+","",str(s or "")).strip()
def pnu(p):
    d=re.sub(r"\D","",str(p.get("pnu") or ""))
    return d if len(d)==19 else ""
def num(v):
    try:return float(v)
    except:return 0.0
def safe(g):
    try:
        if not g.is_valid:g=g.buffer(0)
    except:return None
    return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def area_m2(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat)
def richness(p):
    ks=("building_uid","pnu","building_name","building_dong","register_name","register_dong","register_matched","height_source","use_name")
    conf={"높음":3,"보통":2,"낮음":1}.get(str(p.get("height_confidence") or ""),0)
    return sum(1 for k in ks if p.get(k) not in (None,"",False))+conf

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
report={"removed":0,"pairs":[],"districts":{}}

for did,meta in manifest["buildings"].items():
    path=ROOT/meta["file"];fc=load_gz(path);feats=fc.get("features",[])
    rows=[];geoms=[]
    for i,f in enumerate(feats):
        g=safe(shape(f.get("geometry")))
        if g is None:continue
        p=f.get("properties") or {}
        rows.append({"i":i,"f":f,"g":g,"p":p,"a":area_m2(g)})
        geoms.append(g)
    tree=STRtree(geoms) if geoms else None
    remove=set();pairs=[]
    for i,r in enumerate(rows):
        if r["i"] in remove or not tree:continue
        for item in tree.query(r["g"]):
            try:j=int(item)
            except:j=geoms.index(item)
            if j<=i:continue
            s=rows[j]
            if s["i"] in remove:continue
            pa,pb=r["p"],s["p"]
            if not pnu(pa) or pnu(pa)!=pnu(pb):continue
            da=norm(pa.get("building_dong") or pa.get("register_dong"))
            db=norm(pb.get("building_dong") or pb.get("register_dong"))
            if not da or da!=db:continue
            ha=num(pa.get("render_height") or pa.get("height_m"));hb=num(pb.get("render_height") or pb.get("height_m"))
            if ha and hb and abs(ha-hb)>.5:continue
            ar=min(r["a"],s["a"])/max(r["a"],s["a"]) if r["a"] and s["a"] else 0
            if ar<.995:continue
            try:ov=r["g"].intersection(s["g"]).area/min(r["g"].area,s["g"].area)
            except:ov=0
            if ov<.995:continue
            # 보존할 쪽은 정보가 더 풍부한 feature. 동률이면 앞쪽 index 유지.
            keep,drop=(r,s) if richness(pa)>=richness(pb) else (s,r)
            remove.add(drop["i"])
            pairs.append({
                "keep_index":keep["i"],"remove_index":drop["i"],
                "pnu":pnu(pa),"dong":da,"overlap_ratio":round(ov,4),
                "area_ratio":round(ar,4),"keep_uid":keep["p"].get("building_uid"),
                "remove_uid":drop["p"].get("building_uid")
            })
    if remove:
        fc["features"]=[f for i,f in enumerate(feats) if i not in remove]
        size=save_gz(path,fc);meta["count"]=len(fc["features"]);meta["bytes"]=size;meta["static_version"]="2026-10-08-03"
    report["districts"][did]=len(remove);report["removed"]+=len(remove);report["pairs"].extend([{"district_id":did,**x} for x in pairs])

manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
manifest.setdefault("notes",{})["exact_duplicate_fix"]="2026-10-08: 동일 PNU·동명칭·높이이며 geometry 중첩>=99.5%, 면적비>=99.5%인 확정 중복만 제거."
MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
