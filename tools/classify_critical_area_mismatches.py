#!/usr/bin/env python3
import gzip,json,math
from pathlib import Path
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"
MANIFEST=ROOT/"data/manifest.json"
OUT=ROOT/"data/register_area_mismatch_classified.json"

manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
district_names={k:v.get("name") for k,v in manifest.get("buildings",{}).items()}

apt_words=("아파트","타운","주공","센트럴","파크","푸르지오","자이","힐스테이트","아이파크","더샵","엘리시움","한보","현대")
def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0
def txt(p):
    return " ".join(str(p.get(k) or "") for k in ("building_name","building_dong","register_name","register_dong"))

classes={k:[] for k in (
  "apartment_complex_area","supplement_split_polygon","tiny_auxiliary_polygon",
  "register_area_definition_gap","probable_wrong_height_match"
)}

for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    with gzip.open(path,"rt",encoding="utf-8") as f: fc=json.load(f)
    for idx,feat in enumerate(fc.get("features",[])):
        p=feat.get("properties") or {}
        if not p.get("register_matched"): continue
        try:g=shape(feat["geometry"])
        except:continue
        if g.is_empty: continue
        footprint=metric_area(g)
        try:ra=float(p.get("register_building_area_m2") or 0)
        except:ra=0
        if footprint<=0 or ra<=0: continue
        ratio=min(footprint,ra)/max(footprint,ra)
        if ratio>=0.35: continue
        try:h=float(p.get("render_height") or p.get("height_m") or 0); fl=float(p.get("floors_above") or 0)
        except:h=0;fl=0
        risk=0
        if ratio<.10:risk+=6
        elif ratio<.20:risk+=5
        elif ratio<.25:risk+=4
        else:risk+=3
        if h>=50:risk+=4
        elif h>=30:risk+=3
        elif h>=15:risk+=2
        if fl>=15:risk+=3
        elif fl>=8:risk+=2
        if any(p.get(k) for k in ("building_name","building_dong","register_name","register_dong")): risk+=1
        if p.get("height_source")=="건축물대장 실제 높이": risk+=2
        if risk<10: continue

        t=txt(p); src=p.get("data_source") or ""; score=p.get("register_match_score"); basis=p.get("register_match_basis") or ""
        if any(w in t for w in apt_words) and fl>=8:
            cls="apartment_complex_area"; reason="고층 공동주택/단지형 건물: 개별 동 footprint와 대장 면적 정의 차이 가능"
        elif src in ("OSM 정적 보완","Overture 정적 보완"):
            cls="supplement_split_polygon"; reason=f"{src} 분할/부분 폴리곤 가능성"
        elif footprint<120 and ratio<.10:
            cls="tiny_auxiliary_polygon"; reason="GIS footprint가 매우 작아 부속물/파편 가능성"
        elif (isinstance(score,(int,float)) and score>=85) or "동명칭 정확" in basis or "건물명 정확" in basis:
            cls="register_area_definition_gap"; reason="식별은 강하지만 면적 정의가 다른 사례 가능성"
        else:
            cls="probable_wrong_height_match"; reason="강한 식별 근거 없이 고층 대장값이 붙어 실제 오매칭 가능성"

        rp=g.representative_point()
        rec={
          "classification":cls,"classification_reason":reason,"risk_score":risk,
          "district_id":did,"district_name":district_names.get(did),"index":idx,
          "centroid":[round(rp.x,7),round(rp.y,7)],"building_uid":p.get("building_uid"),
          "pnu":p.get("pnu"),"jibun":p.get("jibun"),
          "building_name":p.get("building_name"),"building_dong":p.get("building_dong"),
          "register_name":p.get("register_name"),"register_dong":p.get("register_dong"),
          "render_height":h,"floors_above":fl,"footprint_area_m2":round(footprint,1),
          "register_building_area_m2":ra,"area_ratio":round(ratio,4),
          "height_source":p.get("height_source"),"match_score":score,
          "match_margin":p.get("register_match_margin"),"match_basis":basis,"data_source":src
        }
        classes[cls].append(rec)

for v in classes.values(): v.sort(key=lambda x:(-x["risk_score"],x["area_ratio"]))
summary={k:len(v) for k,v in classes.items()}
OUT.write_text(json.dumps({
  "classified_total":sum(summary.values()),
  "classified_summary":summary,
  "classes":classes
},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"classified_total":sum(summary.values()),"classified_summary":summary},ensure_ascii=False,indent=2))
