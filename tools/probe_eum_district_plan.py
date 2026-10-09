#!/usr/bin/env python3
import requests,re,json
from bs4 import BeautifulSoup
URL="https://www.eum.go.kr/web/op/sv/svItemDet.jsp?currentPageNo=1&dataCd=005&dataTypeCd=SHP&selectType=subject"
r=requests.get(URL,headers={"User-Agent":"Mozilla/5.0"},timeout=60)
r.raise_for_status()
html=r.text
needle="지구단위계획구역_20260929_전국.zip"
idx=html.find(needle)
out={"status":r.status_code,"length":len(html),"found":idx>=0}
if idx>=0:
    out["snippet"]=html[max(0,idx-4000):idx+5000]
# collect forms and scripts/onclicks/hrefs around 'download'
soup=BeautifulSoup(html,"html.parser")
out["forms"]=[{"action":f.get("action"),"method":f.get("method"),"id":f.get("id"),"name":f.get("name"),
               "inputs":[{"name":i.get("name"),"value":i.get("value"),"type":i.get("type")} for i in f.find_all("input")[:30]]}
              for f in soup.find_all("form")]
hits=[]
for tag in soup.find_all(True):
    txt=" ".join([str(tag.get("href") or ""),str(tag.get("onclick") or ""),str(tag.get("action") or ""),tag.get_text(" ",strip=True)])
    if "download" in txt.lower() or "down" in txt.lower() or "20260929" in txt:
        hits.append({"tag":tag.name,"id":tag.get("id"),"class":tag.get("class"),"href":tag.get("href"),"onclick":tag.get("onclick"),"text":tag.get_text(" ",strip=True)[:300]})
out["hits"]=hits[:200]
open("data/eum_district_plan_download_probe.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False,indent=2)[:30000])
