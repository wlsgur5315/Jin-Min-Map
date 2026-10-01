#!/usr/bin/env python3
import argparse, gzip, json, math, re, subprocess, tempfile, time
from pathlib import Path
import requests
from shapely.geometry import shape, mapping, Polygon, LineString
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree
ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/"data/jinju_districts.geojson"; REGIDX=ROOT/"data/register/index.json"; MANIFEST=ROOT/"data/manifest.json"; REPORT=ROOT/"data/static_build_report_all.json"
SUPPLEMENT_SOURCES={"OSM 정적 보완","Overture 정적 보완"}
def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
def save_gz(p,obj):
    raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode()
    with gzip.open(p,"wb",compresslevel=9) as f:f.write(raw)
    return p.stat().st_size
def prop(p,*names):
    for n in names:
        v=p.get(n)
        if v is not None and str(v).strip()!="":return str(v).strip()
    return ""
def norm(s):return re.sub(r"\s+|번지$","",str(s or "")).strip()
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
    if g.geom_type not in ("Polygon","MultiPolygon") or g.area<=1e-11:return None
    minx,miny,maxx,maxy=g.bounds
    if min(maxx-minx,maxy-miny)<0.000003:return None
    return g
def floor_h(use):
    s=str(use or "")
    # 실제 높이가 없는 경우에만 사용하는 용도별 보수적 층고값.
    if re.search("공동주택|아파트|연립|다세대|다가구",s):return 2.9
    if re.search("단독주택",s):return 3.1
    if re.search("교육|학교|연구",s):return 3.8
    if re.search("의료|병원",s):return 4.0
    if re.search("업무|사무",s):return 3.7
    if re.search("근린생활|판매|상업",s):return 4.0
    if re.search("문화|집회|체육|운동",s):return 4.5
    if re.search("공장|창고|산업",s):return 5.0
    return 3.3
def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0
def pnu_from_props(p):
    d=re.sub(r"\D","",prop(p,"pnu","PNU","pnu_cd","PNU_CD","pnu_code","PNU_CODE","parcel_pnu","PARCEL_PNU","ld_pnu","LD_PNU","plat_pnu","PLAT_PNU","lot_pnu","LOT_PNU"))
    return d if len(d)==19 else ""
def clear_previous_register_enrichment(p):
    """이전 정적 빌드에서 붙은 대장값이 다음 매칭을 자기강화하지 않도록 제거한다."""
    q=dict(p or {})
    src=str(q.get("height_source") or "")
    if q.get("register_matched") or "건축물대장" in src or "비정상 높이 제외" in src:
        for k in (
            "render_height","render_base","render_top","height_m",
            "floors_above","floors_below",
            "register_matched","register_name","register_dong","register_use",
            "register_building_area_m2","register_match_score",
            "register_match_margin","register_match_basis"
        ):
            q.pop(k,None)
        q.pop("height_confidence",None)
        q.pop("height_source",None)
    return q
def pnu_variants(pnu):
    if not pnu or len(pnu)!=19:return[]
    out=[pnu];land=pnu[10]
    if land=="1":out.append(pnu[:10]+"0"+pnu[11:])
    elif land=="2":out.append(pnu[:10]+"1"+pnu[11:])
    elif land=="0":out.append(pnu[:10]+"1"+pnu[11:])
    return list(dict.fromkeys(out))
def load_register_all():
    idx=json.loads(REGIDX.read_text(encoding="utf-8"));by_pnu={};by_loc={}
    for rel in idx.get("shards",[]):
        part=json.loads((ROOT/rel).read_text(encoding="utf-8"))
        for r in part.get("records",[]):
            if len(r)<11:continue
            by_pnu.setdefault(str(r[0]),[]).append(r)
            by_loc.setdefault(norm(r[1]),[]).append(r)
            by_loc.setdefault(norm(r[2]),[]).append(r)
    return by_pnu,by_loc
def choose_reg(cands,props,area_m2):
    """다중동 필지에서는 footprint 면적을 최우선으로 사용해 잘못된 동 매칭을 줄인다."""
    if not cands:return None
    name=norm(prop(props,"building_name","name","BLD_NM","bld_nm"))
    dong=norm(prop(props,"building_dong","dong_name","dong","동명칭"))
    use=norm(prop(props,"use_name","main_use_name","building","class"))
    try:floors=float(prop(props,"floors_above","levels","building:levels") or 0)
    except:floors=0
    many=len(cands)>=5

    ranked=[]
    for r in cands:
        try:
            h=float(r[3] or 0);fl=float(r[4] or 0);ra=float(r[9] or 0)
        except:continue
        rn=norm(r[6]);rd=norm(r[7]);ru=norm(r[8])
        sc=0.0;strong=0;why=[];area_ratio=0.0

        if name and rn:
            if name==rn:sc+=24;strong+=3;why.append("건물명 정확")
            elif name in rn or rn in name:sc+=15;strong+=2;why.append("건물명 유사")
        if dong and rd:
            if dong==rd:sc+=28;strong+=3;why.append("동명칭 정확")
            elif dong in rd or rd in dong:sc+=17;strong+=2;why.append("동명칭 유사")

        if area_m2>0 and ra>0:
            area_ratio=min(area_m2,ra)/max(area_m2,ra)
            if many:
                # 대학·병원·공장처럼 한 필지에 많은 동이 있는 경우 면적이 가장 안정적인 구분 단서
                if area_ratio>=.93:sc+=30;strong+=2;why.append("면적 거의일치")
                elif area_ratio>=.85:sc+=25;strong+=1;why.append("면적 매우유사")
                elif area_ratio>=.72:sc+=18;why.append("면적 유사")
                elif area_ratio>=.55:sc+=10
                elif area_ratio>=.35:sc+=3
                else:sc-=8
            else:
                if area_ratio>=.85:sc+=12;strong+=1;why.append("면적 매우유사")
                elif area_ratio>=.65:sc+=8;why.append("면적 유사")
                elif area_ratio>=.45:sc+=4
                elif area_ratio>=.25:sc+=1
                else:sc-=3

        if use and ru:
            if use==ru:sc+=3
            elif use in ru or ru in use:sc+=2

        if floors>0 and fl>0:
            df=abs(floors-fl)
            # 다중동 필지에서는 원 GIS 층수 자체가 틀릴 수 있으므로 보조 단서로만 사용
            if many:
                if df<0.1:sc+=2
                elif df<=1:sc+=1
                elif df>=6:sc-=1
            else:
                if df<0.1:sc+=7;strong+=1;why.append("층수 일치")
                elif df<=1:sc+=4
                elif df<=2:sc+=1.5
                elif df>=5:sc-=3

        if h>0:sc+=1
        if fl>0:sc+=.5
        ranked.append((sc,strong,area_ratio,r,why))

    if not ranked:return None
    ranked.sort(key=lambda x:x[0],reverse=True)
    bs,bstrong,bratio,best,why=ranked[0]
    second=ranked[1][0] if len(ranked)>1 else -999
    margin=bs-second

    if len(ranked)==1:
        if bs<0:return None
    else:
        if many and bstrong==0 and bratio<.55:return None
        if bs<5:return None
        if margin<1.5 and bstrong<2:return None
        if margin<.75 and bstrong<3:return None

    props["register_match_score"]=round(bs,2)
    props["register_match_margin"]=round(margin,2) if len(ranked)>1 else None
    props["register_match_area_ratio"]=round(bratio,4) if bratio else None
    props["register_match_basis"]=" · ".join(why[:4]) if why else "PNU/주소 후보"
    return best
def register_candidates(props,parcel_props,by_pnu,by_loc):
    out=[]
    for p in (props,parcel_props or {}):
        for pv in pnu_variants(pnu_from_props(p)):out+=by_pnu.get(pv,[])
        legal=prop(p,"legal_name","bjd_name","BJD_NAM","bjd_nm","BJD_NM","emd_nm","EMD_NM","emd_name","li_name","법정동명")
        jib=prop(p,"jibun","JIBUN","jibun_addr","lot_no","LOT_NO","plat_plc","PLAT_PLC","지번")
        if legal and jib:
            out+=by_loc.get(norm(legal+jib),[])
            out+=by_loc.get(norm(legal.split()[-1]+jib),[])
    seen=set();u=[]
    for r in out:
        k=tuple(r[:9])
        if k not in seen:seen.add(k);u.append(r)
    return u
def build_index(fc):
    gs=[];ps=[]
    for f in fc.get("features",[]):
        try:g=safe_geom(shape(f["geometry"]))
        except:g=None
        if g is not None:gs.append(g);ps.append(f.get("properties",{}))
    return gs,ps,STRtree(gs) if gs else None
def parcel_for(g,gs,ps,tree):
    if not tree:return None
    best=None;ba=0
    for item in tree.query(g):
        try:i=int(item)
        except:i=gs.index(item)
        try:a=g.intersection(gs[i]).area
        except:a=0
        if a>ba:ba=a;best=(ps[i],gs[i])
    return best
def apply_height(props,g,reg=None,source="GIS"):
    area=metric_area(g)
    if reg:
        h=float(reg[3] or 0);fl=int(float(reg[4] or 0));use=reg[8] or prop(props,"use_name");bad=h>200 or (fl>0 and h/fl>8)
        if h>0 and not bad:
            props.update(
                render_height=round(h,3),height_m=round(h,3),
                floors_above=fl or props.get("floors_above",0),
                floors_below=int(float(reg[5] or 0)),
                register_name=reg[6] or "",register_dong=reg[7] or "",
                register_use=reg[8] or "",register_building_area_m2=reg[9] or 0,
                height_source="건축물대장 실제 높이",height_confidence="높음",
                register_matched=True
            );return
        if fl>0:
            est=fl*floor_h(use)
            props.update(
                render_height=round(est,3),height_m=round(est,3),floors_above=fl,
                floors_below=int(float(reg[5] or 0)),
                register_name=reg[6] or "",register_dong=reg[7] or "",
                register_use=reg[8] or "",register_building_area_m2=reg[9] or 0,
                height_source=(f"건축물대장 이상높이 제외 · {fl}층 기반" if bad else f"건축물대장 {fl}층 기반"),
                height_confidence="보통",register_matched=True
            );return
    try:h=float(prop(props,"height_m","height","render_height") or 0)
    except:h=0
    try:fl=float(prop(props,"floors_above","levels","building:levels") or 0)
    except:fl=0
    use=prop(props,"use_name","building","class")
    if h>1 and h<=200 and not(fl>0 and h/fl>8):props.update(render_height=round(h,3),height_source=f"{source} 기재 높이",height_confidence="높음" if source=="GIS" else "보통")
    elif fl>0:props.update(render_height=round(fl*floor_h(use),3),floors_above=int(fl),height_source=f"{source} {int(fl)}층 기반",height_confidence="보통")
    else:
        if re.search("apart|residential|공동주택|아파트",use,re.I):n=12 if area>800 else 6 if area>300 else 3;h=n*2.9
        elif re.search("retail|commercial|mall|판매|근린",use,re.I):n=5 if area>2500 else 3 if area>700 else 2;h=n*3.6
        elif re.search("school|education|교육|학교",use,re.I):n=4 if area>1500 else 3;h=n*3.6
        elif re.search("industrial|warehouse|factory|공장|창고",use,re.I):n=1;h=10 if area>1500 else 7
        else:n=3 if area>500 else 2 if area>120 else 1;h=n*3.2
        props.update(render_height=round(h,3),floors_above=props.get("floors_above") or n,height_source="용도·면적 기반 추정",height_confidence="낮음")
def fetch_osm(dg):
    minx,miny,maxx,maxy=dg.bounds;q=f'[out:json][timeout:180];(way["building"]({miny},{minx},{maxy},{maxx});relation["building"]({miny},{minx},{maxy},{maxx}););out geom tags;'
    eps=("https://overpass.private.coffee/api/interpreter","https://overpass.nchc.org.tw/api/interpreter","https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter")
    headers={"User-Agent":"Jin-Min-Map static dataset builder/2.0"};last=None
    for attempt in range(3):
        for ep in eps:
            try:
                r=requests.get(ep,params={"data":q},headers=headers,timeout=180)
                if r.status_code in (429,502,503,504):last=RuntimeError(f"{ep}: HTTP {r.status_code}");time.sleep(3+attempt*4);continue
                r.raise_for_status();data=r.json()
                if data.get("elements") is not None:return data
            except Exception as e:last=e;time.sleep(3+attempt*4)
    print("OSM fetch failed:",last);return{"elements":[]}
def fetch_overture(dg,did):
    minx,miny,maxx,maxy=dg.bounds;out=Path(tempfile.gettempdir())/f"{did}_overture.geojson"
    if out.exists():out.unlink()
    try:
        subprocess.run(["overturemaps","download",f"--bbox={minx},{miny},{maxx},{maxy}","-f","geojson","--type=building","-o",str(out)],check=True,timeout=300,stdout=subprocess.DEVNULL)
        return json.loads(out.read_text(encoding="utf-8"))
    except Exception as e:print("Overture fetch failed:",did,e);return{"features":[]}
def osm_geom(el):
    if el.get("type")=="way":
        pts=[(x["lon"],x["lat"]) for x in el.get("geometry",[]) if "lon" in x]
        if len(pts)>=4:
            if pts[0]!=pts[-1]:pts.append(pts[0])
            return safe_geom(Polygon(pts))
    if el.get("type")=="relation":
        lines=[]
        for m in el.get("members",[]):
            if m.get("role") not in ("outer",""):continue
            pts=[(x["lon"],x["lat"]) for x in m.get("geometry",[]) if "lon" in x]
            if len(pts)>=2:lines.append(LineString(pts))
        if lines:
            ps=list(polygonize(unary_union(lines)))
            if ps:return safe_geom(unary_union(ps))
    return None
def overture_props(p):
    q={"overture_id":p.get("id") or p.get("@id"),"data_source":"Overture 정적 보완"}
    if isinstance(p.get("height"),(int,float)):q["height_m"]=p["height"]
    nf=p.get("num_floors") or p.get("numFloors")
    if isinstance(nf,(int,float)):q["floors_above"]=nf
    cls=p.get("class") or p.get("subtype")
    if cls:q["use_name"]=str(cls)
    names=p.get("names")
    if isinstance(names,dict) and isinstance(names.get("primary"),str):q["building_name"]=names["primary"]
    return q
def duplicate_ratio(g,geoms,tree,threshold):
    if not tree:return False
    ga=max(g.area,1e-15)
    for item in tree.query(g):
        try:i=int(item)
        except:i=geoms.index(item)
        try:ov=g.intersection(geoms[i]).area/ga
        except:ov=0
        if ov>=threshold:return True
    return False
def build_one(did,dname,dg,manifest,by_pnu,by_loc):
    bp=ROOT/manifest["buildings"][did]["file"];ppath=ROOT/manifest["parcels"][did]["file"]
    gis=load_gz(bp);parcels=load_gz(ppath);pg,pps,ptree=build_index(parcels)
    base=[f for f in gis.get("features",[]) if str((f.get("properties") or {}).get("data_source") or "") not in SUPPLEMENT_SOURCES]
    out=[];gg=[];stats={"name":dname,"gis_input":len(base),"gis_valid":0,"osm_raw":0,"osm_added":0,"osm_duplicate":0,"overture_raw":0,"overture_added":0,"overture_duplicate":0,"register_matched":0,"estimated":0}
    for f in base:
        try:g=safe_geom(shape(f["geometry"]))
        except:g=None
        if g is None or not g.intersects(dg):continue
        p=clear_previous_register_enrichment(f.get("properties",{}));ph=parcel_for(g,pg,pps,ptree);reg=choose_reg(register_candidates(p,ph[0] if ph else None,by_pnu,by_loc),p,metric_area(g));apply_height(p,g,reg,"GIS")
        if reg:stats["register_matched"]+=1
        if p.get("height_confidence")=="낮음":stats["estimated"]+=1
        out.append({"type":"Feature","geometry":mapping(g),"properties":p});gg.append(g)
    stats["gis_valid"]=len(out);gtree=STRtree(gg) if gg else None
    osm=fetch_osm(dg);stats["osm_raw"]=len(osm.get("elements",[]))
    for el in osm.get("elements",[]):
        g=osm_geom(el)
        if g is None or not dg.contains(g.representative_point()):continue
        if duplicate_ratio(g,gg,gtree,.25):stats["osm_duplicate"]+=1;continue
        p=dict(el.get("tags",{}));p.update(data_source="OSM 정적 보완",osm_id=f'{el.get("type")}/{el.get("id")}')
        ph=parcel_for(g,pg,pps,ptree);reg=choose_reg(register_candidates(p,ph[0] if ph else None,by_pnu,by_loc),p,metric_area(g));apply_height(p,g,reg,"OSM")
        if reg:stats["register_matched"]+=1
        if p.get("height_confidence")=="낮음":stats["estimated"]+=1
        out.append({"type":"Feature","geometry":mapping(g),"properties":p});gg.append(g);stats["osm_added"]+=1
    gtree=STRtree(gg) if gg else None;ovt=fetch_overture(dg,did);stats["overture_raw"]=len(ovt.get("features",[]));accepted=[]
    for f in ovt.get("features",[]):
        try:g=safe_geom(shape(f.get("geometry")))
        except:g=None
        if g is None or not dg.contains(g.representative_point()):continue
        if duplicate_ratio(g,gg,gtree,.22):stats["overture_duplicate"]+=1;continue
        isdup=False;ga=max(g.area,1e-15)
        for ag in accepted[-500:]:
            try:
                if g.intersection(ag).area/ga>=.22:isdup=True;break
            except:pass
        if isdup:stats["overture_duplicate"]+=1;continue
        p=overture_props(f.get("properties") or {});ph=parcel_for(g,pg,pps,ptree);reg=choose_reg(register_candidates(p,ph[0] if ph else None,by_pnu,by_loc),p,metric_area(g));apply_height(p,g,reg,"Overture")
        if reg:stats["register_matched"]+=1
        if p.get("height_confidence")=="낮음":stats["estimated"]+=1
        out.append({"type":"Feature","geometry":mapping(g),"properties":p});accepted.append(g);stats["overture_added"]+=1
    size=save_gz(bp,{"type":"FeatureCollection","features":out})
    manifest["buildings"][did].update(count=len(out),bytes=size,static_precomputed=True,static_version="2026-10-01-02")
    stats.update(final_count=len(out),output_bytes=size);print(json.dumps(stats,ensure_ascii=False),flush=True);return stats
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--district",action="append");args=ap.parse_args()
    dist=json.loads(DIST.read_text(encoding="utf-8"));manifest=json.loads(MANIFEST.read_text(encoding="utf-8"));by_pnu,by_loc=load_register_all();wanted=set(args.district or []);rows=[]
    for f in dist["features"]:
        did=str(f["properties"]["district_id"]);dname=f["properties"]["district_name"]
        if wanted and did not in wanted:continue
        if did not in manifest["buildings"] or did not in manifest["parcels"]:continue
        dg=safe_geom(shape(f["geometry"]));print(f"=== {dname} {did} ===",flush=True)
        try:rows.append(build_one(did,dname,dg,manifest,by_pnu,by_loc))
        except Exception as e:print("FAILED",did,dname,repr(e),flush=True);rows.append({"name":dname,"district_id":did,"failed":repr(e)})
        MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    manifest["building_count"]=sum(int(v["count"]) for v in manifest["buildings"].values())
    manifest.setdefault("notes",{})["static_precompute"]="2026-10-01: 다중동 PNU에서 footprint 면적 우선 매칭 + 이전 대장값 자기강화 제거 + 용도별 층고 보정."
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    REPORT.write_text(json.dumps({"generated_at":"2026-10-01","districts":rows},ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__":main()
