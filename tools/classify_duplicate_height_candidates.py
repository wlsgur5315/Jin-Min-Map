#!/usr/bin/env python3
import gzip,json,math,re
from collections import defaultdict
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"
OUT=ROOT/"data/duplicate_height_candidate_classification.json"

def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
def safe_geom(g):
    try:
        if not g.is_valid:g=g.buffer(0)
    except:return None
    return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def area_m2(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat)
def pt(g):
    p=g.representative_point();return (p.x,p.y)
def dist_m(a,b):
    x=(b[0]-a[0])*111320*math.cos(math.radians((a[1]+b[1])/2))
    y=(b[1]-a[1])*110540
    return math.hypot(x,y)
def norm(s):return re.sub(r"\s+","",str(s or "")).strip()
def num(v):
    try:return float(v)
    except:return 0.0
def pnu(p):
    d=re.sub(r"\D","",str(p.get("pnu") or ""))
    return d if len(d)==19 else ""
def ident(p):
    return (
        pnu(p),
        norm(p.get("building_uid")),
        norm(p.get("building_name") or p.get("register_name")),
        norm(p.get("building_dong") or p.get("register_dong"))
    )
def confidence_rank(p):
    c=str(p.get("height_confidence") or "")
    return {"높음":3,"보통":2,"낮음":1}.get(c,0)
def richness(p):
    ks=("building_uid","pnu","building_name","building_dong","register_name","register_dong","register_matched","height_source","use_name")
    return sum(1 for k in ks if p.get(k) not in (None,"",False))+confidence_rank(p)

safe_dups=[];review_dups=[];height={"likely_normal":[],"suspicious":[]}
summary={"near_exact_pairs":0,"safe_duplicate_pairs":0,"review_duplicate_pairs":0,"height_likely_normal":0,"height_suspicious":0}

for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    fc=load_gz(path);rows=[];geoms=[]
    for i,f in enumerate(fc.get("features",[])):
        g=safe_geom(shape(f.get("geometry")))
        if g is None:continue
        p=f.get("properties") or {}
        rows.append({"i":i,"g":g,"p":p,"a":area_m2(g),"c":pt(g)})
        geoms.append(g)
    tree=STRtree(geoms) if geoms else None
    seen=set()
    for i,r in enumerate(rows):
        if not tree:break
        for item in tree.query(r["g"]):
            try:j=int(item)
            except:j=geoms.index(item)
            if j<=i:continue
            s=rows[j]
            if dist_m(r["c"],s["c"])>4:continue
            ar=min(r["a"],s["a"])/max(r["a"],s["a"]) if r["a"] and s["a"] else 0
            if ar<.98:continue
            try:ov=r["g"].intersection(s["g"]).area/min(r["g"].area,s["g"].area)
            except:ov=0
            if ov<.985:continue
            summary["near_exact_pairs"]+=1
            pa,pb=r["p"],s["p"]; ia,ib=ident(pa),ident(pb)
            same_pnu=bool(ia[0] and ia[0]==ib[0])
            same_uid=bool(ia[1] and ia[1]==ib[1])
            same_named=bool(ia[2] and ia[2]==ib[2] and ia[3] and ia[3]==ib[3])
            ha=num(pa.get("render_height") or pa.get("height_m")); hb=num(pb.get("render_height") or pb.get("height_m"))
            height_close=(ha<=0 or hb<=0 or abs(ha-hb)<=1.5)
            item={"district_id":did,"a_index":r["i"],"b_index":s["i"],
                  "overlap_ratio":round(ov,4),"area_ratio":round(ar,4),
                  "a_pnu":ia[0],"b_pnu":ib[0],"a_uid":ia[1],"b_uid":ib[1],
                  "a_name":ia[2],"b_name":ib[2],"a_dong":ia[3],"b_dong":ib[3],
                  "a_height":ha,"b_height":hb,
                  "a_source":pa.get("data_source") or "GIS","b_source":pb.get("data_source") or "GIS",
                  "a_richness":richness(pa),"b_richness":richness(pb),
                  "centroid":[round(r["c"][0],7),round(r["c"][1],7)]}
            if height_close and (same_uid or same_named or (same_pnu and ia[3] and ia[3]==ib[3])):
                summary["safe_duplicate_pairs"]+=1;safe_dups.append(item)
            else:
                summary["review_duplicate_pairs"]+=1;review_dups.append(item)

    for r in rows:
        p=r["p"]; h=num(p.get("render_height") or p.get("height_m")); fl=num(p.get("floors_above")); a=r["a"]
        if h<=0:continue
        use=str(p.get("use_name") or p.get("register_use") or p.get("building") or "")
        reasons=[]
        if h>180:reasons.append("height>180m")
        if fl>0 and h/fl>8:reasons.append("층당높이>8m")
        if fl>0 and h/fl<1.8:reasons.append("층당높이<1.8m")
        if h>=45 and a<80:reasons.append("작은 footprint 고층")
        if not reasons:continue
        industrial=bool(re.search("공장|창고|산업|industrial|warehouse|factory",use,re.I))
        hall_like=bool(re.search("체육|강당|집회|문화|공연|전시장|gym|hall|arena",use,re.I))
        lowrise_tall=(fl<=1 and h<=15 and (industrial or hall_like or a>=700))
        likely=lowrise_tall and reasons==["층당높이>8m"]
        item={"district_id":did,"index":r["i"],"name":p.get("building_name") or p.get("register_name"),
              "dong":p.get("building_dong") or p.get("register_dong"),"use":use,
              "height":h,"floors":fl,"area_m2":round(a,1),"reasons":reasons,
              "height_source":p.get("height_source"),"confidence":p.get("height_confidence"),
              "centroid":[round(r["c"][0],7),round(r["c"][1],7)]}
        if likely:
            summary["height_likely_normal"]+=1
            if len(height["likely_normal"])<100:height["likely_normal"].append(item)
        else:
            summary["height_suspicious"]+=1
            if len(height["suspicious"])<150:height["suspicious"].append(item)

OUT.write_text(json.dumps({"summary":summary,"safe_duplicates":safe_dups,"review_duplicates":review_dups,"height":height},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
