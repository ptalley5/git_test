#!/usr/bin/env python3
"""Search public document-upload and legal-mirror sites for missing Velocitel filings."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("research-output/velocitel-public-uploads")
RAW = OUT / "raw"
FOUND = OUT / "found"
for p in (OUT, RAW, FOUND): p.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 public-record-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

PACER_IDS = [
    "13104645147", "13104696383", "13104696400", "13104696466", "13104696485",
    "13104721692", "13105515113", "13105515142", "13105533867", "13105558489",
    "13105558508", "13105558553", "13105558557", "13105558604", "13105558614",
    "13105559282", "13105560840", "13105567016", "13105569002", "13105581061",
]
FILENAMES = [
    "gov.uscourts.nced.147135.1.0.pdf", "gov.uscourts.nced.147135.13.0.pdf",
    "gov.uscourts.nced.147135.14.0.pdf", "gov.uscourts.nced.147135.15.0.pdf",
    "gov.uscourts.nced.147135.16.0.pdf", "gov.uscourts.nced.147135.30.0.pdf",
    "gov.uscourts.nced.147135.57.0.pdf", "gov.uscourts.nced.147135.58.0.pdf",
    "gov.uscourts.nced.147135.59.0.pdf", "gov.uscourts.nced.147135.63.0.pdf",
    "gov.uscourts.nced.147135.64.0.pdf", "gov.uscourts.nced.147135.66.0.pdf",
    "gov.uscourts.nced.147135.67.0.pdf", "gov.uscourts.nced.147135.78.0.pdf",
]
BASE_QUERIES = [
    '"Velocitel, Inc. d/b/a FDH Velocitel v. Bauer"',
    '"Velocitel v. Bauer" complaint', '"Velocitel" "Cory Bauer" complaint',
    '"Velocitel" "Cory Bauer" "Motion for Sanctions"',
    '"FDH Velocitel" "Delta Oaks Group" litigation',
    '"5:15-cv-00628"', '"5:15-CV-628-D"', '"5:15-CV-628-BO"',
    '"147135" "Velocitel"', '"5670822" "Velocitel"',
    '"Cory Bauer" "flash drive" FDH', '"Delta Oaks" "flash drive" FDH',
    '"unknown foundation" "Delta Oaks" FDH',
]
SITE_QUERIES = [
    'site:documentcloud.org Velocitel Bauer', 'site:assets.documentcloud.org Velocitel',
    'site:drive.google.com "5:15-cv-00628"', 'site:docs.google.com "5:15-cv-00628"',
    'site:dropbox.com "Velocitel" Bauer', 'site:box.com "Velocitel" Bauer',
    'site:scribd.com "Velocitel" Bauer', 'site:issuu.com "Velocitel" Bauer',
    'site:law360.com "Velocitel" Bauer', 'site:assets.law360news.com Velocitel',
    'site:casetext.com "Velocitel" Bauer', 'site:leagle.com "Velocitel" Bauer',
    'site:law.justia.com "Velocitel" Bauer', 'site:cases.justia.com "Velocitel" Bauer',
    'site:storage.courtlistener.com/recap "147135"', 'site:archive.org/download/gov.uscourts.nced.147135',
    'site:muckrock.com "Velocitel" Bauer', 'site:perma.cc "5:15-cv-00628"',
    'site:archive.ph "5:15-cv-00628"', 'site:ghostarchive.org "Velocitel" Bauer',
    'site:s3.amazonaws.com "gov.uscourts.nced.147135"',
    'site:storage.googleapis.com "gov.uscourts.nced.147135"',
    'site:github.com "gov.uscourts.nced.147135"', 'site:gitlab.com "13104645147"',
]
queries = BASE_QUERIES + SITE_QUERIES + [f'"{x}"' for x in PACER_IDS] + [f'"{x}"' for x in FILENAMES]
records=[]; search_results=[]; candidates=[]; downloads=[]


def safe(v): return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:190] or 'item'
def fetch(label,url,params=None,timeout=70,save=True):
    try:
        r=S.get(url,params=params,timeout=timeout,allow_redirects=True);data=r.content;c=r.headers.get('content-type','');path=None
        if save:
            ext='.pdf' if data.startswith(b'%PDF') or 'pdf' in c.lower() else '.json' if 'json' in c.lower() else '.html' if 'html' in c.lower() or data.lstrip().startswith(b'<') else '.bin';path=RAW/f'{safe(label)}{ext}';path.write_bytes(data)
        records.append({'label':label,'requested_url':r.request.url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'sha256':hashlib.sha256(data).hexdigest() if data else None,'saved':str(path) if path else None});print(label,r.status_code,len(data),r.url,flush=True);return r
    except Exception as e:records.append({'label':label,'requested_url':url,'error':repr(e)});print(label,'ERROR',repr(e),flush=True);return None
def visible(data,ctype=''):
    try:
        if 'html' in ctype.lower() or data.lstrip().startswith(b'<'):return re.sub(r'\s+',' ',BeautifulSoup(data,'lxml').get_text(' ',strip=True))
        return data.decode('utf-8','replace')
    except:return ''
def normalize_link(href,base):
    if not href:return ''
    u=urljoin(base,href)
    # unwrap common search redirects
    try:
        p=urlparse(u);qs=parse_qs(p.query)
        for k in ['url','u','q','target','dest','destination','click_url']:
            if k in qs and qs[k]:
                cand=unquote(qs[k][0])
                if cand.startswith('http'):u=cand;break
    except:pass
    return u
def relevant_url(u,label=''):
    s=(u+' '+label).lower()
    return any(x in s for x in ['velocitel','bauer','delta-oaks','delta_oaks','131046','131047','131055','147135','5670822','5:15-cv-00628','5%3a2015cv00628','gov.uscourts.nced.147135']) or any(d in s for d in ['documentcloud','assets.documentcloud','drive.google','docs.google','dropbox','scribd','issuu','law360','casetext','leagle','courtlistener','archive.org','justia','muckrock','perma.cc','archive.ph','ghostarchive'])

def parse_search(q,engine,r):
    text=visible(r.content,r.headers.get('content-type',''))
    links=[]
    try:
        soup=BeautifulSoup(r.content,'lxml')
        for a in soup.find_all('a',href=True):
            lab=' '.join(a.get_text(' ',strip=True).split());u=normalize_link(a.get('href'),r.url)
            if u.startswith('http') and relevant_url(u,lab):links.append({'text':lab,'url':u})
    except:pass
    # raw URL extraction covers Jina text
    for u in re.findall(r'https?://[^\s<>")\]]+',r.text):
        u=u.rstrip('.,;')
        if relevant_url(u):links.append({'text':'','url':u})
    uniq=[];seen=set()
    for x in links:
        key=x['url']
        if key in seen:continue
        seen.add(key);uniq.append(x);candidates.append({'query':q,'engine':engine,**x})
    search_results.append({'query':q,'engine':engine,'status':r.status_code,'final_url':r.url,'links':uniq[:500],'text':text[:250000]})

for i,q in enumerate(queries,1):
    engines=[
        ('google_jina','https://r.jina.ai/http://www.google.com/search?q='+quote_plus(q)),
        ('bing_jina','https://r.jina.ai/http://www.bing.com/search?q='+quote_plus(q)),
        ('brave','https://search.brave.com/search?q='+quote_plus(q)+'&source=web'),
    ]
    for engine,url in engines:
        r=fetch(f'q{i}_{engine}',url,timeout=75)
        if r:parse_search(q,engine,r)
    time.sleep(.04)

# Direct public search APIs and index pages.
direct={
 'documentcloud_api_q':'https://api.www.documentcloud.org/api/documents/?q='+quote_plus('Velocitel Bauer'),
 'documentcloud_api_search':'https://api.www.documentcloud.org/api/documents/?search='+quote_plus('Velocitel Bauer'),
 'documentcloud_web':'https://www.documentcloud.org/app?q='+quote_plus('Velocitel Bauer'),
 'ia_pacerid':'https://archive.org/advancedsearch.php?q='+quote_plus('("13104645147" OR "13105515142" OR "5:15-cv-00628")')+'&fl[]=identifier,title,description,creator&rows=500&page=1&output=json',
 'urlscan_case':'https://urlscan.io/api/v1/search/?q='+quote_plus('"5:15-cv-00628"'),
 'urlscan_doc':'https://urlscan.io/api/v1/search/?q='+quote_plus('filename:13104645147'),
 'muckrock_search':'https://www.muckrock.com/search/?q='+quote_plus('Velocitel Bauer'),
 'perma_search':'https://perma.cc/search?url='+quote_plus('ecf.nced.uscourts.gov/doc1/13104645147'),
 'archive_today_case':'https://archive.ph/https://ecf.nced.uscourts.gov/doc1/13104645147',
 'ghostarchive_search':'https://ghostarchive.org/search?term='+quote_plus('Velocitel Bauer'),
 'courtlistener_search':'https://www.courtlistener.com/?type=r&q='+quote_plus('"13104645147"'),
 'courtlistener_case_search':'https://www.courtlistener.com/?type=r&q='+quote_plus('"5:15-cv-00628"'),
}
for label,url in direct.items():
    r=fetch(label,url,timeout=90)
    if not r:continue
    text=visible(r.content,r.headers.get('content-type',''));links=[]
    try:
        soup=BeautifulSoup(r.content,'lxml')
        for a in soup.find_all('a',href=True):
            lab=' '.join(a.get_text(' ',strip=True).split());u=normalize_link(a.get('href'),r.url)
            if u.startswith('http') and relevant_url(u,lab):links.append({'text':lab,'url':u})
    except:pass
    search_results.append({'query':label,'engine':'direct','status':r.status_code,'final_url':r.url,'links':links[:500],'text':text[:300000]})
    for x in links:candidates.append({'query':label,'engine':'direct',**x})

# Safely inspect candidate URLs. Do not follow PACER/login/paywall endpoints; only public mirrors/uploads.
allowed_hosts=('documentcloud.org','assets.documentcloud.org','drive.google.com','docs.google.com','dropbox.com','scribd.com','issuu.com','law360.com','law360news.com','casetext.com','leagle.com','justia.com','courtlistener.com','archive.org','muckrock.com','perma.cc','archive.ph','ghostarchive.org','amazonaws.com','storage.googleapis.com','github.com','gitlab.com')
seen=set()
for i,c in enumerate(candidates,1):
    u=c.get('url','')
    try:host=urlparse(u).hostname or ''
    except:continue
    if not any(host==h or host.endswith('.'+h) for h in allowed_hosts):continue
    if u in seen:continue
    seen.add(u)
    if len(seen)>350:break
    r=fetch(f'candidate_{i}',u,timeout=70,save=False)
    if not r:continue
    is_pdf=r.content.startswith(b'%PDF') or 'application/pdf' in r.headers.get('content-type','').lower()
    text=visible(r.content,r.headers.get('content-type',''))[:30000]
    match=any(x.lower() in (u+' '+text).lower() for x in ['velocitel','cory bauer','delta oaks','5:15-cv-00628','13104645147','13105515142','gov.uscourts.nced.147135'])
    if is_pdf or match:
        ext='.pdf' if is_pdf else '.html';path=FOUND/f'{safe(str(i)+"_"+u)}{ext}';path.write_bytes(r.content)
        downloads.append({'candidate':c,'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'size':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest(),'is_pdf':is_pdf,'matched':match,'saved':str(path),'text':text})

# Dedupe candidate records.
uniq=[];seen=set()
for c in candidates:
    key=c.get('url')
    if not key or key in seen:continue
    seen.add(key);uniq.append(c)
(OUT/'search_results.json').write_text(json.dumps(search_results,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'candidate_urls.json').write_text(json.dumps(uniq,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'downloads.json').write_text(json.dumps(downloads,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'fetch_records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
summary={'queries':len(queries),'candidate_urls':len(uniq),'candidate_urls_fetched':len(seen),'relevant_downloads':len(downloads),'pdfs_found':sum(1 for x in downloads if x.get('is_pdf')),'note':'Public search/upload/mirror sites only; no accounts or paywall bypass.'}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2),flush=True)
