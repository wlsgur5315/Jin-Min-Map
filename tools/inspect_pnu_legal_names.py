#!/usr/bin/env python3
import gzip,json,re
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PAR=ROOT/"data/parcels";BLD=ROOT/"data/buildings"
parcel_codes=Counter()
for path in PAR.glob("*.geojson.gz"):
  with gzip.open(path,"rt",encoding="utf-8") as f:fc=json.load(f)
  for feat in fc.get("features",[]):
    p=feat.get("properties") or {}
    d=re.sub(r"\D","",str(p.get("pnu") or ""))
    if len(d)==19:parcel_codes[d[:10]]+=1
name_votes=defaultdict(Counter)
for path in BLD.glob("*.geojson.gz"):
  with gzip.open(path,"rt",encoding="utf-8") as f:fc=json.load(f)
  for feat in fc.get("features",[]):
    p=feat.get("properties") or {}
    d=re.sub(r"\D","",str(p.get("pnu") or p.get("PNU") or ""))
    if len(d)!=19:continue
    name=str(p.get("legal_name") or p.get("bjd_name") or p.get("BJD_NM") or "").strip()
    if name:name_votes[d[:10]][name]+=1
mapping={}
for code,v in name_votes.items():
  if v:mapping[code]=v.most_common(1)[0][0]
report={"parcel_code_count":len(parcel_codes),"mapped_count":sum(1 for c in parcel_codes if c in mapping),
"unmapped":[{"code":c,"parcels":n} for c,n in sorted(parcel_codes.items()) if c not in mapping],
"mapping":[{"code":c,"name":mapping.get(c),"parcels":n,"votes":name_votes[c].most_common(5)} for c,n in sorted(parcel_codes.items())]}
(ROOT/"data/pnu_legal_name_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"parcel_code_count":report["parcel_code_count"],"mapped_count":report["mapped_count"],"unmapped":report["unmapped"][:100]},ensure_ascii=False,indent=2))
