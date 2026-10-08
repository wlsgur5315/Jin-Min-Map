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
    """GIS 식별자를 우선하되, 실제 footprint와 심하게 불일치하면 재건축/속성 노후화로 보고 면적 후보를 사용한다."""
    if not cands:return None
    name=norm(prop(props,"building_name","name","BLD_NM","bld_nm"))
    dong=norm(prop(props,"building_dong","dong_name","dong","동명칭"))
    use=norm(prop(props,"use_name","main_use_name","building","class"))
    try:floors=float(prop(props,"floors_above","levels","building:levels") or 0)
    except:floors=0
    many=len(cands)>=5

    def area_ratio(r):
        try:ra=float(r[9] or 0)
        except:return 0.0
        if area_m2<=0 or ra<=0:return 0.0
        return min(area_m2,ra)/max(area_m2,ra)

    # footprint에 가장 잘 맞는 대장 후보. 오래된 GIS 속성보다 실제 도형이 최신인 경우를 판별하는 데 사용.
    area_rank=sorted(((area_ratio(r),r) for r in cands),key=lambda x:x[0],reverse=True)
    best_ar,best_area_rec=area_rank[0] if area_rank else (0.0,None)
    second_ar=area_rank[1][0] if len(area_rank)>1 else 0.0

    # 1) 기존 GIS 동명칭 정확 일치 후보
    if dong:
        exact=[r for r in cands if norm(r[7])==dong]
        if len(exact)==1:
            er=area_ratio(exact[0])
            # GIS 동명칭의 대장 면적과 현재 polygon이 크게 다르고,
            # 다른 후보가 polygon 면적과 거의 맞으면 재건축/갱신된 건물로 판단.
            if many and er<.55 and best_ar>=.85 and best_ar-second_ar>=.08 and best_area_rec is not exact[0]:
                props["register_match_score"]=88
                props["register_match_margin"]=round((best_ar-second_ar)*100,2)
                props["register_match_area_ratio"]=round(best_ar,4)
                props["register_match_basis"]="GIS 속성 노후 추정 · footprint 면적 우선"
                return best_area_rec
            props["register_match_score"]=100
            props["register_match_margin"]=100
            props["register_match_area_ratio"]=round(er,4) if er else None
            props["register_match_basis"]="GIS 동명칭 정확 일치"
            return exact[0]
        similar=[r for r in cands if norm(r[7]) and (dong in norm(r[7]) or norm(r[7]) in dong)]
        if len(similar)==1:
            sr=area_ratio(similar[0])
            if many and sr<.50 and best_ar>=.85 and best_ar-second_ar>=.08 and best_area_rec is not similar[0]:
                props["register_match_score"]=86
                props["register_match_margin"]=round((best_ar-second_ar)*100,2)
                props["register_match_area_ratio"]=round(best_ar,4)
                props["register_match_basis"]="GIS 속성 노후 추정 · footprint 면적 우선"
                return best_area_rec
            props["register_match_score"]=90
            props["register_match_margin"]=90
            props["register_match_area_ratio"]=round(sr,4) if sr else None
            props["register_match_basis"]="GIS 동명칭 유사 일치"
            return similar[0]

    # 2) 건물명 정확/유사 일치
    if name:
        exact=[r for r in cands if norm(r[6])==name]
        if len(exact)==1:
            props["register_match_score"]=95
            props["register_match_margin"]=95
            props["register_match_area_ratio"]=round(area_ratio(exact[0]),4) or None
            props["register_match_basis"]="GIS 건물명 정확 일치"
            return exact[0]
        similar=[r for r in cands if norm(r[6]) and (name in norm(r[6]) or norm(r[6]) in name)]
        if len(similar)==1:
            props["register_match_score"]=85
            props["register_match_margin"]=85
            props["register_match_area_ratio"]=round(area_ratio(similar[0]),4) or None
            props["register_match_basis"]="GIS 건물명 유사 일치"
            return similar[0]

    ranked=[]
    for r in cands:
        try:
            h=float(r[3] or 0);fl=float(r[4] or 0);ra=float(r[9] or 0)
        except:continue
        ru=norm(r[8]);sc=0.0;why=[];ar=area_ratio(r)
        if ar>0:
            if many:
                if ar>=.93:sc+=30;why.append("면적 거의일치")
                elif ar>=.85:sc+=25;why.append("면적 매우유사")
                elif ar>=.72:sc+=18;why.append("면적 유사")
                elif ar>=.55:sc+=10
                elif ar>=.35:sc+=3
                else:sc-=8
            else:
                if ar>=.85:sc+=12;why.append("면적 매우유사")
                elif ar>=.65:sc+=8;why.append("면적 유사")
                elif ar>=.45:sc+=4
                elif ar>=.25:sc+=1
                else:sc-=3
        if use and ru:
            if use==ru:sc+=3
            elif use in ru or ru in use:sc+=2
        if floors>0 and fl>0 and not many:
            df=abs(floors-fl)
            if df<0.1:sc+=5
            elif df<=1:sc+=2
        if h>0:sc+=1
        if fl>0:sc+=.5
        ranked.append((sc,ar,r,why))

    if not ranked:return None
    ranked.sort(key=lambda x:x[0],reverse=True)
    bs,bratio,best,why=ranked[0]
    second=ranked[1][0] if len(ranked)>1 else -999
    margin=bs-second
    if len(ranked)>1:
        if many and bratio<.72:return None
        if bs<8 or margin<3:return None
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
def _dist_m(a,b):
    x=(b[0]-a[0])*111320*math.cos(math.radians((a[1]+b[1])/2))
    y=(b[1]-a[1])*110540
    return math.hypot(x,y)

def _cluster_rows(rows,max_dist=120):
    left=set(range(len(rows)));clusters=[]
    while left:
        seed=left.pop();cluster=[seed];stack=[seed]
        while stack:
            i=stack.pop();a=rows[i]["pt"]
            near=[j for j in list(left) if _dist_m(a,rows[j]["pt"])<=max_dist]
            for j in near:
                left.remove(j);cluster.append(j);stack.append(j)
        clusters.append(cluster)
    return clusters

def merge_split_register_groups(features):
    """동일 PNU·동일 대장 레코드가 여러 분할 polygon에 복제되면 120m 이내 그룹을 하나의 geometry로 병합."""
    groups={};rows=[]
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
        rec={"idx":idx,"f":f,"p":p,"g":g,"area":metric_area(g),"pt":(rp.x,rp.y),"ra":ra}
        rows.append(rec)
        key=(pn,norm(p.get("register_name")),norm(p.get("register_dong")),h,fl,ra)
        groups.setdefault(key,[]).append(rec)

    replace={};removed=set();stats={"candidate_groups":0,"merged_groups":0,"merged_features":0}
    for key,items in groups.items():
        if len(items)<2:continue
        stats["candidate_groups"]+=1
        for ci in _cluster_rows(items,120):
            part=[items[i] for i in ci]
            if len(part)<2:continue
            ug=safe_geom(unary_union([x["g"] for x in part]))
            if ug is None:continue
            group_area=metric_area(ug);ra=part[0]["ra"]
            ratio=min(group_area,ra)/max(group_area,ra) if group_area>0 and ra>0 else 0
            if ratio<0.35:continue
            rep=sorted(part,key=lambda x:((1 if x["p"].get("building_name") else 0)+(1 if x["p"].get("building_dong") else 0),x["area"]),reverse=True)[0]
            nf=dict(rep["f"]);np=dict(rep["p"])
            nf["geometry"]=mapping(ug);nf["properties"]=np
            np["register_grouped_parts"]=len(part)
            np["register_group_footprint_area_m2"]=round(group_area,1)
            np["register_group_area_ratio"]=round(ratio,4)
            old=str(np.get("register_match_basis") or "")
            tag="동일 PNU 분할 footprint 그룹 병합"
            np["register_match_basis"]=(old+" · "+tag).strip(" ·") if old else tag
            np["register_group_sources"]=" / ".join(sorted({str(x["p"].get("data_source") or "GIS 원본") for x in part}))
            replace[rep["idx"]]=nf
            for x in part:
                if x["idx"]!=rep["idx"]:removed.add(x["idx"])
            stats["merged_groups"]+=1;stats["merged_features"]+=len(part)-1
    out=[]
    for i,f in enumerate(features):
        if i in removed:continue
        out.append(replace.get(i,f))
    return out,stats

def suppress_highrise_register_on_tiny_parts(features):
    """같은 PNU에서 동일 고층 대장값이 여러 폴리곤에 복제된 경우 작은 부속 조각의 높이만 차단."""
    groups={}
    geom_cache={}
    for f in features:
        p=f.get("properties") or {}
        pn=pnu_from_props(p)
        if not pn or not p.get("register_matched"):continue
        try:g=safe_geom(shape(f.get("geometry")))
        except:g=None
        if g is None:continue
        geom_cache[id(f)]=(g,metric_area(g))
        try:h=float(p.get("render_height") or 0);fl=float(p.get("floors_above") or 0)
        except:h=0;fl=0
        if h<30 and fl<8:continue
        regkey=(norm(p.get("register_name")),norm(p.get("register_dong")),round(h,1),int(fl))
        groups.setdefault((pn,regkey),[]).append(f)

    changed=0
    for (pn,regkey),items in groups.items():
        if len(items)<2:continue
        vals=[]
        for f in items:
            g,a=geom_cache[id(f)]
            p=f.get("properties") or {}
            try:ra=float(p.get("register_building_area_m2") or 0)
            except:ra=0
            ratio=(min(a,ra)/max(a,ra)) if a>0 and ra>0 else 0
            vals.append((f,g,a,ra,ratio))
        vals.sort(key=lambda x:x[4],reverse=True)
        best_ratio=vals[0][4]
        best_area=max(x[2] for x in vals)

        # 같은 대장값을 공유하는 더 큰/더 잘 맞는 본체 후보가 실제로 있을 때만 작은 조각을 억제.
        for f,g,a,ra,ratio in vals:
            p=f.get("properties") or {}
            # 긴급 분류에서 확인된 작은 부속/파편 유형을 더 보수적으로 차단.
            # 단, 동일 PNU·동일 대장값 그룹 안에서 더 큰 본체 후보가 있을 때만 적용.
            tiny=(a<120 and a<best_area*0.25)
            clearly_worse=(ratio<0.10 and (best_ratio>=0.25 or best_ratio>=ratio*4))
            if not (tiny and clearly_worse):continue

            p["suppressed_register_height"]=True
            p["suppressed_register_height_reason"]="동일 PNU·동일 대장 고층값의 작은 부속 폴리곤 복제 차단"
            p["suppressed_register_height_original"]=p.get("render_height")
            for k in ("render_height","height_m","floors_above","floors_below"):
                p.pop(k,None)
            # 대장 식별정보는 진단용으로 보존하되, 이 조각에는 대장 높이를 사용하지 않는다.
            p["register_matched"]=False
            apply_height(p,g,None,"부속 폴리곤")
            if p.get("height_confidence")=="높음":p["height_confidence"]="보통"
            changed+=1
    return changed

def build_one(did,dname,dg,manifest,by_pnu,by_loc):
    bp=ROOT/manifest["buildings"][did]["file"];ppath=ROOT/manifest["parcels"][did]["file"]
    gis=load_gz(bp);parcels=load_gz(ppath);pg,pps,ptree=build_index(parcels)
    base=[f for f in gis.get("features",[]) if str((f.get("properties") or {}).get("data_source") or "") not in SUPPLEMENT_SOURCES]
    out=[];gg=[];stats={"name":dname,"gis_input":len(base),"gis_valid":0,"osm_raw":0,"osm_added":0,"osm_duplicate":0,"overture_raw":0,"overture_added":0,"overture_duplicate":0,"register_matched":0,"estimated":0}
    for f in base:
        try:g=safe_geom(shape(f["geometry"]))
        except:g=None
        if g is None or not g.intersects(dg):continue
        p=clear_previous_register_enrichment(f.get("properties",{}));ph=parcel_for(g,pg,pps,ptree)
        if ph:
            pp=ph[0] or {}
            actual_pnu=pnu_from_props(pp)
            feature_pnu=pnu_from_props(p)
            try:overlap_ratio=g.intersection(ph[1]).area/max(g.area,1e-15)
            except:overlap_ratio=0
            if actual_pnu and overlap_ratio>=0.55:
                if feature_pnu and feature_pnu!=actual_pnu:
                    p["source_pnu_before_spatial_fix"]=feature_pnu
                    p["pnu_spatial_corrected"]=True
                p["pnu"]=actual_pnu
                pj=prop(pp,"jibun","JIBUN","jibun_addr","lot_no","LOT_NO","plat_plc","PLAT_PLC","지번")
                if pj:p["jibun"]=pj
                pl=prop(pp,"legal_name","bjd_name","BJD_NAM","bjd_nm","BJD_NM","emd_nm","EMD_NM","emd_name","li_name","법정동명")
                if pl:p["legal_name"]=pl
        reg=choose_reg(register_candidates(p,ph[0] if ph else None,by_pnu,by_loc),p,metric_area(g));apply_height(p,g,reg,"GIS")
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
        ph=parcel_for(g,pg,pps,ptree)
        if ph:
            pp=ph[0] or {};actual_pnu=pnu_from_props(pp)
            try:overlap_ratio=g.intersection(ph[1]).area/max(g.area,1e-15)
            except:overlap_ratio=0
            if actual_pnu and overlap_ratio>=0.55:
                p["pnu"]=actual_pnu
                pj=prop(pp,"jibun","JIBUN","jibun_addr","lot_no","LOT_NO","plat_plc","PLAT_PLC","지번")
                if pj:p["jibun"]=pj
                pl=prop(pp,"legal_name","bjd_name","BJD_NAM","bjd_nm","BJD_NM","emd_nm","EMD_NM","emd_name","li_name","법정동명")
                if pl:p["legal_name"]=pl
        reg=choose_reg(register_candidates(p,ph[0] if ph else None,by_pnu,by_loc),p,metric_area(g));apply_height(p,g,reg,"OSM")
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
        p=overture_props(f.get("properties") or {});ph=parcel_for(g,pg,pps,ptree)
        if ph:
            pp=ph[0] or {};actual_pnu=pnu_from_props(pp)
            try:overlap_ratio=g.intersection(ph[1]).area/max(g.area,1e-15)
            except:overlap_ratio=0
            if actual_pnu and overlap_ratio>=0.55:
                p["pnu"]=actual_pnu
                pj=prop(pp,"jibun","JIBUN","jibun_addr","lot_no","LOT_NO","plat_plc","PLAT_PLC","지번")
                if pj:p["jibun"]=pj
                pl=prop(pp,"legal_name","bjd_name","BJD_NAM","bjd_nm","BJD_NM","emd_nm","EMD_NM","emd_name","li_name","법정동명")
                if pl:p["legal_name"]=pl
                p["pnu_spatial_corrected"]=True
        reg=choose_reg(register_candidates(p,ph[0] if ph else None,by_pnu,by_loc),p,metric_area(g));apply_height(p,g,reg,"Overture")
        if reg:stats["register_matched"]+=1
        if p.get("height_confidence")=="낮음":stats["estimated"]+=1
        out.append({"type":"Feature","geometry":mapping(g),"properties":p});accepted.append(g);stats["overture_added"]+=1
    out,group_stats=merge_split_register_groups(out)
    stats["register_group_candidates"]=group_stats["candidate_groups"]
    stats["register_groups_merged"]=group_stats["merged_groups"]
    stats["register_group_features_merged"]=group_stats["merged_features"]
    stats["suppressed_tiny_highrise_parts"]=suppress_highrise_register_on_tiny_parts(out)
    size=save_gz(bp,{"type":"FeatureCollection","features":out})
    manifest["buildings"][did].update(count=len(out),bytes=size,static_precomputed=True,static_version="2026-10-08-01")
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
    manifest.setdefault("notes",{})["static_precompute"]="2026-10-08: 공간 PNU 우선 + Overture PNU 공간보완 + 동일 PNU·동일 대장 분할 footprint 그룹 병합 + 작은 부속/파편 고층값 복제 차단."
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    REPORT.write_text(json.dumps({"generated_at":"2026-10-01","districts":rows},ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__":main()
