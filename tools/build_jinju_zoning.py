#!/usr/bin/env python3
import io, os, re, json, gzip, zipfile, tempfile, requests
from pathlib import Path
from xml.etree import ElementTree as ET

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping
from shapely.validation import make_valid

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/zoning"
OUT.mkdir(parents=True,exist_ok=True)
PAGE="https://www.eum.go.kr/web/op/sv/svItemDet.jsp?currentPageNo=1&dataCd=004&dataTypeCd=SHP&selectType=subject"
FILEINFO="https://www.eum.go.kr/web/op/sv/svItemAjaxXml.jsp"
UPDOWN="https://map.eum.go.kr:8002/OpenData/opDownloader.jsp"
HEADERS={"User-Agent":"Mozilla/5.0"}
ZONE_CODES=["UQ111","UQ112","UQ113","UQ114"]
EXTRA_CODES=["UQ121","UQ123"]

NAME_FALLBACK={
 "UQA111":"제1종전용주거지역","UQA112":"제2종전용주거지역",
 "UQA121":"제1종일반주거지역","UQA122":"제2종일반주거지역","UQA123":"제3종일반주거지역","UQA130":"준주거지역",
 "UQA210":"중심상업지역","UQA220":"일반상업지역","UQA230":"근린상업지역","UQA240":"유통상업지역",
 "UQA310":"전용공업지역","UQA320":"일반공업지역","UQA330":"준공업지역",
 "UQA410":"보전녹지지역","UQA420":"생산녹지지역","UQA430":"자연녹지지역",
 "UQB100":"계획관리지역","UQB200":"생산관리지역","UQB300":"보전관리지역",
 "UQC001":"농림지역","UQD001":"자연환경보전지역",
}

def latest_file_info(session):
    r=session.get(PAGE,headers=HEADERS,timeout=60); r.raise_for_status()
    ids=re.findall(r"dataDownload\('([^']+)'\)",r.text)
    if not ids: raise RuntimeError("토지이음 최신 SHP 파일 ID를 찾지 못했습니다.")
    file_id=ids[0]
    resp=session.post(FILEINFO,headers={**HEADERS,"Referer":PAGE,"X-Requested-With":"XMLHttpRequest"},
        data={"function":"selectFileInfo","dataCd":"004","dataTypeCd":"SHP","refDt":"","fileId":file_id},timeout=60)
    resp.raise_for_status()
    obj=resp.json()
    root=ET.fromstring(obj["fileList"])
    node=root.find(".//node")
    d={c.tag:(c.text or "") for c in node}
    d["fileId"]=file_id
    return d

def get_inner_gyeongnam_zip(session,info):
    url=UPDOWN+"?key="+info["key"]+"&filename="+info["fileNm"]
    print("latest",info.get("refDt"),info.get("fileNmKr"),flush=True)
    # 먼저 HTTP Range 기반 remotezip으로 전국 ZIP의 중앙 디렉터리와 48000 멤버만 읽는다.
    try:
        from remotezip import RemoteZip
        with RemoteZip(url,headers=HEADERS,initial_buffer_size=256*1024) as rz:
            names=rz.namelist()
            cand=[n for n in names if re.search(r"(?:KLIP|UPIS)_004_\d+_48000\.zip$",n,re.I)]
            if not cand: cand=[n for n in names if n.endswith("_48000.zip")]
            if not cand: raise RuntimeError("전국 ZIP에서 경상남도 48000 ZIP을 찾지 못했습니다.")
            print("remote member",cand[0],flush=True)
            return rz.read(cand[0]),cand[0]
    except Exception as e:
        print("remotezip fallback:",repr(e),flush=True)

    # Range 미지원 시 전체 ZIP을 임시 파일로 스트리밍한 뒤 48000 멤버만 추출한다.
    tmp=Path(tempfile.gettempdir())/"eum_zoning_all.zip"
    with session.get(url,headers=HEADERS,stream=True,timeout=(60,600)) as rr:
        rr.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in rr.iter_content(1024*1024):
                if chunk:f.write(chunk)
    with zipfile.ZipFile(tmp) as z:
        cand=[n for n in z.namelist() if re.search(r"(?:KLIP|UPIS)_004_\d+_48000\.zip$",n,re.I)]
        if not cand:cand=[n for n in z.namelist() if n.endswith("_48000.zip")]
        if not cand:raise RuntimeError("전국 ZIP에서 경상남도 48000 ZIP을 찾지 못했습니다.")
        return z.read(cand[0]),cand[0]

def extract_inner(data):
    d=Path(tempfile.mkdtemp(prefix="jinju_zoning_"))
    with zipfile.ZipFile(io.BytesIO(data)) as z:z.extractall(d)
    return d

def clean_name(row):
    for k in ("dgm_nm","alias","remark"):
        v=row.get(k)
        if v is not None and str(v).strip() and str(v).lower()!="nan" and not str(v).startswith("UQ"):
            return str(v).strip()
    return NAME_FALLBACK.get(str(row.get("atrb_se") or ""),str(row.get("atrb_se") or "미상"))

def read_layer(base,code,kind):
    paths=list(base.glob(f"*C_{code}.shp"))
    if not paths:return gpd.GeoDataFrame(columns=["kind","layer","code","name","alias","remark","ntfdate","geometry"],geometry="geometry",crs="EPSG:4326")
    g=gpd.read_file(paths[0],encoding="cp949")
    g=g[g["sgg_cd"].astype(str)=="48170"].copy()
    if g.empty:return gpd.GeoDataFrame(columns=["kind","layer","code","name","alias","remark","ntfdate","geometry"],geometry="geometry",crs="EPSG:4326")
    g["kind"]=kind;g["layer"]=code;g["code"]=g["atrb_se"].astype(str)
    g["name"]=g.apply(clean_name,axis=1)
    for c in ("alias","remark","ntfdate"):
        if c not in g.columns:g[c]=None
    g=g[["kind","layer","code","name","alias","remark","ntfdate","geometry"]]
    bad=~g.geometry.is_valid
    if bad.any():g.loc[bad,"geometry"]=g.loc[bad,"geometry"].apply(make_valid)
    return g.to_crs(4326)

def compact_fc(gdf):
    feats=[]
    for _,r in gdf.iterrows():
        if r.geometry is None or r.geometry.is_empty:continue
        p={"kind":r["kind"],"layer":r["layer"],"code":r["code"],"name":r["name"]}
        for k in ("alias","remark","ntfdate"):
            v=r.get(k)
            if v is not None and str(v)!="nan" and str(v).strip():p[k]=str(v).strip()
        feats.append({"type":"Feature","properties":p,"geometry":mapping(r.geometry)})
    return {"type":"FeatureCollection","features":feats}

def save_gz(path,obj):
    raw=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    with gzip.open(path,"wb",compresslevel=9) as f:f.write(raw)
    return len(raw),path.stat().st_size

def main():
    sess=requests.Session()
    info=latest_file_info(sess)
    inner,inner_name=get_inner_gyeongnam_zip(sess,info)
    base=extract_inner(inner)

    frames=[]
    for c in ZONE_CODES:
        x=read_layer(base,c,"zoning");print(c,len(x),flush=True);frames.append(x)
    for c in EXTRA_CODES:
        kind="landscape" if c=="UQ121" else "height_district"
        x=read_layer(base,c,kind);print(c,len(x),flush=True);frames.append(x)
    allg=gpd.GeoDataFrame(pd.concat(frames,ignore_index=True),crs="EPSG:4326")

    districts=gpd.read_file(ROOT/"data/jinju_districts.geojson").to_crs(4326)
    manifest={"source":"토지이음 (도시계획)용도지역정보 SHP","ref_date":info.get("refDt"),"source_file":info.get("fileNmKr"),"inner_file":inner_name,"districts":{}}
    for _,d in districts.iterrows():
        did=str(d.get("district_id")); dname=str(d.get("district_name") or did)
        geom=d.geometry
        sub=allg[allg.geometry.intersects(geom)].copy()
        if not sub.empty:
            sub["geometry"]=sub.geometry.intersection(geom)
            sub=sub[~sub.geometry.is_empty]
        fc=compact_fc(sub)
        raw,gz=save_gz(OUT/f"{did}.geojson.gz",fc)
        counts={}
        for k in ("zoning","landscape","height_district"):
            counts[k]=sum(1 for f in fc["features"] if f["properties"]["kind"]==k)
        manifest["districts"][did]={"name":dname,"file":f"data/zoning/{did}.geojson.gz","count":len(fc["features"]),"bytes":gz,**counts}
        print(did,dname,len(fc["features"]),counts,flush=True)
    (OUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"ref_date":manifest["ref_date"],"district_count":len(manifest["districts"])},ensure_ascii=False))

if __name__=="__main__":main()
