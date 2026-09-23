#!/usr/bin/env python3
import json, gzip, math, re, time
from pathlib import Path
import requests
from shapely.geometry import shape, mapping, Polygon, LineString
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
DISTRICT_ID="38030760"; DISTRICT_NAME="충무공동"
BLD=ROOT/f"data/buildings/{DISTRICT_ID}.geojson.gz"
PAR=ROOT/f"data/parcels/{DISTRICT_ID}.geojson.gz"
DIST=ROOT/"data/jinju_districts.geojson"
REGIDX=ROOT/"data/register/index.json"
REPORT=ROOT/"data/chungmugong_static_build_report.json"

def load_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
def save_gz(p,obj):
    raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode()
    with gzip.open(p,"wb",compresslevel=9) as f:f.write(raw)
    return p.stat().st_size
def prop(p,*names):
    for n in names:
        v=p.get(n)
        if v is not None and str(v).strip()!="": return str(v).strip()
    return ""
def norm(s): return re.sub(r"\s+|번지$","",str(s or "")).strip()
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
    if g.geom_type not in ("Polygon","MultiPolygon"):return None
    if g.area<=1e-11:return None
    minx,miny,maxx,maxy=g.bounds
    if min(maxx-minx,maxy-miny)<0.000003:return None
    return g
def floor_h(use):
    s=str(use or "")
    if re.search("공동주택|단독주택|다가구|다세대|연립",s):return 2.9
    if re.search("업무|근린생활|판매|의료|교육|학교",s):return 3.6
    if re.search("공장|창고",s):return 4.8
    return 3.2
def metric_area(g):
    lat=35.18*math.pi/180
    return g.area*(111320.0**2)*math.cos(lat) if g else 0
def pnu_from_props(p):
    raw=prop(p,"pnu","PNU","pnu_code","PNU_CODE","parcel_pnu","ld_pnu","plat_pnu")
    d=re.sub(r"\D","",raw)
    return d if len(d)==19 else ""
def load_register():
    idx=json.loads(REGIDX.read_text(encoding="utf-8"));by_pnu={};by_loc={}
    for rel in idx.get("shards",[]):
        part=json.loads((ROOT/rel).read_text(encoding="utf-8"))
        for r in part.get("records",[]):
            if len(r)<11:continue
            if not (str(r[1]).startswith(DISTRICT_NAME) or str(r[2]).startswith(DISTRICT_NAME)):continue
            by_pnu.setdefault(str(r[0]),[]).append(r);by_loc.setdefault(norm(r[1]),[]).append(r)
    return by_pnu,by_loc
def choose_reg(cands,props,area_m2):
    if not cands:return None
    name=norm(prop(props,"building_name","name","BLD_NM","bld_nm"));dong=norm(prop(props,"dong_name","dong","동명칭"));use=norm(prop(props,"use_name","main_use_name","building","class"))
    try:floors=float(prop(props,"floors_above","levels","building:levels") or 0)
    except:floors=0
    best=None;bs=-1e9
    for r in cands:
        h=float(r[3] or 0);fl=float(r[4] or 0);rn=norm(r[6]);rd=norm(r[7]);ru=norm(r[8]);ra=float(r[9] or 0)
        sc=(2 if h>0 else 0)+(1 if fl>0 else 0)
        if name and rn and (name in rn or rn in name):sc+=7
        if dong and rd and (dong in rd or rd in dong):sc+=7
        if use and ru and (use in ru or ru in use):sc+=1
        if floors>0 and fl>0:sc+=max(0,3-abs(floors-fl)*0.7)
        if area_m2>0 and ra>0:sc+=6*min(area_m2,ra)/max(area_m2,ra)
        if sc>bs:best,bs=r,sc
    return best
def register_candidates(props,parcel_props,by_pnu,by_loc):
    out=[]
    for p in (props,parcel_props or {}):
        pnu=pnu_from_props(p)
        if pnu in by_pnu:out+=by_pnu[pnu]
        legal=prop(p,"legal_name","bjd_name","emd_nm","li_name");jib=prop(p,"jibun","jibun_addr","lot_no","plat_plc")
        if legal and jib:out+=by_loc.get(norm(legal+jib),[])
    seen=set();u=[]
    for r in out:
        k=tuple(r[:9])
        if k not in seen:seen.add(k);u.append(r)
    return u
def build_parcel_index(parcels):
    gs=[];ps=[]
    for f in parcels.get("features",[]):
        g=safe_geom(shape(f["geometry"]))
        if g is not None:gs.append(g);ps.append(f.get("properties",{}))
    return gs,ps,STRtree(gs)
def parcel_for(g,gs,ps,tree):
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
        h=float(reg[3] or 0);fl=int(float(reg[4] or 0));use=reg[8] or prop(props,"use_name")
        if h>0:
            props.update(render_height=round(h,3),height_m=round(h,3),floors_above=fl or props.get("floors_above",0),height_source="건축물대장 실제 높이",height_confidence="높음",register_matched=True);return
        if fl>0:
            props.update(render_height=round(fl*floor_h(use),3),floors_above=fl,height_source=f"건축물대장 {fl}층 기반",height_confidence="보통",register_matched=True);return
    try:h=float(prop(props,"height_m","height","render_height") or 0)
    except:h=0
    try:fl=float(prop(props,"floors_above","levels","building:levels") or 0)
    except:fl=0
    use=prop(props,"use_name","building","class")
    if h>1:props.update(render_height=round(h,3),height_source=f"{source} 기재 높이",height_confidence="높음" if source=="GIS" else "보통")
    elif fl>0:props.update(render_height=round(fl*floor_h(use),3),floors_above=int(fl),height_source=f"{source} {int(fl)}층 기반",height_confidence="보통")
    else:
        if re.search("apart|residential|공동주택|아파트",use,re.I):n=12 if area>800 else 6 if area>300 else 3;h=n*2.9
        elif re.search("retail|commercial|mall|판매|근린",use,re.I):n=5 if area>2500 else 3 if area>700 else 2;h=n*3.6
        elif re.search("school|education|교육|학교",use,re.I):n=4 if area>1500 else 3;h=n*3.6
        elif re.search("industrial|warehouse|factory|공장|창고",use,re.I):n=1;h=10 if area>1500 else 7
        else:n=3 if area>500 else 2 if area>120 else 1;h=n*3.2
        props.update(render_height=round(h,3),floors_above=props.get("floors_above") or n,height_source="용도·면적 기반 추정",height_confidence="낮음")
def district_geom():
    fc=json.loads(DIST.read_text(encoding="utf-8"))
    return safe_geom(shape(next(x for x in fc["features"] if str(x["properties"].get("district_id"))==DISTRICT_ID)["geometry"]))
def fetch_osm(dg):
    minx,miny,maxx,maxy=dg.bounds
    q=f'[out:json][timeout:180];(way["building"]({miny},{minx},{maxy},{maxx});relation["building"]({miny},{minx},{maxy},{maxx}););out geom tags;'
    endpoints=(
        "https://overpass.private.coffee/api/interpreter",
        "https://overpass.nchc.org.tw/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    )
    headers={"User-Agent":"Jin-Min-Map static dataset builder/1.0"}
    last=None
    for attempt in range(4):
        for ep in endpoints:
            try:
                r=requests.get(ep,params={"data":q},headers=headers,timeout=240)
                if r.status_code in (429,502,503,504):
                    last=RuntimeError(f"{ep}: HTTP {r.status_code}")
                    time.sleep(4+attempt*5);continue
                r.raise_for_status()
                data=r.json()
                if data.get("elements") is not None:return data
            except Exception as e:
                last=e;time.sleep(4+attempt*5)
    raise last
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
def main():
    dg=district_geom();gis=load_gz(BLD);parcels=load_gz(PAR);by_pnu,by_loc=load_register();pg,pp,ptree=build_parcel_index(parcels)
    out=[];gg=[];stats={"gis_input":len(gis.get("features",[])),"gis_valid":0,"osm_raw":0,"osm_added":0,"osm_duplicate":0,"register_matched":0,"estimated":0}
    for f in gis.get("features",[]):
        g=safe_geom(shape(f["geometry"]))
        if g is None or not g.intersects(dg):continue
        p=dict(f.get("properties",{}));ph=parcel_for(g,pg,pp,ptree);reg=choose_reg(register_candidates(p,ph[0] if ph else None,by_pnu,by_loc),p,metric_area(g));apply_height(p,g,reg,"GIS")
        if reg:stats["register_matched"]+=1
        if p.get("height_confidence")=="낮음":stats["estimated"]+=1
        out.append({"type":"Feature","geometry":mapping(g),"properties":p});gg.append(g)
    stats["gis_valid"]=len(out);gtree=STRtree(gg)
    osm=fetch_osm(dg);stats["osm_raw"]=len(osm.get("elements",[]))
    for el in osm.get("elements",[]):
        g=osm_geom(el)
        if g is None or not dg.contains(g.representative_point()):continue
        dup=False;ga=max(g.area,1e-15)
        for item in gtree.query(g):
            try:i=int(item)
            except:i=gg.index(item)
            try:ov=g.intersection(gg[i]).area/ga
            except:ov=0
            if ov>=0.25:dup=True;break
        if dup:stats["osm_duplicate"]+=1;continue
        p=dict(el.get("tags",{}));p.update(data_source="OSM 정적 보완",osm_id=f'{el.get("type")}/{el.get("id")}')
        ph=parcel_for(g,pg,pp,ptree);reg=choose_reg(register_candidates(p,ph[0] if ph else None,by_pnu,by_loc),p,metric_area(g));apply_height(p,g,reg,"OSM")
        if reg:stats["register_matched"]+=1
        if p.get("height_confidence")=="낮음":stats["estimated"]+=1
        out.append({"type":"Feature","geometry":mapping(g),"properties":p});gg.append(g);stats["osm_added"]+=1
    fc={"type":"FeatureCollection","features":out};size=save_gz(BLD,fc)
    mani=json.loads((ROOT/"data/manifest.json").read_text(encoding="utf-8"));mani["buildings"][DISTRICT_ID]["count"]=len(out);mani["buildings"][DISTRICT_ID]["bytes"]=size;mani["building_count"]=sum(int(v["count"]) for v in mani["buildings"].values());mani.setdefault("notes",{})["chungmugong_static_build"]="2026-09-23: GIS 우선 + OSM 누락 정적 보완 + 건축물대장 높이/층수 사전결합. 런타임 폴리곤 절삭 사용 안 함."; (ROOT/"data/manifest.json").write_text(json.dumps(mani,ensure_ascii=False,indent=2),encoding="utf-8")
    stats.update(final_count=len(out),output_bytes=size);REPORT.write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(stats,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
