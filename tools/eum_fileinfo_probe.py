#!/usr/bin/env python3
import json, requests
from pathlib import Path

page="https://www.eum.go.kr/web/op/sv/svItemDet.jsp?currentPageNo=1&dataCd=004&dataTypeCd=SHP&selectType=subject"
api="https://www.eum.go.kr/web/op/sv/svItemAjaxXml.jsp"
s=requests.Session()
headers={"User-Agent":"Mozilla/5.0","Referer":page,"X-Requested-With":"XMLHttpRequest"}
r=s.get(page,headers=headers,timeout=30); r.raise_for_status()
resp=s.post(api,headers=headers,data={
  "function":"selectFileInfo",
  "dataCd":"004",
  "dataTypeCd":"SHP",
  "refDt":"",
  "fileId":"675"
},timeout=60)
out={
 "status":resp.status_code,
 "content_type":resp.headers.get("content-type"),
 "text":resp.text[:20000],
 "cookies":s.cookies.get_dict()
}
Path("data/eum_fileinfo_probe.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out,ensure_ascii=False,indent=2))
