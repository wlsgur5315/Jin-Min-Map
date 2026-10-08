#!/usr/bin/env python3
import re, json, requests
from pathlib import Path

url="https://www.eum.go.kr/web/op/sv/svItemDet.jsp?currentPageNo=1&dataCd=004&dataTypeCd=SHP&selectType=subject"
s=requests.Session()
headers={"User-Agent":"Mozilla/5.0"}
r=s.get(url,timeout=30,headers=headers)
r.raise_for_status()
html=r.text

js_url="https://www.eum.go.kr/web/js/op/sv/svItemDet.js"
jr=s.get(js_url,timeout=30,headers={**headers,"Referer":url})
js=jr.text

out={
  "url":r.url,
  "status":r.status_code,
  "length":len(html),
  "js_status":jr.status_code,
  "js_length":len(js),
  "js_text":js,
  "download_ids":re.findall(r"dataDownload\('([^']+)'\)",html),
  "zip_names":re.findall(r">([^<]+\.zip)</td>",html,re.I),
}
Path("data/eum_svItemDet.js").write_text(js,encoding="utf-8")
Path("data/eum_download_probe.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in out.items() if k!="js_text"},ensure_ascii=False,indent=2))
