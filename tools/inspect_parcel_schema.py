#!/usr/bin/env python3
import gzip,json
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"data/parcels"
keys=Counter(); examples=defaultdict(list); files=[]
for path in sorted(P.glob("*.geojson.gz"))[:30]:
    with gzip.open(path,"rt",encoding="utf-8") as f: fc=json.load(f)
    fs=fc.get("features",[])
    files.append({"file":path.name,"count":len(fs)})
    for feat in fs[:200]:
        p=feat.get("properties") or {}
        for k,v in p.items():
            keys[k]+=1
            if len(examples[k])<5 and v not in (None,""):
                examples[k].append(v)
report={"files":files,"keys":[{"key":k,"count":c,"examples":examples[k]} for k,c in keys.most_common()]}
(ROOT/"data/parcel_schema_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report["keys"][:40],ensure_ascii=False,indent=2))
