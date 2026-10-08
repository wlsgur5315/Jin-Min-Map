#!/usr/bin/env python3
import gzip,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; MANIFEST=ROOT/"data/manifest.json"
OUT=ROOT/"data/impossible_low_height_fix_report.json"

def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
def save_gz(p,obj):
    raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode()
    with gzip.open(p,"wb",compresslevel=9) as f:f.write(raw)
    return p.stat().st_size
def num(v):
    try:return float(v)
    except:return 0.0
def floor_h(use):
    s=str(use or "")
    if re.search("공동주택|아파트|연립|다세대|다가구",s):return 2.9
    if re.search("단독주택",s):return 3.1
    if re.search("교육|학교|연구",s):return 3.8
    if re.search("의료|병원",s):return 4.0
    if re.search("업무|사무",s):return 3.7
    if re.search("근린생활|판매|상업|숙박",s):return 4.0
    if re.search("문화|집회|체육|운동",s):return 4.5
    if re.search("공장|창고|산업",s):return 5.0
    return 3.3

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
report={"corrected":0,"districts":{},"examples":[]}

for did,meta in manifest["buildings"].items():
    path=ROOT/meta["file"];fc=load_gz(path);changed=0
    for i,f in enumerate(fc.get("features",[])):
        p=f.get("properties") or {}
        h=num(p.get("render_height") or p.get("height_m"));fl=num(p.get("floors_above"))
        if fl<2 or h<=0 or h/fl>=1.8:continue
        # 이미 사용자가 검증한 수동 override는 건드리지 않는다.
        if p.get("verified_override"):continue
        use=p.get("register_use") or p.get("use_name") or p.get("building") or ""
        old=h; new=round(fl*floor_h(use),3)
        p["corrected_low_height_original"]=old
        p["corrected_low_height_reason"]="2층 이상인데 기존 총높이/층수<1.8m"
        p["render_height"]=new;p["height_m"]=new
        p["height_source"]=f"건축물대장 비정상 저높이 제외 · {int(fl)}층 기반"
        p["height_confidence"]="보통"
        changed+=1;report["corrected"]+=1
        if len(report["examples"])<40:
            report["examples"].append({
                "district_id":did,"index":i,
                "name":p.get("building_name") or p.get("register_name"),
                "dong":p.get("building_dong") or p.get("register_dong"),
                "use":use,"floors":fl,"old_height":old,"new_height":new
            })
    if changed:
        size=save_gz(path,fc);meta["bytes"]=size;meta["static_version"]="2026-10-08-04"
    report["districts"][did]=changed

manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
manifest.setdefault("notes",{})["impossible_low_height_fix"]="2026-10-08: 2층 이상인데 총높이/층수<1.8m인 비정상 저높이는 용도별 층고×층수로 보정. verified_override 제외."
MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
