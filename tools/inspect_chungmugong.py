import gzip,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def load(p):
  with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)
p=load(R/"data/parcels/38030760.geojson.gz")
b=load(R/"data/buildings/38030760.geojson.gz")
out={
 "parcel_count":len(p.get("features",[])),
 "parcel_keys":sorted({k for f in p.get("features",[])[:200] for k in (f.get("properties") or {}).keys()}),
 "parcel_samples":[f.get("properties",{}) for f in p.get("features",[])[:5]],
 "building_count":len(b.get("features",[])),
 "building_keys":sorted({k for f in b.get("features",[])[:200] for k in (f.get("properties") or {}).keys()}),
 "building_samples":[f.get("properties",{}) for f in b.get("features",[])[:5]]
}
(R/"data/chungmugong_schema_report.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out,ensure_ascii=False,indent=2))
