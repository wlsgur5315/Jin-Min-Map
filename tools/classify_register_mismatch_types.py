#!/usr/bin/env python3
import gzip, json, math, re
from collections import Counter, defaultdict
from pathlib import Path
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"
MANIFEST=ROOT/"data/manifest.json"
OUT=ROOT/"data/register_mismatch_type_analysis.json"

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
district_names={k:v.get("name") for k,v in manifest.get("buildings",{}).items()}

def norm(s):
    return re.sub(r"\s+","",str(s or "")).strip()

def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0

def dist_m(a,b):
    if not a or not b:return 999999
    lon1,lat1=a; lon2,lat2=b
    x=(lon2-lon1)*111320*math.cos(math.radians((lat1+lat2)/2))
    y=(lat2-lat1)*110540
    return math.hypot(x,y)

def risk_score(p,ratio,h,fl):
    s=0
    if ratio<0.10:s+=6
    elif ratio<0.20:s+=5
    elif ratio<0.25:s+=4
    else:s+=3
    if h>=50:s+=4
    elif h>=30:s+=3
    elif h>=15:s+=2
    if fl>=15:s+=3
    elif fl>=8:s+=2
    if p.get("building_name") or p.get("building_dong") or p.get("register_name") or p.get("register_dong"):s+=1
    if p.get("height_source")=="건축물대장 실제 높이":s+=2
    return s

all_rows=[]
urgent=[]
by_sig=defaultdict(list)

for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        fc=json.load(f)
    for idx,feat in enumerate(fc.get("features",[])):
        p=feat.get("properties") or {}
        if not p.get("register_matched"):continue
        try:g=shape(feat["geometry"])
        except:continue
        if g.is_empty:continue
        footprint=metric_area(g)
        try:ra=float(p.get("register_building_area_m2") or 0)
        except:ra=0
        if footprint<=0 or ra<=0:continue
        ratio=min(footprint,ra)/max(footprint,ra)
        try:h=float(p.get("render_height") or p.get("height_m") or 0)
        except:h=0
        try:fl=float(p.get("floors_above") or 0)
        except:fl=0
        pt=g.representative_point()
        row={
            "district_id":did,"district_name":district_names.get(did),"index":idx,
            "centroid":[round(pt.x,7),round(pt.y,7)],
            "building_uid":p.get("building_uid"),"pnu":p.get("pnu"),"jibun":p.get("jibun"),
            "building_name":p.get("building_name"),"building_dong":p.get("building_dong"),
            "register_name":p.get("register_name"),"register_dong":p.get("register_dong"),
            "render_height":h,"floors_above":fl,"footprint_area_m2":round(footprint,1),
            "register_building_area_m2":ra,"area_ratio":round(ratio,4),
            "height_source":p.get("height_source"),"match_score":p.get("register_match_score"),
            "match_margin":p.get("register_match_margin"),"match_basis":p.get("register_match_basis"),
            "data_source":p.get("data_source"),"pnu_spatial_corrected":p.get("pnu_spatial_corrected")
        }
        sig=(did,norm(p.get("register_name")),norm(p.get("register_dong")),round(h,1),round(fl,1),round(ra,1))
        row["_sig"]=sig
        all_rows.append(row);by_sig[sig].append(row)
        if ratio<0.35 and risk_score(p,ratio,h,fl)>=10:urgent.append(row)

type_counts=Counter()
examples=defaultdict(list)
details=[]

for r in urgent:
    peers=[x for x in by_sig[r["_sig"]] if dist_m(r["centroid"],x["centroid"])<=120]
    group_area=sum(x["footprint_area_m2"] for x in peers)
    ra=r["register_building_area_m2"]
    group_ratio=min(group_area,ra)/max(group_area,ra) if group_area>0 and ra>0 else 0
    supplement=str(r.get("data_source") or "") in {"OSM 정적 보완","Overture 정적 보완"}
    no_pnu=not str(r.get("pnu") or "").strip()
    basis=str(r.get("match_basis") or "")
    score=r.get("match_score")
    try:score=float(score)
    except:score=None
    exact=("정확 일치" in basis)
    very_small=r["area_ratio"]<0.10

    if supplement and no_pnu and len(peers)>=2 and group_ratio>=0.35:
        typ="PNU없는 보완데이터 분할·대장값 복제"
    elif len(peers)>=2 and group_ratio>=0.35:
        typ="분할 footprint 그룹에 동일 대장값 복제"
    elif very_small and exact:
        typ="작은 부속동·파편에 동전체 대장값 적용"
    elif ("PNU/주소 후보" in basis) or (score is not None and score<3):
        typ="약한 PNU·주소 후보 오매칭"
    elif supplement and no_pnu:
        typ="PNU없는 보완데이터 단일 오매칭"
    else:
        typ="기타 심한 면적 불일치"

    type_counts[typ]+=1
    item={k:v for k,v in r.items() if k!="_sig"}
    item.update({"type":typ,"near_same_register_count":len(peers),"group_footprint_area_m2":round(group_area,1),"group_area_ratio":round(group_ratio,4)})
    details.append(item)
    if len(examples[typ])<12:examples[typ].append(item)

details.sort(key=lambda x:(x["type"],x["area_ratio"],-(x["render_height"] or 0)))
report={
    "summary":{
        "urgent_total":len(urgent),
        "type_counts":dict(type_counts.most_common()),
        "classified_total":sum(type_counts.values())
    },
    "method":{
        "urgent_rule":"기존 priority와 동일한 risk_score>=10 및 area_ratio<0.35",
        "group_rule":"같은 district + register_name/dong + height/floors + register area, 120m 이내",
        "group_fix_signal":"주변 동일대장 polygon 합계 면적비가 0.35 이상이면 분할/복제 가능성이 높음"
    },
    "examples":dict(examples),
    "all_urgent":details
}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report["summary"],ensure_ascii=False,indent=2))
