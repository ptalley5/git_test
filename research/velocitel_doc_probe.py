#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

OUT=Path('research-output/document-probe'); OUT.mkdir(parents=True,exist_ok=True)
RAW=OUT/'raw'; RAW.mkdir(exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36','Accept-Language':'en-US,en;q=0.9'})
# PlainSite file IDs from its public docket page.
docs={
 'complaint_de1':'133628108',
 'initial_motion_de4':'133628111',
 'expedited_discovery_de15':'133628119',
 'pi_motion_de21':'133628129',
 'answer_de44':'133628165',
 'sanctions_de57':'133628175',
 'compel_de63':'133628181',
 'compel_de66':'133628184',
}
patterns=[
 'https://www.plainsite.org/dockets/request.html?id={id}',
 'https://www.plainsite.org/dockets/download.html?id={id}',
 'https://www.plainsite.org/dockets/view.html?id={id}',
 'https://www.plainsite.org/dockets/document.html?id={id}',
 'https://www.plainsite.org/dockets/get.html?id={id}',
 'https://www.plainsite.org/dockets/file.html?id={id}',
 'https://www.plainsite.org/dockets/request/index.html?id={id}',
]
results=[]
for label,docid in docs.items():
 for pi,pat in enumerate(patterns,1):
  url=pat.format(id=docid)
  try:
   r=s.get(url,timeout=45,allow_redirects=True)
   ctype=r.headers.get('content-type','')
   data=r.content
   ext='.pdf' if data.startswith(b'%PDF') or 'pdf' in ctype.lower() else '.html' if 'html' in ctype.lower() else '.bin'
   fp=RAW/f'{label}_{pi}{ext}'; fp.write_bytes(data)
   text=''
   links=[]
   if ext=='.html':
    soup=BeautifulSoup(data,'lxml')
    text=' '.join(soup.get_text(' ',strip=True).split())[:10000]
    links=[{'text':' '.join(a.get_text(' ',strip=True).split()),'href':urljoin(r.url,a.get('href'))} for a in soup.find_all('a',href=True)]
   results.append({'label':label,'docid':docid,'url':url,'status':r.status_code,'final_url':r.url,'content_type':ctype,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'saved':str(fp),'text':text,'links':links[:300]})
   print(label,pi,r.status_code,len(data),r.url,ctype)
  except Exception as e:
   results.append({'label':label,'docid':docid,'url':url,'error':repr(e)})

# Inspect public docket HTML and JS for hidden download/request routes.
for url,label in [
 ('https://www.plainsite.org/dockets/index.html?id=8068743','plainsite_case'),
 ('https://www.plainsite.org/profiles/velocitel-inc-dba-fdh-velocitel/','plainsite_profile'),
]:
 try:
  r=s.get(url,timeout=45)
  fp=RAW/f'{label}.html'; fp.write_bytes(r.content)
  soup=BeautifulSoup(r.content,'lxml')
  scripts=[]
  for tag in soup.find_all('script'):
   if tag.get('src'): scripts.append(urljoin(r.url,tag.get('src')))
  results.append({'label':label,'url':url,'status':r.status_code,'final_url':r.url,'size':len(r.content),'scripts':scripts,'text':' '.join(soup.get_text(' ',strip=True).split())[:20000]})
  for i,surl in enumerate(scripts[:30],1):
   try:
    rr=s.get(surl,timeout=30)
    (RAW/f'{label}_script_{i}.js').write_bytes(rr.content)
   except Exception: pass
 except Exception as e: results.append({'label':label,'url':url,'error':repr(e)})

# PACER and CourtListener direct candidates for the complaint.
for label,url in [
 ('pacer_complaint','https://ecf.nced.uscourts.gov/doc1/13104645147?caseid=147135'),
 ('pacer_complaint_bare','https://ecf.nced.uscourts.gov/doc1/13104645147'),
 ('courtlistener_complaint_page','https://www.courtlistener.com/docket/5670822/1/velocitel-inc-dba-fdh-velocitel-v-bauer/'),
 ('courtlistener_storage','https://storage.courtlistener.com/recap/gov.uscourts.nced.147135/gov.uscourts.nced.147135.1.0.pdf'),
 ('archive_complaint','https://archive.org/download/gov.uscourts.nced.147135/gov.uscourts.nced.147135.1.0.pdf'),
]:
 try:
  r=s.get(url,timeout=60,allow_redirects=True)
  ext='.pdf' if r.content.startswith(b'%PDF') or 'pdf' in r.headers.get('content-type','').lower() else '.html'
  fp=RAW/f'{label}{ext}'; fp.write_bytes(r.content)
  results.append({'label':label,'url':url,'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'size':len(r.content),'saved':str(fp),'text':' '.join(BeautifulSoup(r.content,'lxml').get_text(' ',strip=True).split())[:10000] if ext=='.html' else ''})
 except Exception as e: results.append({'label':label,'url':url,'error':repr(e)})

(OUT/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print('Wrote',len(results),'probe records')
