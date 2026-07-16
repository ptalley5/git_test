#!/usr/bin/env python3
"""Research other public Velocitel cases for overlapping former-employee/IP facts."""
from __future__ import annotations
import hashlib, io, json, re
from pathlib import Path
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT=Path('research-output/velocitel-other-cases');RAW=OUT/'raw';PDF=OUT/'pdf';TEXT=OUT/'text'
for p in (OUT,RAW,PDF,TEXT):p.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 public-record-research/1.0','Accept-Language':'en-US,en;q=0.9'})
records=[];cases=[];documents=[];hits=[]
KEYWORDS=['flash drive','usb','storage media','hard drive','source code','software','trade secret','confidential','proprietary','misappropriat','noncompete','non-compete','former employee','foundation','nondestructive','Delta Oaks','Cory Bauer','Joseph Borrelli','Kathy Hoffman Gillis','Vertex Innovations','Corbin Hardy','Wave Inspection']
TARGETS={
 'hoffman':{'docket_id':'5584426','ia':'gov.uscourts.cod.160151','pacer_case':'160151','initial_doc':'03906153990','title':'Velocitel, Inc. v. Hoffman Gillis et al','court':'cod'},
 'bauer':{'docket_id':'5670822','ia':'gov.uscourts.nced.147135','pacer_case':'147135','initial_doc':'13104645147','title':'Velocitel v. Bauer','court':'nced'},
 'hardy':{'docket_id':'5688345','ia':'gov.uscourts.nced.147131','pacer_case':'147131','initial_doc':None,'title':'Velocitel v. Hardy','court':'nced'},
}
QUERIES=['"Velocitel, Inc. v. Hoffman Gillis"','"Velocitel" "Kathy Hoffman Gillis"','"Velocitel" "Vertex Innovations"','"1:15-cv-02761"','"03906153990"','"Velocitel" former employee lawsuit','"Velocitel" noncompete employee','"FDH Velocitel" trade secret former employee','"Velocitel" "Wave Inspection Technologies"','"Velocitel" "Delta Oaks Group"']

def safe(v):return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:190] or 'item'
def fetch(label,url,params=None,timeout=75,save=True):
 try:
  r=S.get(url,params=params,timeout=timeout,allow_redirects=True);data=r.content;c=r.headers.get('content-type','');path=None
  if save:
   ext='.pdf' if data.startswith(b'%PDF') or 'pdf' in c.lower() else '.json' if 'json' in c.lower() else '.html' if 'html' in c.lower() or data.lstrip().startswith(b'<') else '.bin';path=RAW/f'{safe(label)}{ext}';path.write_bytes(data)
  records.append({'label':label,'requested_url':r.request.url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'sha256':hashlib.sha256(data).hexdigest() if data else None,'saved':str(path) if path else None});print(label,r.status_code,len(data),r.url,flush=True);return r
 except Exception as e:records.append({'label':label,'requested_url':url,'error':repr(e)});print(label,'ERROR',repr(e),flush=True);return None
def clean(data):
 try:return re.sub(r'\s+',' ',BeautifulSoup(data,'lxml').get_text(' ',strip=True))
 except:return data.decode('utf-8','replace')
def scan(source,url,text,extra=None):
 lo=text.lower()
 for kw in KEYWORDS:
  pos=0;count=0
  while True:
   i=lo.find(kw.lower(),pos)
   if i<0:break
   count+=1
   if count<=15:
    row={'source':source,'url':url,'keyword':kw,'snippet':re.sub(r'\s+',' ',text[max(0,i-600):i+len(kw)+1600])};row.update(extra or {});hits.append(row)
   pos=i+max(1,len(kw))
def pdftext(data):
 out=[];errs=[]
 try:
  reader=PdfReader(io.BytesIO(data),strict=False)
  for i,p in enumerate(reader.pages,1):
   try:t=p.extract_text() or ''
   except Exception as e:t='';errs.append(f'page {i}: {e!r}')
   out.append(f'\n===== PAGE {i} =====\n{t}')
 except Exception as e:errs.append(repr(e))
 return ''.join(out),errs

for name,c in TARGETS.items():
 # Public docket pages and PacerMonitor.
 urls=[
  ('cl',f'https://www.courtlistener.com/docket/{c["docket_id"]}/?order_by=asc'),
  ('cl_search',f'https://www.courtlistener.com/?type=r&q='+quote_plus(c['title'])),
  ('pacer_monitor',f'https://www.pacermonitor.com/public/case/{c["pacer_case"]}/'+('Velocitel_Inc_v_Hoffman_Gillis_et_al' if name=='hoffman' else 'Velocitel_Inc_v_Bauer_et_al')),
  ('justia',f'https://dockets.justia.com/docket/'+('colorado/codce/1%3A2015cv02761/160151' if name=='hoffman' else 'north-carolina/ncedce/5%3A2015cv00628/147135')),
 ]
 for kind,url in urls:
  r=fetch(f'{name}_{kind}',url)
  if r:scan(kind,r.url,clean(r.content),{'case':name})
 r=fetch(f'{name}_ia_meta','https://archive.org/metadata/'+c['ia'])
 if not r:continue
 try:meta=r.json()
 except Exception:continue
 case={'name':name,'target':c,'metadata':meta.get('metadata',{}),'files':meta.get('files',[])};cases.append(case)
 for f in meta.get('files',[]) or []:
  fn=f.get('name','')
  if fn.endswith('.docket.json'):
   rr=fetch(f'{name}_docket_json',f'https://archive.org/download/{c["ia"]}/{fn}')
   if rr:
    try:d=rr.json();case['docket_json']=d;scan('docket_json',rr.url,json.dumps(d,ensure_ascii=False),{'case':name})
    except:pass
  elif fn.lower().endswith('.pdf'):
   rr=fetch(f'{name}_{safe(fn)}',f'https://archive.org/download/{c["ia"]}/{fn}',timeout=120,save=False)
   if rr and rr.status_code==200 and rr.content.startswith(b'%PDF'):
    pp=PDF/safe(fn);pp.write_bytes(rr.content);t,errs=pdftext(rr.content);tp=TEXT/(safe(fn)+'.txt');tp.write_text(t,encoding='utf-8',errors='replace');documents.append({'case':name,'name':fn,'url':rr.url,'pdf':str(pp),'text':str(tp),'errors':errs});scan('pdf',rr.url,t,{'case':name,'name':fn})

# Search indexes and archive exact initial complaint URL for Hoffman.
for i,q in enumerate(QUERIES,1):
 for engine,url in [('google_jina','https://r.jina.ai/http://www.google.com/search?q='+quote_plus(q)),('bing_jina','https://r.jina.ai/http://www.bing.com/search?q='+quote_plus(q)),('ddg','https://html.duckduckgo.com/html/?q='+quote_plus(q))]:
  r=fetch(f'search_{i}_{engine}',url,timeout=75)
  if r:scan(engine,r.url,clean(r.content),{'query':q})

for label,url in [('wb_hoffman_doc','https://web.archive.org/cdx/search/cdx'),('arquivo_hoffman_doc','https://arquivo.pt/wayback/cdx')]:
 r=fetch(label,url,params={'url':'https://ecf.cod.uscourts.gov/doc1/03906153990*','output':'json','filter':'statuscode:200','limit':'1000'},timeout=90)
 if r:
  try:documents.append({'kind':label,'archive_results':r.json()})
  except:documents.append({'kind':label,'text':r.text[:200000]})

(OUT/'cases.json').write_text(json.dumps(cases,indent=2,ensure_ascii=False),encoding='utf-8');(OUT/'documents.json').write_text(json.dumps(documents,indent=2,ensure_ascii=False),encoding='utf-8');(OUT/'hits.json').write_text(json.dumps(hits,indent=2,ensure_ascii=False),encoding='utf-8');(OUT/'fetch_records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
summary={'cases':len(cases),'free_pdfs':sum(1 for x in documents if x.get('pdf')),'keyword_hits':len(hits),'fetches':len(records),'note':'Public open sources only.'};(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2),flush=True)
