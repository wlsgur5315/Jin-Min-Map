#!/usr/bin/env python3
import gzip,json,math,re
from collections import defaultdict
from pathlib import Path
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; MANIFEST=ROOT/"data/manifest.json"
REPORT=ROOT/"data/weak_register_match_fix_report.json"

def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
def save_gz(p,obj):
    raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode()
    with gzip.open(p,"wb",compresslevel=9) as f:f.write(raw)
    return p.stat().st_size
def norm(s): return re.sub(r"\s+","",str(s or "")).strip()
def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0
def dist_m(a,b):
    x=(b[0]-a[0])*111320*math.cos(math.radians((a[1]+b[1])/2))
    y=(b[1]-a[1])*110540
    return math.hypot(x,y)
def risk(p,ratio):
    try:h=float(p.get("render_height") or p.get("height_m") or 0)
    except:h=0
    try:fl=float(p.get("floors_above") or 0)
    except:fl=0
    s=6 if ratio<.10 else 5 if ratio<.20 else 4 if ratio<.25 else 3
    s+=4 if h>=50 else 3 if h>=30 else 2 if h>=15 else 0
    s+=3 if fl>=15 else 2 if fl>=8 else 0
    if p.get("building_name") or p.get("building_dong") or p.get("register_name") or p.get("register_dong"):s+=1
    if p.get("height_source")=="건축물대장 실제 높이":s+=2
    return s
def fallback_height(p,area):
    use=str(p.get("use_name") or p.get("building") or "")
    try:h=float(p.get("source_height_m") or 0)
    except:h=0
    try:fl=float(p.get("source_floors_above") or 0)
    except:fl=0
    if h>1 and h<=200:
        return h,fl or p.get("floors_above") or 0,"원본 GIS/OSM 높이"
    if fl>0:
        fh=2.9 if re.search("공동주택|아파트|residential",use,re.I) else 3.6
        return fl*fh,fl,"원본 층수 기반"
    if re.search("공동주택|아파트|residential",use,re.I):
        n=12 if area>800 else 6 if area>300 else 3; return n*2.9,n,"용도·면적 기반 추정"
    if re.search("공장|창고|industrial|warehouse|factory",use,re.I):
        return (10 if area>1500 else 7),1,"용도·면적 기반 추정"
    n=3 if area>500 else 2 if area>120 else 1
    return n*3.2,n,"용도·면적 기반 추정"

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
summary={"suppressed":0,"districts":{},"examples":[]}

for did,meta in manifest["buildings"].items():
    path=ROOT/meta["file"]; fc=load_gz(path); rows=[]; groups=defaultdict(list)
    for i,f in enumerate(fc.get("features",[])):
        p=f.get("properties") or {}
        if not p.get("register_matched") or str(p.get("register_match_basis") or "")!="PNU/주소 후보":continue
        try:g=shape(f["geometry"])
        except:continue
        if g.is_empty:continue
        area=metric_area(g)
        try:ra=float(p.get("register_building_area_m2") or 0)
        except:ra=0
        if area<=0 or ra<=0:continue
        ratio=min(area,ra)/max(area,ra)
        if ratio>=.35 or risk(p,ratio)<10:continue
        rp=g.representative_point()
        rec={"i":i,"f":f,"p":p,"g":g,"area":area,"ra":ra,"ratio":ratio,"pt":(rp.x,rp.y)}
        rows.append(rec)
        key=(norm(p.get("register_name")),norm(p.get("register_dong")),round(float(p.get("render_height") or 0),1),round(float(p.get("floors_above") or 0),1),round(ra,1))
        groups[key].append(rec)
    changed=0
    for key,items in groups.items():
        for r in items:
            peers=[x for x in items if dist_m(r["pt"],x["pt"])<=120]
            total=sum(x["area"] for x in peers)
            gr=min(total,r["ra"])/max(total,r["ra"]) if total>0 and r["ra"]>0 else 0
            if gr>=.35: continue
            p=r["p"]
            p["suppressed_register_height"]=True
            p["suppressed_register_height_reason"]="PNU/주소 후보만으로 매칭되었고, 주변 동일대장 그룹 면적도 대장면적의 35% 미만"
            p["suppressed_register_height_original"]=p.get("render_height")
            p["register_matched"]=False
            p["register_match_rejected"]=True
            p["register_group_area_ratio_before_reject"]=round(gr,4)
            for k in ("render_height","height_m","floors_above","floors_below"):
                p.pop(k,None)
            h,fl,src=fallback_height(p,r["area"])
            p["render_height"]=round(h,3); p["height_m"]=round(h,3)
            if fl:p["floors_above"]=fl
            p["height_source"]=src
            p["height_confidence"]="낮음" if "추정" in src else "보통"
            changed+=1
            if len(summary["examples"])<20:
                summary["examples"].append({"district_id":did,"register_name":p.get("register_name"),"ratio":round(r["ratio"],4),"group_ratio":round(gr,4),"new_height":round(h,2)})
    if changed:
        size=save_gz(path,fc); meta["bytes"]=size; meta["static_version"]="2026-10-08-02"
    summary["districts"][did]=changed; summary["suppressed"]+=changed

manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
manifest.setdefault("notes",{})["weak_register_match_fix"]="2026-10-08: 긴급 PNU/주소 후보 매칭 중 주변 동일대장 그룹 면적비도 0.35 미만인 경우 대장 높이를 거부하고 보수적 높이로 대체."
MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
REPORT.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
