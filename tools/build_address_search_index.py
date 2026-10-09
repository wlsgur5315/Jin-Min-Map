#!/usr/bin/env python3
import gzip,json,re
from pathlib import Path
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[1]
MAN=json.loads((ROOT/"data/manifest.json").read_text(encoding="utf-8"))
LEGAL=json.loads((ROOT/"data/pnu_legal_names.json").read_text(encoding="utf-8")).get("names",{})
with gzip.open(ROOT/"data/jinju_road_addresses.json.gz","rt",encoding="utf-8") as f:
    ROAD=json.load(f).get("addresses",{})

def digits(v): return re.sub(r"\D","",str(v or ""))
def lot_from_pnu(p):
    if len(p)!=19:return ""
    mountain=p[10]=="2"
    main=str(int(p[11:15])); sub=str(int(p[15:19]))
    return ("산 " if mountain else "")+main+(("-"+sub) if sub!="0" else "")
def norm(s):
    return re.sub(r"\s+","",str(s or "")).lower()

entries=[]
seen=set()
for did,meta in MAN.get("parcels",{}).items():
    path=ROOT/meta["file"]
    with gzip.open(path,"rt",encoding="utf-8") as f: fc=json.load(f)
    for feat in fc.get("features",[]):
        pr=feat.get("properties") or {}
        p=digits(pr.get("pnu") or pr.get("PNU"))
        if len(p)!=19 or p in seen: continue
        seen.add(p)
        legal=LEGAL.get(p[:10],"")
        lot=lot_from_pnu(p)
        jibun=(legal+" "+lot).strip()
        rv=ROAD.get(p,"")
        road=rv[0] if isinstance(rv,list) and rv else (rv if isinstance(rv,str) else "")
        try:
            pt=shape(feat["geometry"]).representative_point()
            lon,lat=round(pt.x,7),round(pt.y,7)
        except: continue
        aliases=[]
        for x in (jibun,road,lot,legal,p):
            nx=norm(x)
            if nx and nx not in aliases: aliases.append(nx)
        entries.append([p,str(did),lon,lat,jibun,road,"|".join(aliases)])

out={"version":"2026-10-09-01","count":len(entries),"entries":entries}
raw=json.dumps(out,ensure_ascii=False,separators=(",",":")).encode("utf-8")
outp=ROOT/"data/jinju_address_search_index.json.gz"
with gzip.open(outp,"wb",compresslevel=9) as f:f.write(raw)
print(json.dumps({"count":len(entries),"bytes":outp.stat().st_size,
"road_count":sum(1 for e in entries if e[5]),
"samples":[e for e in entries if "상대동 33-15" in e[4] or "도동로 134" in e[5]][:5]},ensure_ascii=False,indent=2))
