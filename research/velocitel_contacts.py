#!/usr/bin/env python3
"""Find public contact paths for counsel/libraries/archives that may share unsealed filings."""
from __future__ import annotations
import hashlib,json,re,time
from pathlib import Path
from urllib.parse import quote_plus,urljoin
import requests
from bs4 import BeautifulSoup
OUT=Path('research-output/free-contact-routes'); RAW=OUT/'raw'; OUT.mkdir(parents=True,exist_ok=True); RAW.mkdir(exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 public-record-research/1.0','Accept-Language':'en-US,en;q=0.9'})
records=[]; candidates=[]
QUERIES=[
 '"Amy Reeder Worley" attorney','"Amy Reeder Worley" Velocitel','"Amy Worley" Raleigh lawyer',
 '"5:15-cv-00628" counsel','"5:15-CV-628-D" attorney','"Velocitel, Inc." "Bauer" attorney',
 '"Velocitel v. Bauer" lawyer','"FDH Velocitel" "Cory Bauer" attorney',
 '"13104645155"','"13104696374"','"13104709934"','"13104818334"','"13105528674"',
 '"Cory Bauer" litigation attorney North Carolina','"Joseph Borrelli" litigation attorney North Carolina',
 '"Delta Oaks Group" litigation counsel','site:smithlaw.com "Amy Worley"','site:smithandersonlaw.com "Amy Worley"',
 'site:ncbar.gov "Amy Reeder Worley"','site:ncbar.gov "Amy Worley"',
]
DIRECT={
 'justia_lawyer_search':'https://lawyers.justia.com/search?match=any&query=Amy+Reeder+Worley',
 'justia_case':'https://dockets.justia.com/docket/north-carolina/ncedce/5%3A2015cv00628/147135',
 'courtlistener_case':'https://www.courtlistener.com/docket/5670822/velocitel-inc-dba-fdh-velocitel-v-bauer/',
 'nced_locations':'https://www.nced.uscourts.gov/courtlocations/default.aspx?loc=ral',
 'nced_contacts':'https://www.nced.uscourts.gov/contact/default.aspx',
 'pacer_help':'https://pacer.uscourts.gov/help/contact-us',
 'flp_contact':'https://free.law/contact/',
 'nc_supreme_library':'https://www.nccourts.gov/locations/supreme-court-of-north-carolina/supreme-court-library',
 'unc_law_library':'https://law.unc.edu/library/',
 'duke_law_library':'https://law.duke.edu/lib/',
 'nccu_law_library':'https://law.nccu.edu/academics/library/',
 'campbell_law_library':'https://law.campbell.edu/learn-more/law-library/',
}
EMAIL_RE=re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')
PHONE_RE=re.compile(r'(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}')
def safe(v):return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:180] or 'item'
def fetch(label,url,timeout=60):
 try:
  r=S.get(url,timeout=timeout,allow_redirects=True); data=r.content; c=r.headers.get('content-type',''); ext='.json' if 'json' in c.lower() else '.html' if 'html' in c.lower() or data.lstrip().startswith(b'<') else '.bin'; fp=RAW/f'{safe(label)}{ext}'; fp.write_bytes(data)
  text=re.sub(r'\s+',' ',BeautifulSoup(data,'lxml').get_text(' ',strip=True)) if ext=='.html' else data.decode('utf-8','replace')
  links=[]
  if ext=='.html':
   soup=BeautifulSoup(data,'lxml'); links=[{'text':' '.join(a.get_text(' ',strip=True).split()),'href':urljoin(r.url,a.get('href'))} for a in soup.find_all('a',href=True)]
  rec={'label':label,'url':url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'sha256':hashlib.sha256(data).hexdigest() if data else None,'saved':str(fp),'emails':sorted(set(EMAIL_RE.findall(text))),'phones':sorted(set(PHONE_RE.findall(text))),'text_sample':text[:60000],'links':links[:1000]}; records.append(rec); print(label,r.status_code,len(data),r.url,flush=True); return rec
 except Exception as e: records.append({'label':label,'url':url,'error':repr(e)}); print(label,'ERROR',repr(e),flush=True); return None
for label,url in DIRECT.items():fetch(label,url)
for i,q in enumerate(QUERIES,1):
 for engine,url in [('google_jina','https://r.jina.ai/http://www.google.com/search?q='+quote_plus(q)),('bing_jina','https://r.jina.ai/http://www.bing.com/search?q='+quote_plus(q)),('ddg','https://html.duckduckgo.com/html/?q='+quote_plus(q))]:fetch(f'q{i}_{engine}',url,75)
 time.sleep(.1)
# Follow likely professional, court, library, bar and firm links discovered in results.
seen=set(); follow=[]
for rec in records:
 for link in rec.get('links',[]):
  u=link.get('href',''); t=(link.get('text','')+' '+u).lower()
  if any(k in t for k in ['amy worley','amy reeder','smith anderson','attorney','lawyer','counsel','law library','court library','ncbar','nccourts','free.law/contact']):
   if u.startswith('http') and u not in seen:seen.add(u);follow.append(u)
for i,u in enumerate(follow[:150],1):fetch(f'follow_{i}',u,50)
# Summarize candidate contacts with context.
for rec in records:
 if rec.get('emails') or rec.get('phones'):
  candidates.append({'label':rec.get('label'),'url':rec.get('final_url') or rec.get('url'),'emails':rec.get('emails'),'phones':rec.get('phones'),'context':rec.get('text_sample','')[:10000]})
(OUT/'records.json').write_text(json.dumps(records,indent=2),encoding='utf-8'); (OUT/'candidate_contacts.json').write_text(json.dumps(candidates,indent=2),encoding='utf-8'); (OUT/'summary.json').write_text(json.dumps({'fetches':len(records),'candidate_pages':len(candidates)},indent=2),encoding='utf-8'); print(json.dumps({'fetches':len(records),'candidate_pages':len(candidates)},indent=2))
