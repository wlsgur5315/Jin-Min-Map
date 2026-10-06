#!/usr/bin/env python3
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"data/register_area_mismatch_priority.json"
OUT=ROOT/"data/register_area_mismatch_classified.json"

d=json.loads(SRC.read_text(encoding="utf-8"))
rows=d.get("top_critical",[])
classes={
  "apartment_complex_area":[],
  "supplement_split_polygon":[],
  "tiny_auxiliary_polygon":[],
  "register_area_definition_gap":[],
  "probable_wrong_height_match":[]
}

apt_words=("아파트","타운","주공","센트럴","파크","푸르지오","자이","힐스테이트","아이파크","더샵","엘리시움","한보","현대")
large_words=("백화점","병원","타워","센터","상가","쇼핑","호텔","오피스텔","시장")

def text(r):
    return " ".join(str(r.get(k) or "") for k in ("building_name","building_dong","register_name","register_dong"))

for r in rows:
    if r.get("priority")!="긴급": continue
    t=text(r)
    src=r.get("data_source") or ""
    area=float(r.get("footprint_area_m2") or 0)
    ratio=float(r.get("area_ratio") or 0)
    score=r.get("match_score")
    basis=r.get("match_basis") or ""
    fl=float(r.get("floors_above") or 0)
    h=float(r.get("render_height") or 0)

    # 1. 공동주택은 대장 건축면적이 단지/주건축물 기준으로 잡혀 한 동 footprint와 다를 수 있음
    if any(w in t for w in apt_words) and fl>=8:
        cls="apartment_complex_area"
        reason="고층 공동주택/단지형 건물: 대장 건축면적과 개별 동 footprint 정의 차이 가능"
    # 2. OSM/Overture는 한 건물을 여러 조각으로 나누는 경우
    elif src in ("OSM 정적 보완","Overture 정적 보완"):
        cls="supplement_split_polygon"
        reason=f"{src} 분할/부분 폴리곤 가능성"
    # 3. 아주 작은 GIS 조각은 부속물/파편 가능성
    elif area<120 and ratio<0.10:
        cls="tiny_auxiliary_polygon"
        reason="GIS footprint가 매우 작아 부속물/파편 가능성"
    # 4. 명칭 일치가 강하고 GIS 동명칭 정확 일치면 면적 정의 차이일 가능성
    elif (score is not None and isinstance(score,(int,float)) and score>=85) or "동명칭 정확" in basis or "건물명 정확" in basis:
        cls="register_area_definition_gap"
        reason="식별은 강하지만 면적 정의가 다를 가능성"
    else:
        cls="probable_wrong_height_match"
        reason="강한 식별 근거 없이 고층 대장값이 붙어 실제 오매칭 가능성"

    rr=dict(r)
    rr["classification"]=cls
    rr["classification_reason"]=reason
    classes[cls].append(rr)

summary={k:len(v) for k,v in classes.items()}
report={
  "source_summary":d.get("summary"),
  "classified_summary":summary,
  "classes":{k:v[:150] for k,v in classes.items()}
}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"classified_summary":summary},ensure_ascii=False,indent=2))
