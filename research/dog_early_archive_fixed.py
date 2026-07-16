#!/usr/bin/env python3
"""Recover early Delta Oaks pages from Wayback with corrected CDX parameters."""
from __future__ import annotations
import hashlib, json, re, time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

OUT=Path('research-output/dog-early-archive-fixed');RAW=OUT/'raw';FOUND=OUT/'found'
for p in (OUT,RAW,FOUND):p.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 public-record-research/1.0','Accept-Language':'en-US,en;q=0.9'})
TERMS=['below grade foundation mapping','below-grade foundation mapping','unknown foundation investigation','unknown foundation investigations','foundation investigation','foundation mapping','proprietary','patent pending','patented','patent','Cory Bauer','Joe Borrelli','Joseph Borrelli','Rhett Butler','founding member','co-founder','October 2015','previous jobs','geotechnical investigation','parallel seismic','pull testing','reinforcing steel']
records=[];captures=[];pages=[];hits=[]

def safe(v):return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:190] or 'item'
def fetch(label,url,params=None,timeout=90,save=False):
 try:
  r=S.get(url,params=params,timeout=timeout,allow_redirects=True);data=r.content;c=r.headers.get('content-type','');path=None
  if save:
   ext='.json' if 'json' in c.lower() else '.html' if 'html' in c.lower() or data.lstrip().startswith(b'<') else '.bin';path=RAW/f'{safe(label)}{ext}';path.write_bytes(data)
  records.append({'label':label,'requested_url':r.request.url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'sha256':hashlib.sha256(data).hexdigest() if data else None,'saved':str(path) if path else None});print(label,r.status_code,len(data),r.url,flush=True);return r
 except Exception as e:records.append({'label':label,'requested_url':url,'error':repr(e)});print(label,'ERROR',repr(e),flush=True);return None
def text(data):
 soup=BeautifulSoup(data,'lxml');title=soup.title.get_text(' ',strip=True) if soup.title else None
 for tag in soup(['script','style','noscript']):tag.decompose()
 return re.sub(r'\s+',' ',soup.get_text(' ',strip=True)).strip(),title
def scan(original,ts,t):
 lo=t.lower()
 for term in TERMS:
  pos=0;count=0
  while True:
   i=lo.find(term.lower(),pos)
   if i<0:break
   count+=1
   if count<=12:hits.append({'original':original,'timestamp':ts,'term':term,'snippet':re.sub(r'\s+',' ',t[max(0,i-650):i+len(term)+1800])})
   pos=i+max(1,len(term))

# Broad host-level CDX query catches historical slugs not known in advance.
for scheme in ['http','https']:
 for host in ['deltaoaksgroup.com','www.deltaoaksgroup.com']:
  r=fetch(f'cdx_{scheme}_{host}', 'https://web.archive.org/cdx/search/cdx', params={'url':f'{scheme}://{host}/*','output':'json','fl':'timestamp,original,statuscode,mimetype,digest,length','filter':'statuscode:200','from':'2015','to':'2024','collapse':'digest','limit':'10000'},timeout=120,save=True)
  if not r:continue
  try:rows=r.json()
  except Exception:continue
  if not isinstance(rows,list) or len(rows)<2:continue
  head=rows[0]
  for row in rows[1:]:
   cap=dict(zip(head,row));captures.append(cap)

# Deduplicate and select all likely substantive pages through 2021, plus first capture per URL/year.
uniq={(c.get('timestamp'),c.get('original'),c.get('digest')):c for c in captures};captures=list(uniq.values())
by=defaultdict(list)
for c in captures:by[c.get('original','')].append(c)
selected={}
for original,rows in by.items():
 rows=sorted(rows,key=lambda c:c.get('timestamp',''))
 u=original.lower();score=sum(k in u for k in ['foundation','field','geotech','structural','leadership','cory','borrelli','butler','about','name','overview','home','service','inspection','patent'])
 for c in rows:
  ts=c.get('timestamp','');year=ts[:4]
  if c is rows[0] or score or ts<'20220101000000':selected[(ts,original)]=c
  # only one per URL/year if unscored to avoid excess
  if not score:
   break
# cap but prioritize relevant URLs and earliest timestamps
sel=sorted(selected.values(),key=lambda c:(-sum(k in c.get('original','').lower() for k in ['foundation','field','geotech','structural','leadership','cory','borrelli','butler','about','name','overview','home','service','inspection','patent']),c.get('timestamp','')))[:700]
for idx,c in enumerate(sel,1):
 r=fetch(f'replay_{idx}_{c.get("timestamp")}',f'https://web.archive.org/web/{c["timestamp"]}id_/{c["original"]}',timeout=100,save=False)
 if not r or r.status_code!=200 or not r.content:continue
 t,title=text(r.content);path=FOUND/f'{c["timestamp"]}_{safe(c["original"])}.html';path.write_bytes(r.content)
 pages.append({'timestamp':c['timestamp'],'original':c['original'],'replay_url':r.request.url,'final_url':r.url,'title':title,'size':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest(),'saved':str(path),'text':t[:300000]});scan(c['original'],c['timestamp'],t);time.sleep(.03)

(OUT/'captures.json').write_text(json.dumps(captures,indent=2),encoding='utf-8');(OUT/'pages.json').write_text(json.dumps(pages,indent=2,ensure_ascii=False),encoding='utf-8');(OUT/'hits.json').write_text(json.dumps(hits,indent=2,ensure_ascii=False),encoding='utf-8');(OUT/'fetch_records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
summary={'captures':len(captures),'selected':len(sel),'pages_recovered':len(pages),'keyword_hits':len(hits),'earliest_capture':min((c.get('timestamp','') for c in captures),default=None),'note':'Public Wayback captures only.'};(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2),flush=True)
