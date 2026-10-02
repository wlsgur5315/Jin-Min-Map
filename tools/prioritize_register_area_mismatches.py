#!/usr/bin/env python3
import gzip, json, math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"
MANIFEST=ROOT/"data/manifest.json"
OUT=ROOT/"data/register_area_mismatch_priority.json"

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
district_names={k:v.get("name") for k,v in manifest.get("buildings",{}).items()}

def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0

rows=[]
from shapely.geometry import shape

for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        fc=json.load(f)
    for idx,feat in enumerate(fc.get("features",[])):
        p=feat.get("properties") or {}
        if not p.get("register_matched"):
            continue
        try:g=shape(feat["geometry"])
        except:continue
        if g.is_empty: continue
        footprint=metric_area(g)
        try:ra=float(p.get("register_building_area_m2") or 0)
        except:ra=0
        if footprint<=0 or ra<=0:
            continue
        ratio=min(footprint,ra)/max(footprint,ra)
        if ratio>=0.35:
            continue
        try:h=float(p.get("render_height") or p.get("height_m") or 0)
        except:h=0
        try:fl=float(p.get("floors_above") or 0)
        except:fl=0

        # 우선순위: 면적 불일치가 심하고, 실제 3D 영향이 큰 고층/대형 건물을 먼저 본다.
        risk_score=0
        reasons=[]
        if ratio<0.10:
            risk_score+=6; reasons.append("면적비<0.10")
        elif ratio<0.20:
            risk_score+=5; reasons.append("면적비<0.20")
        elif ratio<0.25:
            risk_score+=4; reasons.append("면적비<0.25")
        else:
            risk_score+=3; reasons.append("면적비<0.35")

        if h>=50:
            risk_score+=4; reasons.append("높이>=50m")
        elif h>=30:
            risk_score+=3; reasons.append("높이>=30m")
        elif h>=15:
            risk_score+=2; reasons.append("높이>=15m")

        if fl>=15:
            risk_score+=3; reasons.append("15층이상")
        elif fl>=8:
            risk_score+=2; reasons.append("8층이상")

        if p.get("building_name") or p.get("building_dong") or p.get("register_name") or p.get("register_dong"):
            risk_score+=1; reasons.append("식별명칭있음")

        if p.get("height_source")=="건축물대장 실제 높이":
            risk_score+=2; reasons.append("대장실제높이사용")

        if risk_score>=10:
            priority="긴급"
        elif risk_score>=7:
            priority="높음"
        else:
            priority="검토"

        rp=g.representative_point()
        rows.append({
            "priority":priority,
            "risk_score":risk_score,
            "reasons":reasons,
            "district_id":did,
            "district_name":district_names.get(did),
            "index":idx,
            "centroid":[round(rp.x,7),round(rp.y,7)],
            "building_uid":p.get("building_uid"),
            "pnu":p.get("pnu"),
            "jibun":p.get("jibun"),
            "building_name":p.get("building_name"),
            "building_dong":p.get("building_dong"),
            "register_name":p.get("register_name"),
            "register_dong":p.get("register_dong"),
            "render_height":h,
            "floors_above":fl,
            "footprint_area_m2":round(footprint,1),
            "register_building_area_m2":ra,
            "area_ratio":round(ratio,4),
            "height_source":p.get("height_source"),
            "match_score":p.get("register_match_score"),
            "match_margin":p.get("register_match_margin"),
            "match_basis":p.get("register_match_basis"),
            "data_source":p.get("data_source"),
            "pnu_spatial_corrected":p.get("pnu_spatial_corrected")
        })

rows.sort(key=lambda x:(-x["risk_score"], x["area_ratio"], -(x["render_height"] or 0)))
summary={"total":len(rows),"긴급":0,"높음":0,"검토":0}
for r in rows: summary[r["priority"]]+=1

report={
    "summary":summary,
    "criteria":{
        "source":"건축물대장 매칭 + footprint 면적비<0.35",
        "priority":"면적비, 높이, 층수, 식별명칭, 실제대장높이 사용 여부를 합산"
    },
    "top_critical":rows[:300],
    "all_count":len(rows)
}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"summary":summary,"top20":rows[:20]},ensure_ascii=False,indent=2))
