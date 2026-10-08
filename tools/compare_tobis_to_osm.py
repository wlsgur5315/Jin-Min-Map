#!/usr/bin/env python3
import gzip,json,re,math,requests
from pathlib import Path
from shapely.geometry import shape, LineString
from shapely.ops import unary_union

ROOT=Path(__file__).resolve().parents[1]
B=ROOT/"data/buildings/38030770.geojson.gz"
TARGET="4817011900100330015"
OUT=ROOT/"data/tobis_osm_shape_compare.json"

with gzip.open(B,"rt",encoding="utf-8") as f: fc=json.load(f)
rows=[]
for i,feat in enumerate(fc.get("features",[])):
    p=feat.get("properties") or {}
    d=re.sub(r"\D","",str(p.get("pnu") or p.get("PNU") or ""))
    name=str(p.get("building_name") or p.get("register_name") or "")
    if d==TARGET or "토비스유압" in name:
        g=shape(feat["geometry"])
        rows.append((i,p,g))

# Fetch OSM buildings + roads in 250m bbox around site.
lat,lon=35.1822,128.1233
q=f"""[out:json][timeout:60];
(
 way["building"](around:250,{lat},{lon});
 relation["building"](around:250,{lat},{lon});
 way["highway"](around:250,{lat},{lon});
);
out geom;"""
urls=["https://overpass.kumi.systems/api/interpreter","https://overpass-api.de/api/interpreter"]
last=None
for u in urls:
    try:
        r=requests.get(u,params={"data":q},headers={"User-Agent":"Jin-Min-Map/1.0"},timeout=90)
        r.raise_for_status(); data=r.json(); last=None; break
    except Exception as e:
        last=e
if last: raise last

osm_buildings=[];roads=[]
for el in data.get("elements",[]):
    tags=el.get("tags") or {}
    geom=el.get("geometry") or []
    if len(geom)<2: continue
    pts=[(x["lon"],x["lat"]) for x in geom]
    if "building" in tags and len(pts)>=4:
        from shapely.geometry import Polygon
        try:
            pg=Polygon(pts)
            if pg.is_valid and not pg.is_empty:osm_buildings.append((el.get("id"),tags,pg))
        except: pass
    if "highway" in tags:
        try:roads.append((el.get("id"),tags,LineString(pts)))
        except:pass

# approximate metric areas/distances by scaling around site
mx=111320*math.cos(math.radians(lat)); my=110540
from shapely.ops import transform
def metric(g):
    return transform(lambda x,y,z=None:(x*mx,y*my),g)

osm_m=[(oid,t,metric(g)) for oid,t,g in osm_buildings]
road_bufs=[]
for oid,t,g in roads:
    hw=t.get("highway","")
    width={"primary":8,"secondary":7,"tertiary":6,"residential":5,"service":3.5,"unclassified":4.5}.get(hw,3.5)
    road_bufs.append((oid,t,metric(g).buffer(width/2)))
road_union=unary_union([x[2] for x in road_bufs]) if road_bufs else None

out=[]
for i,p,g in rows:
    gm=metric(g); area=gm.area
    best=None
    for oid,t,og in osm_m:
        inter=gm.intersection(og).area
        if inter<=0:continue
        union=gm.union(og).area
        iou=inter/union if union else 0
        cov=inter/area if area else 0
        ocov=inter/og.area if og.area else 0
        cand={"osm_id":oid,"osm_name":t.get("name"),"iou":iou,"candidate_coverage":cov,"osm_coverage":ocov,"osm_area_m2":og.area}
        if not best or cand["iou"]>best["iou"]:best=cand
    road_ratio=gm.intersection(road_union).area/area if road_union and area else 0
    c=gm.centroid
    out.append({
      "index":i,"uid":p.get("building_uid"),"name":p.get("building_name") or p.get("register_name"),
      "dong":p.get("building_dong") or p.get("register_dong"),
      "height":p.get("render_height") or p.get("height_m"),"floors":p.get("floors_above"),
      "area_m2":round(area,1),"centroid_lonlat":[round(c.x/mx,7),round(c.y/my,7)],
      "road_overlap_ratio":round(road_ratio,4),
      "best_osm":None if not best else {
        **best,
        "iou":round(best["iou"],4),"candidate_coverage":round(best["candidate_coverage"],4),
        "osm_coverage":round(best["osm_coverage"],4),"osm_area_m2":round(best["osm_area_m2"],1)
      }
    })
OUT.write_text(json.dumps({"osm_building_count":len(osm_buildings),"road_count":len(roads),"records":out},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(json.loads(OUT.read_text(encoding="utf-8")),ensure_ascii=False,indent=2))
