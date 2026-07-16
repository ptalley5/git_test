#!/usr/bin/env python3
"""Compact high-value search for public copies of missing Velocitel filings."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from urllib.parse import parse_qs,quote_plus,unquote,urljoin,urlparse
import requests
from bs4 import BeautifulSoup
OUT=Path('research-output/velocitel-public-uploads-compact');RAW=OUT/'raw';FOUND=OUT/'found'
for p in (OUT,RAW,FOUND):p.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 public-record-research/1.0','Accept-Language':'en-US,en;q=0.9'})
Q=['"Velocitel, Inc. d/b/a FDH Velocitel v. Bauer"','"5:15-cv-00628"','"13104645147"','"13104696400"','"13105515142"','"13105533867"','"gov.uscourts.nced.147135.1.0.pdf"','"gov.uscourts.nced.147135.14.0.pdf"','"gov.uscourts.nced.147135.58.0.pdf"','site:documentcloud.org Velocitel Bauer','site:assets.documentcloud.org Velocitel','site:drive.google.com "5:15-cv-00628"','site:law360.com "Velocitel" Bauer','site:casetext.com "Velocitel" Bauer','site:muckrock.com "Velocitel" Bauer']
records=[];results=[];cands=[];downloads=[]
def safe(v):return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:180] or 'item'
def fetch(label,url,timeout=60,save=True):
 try:
  r=S.get(url,timeout=timeout,allow_redirects=True);data=r.content;c=r.headers.get('content-type','');path=None
  if save:
   ext='.pdf' if data.startswith(b'%PDF') or 'pdf' in c.lower() else '.json' if 'json' in c.lower() else '.html' if 'html' in c.lower() or data.lstrip().startswith(b'<') else '.bin';path=RAW/f'{safe(label)}{ext}';path.write_bytes(data)
  records.append({'label':label,'requested_url':r.request.url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'sha256':hashlib.sha256(data).hexdigest() if data else None,'saved':str(path) if path else None});print(label,r.status_code,len(data),r.url,flush=True);return r
 except Exception as e:records.append({'label':label,'requested_url':url,'error':repr(e)});print(label,'ERROR',repr(e),flush=True);return None
def text(r):
 try:return re.sub(r'\s+',' ',BeautifulSoup(r.content,'lxml').get_text(' ',strip=True)) if 'html' in r.headers.get('content-type','').lower() or r.content.lstrip().startswith(b'<') else r.text
 except:return ''
def unwrap(u,base):
 u=urljoin(base,u)
 try:
  qs=parse_qs(urlparse(u).query)
  for k in ['url','u','q','target','click_url']:
   if qs.get(k) and unquote(qs[k][0]).startswith('http'):return unquote(qs[k][0])
 except:pass
 return u
def rel(u,lab=''):
 s=(u+' '+lab).lower();return any(x in s for x in ['velocitel','131046','131055','147135','5670822','5:15-cv-00628','gov.uscourts.nced.147135']) or any(x in s for x in ['documentcloud','drive.google','law360','casetext','muckrock','courtlistener','archive.org','justia','perma.cc'])
for i,q in enumerate(Q,1):
 for eng,url in [('google','https://r.jina.ai/http://www.google.com/search?q='+quote_plus(q)),('bing','https://r.jina.ai/http://www.bing.com/search?q='+quote_plus(q)),('brave','https://search.brave.com/search?q='+quote_plus(q)+'&source=web')]:
  r=fetch(f'q{i}_{eng}',url,75)
  if not r:continue
  t=text(r);links=[]
  soup=BeautifulSoup(r.content,'lxml')
  for a in soup.find_all('a',href=True):
   lab=' '.join(a.get_text(' ',strip=True).split());u=unwrap(a.get('href'),r.url)
   if u.startswith('http') and rel(u,lab):links.append({'text':lab,'url':u})
  for u in re.findall(r'https?://[^\s<>")\]]+',r.text):
   u=u.rstrip('.,;')
   if rel(u):links.append({'text':'','url':u})
  seen=set();uniq=[]
  for x in links:
   if x['url'] in seen:continue
   seen.add(x['url']);uniq.append(x);cands.append({'query':q,'engine':eng,**x})
  results.append({'query':q,'engine':eng,'status':r.status_code,'links':uniq[:300],'text':t[:200000]})
DIRECT={'documentcloud':'https://api.www.documentcloud.org/api/documents/?q='+quote_plus('Velocitel Bauer'),'ia':'https://archive.org/advancedsearch.php?q='+quote_plus('("13104645147" OR "13104696400" OR "13105515142" OR "5:15-cv-00628")')+'&fl[]=identifier,title,description&rows=200&output=json','urlscan':'https://urlscan.io/api/v1/search/?q='+quote_plus('"5:15-cv-00628"'),'muckrock':'https://www.muckrock.com/search/?q='+quote_plus('Velocitel Bauer'),'perma':'https://perma.cc/search?url='+quote_plus('ecf.nced.uscourts.gov/doc1/13104645147')}
for lab,u in DIRECT.items():
 r=fetch(lab,u,75)
 if r:results.append({'query':lab,'engine':'direct','status':r.status_code,'text':text(r)[:300000]})
allowed=['documentcloud.org','assets.documentcloud.org','drive.google.com','law360.com','law360news.com','casetext.com','muckrock.com','courtlistener.com','archive.org','justia.com','perma.cc']
seen=set()
for i,c in enumerate(cands,1):
 u=c['url'];host=urlparse(u).hostname or ''
 if not any(host==h or host.endswith('.'+h) for h in allowed) or u in seen:continue
 seen.add(u)
 if len(seen)>100:break
 r=fetch(f'cand_{i}',u,60,False)
 if not r:continue
 t=text(r)[:30000];isp=r.content.startswith(b'%PDF') or 'pdf' in r.headers.get('content-type','').lower();match=any(x in (u+' '+t).lower() for x in ['velocitel','5:15-cv-00628','13104645147','13105515142','gov.uscourts.nced.147135'])
 if isp or match:
  ext='.pdf' if isp else '.html';p=FOUND/f'{safe(str(i)+"_"+u)}{ext}';p.write_bytes(r.content);downloads.append({'candidate':c,'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'size':len(r.content),'is_pdf':isp,'matched':match,'saved':str(p),'text':t})
uniq=[];seen2=set()
for c in cands:
 if c['url'] in seen2:continue
 seen2.add(c['url']);uniq.append(c)
for name,data in [('search_results',results),('candidate_urls',uniq),('downloads',downloads),('fetch_records',records)]: (OUT/(name+'.json')).write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
summary={'queries':len(Q),'candidate_urls':len(uniq),'candidate_urls_fetched':len(seen),'relevant_downloads':len(downloads),'pdfs_found':sum(x['is_pdf'] for x in downloads),'note':'Public sources only.'};(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2),flush=True)
