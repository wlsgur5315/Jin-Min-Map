#!/usr/bin/env python3
import gzip, json, math, re
from collections import defaultdict
from pathlib import Path
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"
PARCEL=ROOT/"data/parcels"
MANIFEST=ROOT/"data/manifest.json"
REPORT=ROOT/"data/register_split_group_fix_report.json"
SUPPLEMENT={"OSM 정적 보완","Overture 정적 보완"}

def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)

def save_gz(p,obj):
    raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode()
    with gzip.open(p,"wb",compresslevel=9) as f:f.write(raw)
    return p.stat().st_size

def norm(s):
    return re.sub(r"\s+","",str(s or "")).strip()

def prop(p,*names):
    for n in names:
        v=p.get(n)
        if v is not None and str(v).strip()!="":return str(v).strip()
    return ""

def pnu_from_props(p):
    d=re.sub(r"\D","",prop(p,"pnu","PNU","pnu_cd","PNU_CD","pnu_code","PNU_CODE","parcel_pnu","PARCEL_PNU","ld_pnu","LD_PNU","plat_pnu","PLAT_PNU","lot_pnu","LOT_PNU"))
    return d if len(d)==19 else ""

def safe_geom(g):
    if g is None or g.is_empty:return None
    try:
        if not g.is_valid:g=g.buffer(0)
    except Exception:return None
    if g.is_empty:return None
    if g.geom_type=="GeometryCollection":
        ps=[x for x in g.geoms if x.geom_type in ("Polygon","MultiPolygon")]
        if not ps:return None
        g=unary_union(ps)
    return g if g.geom_type in ("Polygon","MultiPolygon") and not g.is_empty else None

def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0

def dist_m(a,b):
    x=(b[0]-a[0])*111320*math.cos(math.radians((a[1]+b[1])/2))
    y=(b[1]-a[1])*110540
    return math.hypot(x,y)

def build_parcel_index(fc):
    geoms=[];props=[]
    for f in fc.get("features",[]):
        try:g=safe_geom(shape(f.get("geometry")))
        except:g=None
        if g is not None:
            geoms.append(g);props.append(f.get("properties") or {})
    return geoms,props,STRtree(geoms) if geoms else None

def best_parcel(g,geoms,props,tree):
    if not tree:return None
    best=None;best_a=0
    for item in tree.query(g):
        try:i=int(item)
        except:i=geoms.index(item)
        try:a=g.intersection(geoms[i]).area
        except:a=0
        if a>best_a:
            best_a=a;best=(props[i],geoms[i])
    return best

def spatial_fill_pnu(features,parcel_fc):
    pgs,pps,ptree=build_parcel_index(parcel_fc)
    changed=0
    for f in features:
        p=f.get("properties") or {}
        if pnu_from_props(p):continue
        if not p.get("register_matched"):continue
        if str(p.get("data_source") or "") not in SUPPLEMENT:continue
        try:g=safe_geom(shape(f.get("geometry")))
        except:g=None
        if g is None:continue
        hit=best_parcel(g,pgs,pps,ptree)
        if not hit:continue
        pp,pg=hit
        try:ov=g.intersection(pg).area/max(g.area,1e-15)
        except:ov=0
        pn=pnu_from_props(pp)
        if not pn or ov<0.55:continue
        p["pnu"]=pn
        jib=prop(pp,"jibun","JIBUN","jibun_addr","lot_no","LOT_NO","plat_plc","PLAT_PLC","지번")
        if jib:p["jibun"]=jib
        legal=prop(pp,"legal_name","bjd_name","BJD_NAM","bjd_nm","BJD_NM","emd_nm","EMD_NM","emd_name","li_name","법정동명")
        if legal:p["legal_name"]=legal
        p["pnu_spatial_corrected"]=True
        changed+=1
    return changed

def is_urgent_fragment(p,ratio):
    try:h=float(p.get("render_height") or p.get("height_m") or 0)
    except:h=0
    try:fl=float(p.get("floors_above") or 0)
    except:fl=0
    score=0
    if ratio<0.10:score+=6
    elif ratio<0.20:score+=5
    elif ratio<0.25:score+=4
    else:score+=3
    if h>=50:score+=4
    elif h>=30:score+=3
    elif h>=15:score+=2
    if fl>=15:score+=3
    elif fl>=8:score+=2
    if p.get("building_name") or p.get("building_dong") or p.get("register_name") or p.get("register_dong"):score+=1
    if p.get("height_source")=="건축물대장 실제 높이":score+=2
    return ratio<0.35 and score>=10

def cluster_indices(rows,max_dist=120):
    left=set(range(len(rows)));clusters=[]
    while left:
        seed=left.pop();cluster=[seed];stack=[seed]
        while stack:
            i=stack.pop();a=rows[i]["pt"]
            near=[j for j in list(left) if dist_m(a,rows[j]["pt"])<=max_dist]
            for j in near:
                left.remove(j);cluster.append(j);stack.append(j)
        clusters.append(cluster)
    return clusters

def merge_groups(features):
    rows=[];groups=defaultdict(list)
    for idx,f in enumerate(features):
        p=f.get("properties") or {}
        if not p.get("register_matched"):continue
        pn=pnu_from_props(p)
        if not pn:continue
        try:g=safe_geom(shape(f.get("geometry")))
        except:g=None
        if g is None:continue
        try:
            h=round(float(p.get("render_height") or p.get("height_m") or 0),1)
            fl=round(float(p.get("floors_above") or 0),1)
            ra=round(float(p.get("register_building_area_m2") or 0),1)
        except:continue
        if ra<=0:continue
        rp=g.representative_point()
        area=metric_area(g)
        ratio=min(area,ra)/max(area,ra) if area>0 and ra>0 else 0
        rec={"idx":idx,"f":f,"p":p,"g":g,"area":area,"pt":(rp.x,rp.y),"ra":ra,"urgent":is_urgent_fragment(p,ratio)}
        rows.append(rec)
        key=(pn,norm(p.get("register_name")),norm(p.get("register_dong")),h,fl,ra)
        groups[key].append(rec)

    replace={};removed=set();stats={"candidate_groups":0,"merged_groups":0,"merged_features":0}
    for key,items in groups.items():
        if len(items)<2:continue
        stats["candidate_groups"]+=1
        for ci in cluster_indices(items,120):
            part=[items[i] for i in ci]
            if len(part)<2 or not any(x["urgent"] for x in part):continue
            ug=safe_geom(unary_union([x["g"] for x in part]))
            if ug is None:continue
            group_area=metric_area(ug);ra=part[0]["ra"]
            ratio=min(group_area,ra)/max(group_area,ra) if group_area>0 and ra>0 else 0
            if ratio<0.35:continue
            part_sorted=sorted(part,key=lambda x:((1 if x["p"].get("building_name") else 0)+(1 if x["p"].get("building_dong") else 0),x["area"]),reverse=True)
            rep=part_sorted[0]
            nf=dict(rep["f"]);np=dict(rep["p"])
            nf["geometry"]=mapping(ug);nf["properties"]=np
            np["register_grouped_parts"]=len(part)
            np["register_group_footprint_area_m2"]=round(group_area,1)
            np["register_group_area_ratio"]=round(ratio,4)
            old=str(np.get("register_match_basis") or "")
            tag="동일 PNU 분할 footprint 그룹 병합"
            np["register_match_basis"]=(old+" · "+tag).strip(" ·") if old else tag
            srcs=sorted({str(x["p"].get("data_source") or "GIS 원본") for x in part})
            np["register_group_sources"]=" / ".join(srcs)
            replace[rep["idx"]]=nf
            for x in part:
                if x["idx"]!=rep["idx"]:removed.add(x["idx"])
            stats["merged_groups"]+=1
            stats["merged_features"]+=len(part)-1

    out=[]
    for i,f in enumerate(features):
        if i in removed:continue
        out.append(replace.get(i,f))
    return out,stats

def main():
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
    total={"pnu_filled":0,"candidate_groups":0,"merged_groups":0,"merged_features":0,"districts":{}}
    for did,meta in manifest.get("buildings",{}).items():
        bp=ROOT/meta["file"];pp=ROOT/manifest["parcels"][did]["file"]
        b=load_gz(bp);p=load_gz(pp)
        before=len(b.get("features",[]))
        filled=spatial_fill_pnu(b["features"],p)
        merged,st=merge_groups(b["features"]);b["features"]=merged
        size=save_gz(bp,b)
        meta.update(count=len(merged),bytes=size,static_precomputed=True,static_version="2026-10-08-01")
        total["pnu_filled"]+=filled
        for k in ("candidate_groups","merged_groups","merged_features"):total[k]+=st[k]
        total["districts"][did]={"name":meta.get("name"),"before":before,"after":len(merged),"pnu_filled":filled,**st}
        print(did,total["districts"][did],flush=True)
    manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
    manifest.setdefault("notes",{})["register_split_group_fix"]="2026-10-08: 동일 PNU·동일 대장 레코드의 120m 이내 분할 footprint를 그룹 면적비>=0.35일 때 병합하고, 보완 데이터의 누락 PNU를 공간 중첩>=55% 기준으로 보완."
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    REPORT.write_text(json.dumps(total,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in total.items() if k!="districts"},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
