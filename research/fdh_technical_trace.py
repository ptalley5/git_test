#!/usr/bin/env python3
"""Resolve FDH Engineering patent portfolio using Google Patents public endpoints."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("fdh-technical-trace-output")
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})

QUERIES = [
    '"Fdh Engineering, Inc."',
    '"Fdh Engineering"',
    '"FDH Infrastructure Services" patent',
    '"J. Darrin Holt"',
    '"Mark Cesare" "FDH Engineering"',
    '"Robert Lindyberg" "FDH Engineering"',
    '"subsurface anchor corrosion" patent',
    '"concrete structural mapping" patent',
    '"mapping steel reinforcements" concrete foundation',
    '"determining tension in a rod"',
    '"dispersive side sonic" patent',
    '"dispersive pulse echo" patent',
]
KNOWN_IDS = ["US7548192B1", "US8176800B2", "US20230213401A1", "WO2012094284A2", "CA3022477A1", "EP3455413A1", "US10451399B2"]


def fetch(label: str, url: str, **kwargs):
    try:
        r = S.get(url, timeout=45, allow_redirects=True, **kwargs)
        ctype = (r.headers.get("content-type") or "").lower()
        ext = ".json" if "json" in ctype else ".html" if "html" in ctype else ".bin"
        (RAW / f"{label}{ext}").write_bytes(r.content)
        print(label, r.status_code, len(r.content), r.url, r.headers.get("content-type"), flush=True)
        return r
    except Exception as exc:
        print(label, "ERROR", repr(exc), flush=True)
        return None


def normalize_patent_result(item):
    patent = item.get("patent", {})
    return {
        "id": item.get("id"),
        "rank": item.get("rank"),
        "title": BeautifulSoup(patent.get("title", ""), "lxml").get_text(" ", strip=True),
        "snippet": BeautifulSoup(patent.get("snippet", ""), "lxml").get_text(" ", strip=True),
        "priority_date": patent.get("priority_date"),
        "filing_date": patent.get("filing_date"),
        "grant_date": patent.get("grant_date"),
        "publication_date": patent.get("publication_date"),
        "inventor": patent.get("inventor"),
        "assignee": patent.get("assignee"),
        "publication_number": patent.get("publication_number"),
        "pdf": patent.get("pdf"),
        "entity_matches": item.get("entity_matches"),
    }


searches = []
for i, query in enumerate(QUERIES, 1):
    r = fetch(f"xhr_{i}", "https://patents.google.com/xhr/query", params={"url": "q=" + query, "exp": ""})
    parsed = None
    normalized = []
    if r:
        try:
            parsed = r.json()
            results = parsed.get("results", {})
            for cluster in results.get("cluster", []):
                for item in cluster.get("result", []):
                    normalized.append(normalize_patent_result(item))
        except Exception:
            parsed = {"raw_text": r.text[:300000]}
    web = fetch(f"web_{i}", "https://r.jina.ai/http://www.google.com/search?q=" + quote_plus("site:patents.google.com/patent " + query))
    searches.append({
        "query": query,
        "xhr_status": r.status_code if r else None,
        "total": (parsed or {}).get("results", {}).get("total_num_results") if isinstance(parsed, dict) else None,
        "results": normalized,
        "web_status": web.status_code if web else None,
        "web_text": web.text[:300000] if web else "",
    })

patents = []
for patent_id in KNOWN_IDS:
    r = fetch(f"patent_{patent_id}", f"https://patents.google.com/patent/{patent_id}/en")
    if not r:
        continue
    soup = BeautifulSoup(r.text, "lxml")
    metadata = {}
    for meta in soup.find_all("meta"):
        scheme = meta.get("scheme")
        name = meta.get("name") or meta.get("property")
        content = meta.get("content")
        key = scheme or name
        if key and content:
            metadata.setdefault(key, []).append(content)
    # Patent pages also expose schema.org tags as <meta scheme="...">.
    fields = {}
    for field in [
        "title", "DC.title", "DC.contributor", "DC.relation", "DC.date", "DC.type",
        "inventor", "assignee", "filingDate", "priorityDate", "publicationDate", "grantDate",
    ]:
        nodes = soup.find_all(attrs={"scheme": field}) + soup.find_all("meta", attrs={"name": field})
        vals = [n.get("content") for n in nodes if n.get("content")]
        if vals:
            fields[field] = vals
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    patents.append({
        "patent_id": patent_id,
        "status": r.status_code,
        "final_url": r.url,
        "page_title": soup.title.get_text(" ", strip=True) if soup.title else None,
        "fields": fields,
        "metadata": metadata,
        "text_sample": text[:500000],
        "links": [
            {"text": " ".join(a.get_text(" ", strip=True).split()), "href": urljoin(r.url, a.get("href"))}
            for a in soup.find_all("a", href=True)
            if "/patent/" in a.get("href", "")
        ][:500],
    })

(OUT / "portfolio_searches.json").write_text(json.dumps(searches, indent=2, ensure_ascii=False), encoding="utf-8")
(OUT / "patent_metadata.json").write_text(json.dumps(patents, indent=2, ensure_ascii=False), encoding="utf-8")

# Deduplicate potentially FDH-related search results.
candidates = []
seen = set()
for search in searches:
    for result in search["results"]:
        combined = " ".join(str(result.get(k) or "") for k in ["title", "snippet", "inventor", "assignee", "publication_number"]).lower()
        if any(token in combined for token in ["fdh", "darrin holt", "lindyberg", "mark cesare", "foundation", "rod", "reinforcement"]):
            key = result.get("publication_number") or result.get("id")
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"matched_query": search["query"], **result})
(OUT / "fdh_patent_candidates.json").write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")

print("\n=== FDH CANDIDATES ===", flush=True)
print(json.dumps(candidates, indent=2, ensure_ascii=False), flush=True)
print("\n=== KNOWN PATENT METADATA ===", flush=True)
print(json.dumps(patents, indent=2, ensure_ascii=False)[:200000], flush=True)
