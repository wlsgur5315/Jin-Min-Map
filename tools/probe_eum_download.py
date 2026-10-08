#!/usr/bin/env python3
import re, json, requests
from pathlib import Path
url="https://www.eum.go.kr/web/op/sv/svItemDet.jsp?currentPageNo=1&dataCd=004&dataTypeCd=SHP&selectType=subject"
s=requests.Session()
r=s.get(url,timeout=30,headers={"User-Agent":"Mozilla/5.0"})
r.raise_for_status()
html=r.text
js_url="https://www.eum.go.kr/web/js/op/sv/svItemDet.js"
try:
    jr=s.get(js_url,timeout=30,headers={"User-Agent":"Mozilla/5.0","Referer":url})
    js=jr.text
    js_status=jr.status_code
except Exception as e:
    js=""
    js_status=str(e)
patterns=[
    r'https?://[^"\']+',
    r'[^"\']+\.zip[^"\']*',
    r'onclick="([^"]+)"',
    r'(?:download|down|file)[A-Za-z0-9_]*\([^)]*\)',
    r'<form[^>]+action="([^"]+)"'
]
out={"url":r.url,"status":r.status_code,"length":len(html),"matches":{},"js_length":len(js),"js_status":js_status}
out["js_context"]=[line.strip()[:1500] for line in js.splitlines() if "dataDownload" in line or "download" in line.lower() or "file" in line.lower()][:300]
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

# locate dataDownload function / external scripts
for i,line in enumerate(lines):
    if "dataDownload" in line or ("<script" in line and "src=" in line):
        out.setdefault("function_context",[]).append({"line":i+1,"text":line.strip()[:1500]})
Path("data/eum_svItemDet.js").write_text(js,encoding="utf-8")\nPath("data/eum_download_probe.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out,ensure_ascii=False,indent=2)[:12000])
