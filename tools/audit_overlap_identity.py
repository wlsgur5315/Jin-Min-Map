#!/usr/bin/env python3
import gzip,json,math,re
from pathlib import Path
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"data/buildings"; OUT=ROOT/"data/overlap_identity_audit.json"

def load(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def norm(x):return re.sub(r"\s+","",str(x or "")).strip()
def num(x):
    try:return float(x)
    except:return 0.0
def pnu(p):
    d=re.sub(r"\D","",str(p.get("pnu") or ""))
    return d if len(d)==19 else ""
def area_m2(g):
    lat=35.18*math.pi/180
    return g.area*(111320**2)*math.cos(lat)
def safe(g):
    try:
        if not g.is_valid:g=g.buffer(0)
    except:return None
    return g if g and not g.is_empty and g.geom_type in ("Polygon","MultiPolygon") else None
def pt(g):
    p=g.representative_point();return (p.x,p.y)
def dist(a,b):
    x=(b[0]-a[0])*111320*math.cos(math.radians((a[1]+b[1])/2))
    y=(b[1]-a[1])*110540
    return math.hypot(x,y)
def ident(p):
    return {
      "pnu":pnu(p),
      "uid":norm(p.get("building_uid")),
      "name":norm(p.get("building_name") or p.get("register_name")),
      "dong":norm(p.get("building_dong") or p.get("register_dong")),
      "reg_dong":norm(p.get("register_dong")),
      "height":num(p.get("render_height") or p.get("height_m")),
      "floors":num(p.get("floors_above")),
      "source":p.get("data_source") or "GIS"
    }

pairs=[];summary={"all":0,"strong_identity":0,"near_exact_unknown":0,"review":0}
for path in sorted(BUILD.glob("*.geojson.gz")):
    did=path.stem.split(".")[0]
    fc=load(path);rows=[];geoms=[]
    for i,f in enumerate(fc.get("features",[])):
        g=safe(shape(f.get("geometry")))
        if g is None:continue
        rows.append({"i":i,"g":g,"a":area_m2(g),"c":pt(g),"p":f.get("properties") or {}})
        geoms.append(g)
    tree=STRtree(geoms) if geoms else None
    for i,r in enumerate(rows):
        if not tree:break
        for item in tree.query(r["g"]):
            try:j=int(item)
            except:j=geoms.index(item)
            if j<=i:continue
            s=rows[j]
            if dist(r["c"],s["c"])>10:continue
            ar=min(r["a"],s["a"])/max(r["a"],s["a"]) if r["a"] and s["a"] else 0
            if ar<.75:continue
            try:ov=r["g"].intersection(s["g"]).area/min(r["g"].area,s["g"].area)
            except:ov=0
            if ov<.80:continue
            ia,ib=ident(r["p"]),ident(s["p"])
            same_uid=bool(ia["uid"] and ia["uid"]==ib["uid"])
            same_pnu=bool(ia["pnu"] and ia["pnu"]==ib["pnu"])
            same_dong=bool(ia["dong"] and ia["dong"]==ib["dong"])
            same_name=bool(ia["name"] and ia["name"]==ib["name"])
            same_reg_dong=bool(ia["reg_dong"] and ia["reg_dong"]==ib["reg_dong"])
            hclose=(ia["height"]<=0 or ib["height"]<=0 or abs(ia["height"]-ib["height"])<=1.5)
            fclose=(ia["floors"]<=0 or ib["floors"]<=0 or abs(ia["floors"]-ib["floors"])<=1)
            strong=(same_uid or (same_pnu and (same_dong or same_reg_dong or same_name) and hclose and fclose))
            near_unknown=(ov>=.95 and ar>=.95 and not strong)
            cls="strong_identity" if strong else ("near_exact_unknown" if near_unknown else "review")
            summary["all"]+=1;summary[cls]+=1
            pairs.append({
              "district_id":did,"a_index":r["i"],"b_index":s["i"],
              "overlap_ratio":round(ov,4),"area_ratio":round(ar,4),
              "a":ia,"b":ib,"same_uid":same_uid,"same_pnu":same_pnu,
              "same_dong":same_dong,"same_name":same_name,"same_reg_dong":same_reg_dong,
              "height_close":hclose,"floors_close":fclose,"class":cls,
              "centroid":[round(r["c"][0],7),round(r["c"][1],7)]
            })
pairs.sort(key=lambda x:(x["class"]!="strong_identity",-x["overlap_ratio"],-x["area_ratio"]))
OUT.write_text(json.dumps({"summary":summary,"pairs":pairs},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(pairs[:40],ensure_ascii=False,indent=2))
