import gzip,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
p=R/"data/buildings/38030760.geojson.gz"
with gzip.open(p,"rt",encoding="utf-8") as f:fc=json.load(f)
rows=[]
for i,x in enumerate(fc.get("features",[])):
    a=x.get("properties") or {}
    try:h=float(a.get("render_height") or a.get("height_m") or 0)
    except:h=0
    try:fl=float(a.get("floors_above") or 0)
    except:fl=0
    if h>80 or fl>30:
        rows.append({
          "i":i,"h":h,"floors":fl,"name":a.get("building_name") or a.get("name"),
          "jibun":a.get("jibun"),"src":a.get("data_source"),"height_source":a.get("height_source"),
          "use":a.get("use_name") or a.get("building"),"pnu":a.get("pnu"),"osm_id":a.get("osm_id")
        })
rows=sorted(rows,key=lambda x:x["h"],reverse=True)[:100]
out={"count_over_80m":len(rows),"top":rows}
(R/"data/chungmugong_height_outliers.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out,ensure_ascii=False,indent=2))
