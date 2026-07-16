#!/usr/bin/env python3
"""Trace FDH/Velocitel and Delta Oaks foundation-investigation technology using free sources."""
from __future__ import annotations
import gzip, hashlib, io, json, re, time
from pathlib import Path
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup
try:
    from warcio.archiveiterator import ArchiveIterator
except Exception:
    ArchiveIterator = None

OUT=Path('research-output/fdh-technical-trace'); RAW=OUT/'raw'; FOUND=OUT/'found'
for p in (OUT,RAW,FOUND): p.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 public-research/1.0','Accept-Language':'en-US,en;q=0.9'})
records=[]; discoveries=[]
DOMAINS=['fdh-inc.com','www.fdh-inc.com','fdhvelocitel.com','www.fdhvelocitel.com','velocitel.com','www.velocitel.com','fdhengineering.com','www.fdhengineering.com','deltaoaksgroup.com','www.deltaoaksgroup.com','deltaoaks.com','www.deltaoaks.com']
TERMS=['unknown foundation','foundation investigation','foundation mapping','foundation depth','subsurface foundation','nondestructive','non-destructive','NDE','NDT','sonic echo','impulse response','parallel seismic','dispersive wave','dispersive side sonic','pulse echo','ground penetrating radar','GPR','software','mapping software','tower foundation','embedded length','buried foundation','foundation profiler']
PEOPLE=['Cory Bauer','Joseph Borrelli','J. Darrin Holt','Darrin Holt','Robert Lindyberg','Mark Cesare','Laura Guy']
PATENT_QUERIES=['"FDH Engineering"','"FDH Infrastructure Services"','"FDH Velocitel"','assignee=(FDH Engineering)','inventor=(Darrin Holt)','inventor=(Robert Lindyberg)','"unknown foundation" nondestructive','"foundation mapping" concrete','"dispersive side sonic"','"dispersive pulse echo"','"embedded length" foundation','"subsurface anchor corrosion"','"determining tension in a rod"']
KNOWN_PATENTS=['US7548192B1','US8176800B2','US10451399B2','US20230213401A1','WO2012094284A2','CA3022477A1','EP3455413A1']

def safe(v): return re.sub(r'[^A-Za-z0-9._-]+','_',v).strip('_')[:180] or 'item'
def txt(data,ctype='',limit=250000):
    try:
        if 'html' in ctype.lower() or data.lstrip().startswith(b'<'):
            return re.sub(r'\s+',' ',BeautifulSoup(data,'lxml').get_text(' ',strip=True))[:limit]
        return data.decode('utf-8','replace')[:limit]
    except Exception:return ''
def fetch(label,url,params=None,timeout=60,save=True):
    try:
        r=S.get(url,params=params,timeout=timeout,allow_redirects=True); data=r.content; c=r.headers.get('content-type','')
        ext='.pdf' if data.startswith(b'%PDF') or 'pdf' in c.lower() else '.json' if 'json' in c.lower() else '.xml' if 'xml' in c.lower() else '.html' if 'html' in c.lower() or data.lstrip().startswith(b'<') else '.bin'
        fp=None
        if save: fp=RAW/f'{safe(label)}{ext}'; fp.write_bytes(data)
        rec={'label':label,'url':url,'request_url':r.request.url,'status':r.status_code,'final_url':r.url,'content_type':c,'size':len(data),'sha256':hashlib.sha256(data).hexdigest() if data else None,'saved':str(fp) if fp else None,'text_sample':txt(data,c,20000)}; records.append(rec)
        print(label,r.status_code,len(data),r.url,flush=True)
        return r
    except Exception as e: records.append({'label':label,'url':url,'error':repr(e)}); print(label,'ERROR',repr(e),flush=True); return None

def hits_from_text(source,url,text):
    lower=text.lower(); hs=[]
    for term in TERMS+PEOPLE:
        pos=0
        while True:
            i=lower.find(term.lower(),pos)
            if i<0: break
            hs.append({'source':source,'url':url,'term':term,'snippet':re.sub(r'\s+',' ',text[max(0,i-500):i+1400])}); pos=i+len(term)
            if sum(1 for x in hs if x['term']==term)>=10: break
    return hs

def web_searches():
    queries=[]
    for term in TERMS:
        queries += [f'"{term}" "FDH" telecom',f'"{term}" "Delta Oaks"',f'"{term}" "Cory Bauer"']
    queries += [f'"{p}" FDH foundation' for p in PEOPLE]+['"FDH Velocitel" patent','"FDH Engineering" patent foundation','site:deltaoaksgroup.com foundation','site:fdh-inc.com foundation','site:fdhvelocitel.com foundation','"Delta Oaks Group" foundation investigation','"Cory Bauer" FDH Velocitel','"Joseph Borrelli" FDH Velocitel']
    out=[]
    for i,q in enumerate(queries,1):
        for engine,url in [('google_jina','https://r.jina.ai/http://www.google.com/search?q='+quote_plus(q)),('bing_jina','https://r.jina.ai/http://www.bing.com/search?q='+quote_plus(q)),('ddg','https://html.duckduckgo.com/html/?q='+quote_plus(q))]:
            r=fetch(f'web_{i}_{engine}',url,timeout=70)
            if r:
                t=txt(r.content,r.headers.get('content-type','')); out.append({'query':q,'engine':engine,'status':r.status_code,'text':t,'hits':hits_from_text(engine,r.url,t)})
        time.sleep(.12)
    (OUT/'web_searches.json').write_text(json.dumps(out,indent=2),encoding='utf-8')

def wayback_domains():
    captures=[]; selected=[]
    for d in DOMAINS:
        r=fetch('cdx_'+safe(d),'https://web.archive.org/cdx/search/cdx',params={'url':d+'/*','output':'json','fl':'timestamp,original,statuscode,mimetype,digest,length','filter':'statuscode:200','filter':'timestamp:2010-2019','collapse':'digest','limit':'5000'},timeout=100)
        if not r: continue
        try: rows=r.json()
        except Exception: continue
        if not isinstance(rows,list) or len(rows)<2: continue
        head=rows[0]
        for row in rows[1:]:
            c=dict(zip(head,row)); c['domain']=d; captures.append(c)
            u=(c.get('original') or '').lower(); mime=(c.get('mimetype') or '').lower()
            score=sum(1 for t in ['foundation','nde','ndt','non-destructive','nondestructive','sonic','seismic','mapping','tower','engineering','service','brochure','pdf','technology'] if t in u)
            if score or 'pdf' in mime: selected.append((score,c))
    selected=sorted(selected,key=lambda x:(-x[0],x[1].get('timestamp','')))[:500]
    replay=[]
    for idx,(_,c) in enumerate(selected,1):
        r=fetch(f'wb_{idx}_{c.get("timestamp")}',f'https://web.archive.org/web/{c["timestamp"]}id_/{c["original"]}',timeout=90)
        if not r: continue
        t=txt(r.content,r.headers.get('content-type',''))
        hs=hits_from_text('wayback',c['original'],t)
        if hs or r.content.startswith(b'%PDF'):
            ext='.pdf' if r.content.startswith(b'%PDF') else '.html'; fp=FOUND/f'wayback_{idx}_{safe(c["original"],)}{ext}'; fp.write_bytes(r.content)
            replay.append({'capture':c,'saved':str(fp),'hits':hs,'text_sample':t[:50000]}); discoveries.extend(hs)
    (OUT/'wayback_captures.json').write_text(json.dumps(captures,indent=2),encoding='utf-8'); (OUT/'wayback_selected.json').write_text(json.dumps(replay,indent=2),encoding='utf-8')

def commoncrawl_domains():
    r=fetch('cc_collections','https://index.commoncrawl.org/collinfo.json',timeout=60)
    if not r:return
    try: cols=r.json()
    except:return
    cols=[c for c in cols if re.search(r'CC-MAIN-(20(?:1[0-9]|2[0-6]))',c.get('id',''))][:90]
    hits=[]
    for c in cols:
        endpoint=c.get('cdx-api') or f'https://index.commoncrawl.org/{c["id"]}-index'
        for d in DOMAINS:
            rr=fetch(f'ccidx_{c["id"]}_{safe(d)}',endpoint,params={'url':d+'/*','output':'json','matchType':'domain','filter':'status:200'},timeout=40,save=False)
            if not rr: continue
            for line in rr.text.splitlines():
                try:
                    h=json.loads(line); h['collection']=c['id'];
                    u=h.get('url','').lower(); mime=(h.get('mime-detected') or h.get('mime') or '').lower()
                    if any(t.replace(' ','') in u.replace('-','').replace('_','') for t in ['foundation','nondestructive','sonic','seismic','mapping','technology','brochure']) or 'pdf' in mime: hits.append(h)
                except: pass
    uniq={(h.get('filename'),h.get('offset'),h.get('length')):h for h in hits}; hits=list(uniq.values())
    (OUT/'commoncrawl_hits.json').write_text(json.dumps(hits,indent=2),encoding='utf-8')
    recovered=[]
    for idx,h in enumerate(hits[:250],1):
        try:
            off=int(h['offset']); length=int(h['length']); rr=S.get('https://data.commoncrawl.org/'+h['filename'],headers={'Range':f'bytes={off}-{off+length-1}'},timeout=90); data=rr.content; payload=b''; headers={}
            candidates=[data]
            if data[:2]==b'\x1f\x8b':
                try:candidates.append(gzip.decompress(data))
                except:pass
            if ArchiveIterator:
                for candidate in candidates:
                    try:
                        for rec in ArchiveIterator(io.BytesIO(candidate)):
                            if rec.rec_type=='response': payload=rec.content_stream().read(); headers=dict(rec.http_headers.headers) if rec.http_headers else {}; break
                    except:pass
                    if payload:break
            if not payload:continue
            ctype=headers.get('Content-Type') or headers.get('content-type') or h.get('mime-detected',''); t=txt(payload,ctype); hs=hits_from_text('commoncrawl',h.get('url',''),t)
            if hs or payload.startswith(b'%PDF'):
                ext='.pdf' if payload.startswith(b'%PDF') else '.html'; fp=FOUND/f'cc_{idx}_{safe(h.get("url",""))}{ext}'; fp.write_bytes(payload); recovered.append({'hit':h,'saved':str(fp),'hits':hs,'text_sample':t[:50000]}); discoveries.extend(hs)
        except Exception as e: records.append({'label':'cc_payload','url':h.get('url'),'error':repr(e)})
    (OUT/'commoncrawl_recovered.json').write_text(json.dumps(recovered,indent=2),encoding='utf-8')

def patents():
    searches=[]; candidates=[]
    for i,q in enumerate(PATENT_QUERIES,1):
        r=fetch(f'patent_xhr_{i}','https://patents.google.com/xhr/query',params={'url':'q='+q,'exp':''},timeout=75)
        parsed=None; normalized=[]
        if r:
            try: parsed=r.json()
            except: parsed={'raw':r.text[:300000]}
            resultobj=parsed.get('results',{}) if isinstance(parsed,dict) else {}
            if isinstance(resultobj,dict):
                clusters=resultobj.get('cluster',[]) or []
                if isinstance(clusters,dict): clusters=[clusters]
                for cluster in clusters:
                    if not isinstance(cluster,dict):continue
                    items=cluster.get('result',[]) or []
                    if isinstance(items,dict):items=[items]
                    for item in items:
                        if not isinstance(item,dict):continue
                        p=item.get('patent',{}) if isinstance(item.get('patent',{}),dict) else {}
                        row={'query':q,'id':item.get('id'),'rank':item.get('rank'),'title':BeautifulSoup(str(p.get('title','')),'lxml').get_text(' ',strip=True),'snippet':BeautifulSoup(str(p.get('snippet','')),'lxml').get_text(' ',strip=True),'inventor':p.get('inventor'),'assignee':p.get('assignee'),'publication_number':p.get('publication_number'),'filing_date':p.get('filing_date'),'priority_date':p.get('priority_date'),'pdf':p.get('pdf')}; normalized.append(row)
                        combo=json.dumps(row).lower()
                        if any(x in combo for x in ['fdh','holt','lindyberg','foundation','sonic','seismic','reinforcement','anchor']):candidates.append(row)
        searches.append({'query':q,'status':r.status_code if r else None,'parsed':parsed,'normalized':normalized})
    metadata=[]
    ids=set(KNOWN_PATENTS+[str(x.get('publication_number') or x.get('id') or '').replace('/patent/','').split('/')[0] for x in candidates])
    for pid in sorted(x for x in ids if x):
        r=fetch('patent_'+safe(pid),f'https://patents.google.com/patent/{pid}/en',timeout=70)
        if not r:continue
        soup=BeautifulSoup(r.text,'lxml'); fields={}
        for key in ['DC.title','DC.contributor','DC.relation','DC.date','inventor','assignee','filingDate','priorityDate','publicationDate','grantDate']:
            vals=[]
            for n in soup.find_all('meta'):
                if n.get('scheme')==key or n.get('name')==key or n.get('property')==key:
                    if n.get('content'):vals.append(n.get('content'))
            if vals:fields[key]=vals
        t=re.sub(r'\s+',' ',soup.get_text(' ',strip=True)); hs=hits_from_text('google_patents',r.url,t)
        metadata.append({'id':pid,'status':r.status_code,'title':soup.title.get_text(' ',strip=True) if soup.title else None,'fields':fields,'hits':hs,'text_sample':t[:400000]}); discoveries.extend(hs)
    (OUT/'patent_searches.json').write_text(json.dumps(searches,indent=2),encoding='utf-8'); (OUT/'patent_candidates.json').write_text(json.dumps(candidates,indent=2),encoding='utf-8'); (OUT/'patent_metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')

def other_sources():
    urls={'google_books':'https://www.googleapis.com/books/v1/volumes?q='+quote_plus('FDH Engineering foundation nondestructive'),'crossref':'https://api.crossref.org/works?query.bibliographic='+quote_plus('FDH Engineering foundation nondestructive')+'&rows=100','openalex':'https://api.openalex.org/works?search='+quote_plus('FDH Engineering foundation nondestructive')+'&per-page=100','semantic_scholar':'https://api.semanticscholar.org/graph/v1/paper/search?query='+quote_plus('FDH Engineering foundation nondestructive')+'&limit=100&fields=title,abstract,authors,year,url','internet_archive':'https://archive.org/advancedsearch.php?q='+quote_plus('(creator:(FDH Engineering) OR title:(FDH Engineering) OR description:(FDH Engineering) OR title:(Delta Oaks) OR description:(Delta Oaks))')+'&fl[]=identifier,title,description,creator,mediatype&rows=500&page=1&output=json','sec':'https://efts.sec.gov/LATEST/search-index?q='+quote_plus('"FDH Engineering" foundation')}
    out=[]
    for label,url in urls.items():
        r=fetch(label,url,timeout=75)
        if r:
            t=txt(r.content,r.headers.get('content-type','')); hs=hits_from_text(label,r.url,t); out.append({'label':label,'status':r.status_code,'hits':hs,'text_sample':t[:300000]}); discoveries.extend(hs)
    (OUT/'other_sources.json').write_text(json.dumps(out,indent=2),encoding='utf-8')

def main():
    web_searches(); wayback_domains(); commoncrawl_domains(); patents(); other_sources()
    (OUT/'fetch_records.json').write_text(json.dumps(records,indent=2),encoding='utf-8'); (OUT/'discoveries.json').write_text(json.dumps(discoveries,indent=2),encoding='utf-8')
    summary={'fetches':len(records),'discoveries':len(discoveries),'found_files':len(list(FOUND.glob('*'))),'note':'Open, unauthenticated sources only.'}; (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8'); print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
