#!/usr/bin/env python3
"""Probe public RECAP/Internet Archive attachment paths for key Velocitel filings."""
from __future__ import annotations
import concurrent.futures as cf
import hashlib,json,re
from pathlib import Path
import requests

OUT=Path('research-output/velocitel-attachment-probe');RAW=OUT/'raw';FOUND=OUT/'found'
for p in (OUT,RAW,FOUND):p.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 public-record-research/1.0','Accept-Language':'en-US,en;q=0.9'})
CASES={
 'bauer':{'identifier':'gov.uscourts.nced.147135','entries':[1,7,13,14,15,16,17,22,25,26,27,30,57,58,59,63,64,66,67,70,71,72,73,77,78,82],'max_att':15},
 'hardy':{'identifier':'gov.uscourts.nced.147131','entries':[1,8,9,10,11,12,13,14,15,16,17,18,19,20,55,57,64,65,72,89],'max_att':15},
 'hoffman':{'identifier':'gov.uscourts.cod.160151','entries':[1,5,6,8,26],'max_att':12},
}
records=[];found=[]

def safe(v):return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:190] or 'item'
def get_one(task):
 case,identifier,de,att,source,url=task
 try:
  r=S.get(url,timeout=40,allow_redirects=True,headers={'Range':'bytes=0-4095'});data=r.content;c=r.headers.get('content-type','');is_pdf=data.startswith(b'%PDF') or 'application/pdf' in c.lower();rec={'case':case,'identifier':identifier,'entry':de,'attachment':att,'source':source,'url':url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'is_pdf_prefix':is_pdf,'sha256_prefix':hashlib.sha256(data).hexdigest() if data else None}
  if r.status_code==200 and is_pdf:
   # Fetch full PDF without Range, if the server honored the partial request.
   rr=S.get(url,timeout=90,allow_redirects=True);full=rr.content
   if rr.status_code==200 and full.startswith(b'%PDF'):
    path=FOUND/f'{case}_de{de}_att{att}_{source}.pdf';path.write_bytes(full);rec.update({'full_size':len(full),'sha256':hashlib.sha256(full).hexdigest(),'saved':str(path)});found.append(rec)
  print(case,de,att,source,r.status_code,len(data),c,flush=True);return rec
 except Exception as e:
  rec={'case':case,'identifier':identifier,'entry':de,'attachment':att,'source':source,'url':url,'error':repr(e)};print(case,de,att,source,'ERROR',repr(e),flush=True);return rec

tasks=[]
for case,c in CASES.items():
 ident=c['identifier']
 for de in c['entries']:
  for att in range(0,c['max_att']+1):
   fn=f'{ident}.{de}.{att}.pdf'
   tasks.append((case,ident,de,att,'courtlistener',f'https://storage.courtlistener.com/recap/{ident}/{fn}'))
   tasks.append((case,ident,de,att,'archive',f'https://archive.org/download/{ident}/{fn}'))
with cf.ThreadPoolExecutor(max_workers=18) as ex:
 for rec in ex.map(get_one,tasks):records.append(rec)
(OUT/'records.json').write_text(json.dumps(records,indent=2),encoding='utf-8');(OUT/'found.json').write_text(json.dumps(found,indent=2),encoding='utf-8')
summary={'requests':len(records),'pdfs_found':len(found),'unique_found':len({(x['case'],x['entry'],x['attachment']) for x in found}),'note':'Public RECAP and Internet Archive paths only; no PACER access.'};(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2),flush=True)
