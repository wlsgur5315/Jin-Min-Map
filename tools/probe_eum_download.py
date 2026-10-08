#!/usr/bin/env python3
import re, json, requests
from pathlib import Path
url="https://www.eum.go.kr/web/op/sv/svItemDet.jsp?currentPageNo=1&dataCd=004&dataTypeCd=SHP&selectType=subject"
s=requests.Session()
r=s.get(url,timeout=30,headers={"User-Agent":"Mozilla/5.0"})
r.raise_for_status()
html=r.text
patterns=[
    r'https?://[^"\']+',
    r'[^"\']+\.zip[^"\']*',
    r'onclick="([^"]+)"',
    r'(?:download|down|file)[A-Za-z0-9_]*\([^)]*\)',
    r'<form[^>]+action="([^"]+)"'
]
out={"url":r.url,"status":r.status_code,"length":len(html),"matches":{}}
for p in patterns:
    vals=[]
    for m in re.findall(p,html,re.I):
        if isinstance(m,tuple):m=" ".join(m)
        if "down" in str(m).lower() or ".zip" in str(m).lower() or "sv" in str(m).lower():
            vals.append(str(m)[:500])
    out["matches"][p]=vals[:200]
# save relevant lines around download keywords
lines=html.splitlines()
snips=[]
for i,line in enumerate(lines):
    if any(k in line.lower() for k in ["download","downfile","filedown",".zip","fn_down","fn_downfile","down("]):
        snips.append({"line":i+1,"text":line.strip()[:1000]})
out["snippets"]=snips[:300]
Path("data/eum_download_probe.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out,ensure_ascii=False,indent=2)[:12000])
