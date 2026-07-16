#!/usr/bin/env python3
"""Compact public patent and technical-publication trace for FDH/Velocitel/Delta Oaks.

Uses only public, unauthenticated endpoints. Results are candidates, not proof that
any patent or method was involved in Velocitel v. Bauer.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

OUT = Path("research-output/fdh-patent-trace")
RAW = OUT / "raw"
OUT.mkdir(parents=True, exist_ok=True)
RAW.mkdir(exist_ok=True)
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 public-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

QUERIES = [
    '"FDH Engineering, Inc."',
    '"FDH Engineering"',
    '"FDH Infrastructure Services"',
    '"FDH Velocitel"',
    '"Velocitel" foundation inspection',
    'assignee=(FDH Engineering)',
    'assignee=(FDH Infrastructure Services)',
    'assignee=(Velocitel)',
    'inventor=(Darrin Holt)',
    'inventor=(J Darrin Holt)',
    'inventor=(Robert Lindyberg)',
    'inventor=(Mark Cesare)',
    'inventor=(Laura Guy)',
    'inventor=(Cory Bauer)',
    'inventor=(Joseph Borrelli)',
    'inventor=(Corbin Hardy)',
    'inventor=(Shane Boone)',
    '"Wave Inspection Technologies"',
    'assignee=(Wave Inspection Technologies)',
    '"unknown foundation" nondestructive',
    '"foundation mapping" nondestructive',
    '"foundation depth" sonic echo',
    '"dispersive side sonic"',
    '"Effective Dispersion Analysis of Reflections"',
    '"embedded length" pile foundation accelerometer',
    '"foundation profiler" nondestructive',
]

KNOWN_IDS = [
    "US7548192B1", "US8176800B2", "US10451399B2", "US20170322011A1",
    "US20230213401A1", "WO2012094284A2", "CA3022477A1", "EP3455413A1",
]

records = []


def safe(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", v).strip("_")[:160] or "item"


def fetch(label: str, url: str, params=None, timeout=75):
    try:
        r = S.get(url, params=params, timeout=timeout, allow_redirects=True)
        data = r.content
        ctype = r.headers.get("content-type", "")
        ext = ".json" if "json" in ctype.lower() else ".html" if "html" in ctype.lower() or data.lstrip().startswith(b"<") else ".bin"
        p = RAW / f"{safe(label)}{ext}"
        p.write_bytes(data)
        records.append({
            "label": label, "url": url, "request_url": r.request.url,
            "status": r.status_code, "final_url": r.url,
            "content_type": ctype, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest() if data else None,
            "saved": str(p),
        })
        print(label, r.status_code, len(data), r.url, flush=True)
        return r
    except Exception as exc:
        records.append({"label": label, "url": url, "error": repr(exc)})
        print(label, "ERROR", repr(exc), flush=True)
        return None


def plain_html(value) -> str:
    return BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True)


def normalize_result(item: dict, query: str) -> dict:
    patent = item.get("patent") if isinstance(item.get("patent"), dict) else {}
    return {
        "query": query,
        "id": item.get("id"),
        "rank": item.get("rank"),
        "title": plain_html(patent.get("title")),
        "snippet": plain_html(patent.get("snippet")),
        "inventor": patent.get("inventor"),
        "assignee": patent.get("assignee"),
        "publication_number": patent.get("publication_number"),
        "filing_date": patent.get("filing_date"),
        "priority_date": patent.get("priority_date"),
        "grant_date": patent.get("grant_date"),
        "publication_date": patent.get("publication_date"),
        "pdf": patent.get("pdf"),
        "entity_matches": item.get("entity_matches"),
    }


searches = []
all_results = []
for i, query in enumerate(QUERIES, 1):
    r = fetch(f"xhr_{i}", "https://patents.google.com/xhr/query", params={"url": "q=" + query, "exp": ""})
    parsed = None
    normalized = []
    if r:
        try:
            parsed = r.json()
        except Exception:
            parsed = {"raw_text": r.text[:400000]}
    if isinstance(parsed, dict):
        result_obj = parsed.get("results") if isinstance(parsed.get("results"), dict) else {}
        clusters = result_obj.get("cluster") or []
        if isinstance(clusters, dict):
            clusters = [clusters]
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            items = cluster.get("result") or []
            if isinstance(items, dict):
                items = [items]
            for item in items:
                if isinstance(item, dict):
                    row = normalize_result(item, query)
                    normalized.append(row)
                    all_results.append(row)
    web = fetch(f"web_{i}", "https://r.jina.ai/http://www.google.com/search?q=" + quote_plus("site:patents.google.com/patent " + query), timeout=60)
    searches.append({
        "query": query,
        "xhr_status": r.status_code if r else None,
        "results": normalized,
        "web_status": web.status_code if web else None,
        "web_text": web.text[:250000] if web else "",
    })

# Resolve candidate IDs from search results plus manually supplied leads.
ids = set(KNOWN_IDS)
for row in all_results:
    value = str(row.get("publication_number") or row.get("id") or "")
    m = re.search(r"(?:US|WO|EP|CA|AU)\d+[A-Z]\d?", value.replace(" ", ""), re.I)
    if m:
        ids.add(m.group(0).upper())

patents = []
for pid in sorted(ids):
    r = fetch(f"patent_{pid}", f"https://patents.google.com/patent/{pid}/en")
    if not r or r.status_code != 200:
        continue
    soup = BeautifulSoup(r.text, "lxml")
    meta = {}
    for node in soup.find_all("meta"):
        key = node.get("scheme") or node.get("name") or node.get("property")
        value = node.get("content")
        if key and value:
            meta.setdefault(key, []).append(value)
    page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    relevant_snippets = []
    for term in [
        "FDH", "Velocitel", "Delta Oaks", "Wave Inspection", "Darrin Holt",
        "Cory Bauer", "Joseph Borrelli", "foundation", "embedded", "nondestructive",
        "sonic", "seismic", "dispersive", "software", "computer-executable",
    ]:
        pos = page_text.lower().find(term.lower())
        if pos >= 0:
            relevant_snippets.append({"term": term, "snippet": page_text[max(0, pos-500):pos+1800]})
    patents.append({
        "patent_id": pid,
        "url": r.url,
        "title": soup.title.get_text(" ", strip=True) if soup.title else None,
        "metadata": meta,
        "relevant_snippets": relevant_snippets,
        "text_sample": page_text[:600000],
    })

# Search scholarly/public technical indexes for the same entities and techniques.
tech_queries = [
    "FDH Engineering nondestructive foundation",
    "FDH Velocitel foundation investigation",
    "Delta Oaks foundation investigation",
    "unknown foundation telecom tower nondestructive",
    "Effective Dispersion Analysis of Reflections pile foundation",
    "dispersive side sonic pile foundation",
]
other = []
for i, query in enumerate(tech_queries, 1):
    endpoints = {
        "crossref": "https://api.crossref.org/works?query.bibliographic=" + quote_plus(query) + "&rows=100",
        "openalex": "https://api.openalex.org/works?search=" + quote_plus(query) + "&per-page=100",
        "semantic_scholar": "https://api.semanticscholar.org/graph/v1/paper/search?query=" + quote_plus(query) + "&limit=100&fields=title,abstract,authors,year,url,externalIds",
        "google_books": "https://www.googleapis.com/books/v1/volumes?q=" + quote_plus(query) + "&maxResults=40",
    }
    for source, url in endpoints.items():
        r = fetch(f"tech_{i}_{source}", url, timeout=75)
        body = None
        if r:
            try:
                body = r.json()
            except Exception:
                body = {"text": r.text[:300000]}
        other.append({"query": query, "source": source, "status": r.status_code if r else None, "body": body})

# Deduplicate and rank entity/tech candidates.
seen = set()
candidates = []
for row in all_results:
    key = row.get("publication_number") or row.get("id") or json.dumps(row, sort_keys=True)
    if key in seen:
        continue
    seen.add(key)
    combined = json.dumps(row, ensure_ascii=False).lower()
    score = sum(3 for x in ["fdh", "velocitel", "delta oaks", "wave inspection"] if x in combined)
    score += sum(1 for x in ["foundation", "nondestructive", "sonic", "seismic", "dispersive", "embedded", "mapping"] if x in combined)
    if score:
        candidates.append({"score": score, **row})
candidates.sort(key=lambda x: (-x["score"], str(x.get("publication_number") or x.get("id"))))

(OUT / "searches.json").write_text(json.dumps(searches, indent=2, ensure_ascii=False), encoding="utf-8")
(OUT / "all_results.json").write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
(OUT / "ranked_candidates.json").write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")
(OUT / "patent_pages.json").write_text(json.dumps(patents, indent=2, ensure_ascii=False), encoding="utf-8")
(OUT / "technical_indexes.json").write_text(json.dumps(other, indent=2, ensure_ascii=False), encoding="utf-8")
(OUT / "fetch_records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
summary = {
    "queries": len(QUERIES),
    "search_results": len(all_results),
    "ranked_candidates": len(candidates),
    "patent_pages_resolved": len(patents),
    "fetches": len(records),
    "note": "Candidates require entity/assignment validation before linking them to any litigant or lawsuit.",
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
