#!/usr/bin/env python3
"""Search free patent/trademark indexes for Delta Oaks foundation-mapping IP."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("research-output/dog-patent-trace")
RAW = OUT / "raw"
for p in (OUT, RAW): p.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 patent-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

QUERIES = [
    '"Delta Oaks Group"', '"Delta Oaks Group, PLLC"', '"Delta Oaks Group PLLC"',
    'assignee=("Delta Oaks Group")', 'assignee=("Delta Oaks")',
    'inventor=("Cory Bauer")', 'inventor=("Cory A Bauer")',
    'inventor=("Joseph Borrelli")', 'inventor=("Joe Borrelli")',
    'inventor=("Rhett Butler")', 'inventor=("Rhett W Butler")',
    '"below grade foundation mapping"', '"below-grade foundation mapping"',
    '"unknown foundation investigation"', '"unknown foundation investigations"',
    '"foundation components" mapping tower', '"tower foundation" mapping radar',
    '"foundation mapping" telecommunications', '"foundation mapping" "patent pending"',
    '"Delta Oaks" foundation patent', '"Delta Oaks" geotechnical patent',
]
WEB_QUERIES = [
    'site:patents.google.com/patent "Delta Oaks Group"',
    'site:patents.justia.com "Delta Oaks Group"',
    'site:patents.google.com/patent "Cory Bauer" foundation',
    'site:patents.google.com/patent "Joseph Borrelli" foundation',
    'site:patents.google.com/patent "Rhett Butler" foundation',
    '"below grade foundation mapping" patent',
    '"unknown foundation investigations" patent pending',
    '"Delta Oaks Group" patent pending',
    '"Delta Oaks Group" inventor patent',
    '"Cory Bauer" "patent pending"',
]
records=[]; searches=[]; candidates=[]; patent_pages=[]


def safe(v): return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:190] or 'item'

def fetch(label,url,params=None,timeout=75,save=True):
    try:
        r=S.get(url,params=params,timeout=timeout,allow_redirects=True); data=r.content; c=r.headers.get('content-type','')
        ext='.json' if 'json' in c.lower() else '.html' if 'html' in c.lower() or data.lstrip().startswith(b'<') else '.bin'; path=None
        if save: path=RAW/f'{safe(label)}{ext}'; path.write_bytes(data)
        records.append({'label':label,'requested_url':r.request.url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'sha256':hashlib.sha256(data).hexdigest() if data else None,'saved':str(path) if path else None})
        print(label,r.status_code,len(data),r.url,flush=True); return r
    except Exception as e:
        records.append({'label':label,'requested_url':url,'error':repr(e)}); print(label,'ERROR',repr(e),flush=True); return None

def plain(v): return BeautifulSoup(str(v or ''),'lxml').get_text(' ',strip=True)

def normalize_result(query,item):
    p=item.get('patent',{}) if isinstance(item,dict) and isinstance(item.get('patent',{}),dict) else {}
    return {
        'query':query,'id':item.get('id') if isinstance(item,dict) else None,'rank':item.get('rank') if isinstance(item,dict) else None,
        'title':plain(p.get('title')),'snippet':plain(p.get('snippet')),'inventor':p.get('inventor'),'assignee':p.get('assignee'),
        'publication_number':p.get('publication_number'),'filing_date':p.get('filing_date'),'priority_date':p.get('priority_date'),
        'grant_date':p.get('grant_date'),'publication_date':p.get('publication_date'),'pdf':p.get('pdf'),'entity_matches':item.get('entity_matches') if isinstance(item,dict) else None,
    }

def patent_ids_from_text(text):
    ids=set()
    for m in re.finditer(r'(?i)\b(?:US|WO|EP|CA|AU)\s*\d{6,}(?:[A-Z]\d?)?\b',text): ids.add(re.sub(r'\s+','',m.group(0).upper()))
    for m in re.finditer(r'https?://patents\.google\.com/patent/([A-Z]{2}\d+[A-Z]\d?)',text,re.I): ids.add(m.group(1).upper())
    return ids

for i,q in enumerate(QUERIES,1):
    r=fetch(f'xhr_{i}','https://patents.google.com/xhr/query',params={'url':'q='+q,'exp':''})
    parsed=None; norm=[]
    if r:
        try: parsed=r.json()
        except Exception: parsed={'raw':r.text[:500000]}
        obj=parsed.get('results',{}) if isinstance(parsed,dict) else {}
        clusters=obj.get('cluster',[]) if isinstance(obj,dict) else []
        if isinstance(clusters,dict):clusters=[clusters]
        for cluster in clusters or []:
            if not isinstance(cluster,dict):continue
            arr=cluster.get('result',[]) or []
            if isinstance(arr,dict):arr=[arr]
            for item in arr:
                if not isinstance(item,dict):continue
                row=normalize_result(q,item);norm.append(row)
                blob=json.dumps(row,ensure_ascii=False).lower()
                if any(t in blob for t in ['delta oaks','cory bauer','joseph borrelli','joe borrelli','rhett butler','foundation mapping','unknown foundation','below grade']):candidates.append(row)
    searches.append({'query':q,'status':r.status_code if r else None,'normalized':norm,'raw_summary':parsed.get('results',{}).get('total_num_results') if isinstance(parsed,dict) and isinstance(parsed.get('results'),dict) else None})
    time.sleep(.1)

web_results=[]; ids=set()
for i,q in enumerate(WEB_QUERIES,1):
    for engine,url in [('google_jina','https://r.jina.ai/http://www.google.com/search?q='+quote_plus(q)),('bing_jina','https://r.jina.ai/http://www.bing.com/search?q='+quote_plus(q)),('ddg','https://html.duckduckgo.com/html/?q='+quote_plus(q))]:
        r=fetch(f'web_{i}_{engine}',url,timeout=75)
        if not r:continue
        text=re.sub(r'\s+',' ',BeautifulSoup(r.content,'lxml').get_text(' ',strip=True)) if 'html' in r.headers.get('content-type','').lower() or r.content.lstrip().startswith(b'<') else r.text
        found=sorted(patent_ids_from_text(text)); ids.update(found)
        links=[]
        try:
            soup=BeautifulSoup(r.content,'lxml')
            for a in soup.find_all('a',href=True):
                href=urljoin(r.url,a.get('href')); lab=' '.join(a.get_text(' ',strip=True).split())
                if 'patent' in (lab+' '+href).lower() or any(t in (lab+' '+href).lower() for t in ['delta oaks','cory bauer','borrelli','rhett butler']):links.append({'text':lab,'href':href})
        except Exception:pass
        web_results.append({'query':q,'engine':engine,'status':r.status_code,'patent_ids':found,'links':links[:300],'text':text[:300000]})

for row in candidates:
    for v in [row.get('publication_number'),row.get('id')]:
        if v:
            m=re.search(r'([A-Z]{2}\d+[A-Z]\d?)',str(v).replace('/patent/',''),re.I)
            if m:ids.add(m.group(1).upper())

for pid in sorted(ids):
    r=fetch('patent_'+safe(pid),f'https://patents.google.com/patent/{pid}/en',timeout=75)
    if not r or r.status_code!=200:continue
    soup=BeautifulSoup(r.content,'lxml'); fields={}
    for key in ['DC.title','DC.contributor','DC.relation','DC.date','inventor','assignee','filingDate','priorityDate','publicationDate','grantDate']:
        vals=[]
        for n in soup.find_all('meta'):
            if n.get('scheme')==key or n.get('name')==key or n.get('property')==key:
                if n.get('content'):vals.append(n.get('content'))
        if vals:fields[key]=vals
    text=re.sub(r'\s+',' ',soup.get_text(' ',strip=True))
    patent_pages.append({'id':pid,'status':r.status_code,'url':r.url,'title':soup.title.get_text(' ',strip=True) if soup.title else None,'fields':fields,'text':text[:500000]})

# Additional free organization/inventor APIs; failures are preserved as negative evidence.
api_urls={
    'patentsview_assignee':'https://search.patentsview.org/api/v1/assignee/?q='+quote_plus('{"_text_any":{"assignee_organization":"Delta Oaks Group"}}')+'&f=["assignee_id","assignee_organization"]&o={"size":100}',
    'patentsview_cory':'https://search.patentsview.org/api/v1/inventor/?q='+quote_plus('{"_and":[{"inventor_first_name":"Cory"},{"inventor_last_name":"Bauer"}]}')+'&f=["inventor_id","inventor_first_name","inventor_last_name"]&o={"size":100}',
    'patentsview_borrelli':'https://search.patentsview.org/api/v1/inventor/?q='+quote_plus('{"_and":[{"inventor_first_name":"Joseph"},{"inventor_last_name":"Borrelli"}]}')+'&f=["inventor_id","inventor_first_name","inventor_last_name"]&o={"size":100}',
    'uspto_search':'https://ppubs.uspto.gov/pubwebapp/static/pages/ppubsbasic.html',
    'wipo_search':'https://patentscope.wipo.int/search/en/search.jsf',
}
api_results=[]
for label,url in api_urls.items():
    r=fetch(label,url,timeout=75)
    if r:api_results.append({'label':label,'status':r.status_code,'url':r.url,'text':r.text[:500000]})

# Deduplicate candidates.
uniq=[];seen=set()
for row in candidates:
    key=(row.get('publication_number'),row.get('id'),row.get('title'))
    if key in seen:continue
    seen.add(key);uniq.append(row)

(OUT/'searches.json').write_text(json.dumps(searches,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'web_results.json').write_text(json.dumps(web_results,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'candidates.json').write_text(json.dumps(uniq,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'patent_pages.json').write_text(json.dumps(patent_pages,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'api_results.json').write_text(json.dumps(api_results,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'fetch_records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
summary={'queries':len(QUERIES),'web_queries':len(WEB_QUERIES),'candidate_results':len(uniq),'patent_ids_resolved':len(patent_pages),'api_results':len(api_results),'note':'Public patent/search endpoints only.'}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2),flush=True)
