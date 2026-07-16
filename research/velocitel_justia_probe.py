#!/usr/bin/env python3
"""Probe deterministic Justia document paths for missing Velocitel filings."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
from bs4 import BeautifulSoup

OUT=Path('research-output/velocitel-justia-probe');RAW=OUT/'raw';FOUND=OUT/'found'
for p in (OUT,RAW,FOUND):p.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 public-record-research/1.0','Accept-Language':'en-US,en;q=0.9'})
DES=[1,7,13,14,15,16,17,22,25,26,27,30,57,58,59,63,64,66,67,70,71,72,73,77,78,82]
records=[];found=[]

def safe(v):return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:190] or 'item'
def fetch(label,url):
 try:
  r=S.get(url,timeout=60,allow_redirects=True);data=r.content;c=r.headers.get('content-type','');is_pdf=data.startswith(b'%PDF') or 'application/pdf' in c.lower();text=''
  if not is_pdf:
   try:text=re.sub(r'\s+',' ',BeautifulSoup(data,'lxml').get_text(' ',strip=True))[:20000]
   except:text=data.decode('utf-8','replace')[:20000]
  rec={'label':label,'url':url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'sha256':hashlib.sha256(data).hexdigest() if data else None,'is_pdf':is_pdf,'text':text};records.append(rec);print(label,r.status_code,len(data),r.url,c,flush=True)
  if is_pdf and r.status_code==200:
   path=FOUND/f'{label}.pdf';path.write_bytes(data);rec['saved']=str(path);found.append(rec)
  elif r.status_code==200 and any(k in text.lower() for k in ['velocitel','bauer','delta oaks','preliminary injunction','motion for sanctions']):
   path=FOUND/f'{label}.html';path.write_bytes(data);rec['saved']=str(path);found.append(rec)
  else:
   path=RAW/f'{label}.html';path.write_bytes(data)
 except Exception as e:records.append({'label':label,'url':url,'error':repr(e)});print(label,'ERROR',repr(e),flush=True)

for de in DES:
 paths=[
  f'https://docs.justia.com/cases/federal/district-courts/north-carolina/ncedce/5%3A2015cv00628/147135/{de}',
  f'https://docs.justia.com/cases/federal/district-courts/north-carolina/ncedce/5:2015cv00628/147135/{de}',
  f'https://cases.justia.com/federal/district-courts/north-carolina/ncedce/5%3A2015cv00628/147135/{de}/0.pdf',
  f'https://cases.justia.com/federal/district-courts/north-carolina/ncedce/5:2015cv00628/147135/{de}/0.pdf',
  f'https://docs.justia.com/cases/federal/district-courts/north-carolina/ncedce/5%3A2015cv00628/147135/{de}/0.pdf',
  f'https://law.justia.com/cases/federal/district-courts/north-carolina/ncedce/5%3A2015cv00628/147135/{de}/',
 ]
 for i,u in enumerate(paths,1):fetch(f'de{de}_p{i}',u)
(OUT/'records.json').write_text(json.dumps(records,indent=2),encoding='utf-8');(OUT/'found.json').write_text(json.dumps(found,indent=2),encoding='utf-8')
summary={'requests':len(records),'found_records':len(found),'pdfs_found':sum(1 for x in found if x.get('is_pdf')),'note':'Deterministic public Justia paths only.'};(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2),flush=True)
