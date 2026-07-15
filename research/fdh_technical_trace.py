#!/usr/bin/env python3
"""Search public patent indexes for FDH Velocitel's claimed NDE patents."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

OUT = Path("fdh-technical-trace-output")
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})

QUERIES = [
    '"dispersive side sonic"',
    '"dispersive pulse echo" foundation',
    '"dispersive wave propagation" foundation',
    '"unknown foundation" nondestructive',
    'inventor="J Darrin Holt"',
    'inventor="Darrin Holt"',
    'inventor="Robert Lindyberg"',
    'inventor="Robert Douglas" foundation',
    'inventor="Laura Guy" nondestructive',
    'assignee="FDH Engineering"',
    'assignee="FDH Velocitel"',
    'assignee="Velocitel" nondestructive',
]

results = []


def fetch(label: str, url: str, **kwargs):
    try:
        response = SESSION.get(url, timeout=40, allow_redirects=True, **kwargs)
        suffix = ".json" if "json" in (response.headers.get("content-type") or "").lower() else ".html"
        (RAW / f"{label}{suffix}").write_bytes(response.content)
        print(label, response.status_code, len(response.content), response.url, response.headers.get("content-type"), flush=True)
        return response
    except Exception as exc:
        print(label, "ERROR", repr(exc), flush=True)
        return None


for index, query in enumerate(QUERIES, start=1):
    # Google Patents XHR search endpoint.
    xhr = fetch(
        f"xhr_{index}",
        "https://patents.google.com/xhr/query",
        params={"url": "q=" + query, "exp": ""},
    )
    xhr_data = None
    if xhr:
        try:
            xhr_data = xhr.json()
        except Exception:
            xhr_data = {"text": xhr.text[:200000]}

    # Normal Google Patents page, useful for metadata and result links.
    html = fetch(
        f"html_{index}",
        "https://patents.google.com/",
        params={"q": query},
    )
    html_links = []
    html_text = ""
    if html:
        soup = BeautifulSoup(html.text, "lxml")
        html_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href")
            label = " ".join(anchor.get_text(" ", strip=True).split())
            if href and ("/patent/" in href or re.search(r"\b(?:US|WO|EP)\d", label)):
                html_links.append({"text": label, "href": href})

    # Google web search through Jina text proxy to surface indexed patent pages.
    web = fetch(
        f"web_{index}",
        "https://r.jina.ai/http://www.google.com/search?q=" + quote_plus("site:patents.google.com " + query),
    )
    web_text = web.text[:300000] if web else ""

    results.append({
        "query": query,
        "xhr_status": xhr.status_code if xhr else None,
        "xhr": xhr_data,
        "html_status": html.status_code if html else None,
        "html_text": html_text[:200000],
        "html_links": html_links,
        "web_status": web.status_code if web else None,
        "web_text": web_text,
    })

(OUT / "patent_search_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

# Extract likely publication numbers and context from all responses.
candidates = []
publication_pattern = re.compile(r"\b(?:US|WO|EP|CA|AU)\s*\d{4,}[A-Z]?\d?\b", re.I)
for record in results:
    combined = json.dumps(record, ensure_ascii=False)
    for match in publication_pattern.finditer(combined):
        number = re.sub(r"\s+", "", match.group(0).upper())
        candidates.append({
            "query": record["query"],
            "publication": number,
            "context": combined[max(0, match.start() - 350):match.end() + 650],
        })
    for link in record.get("html_links", []):
        candidates.append({"query": record["query"], "publication": link.get("text"), "url": link.get("href")})

# Deduplicate.
unique = []
seen = set()
for candidate in candidates:
    key = (candidate.get("query"), candidate.get("publication"), candidate.get("url"))
    if key in seen:
        continue
    seen.add(key)
    unique.append(candidate)
(OUT / "patent_candidates.json").write_text(json.dumps(unique, indent=2, ensure_ascii=False), encoding="utf-8")

print("\n=== PATENT CANDIDATES ===", flush=True)
print(json.dumps(unique[:300], indent=2, ensure_ascii=False), flush=True)
print("\nQueries:", len(results), "Candidates:", len(unique), flush=True)
