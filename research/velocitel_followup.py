#!/usr/bin/env python3
"""Focused follow-up for Velocitel v. Bauer public docket research."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

OUT = Path("research-output/followup")
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 OpenAI-legal-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

manifest=[]

def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:180]

def get(label: str, url: str, timeout=60):
    try:
        r=S.get(url, timeout=timeout, allow_redirects=True)
        ext=".bin"
        ct=(r.headers.get("content-type") or "").lower()
        if "html" in ct: ext=".html"
        elif "json" in ct: ext=".json"
        elif "xml" in ct or "rss" in ct or "atom" in ct: ext=".xml"
        elif "pdf" in ct or r.content.startswith(b"%PDF"): ext=".pdf"
        p=RAW/(slug(label)+ext)
        p.write_bytes(r.content)
        manifest.append({"label":label,"requested_url":url,"status":r.status_code,"final_url":r.url,"content_type":r.headers.get("content-type"),"bytes":len(r.content),"sha256":hashlib.sha256(r.content).hexdigest(),"path":str(p)})
        print(label, r.status_code, len(r.content), r.url)
        return r
    except Exception as e:
        manifest.append({"label":label,"requested_url":url,"error":repr(e)})
        print(label, "ERROR", repr(e))
        return None

def text(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""

def all_attrs(el):
    if not el: return {}
    return {k:(" ".join(v) if isinstance(v,list) else v) for k,v in el.attrs.items()}

# 1. Exact CourtListener docket and case-specific search pages.
case_url="https://www.courtlistener.com/docket/5670822/velocitel-inc-dba-fdh-velocitel-v-bauer/"
urls={
    "cl_docket":case_url,
    "cl_docket_asc":case_url+"?order_by=asc",
    "cl_doc_1":"https://www.courtlistener.com/docket/5670822/1/velocitel-inc-dba-fdh-velocitel-v-bauer/",
    "cl_case_results":"https://www.courtlistener.com/?type=r&q="+quote_plus("(Velocitel) AND docket_id:5670822"),
    "cl_case_feed":"https://www.courtlistener.com/feed/search/?type=r&q="+quote_plus("(Velocitel) AND docket_id:5670822"),
    "cl_top_prayers":"https://www.courtlistener.com/prayers/top/",
    "cl_prayer_help":"https://www.courtlistener.com/help/pray-and-pay/",
}
responses={k:get(k,u) for k,u in urls.items()}

# Parse full docket rows and all purchase/request metadata.
docket_entries=[]
r=responses.get("cl_docket_asc") or responses.get("cl_docket")
if r and r.status_code==200:
    soup=BeautifulSoup(r.text,"lxml")
    table=soup.select_one("#docket-entry-table")
    rows=(table.select(":scope > div.row") if table else soup.select("div.row[id^='entry-'],div.row[id^='minute-entry-']"))
    for row in rows:
        rid=row.get("id") or ""
        if not (rid.startswith("entry-") or rid.startswith("minute-entry-")):
            continue
        cols=row.find_all("div", recursive=False)
        number=text(cols[0]) if len(cols)>0 else ""
        date=text(cols[1]) if len(cols)>1 else ""
        body=cols[2] if len(cols)>2 else row
        description=""
        for p in body.find_all("p", recursive=False):
            candidate=text(p)
            if candidate:
                description=candidate
                break
        if not description:
            # First p not nested under recap-documents.
            for p in body.find_all("p"):
                if not p.find_parent(class_="recap-documents"):
                    description=text(p)
                    if description: break
        docs=[]
        for d in body.select(".recap-documents"):
            dlinks=[]
            for a in d.find_all("a",href=True):
                dlinks.append({"text":text(a),"href":urljoin(r.url,a.get("href")),"attrs":all_attrs(a)})
            buttons=[]
            for b in d.find_all("button"):
                buttons.append({"text":text(b),"attrs":all_attrs(b)})
            forms=[]
            for f in d.find_all("form"):
                forms.append({"attrs":all_attrs(f)})
            docs.append({"text":text(d),"links":dlinks,"buttons":buttons,"forms":forms})
        row_links=[{"text":text(a),"href":urljoin(r.url,a.get("href")),"attrs":all_attrs(a)} for a in row.find_all("a",href=True)]
        docket_entries.append({"row_id":rid,"entry_number":number,"date":date,"description":description,"row_text":text(row),"documents":docs,"links":row_links})
    (OUT/"courtlistener_docket_entries.json").write_text(json.dumps(docket_entries,indent=2),encoding="utf-8")
    (OUT/"courtlistener_docket_text.txt").write_text("\n".join(f"{x['entry_number']}\t{x['date']}\t{x['row_text']}" for x in docket_entries),encoding="utf-8")

# Collect important entries and every PACER document id/link.
important_terms=["complaint","injunction","expedited","discovery","flash","thumb","usb","drive","foundation","software","confidential","trade secret","forensic","sanction","compel","settlement","settled","stipulation","dismiss"]
important=[]
pacer_links=[]
for e in docket_entries:
    low=e["row_text"].lower()
    terms=[t for t in important_terms if t in low]
    if terms:
        important.append({"terms":terms,**e})
    for link in e["links"]:
        href=link["href"]
        if "uscourts.gov/doc1/" in href or "pacer" in href.lower():
            m=re.search(r"/doc1/(\d+)",href)
            pacer_links.append({"entry_number":e["entry_number"],"date":e["date"],"description":e["description"],"link_text":link["text"],"url":href,"pacer_doc_id":m.group(1) if m else None})
(OUT/"important_docket_entries.json").write_text(json.dumps(important,indent=2),encoding="utf-8")
(OUT/"pacer_document_links.json").write_text(json.dumps(pacer_links,indent=2),encoding="utf-8")

# Fetch CourtListener document pages for important numbered entries when a predictable URL exists.
for e in important:
    n=(e.get("entry_number") or "").strip()
    if not n.isdigit():
        continue
    u=f"https://www.courtlistener.com/docket/5670822/{n}/velocitel-inc-dba-fdh-velocitel-v-bauer/"
    get(f"cl_document_page_{n}",u)
    time.sleep(.15)

# 2. PlainSite exact profile and searches.
plain_urls={
    "plainsite_profile_velocitel":"https://www.plainsite.org/profiles/velocitel-inc-dba-fdh-velocitel/",
    "plainsite_search_exact_case":"https://www.plainsite.org/search/?q="+quote_plus('"5:15-cv-00628"'),
    "plainsite_search_case":"https://www.plainsite.org/search/?q="+quote_plus('5:15-cv-00628'),
    "plainsite_search_title":"https://www.plainsite.org/search/?q="+quote_plus('"Velocitel, Inc. d/b/a FDH Velocitel v. Bauer"'),
    "plainsite_search_names":"https://www.plainsite.org/search/?q="+quote_plus('"Velocitel" "Cory Bauer"'),
}
plain={}
for k,u in plain_urls.items():
    rr=get(k,u)
    if rr:
        ss=BeautifulSoup(rr.text,"lxml")
        plain[k]={"status":rr.status_code,"final_url":rr.url,"title":text(ss.title),"visible_text":text(ss)[:100000],"links":[{"text":text(a),"href":urljoin(rr.url,a.get("href"))} for a in ss.find_all("a",href=True)]}
(OUT/"plainsite_exact_results.json").write_text(json.dumps(plain,indent=2),encoding="utf-8")

# Follow any PlainSite docket links whose text or surrounding URL points to this case/party.
follow=[]
seen=set()
for result in plain.values():
    for a in result.get("links",[]):
        combo=(a["text"]+" "+a["href"]).lower()
        if ("velocitel" in combo or "00628" in combo or "bauer" in combo) and "/dockets/" in a["href"] and a["href"] not in seen:
            seen.add(a["href"])
            rr=get("plainsite_docket_"+str(len(seen)),a["href"])
            if rr:
                ss=BeautifulSoup(rr.text,"lxml")
                follow.append({"url":rr.url,"status":rr.status_code,"title":text(ss.title),"visible_text":text(ss)[:150000],"links":[{"text":text(x),"href":urljoin(rr.url,x.get("href"))} for x in ss.find_all("a",href=True)]})
(OUT/"plainsite_followed_dockets.json").write_text(json.dumps(follow,indent=2),encoding="utf-8")

# 3. Wayback availability and snapshots for core pages and likely complaint URLs.
wayback_targets=[
    case_url,
    "https://www.courtlistener.com/docket/5670822/1/velocitel-inc-dba-fdh-velocitel-v-bauer/",
    "https://storage.courtlistener.com/recap/gov.uscourts.nced.147135/gov.uscourts.nced.147135.1.0.pdf",
    "https://archive.org/download/gov.uscourts.nced.147135/gov.uscourts.nced.147135.1.0.pdf",
    "https://dockets.justia.com/docket/north-carolina/ncedce/5%3A2015cv00628/147135",
    "https://docs.justia.com/cases/federal/district-courts/north-carolina/ncedce/5%3A2015cv00628/147135/1",
]
wayback={}
for i,target in enumerate(wayback_targets,1):
    cdx="https://web.archive.org/cdx/search/cdx?url="+quote_plus(target)+"&output=json&fl=timestamp,original,statuscode,mimetype,digest,length&filter=statuscode:200&collapse=digest&from=2015&to=2026"
    rr=get(f"wayback_cdx_{i}",cdx)
    data=None
    if rr:
        try:data=rr.json()
        except Exception:pass
    wayback[target]=data
    if isinstance(data,list) and len(data)>1:
        # Fetch first and last distinct snapshot.
        for label,row in [("first",data[1]),("last",data[-1])]:
            ts=row[0]; orig=row[1]
            snap=f"https://web.archive.org/web/{ts}id_/{orig}"
            get(f"wayback_{i}_{label}_{ts}",snap,timeout=90)
(OUT/"wayback_results.json").write_text(json.dumps(wayback,indent=2),encoding="utf-8")

# 4. Exact identifier searches across several public search endpoints.
queries=[
    '"13104645147"',
    '"gov.uscourts.nced.147135.1.0.pdf"',
    '"5:15-cv-00628" "flash drive"',
    '"5:15-cv-00628" foundation',
    '"Velocitel" "Cory Bauer" "flash drive"',
    '"FDH Velocitel" "Delta Oaks" lawsuit',
    '"Velocitel v. Bauer" complaint',
    '"Delta Oaks Group" "trade secret"',
    '"unknown foundation investigation" FDH',
    '"unknown foundation" "Delta Oaks"',
]
search=[]
for qi,q in enumerate(queries,1):
    for eng,u in [
        ("bing","https://www.bing.com/search?q="+quote_plus(q)+"&count=50"),
        ("ddg","https://html.duckduckgo.com/html/?q="+quote_plus(q)),
        ("brave","https://search.brave.com/search?q="+quote_plus(q)+"&source=web"),
    ]:
        rr=get(f"exact_search_{qi}_{eng}",u)
        if not rr: continue
        ss=BeautifulSoup(rr.text,"lxml")
        links=[]
        for a in ss.find_all("a",href=True):
            href=urljoin(rr.url,a.get("href")); tx=text(a)
            if tx or href:
                links.append({"text":tx,"href":href})
        search.append({"query":q,"engine":eng,"status":rr.status_code,"final_url":rr.url,"visible_text":text(ss)[:30000],"links":links[:500]})
        time.sleep(.4)
(OUT/"exact_search_results.json").write_text(json.dumps(search,indent=2),encoding="utf-8")

# 5. Direct probes of likely missing complaint storage paths and PACER link.
probes={
    "storage_cl_complaint":"https://storage.courtlistener.com/recap/gov.uscourts.nced.147135/gov.uscourts.nced.147135.1.0.pdf",
    "archive_complaint":"https://archive.org/download/gov.uscourts.nced.147135/gov.uscourts.nced.147135.1.0.pdf",
    "pacer_complaint":"https://ecf.nced.uscourts.gov/doc1/13104645147?caseid=147135",
    "pacer_docket":"https://ecf.nced.uscourts.gov/cgi-bin/DktRpt.pl?147135",
}
probe_results={}
for k,u in probes.items():
    rr=get(k,u,timeout=90)
    if rr:
        probe_results[k]={"status":rr.status_code,"final_url":rr.url,"history":[{"status":h.status_code,"url":h.url,"location":h.headers.get("location")} for h in rr.history],"headers":dict(rr.headers),"sample":rr.text[:3000] if "text" in (rr.headers.get("content-type") or "") or "html" in (rr.headers.get("content-type") or "") else None}
(OUT/"direct_probe_results.json").write_text(json.dumps(probe_results,indent=2),encoding="utf-8")

(OUT/"fetch_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
print("Parsed docket entries:",len(docket_entries))
print("Important entries:",len(important))
print("PACER links:",len(pacer_links))
