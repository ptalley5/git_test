#!/usr/bin/env python3
"""Trace historical FDH foundation-investigation technology using open web archives."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("fdh-technical-trace-output")
RAW = OUT / "raw"
SNAPS = OUT / "snapshots"
for p in (OUT, RAW, SNAPS):
    p.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 OpenAI-public-records-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

TERMS = [
    "unknown foundation", "foundation investigation", "foundation mapping",
    "parallel seismic", "ultraseismic", "sonic echo", "impulse response",
    "foundation depth", "foundation geometry", "below grade", "buried foundation",
    "tower mapping", "line and antenna mapping", "foundation software",
    "proprietary software", "source code", "flash drive", "thumb drive", "usb drive",
    "fdh engineering", "fdh velocitel", "delta oaks", "cory bauer", "joseph borrelli",
]

DOMAINS = [
    "fdhengineering.com", "www.fdhengineering.com",
    "fdh-inc.com", "www.fdh-inc.com",
    "fdhvelocitel.com", "www.fdhvelocitel.com",
    "fdh-is.com", "www.fdh-is.com",
    "velocitel.com", "www.velocitel.com",
    "fdhinfrastructure.com", "www.fdhinfrastructure.com",
    "fdhengineering.net", "www.fdhengineering.net",
    "fdhtowers.com", "www.fdhtowers.com",
]

QUERIES = [
    '"FDH Engineering" tower foundation',
    '"FDH Engineering" "foundation investigation"',
    '"FDH Velocitel" foundation',
    '"FDH Velocitel" software',
    '"FDH" "parallel seismic" tower',
    '"FDH" "unknown foundation"',
    '"Cory Bauer" FDH',
    '"Cory Bauer" foundation tower',
    '"Joseph Borrelli" FDH',
    '"Joseph Borrelli" foundation tower',
    '"Delta Oaks" "unknown foundation"',
    '"Delta Oaks" "parallel seismic"',
    '"tower foundation mapping" software',
    '"unknown foundation" telecom tower',
    '"unknown foundation investigation" tower',
    '"foundation mapping" telecommunications tower',
    '"Velocitel" "FDH Engineering" acquisition',
    '"FDH Infrastructure Services" foundation',
]

manifest: list[dict[str, Any]] = []


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:180] or "item"


def fetch(label: str, url: str, timeout: int = 60, save: bool = True) -> requests.Response | None:
    try:
        r = S.get(url, timeout=timeout, allow_redirects=True)
        ctype = (r.headers.get("content-type") or "").lower()
        ext = ".bin"
        if "html" in ctype: ext = ".html"
        elif "json" in ctype: ext = ".json"
        elif "xml" in ctype: ext = ".xml"
        elif "pdf" in ctype or r.content.startswith(b"%PDF"): ext = ".pdf"
        path = None
        if save:
            path = RAW / f"{safe_name(label)}{ext}"
            path.write_bytes(r.content)
        manifest.append({
            "label": label, "url": url, "status": r.status_code,
            "final_url": r.url, "content_type": r.headers.get("content-type"),
            "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
            "path": str(path) if path else None,
        })
        print(label, r.status_code, len(r.content), r.url)
        return r
    except Exception as exc:
        manifest.append({"label": label, "url": url, "error": repr(exc)})
        print(label, "ERROR", repr(exc))
        return None


def visible_text(content: bytes, ctype: str = "") -> str:
    text = content.decode("utf-8", errors="replace")
    if "html" in ctype.lower() or "<html" in text[:500].lower():
        return re.sub(r"\s+", " ", BeautifulSoup(text, "lxml").get_text(" ", strip=True)).strip()
    return re.sub(r"\s+", " ", text).strip()


def term_hits(text: str, source: str, url: str) -> list[dict[str, Any]]:
    low = text.lower()
    hits: list[dict[str, Any]] = []
    for term in TERMS:
        pos = 0
        seen = 0
        while True:
            idx = low.find(term.lower(), pos)
            if idx < 0:
                break
            seen += 1
            if seen <= 10:
                left = max(0, idx - 350)
                right = min(len(text), idx + len(term) + 600)
                hits.append({
                    "source": source, "url": url, "term": term, "offset": idx,
                    "snippet": re.sub(r"\s+", " ", text[left:right]).strip(),
                })
            pos = idx + max(1, len(term))
    return hits


all_hits: list[dict[str, Any]] = []
search_results: list[dict[str, Any]] = []

# 1. Search-engine and Jina search passes.
for qi, query in enumerate(QUERIES, start=1):
    encoded = quote_plus(query)
    endpoints = [
        ("bing", f"https://www.bing.com/search?q={encoded}&count=50"),
        ("ddg", f"https://html.duckduckgo.com/html/?q={encoded}"),
        ("brave", f"https://search.brave.com/search?q={encoded}&source=web"),
        ("jina_bing", f"https://r.jina.ai/http://www.bing.com/search?q={encoded}"),
        ("jina_google", f"https://r.jina.ai/http://www.google.com/search?q={encoded}"),
    ]
    for engine, url in endpoints:
        r = fetch(f"search_{qi}_{engine}", url)
        if not r:
            continue
        text = visible_text(r.content, r.headers.get("content-type", ""))
        links = []
        try:
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = urljoin(r.url, a.get("href"))
                label = " ".join(a.get_text(" ", strip=True).split())
                if label or href:
                    links.append({"text": label, "href": href})
        except Exception:
            pass
        search_results.append({
            "query": query, "engine": engine, "status": r.status_code,
            "final_url": r.url, "text": text[:80000], "links": links[:1000],
        })
        all_hits.extend(term_hits(text, f"search:{engine}:{query}", r.url))
        time.sleep(0.25)

(OUT / "search_results.json").write_text(json.dumps(search_results, indent=2), encoding="utf-8")

# 2. Wayback CDX discovery and targeted snapshot capture.
wayback: dict[str, Any] = {}
interesting_re = re.compile(r"foundation|tower|mapping|inspection|service|technology|software|engineering|seismic|about|history|news|press", re.I)
for di, domain in enumerate(DOMAINS, start=1):
    cdx = (
        "https://web.archive.org/cdx/search/cdx?url=" + quote(domain + "/*", safe="") +
        "&output=json&fl=timestamp,original,statuscode,mimetype,digest,length"
        "&filter=statuscode:200&collapse=urlkey&from=2000&to=2018"
    )
    r = fetch(f"cdx_{di}_{domain}", cdx, timeout=90)
    rows = None
    if r:
        try:
            rows = r.json()
        except Exception:
            rows = None
    wayback[domain] = rows
    if not isinstance(rows, list) or len(rows) < 2:
        continue
    header = rows[0]
    records = [dict(zip(header, row)) for row in rows[1:] if len(row) == len(header)]
    # prioritize relevant paths, then homepages; cap per domain
    selected = []
    for rec in records:
        original = rec.get("original", "")
        path = urlparse(original).path or "/"
        if interesting_re.search(original):
            selected.append(rec)
    for rec in records:
        path = urlparse(rec.get("original", "")).path or "/"
        if path in {"", "/", "/index.html", "/index.htm", "/home"}:
            selected.append(rec)
    # dedupe and cap
    seen = set(); unique = []
    for rec in selected:
        key = (rec.get("timestamp"), rec.get("original"))
        if key in seen: continue
        seen.add(key); unique.append(rec)
    for si, rec in enumerate(unique[:120], start=1):
        ts = rec["timestamp"]; original = rec["original"]
        snap = f"https://web.archive.org/web/{ts}id_/{original}"
        rr = fetch(f"snapshot_{di}_{si}_{ts}_{safe_name(original)}", snap, timeout=90)
        if not rr or rr.status_code != 200:
            continue
        content_type = rr.headers.get("content-type", "")
        text = visible_text(rr.content, content_type)
        if text:
            snapshot_path = SNAPS / f"{safe_name(domain)}_{ts}_{safe_name(original)}.txt"
            snapshot_path.write_text(text, encoding="utf-8", errors="replace")
            all_hits.extend(term_hits(text, f"wayback:{domain}", original))
        time.sleep(0.15)

(OUT / "wayback_cdx.json").write_text(json.dumps(wayback, indent=2), encoding="utf-8")

# 3. Common Crawl index discovery for candidate domains.
cc_results = {}
for index in ["CC-MAIN-2026-21", "CC-MAIN-2025-30", "CC-MAIN-2024-30", "CC-MAIN-2023-50", "CC-MAIN-2022-49", "CC-MAIN-2021-49", "CC-MAIN-2020-50", "CC-MAIN-2019-51", "CC-MAIN-2018-51"]:
    index_results = {}
    for domain in DOMAINS:
        url = f"https://index.commoncrawl.org/{index}-index?url={quote(domain + '/*', safe='')}&output=json&filter=status:200"
        r = fetch(f"cc_{index}_{domain}", url, timeout=60)
        rows = []
        if r and r.status_code == 200:
            for line in r.text.splitlines():
                try: rows.append(json.loads(line))
                except Exception: pass
        if rows:
            index_results[domain] = rows[:500]
    if index_results:
        cc_results[index] = index_results
(OUT / "commoncrawl_results.json").write_text(json.dumps(cc_results, indent=2), encoding="utf-8")

# 4. Patent and publication searches.
patent_queries = [
    '"FDH Engineering"', '"FDH Velocitel"', '"Cory Bauer"', '"Joseph Borrelli"',
    '"tower foundation" mapping', '"unknown foundation" tower',
    '"parallel seismic" telecommunications',
]
patent_results = []
for pi, q in enumerate(patent_queries, start=1):
    endpoints = [
        ("google_patents", "https://patents.google.com/?q=" + quote_plus(q)),
        ("google_patents_xhr", "https://patents.google.com/xhr/query?url=q%3D" + quote_plus(q) + "&exp="),
        ("lens_jina", "https://r.jina.ai/http://www.google.com/search?q=" + quote_plus("site:patents.google.com " + q)),
        ("crossref", "https://api.crossref.org/works?query=" + quote_plus(q) + "&rows=50"),
        ("semantic_scholar", "https://api.semanticscholar.org/graph/v1/paper/search?query=" + quote_plus(q) + "&limit=50&fields=title,authors,year,url,abstract"),
    ]
    for source, url in endpoints:
        r = fetch(f"patentpub_{pi}_{source}", url, timeout=90)
        if not r: continue
        text = visible_text(r.content, r.headers.get("content-type", ""))
        patent_results.append({"query": q, "source": source, "status": r.status_code, "url": r.url, "text": text[:120000]})
        all_hits.extend(term_hits(text, f"patentpub:{source}:{q}", r.url))
        time.sleep(0.2)
(OUT / "patent_publication_results.json").write_text(json.dumps(patent_results, indent=2), encoding="utf-8")

# 5. Internet Archive metadata/full-text search.
ia_queries = [
    '"FDH Engineering"', '"FDH Velocitel"', '"foundation investigation" tower',
    '"parallel seismic" foundation', '"unknown foundation" tower',
]
ia_results = []
for ii, q in enumerate(ia_queries, start=1):
    url = "https://archive.org/advancedsearch.php?q=" + quote_plus(q) + "&fl[]=identifier,title,description,creator,date&rows=200&page=1&output=json"
    r = fetch(f"ia_search_{ii}", url, timeout=90)
    data = None
    if r:
        try: data = r.json()
        except Exception: pass
    ia_results.append({"query": q, "data": data})
(OUT / "internet_archive_search.json").write_text(json.dumps(ia_results, indent=2), encoding="utf-8")

# 6. Parse discovered external links from search results and fetch promising ones.
external_candidates = []
for result in search_results:
    for link in result.get("links", []):
        href = link.get("href", "")
        label = link.get("text", "")
        combined = (href + " " + label).lower()
        if any(token in combined for token in ["fdh", "velocitel", "deltaoaks", "delta-oaks", "foundation", "parallel-seismic", "parallel_seismic", "tower"]):
            if href.startswith("http") and not any(host in href for host in ["bing.com/search", "google.com/search", "duckduckgo.com", "search.brave.com"]):
                external_candidates.append({"href": href, "text": label, "query": result["query"], "engine": result["engine"]})
# dedupe and cap
unique_candidates=[]; seen=set()
for item in external_candidates:
    href=item["href"]
    if href in seen: continue
    seen.add(href); unique_candidates.append(item)
(OUT / "external_candidates.json").write_text(json.dumps(unique_candidates, indent=2), encoding="utf-8")
for ei, item in enumerate(unique_candidates[:250], start=1):
    r=fetch(f"external_{ei}_{safe_name(item['href'])}", item["href"], timeout=60)
    if not r or r.status_code != 200: continue
    text=visible_text(r.content, r.headers.get("content-type", ""))
    all_hits.extend(term_hits(text, "external", r.url))
    time.sleep(0.1)

# Final outputs.
(OUT / "keyword_hits.json").write_text(json.dumps(all_hits, indent=2), encoding="utf-8")
with (OUT / "keyword_hits.csv").open("w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=["source", "url", "term", "offset", "snippet"])
    writer.writeheader(); writer.writerows(all_hits)
(OUT / "fetch_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

# Build a ranked unique snippet summary.
ranked=[]; snippet_seen=set()
for hit in all_hits:
    norm=re.sub(r"\W+", " ", hit["snippet"].lower()).strip()[:300]
    if norm in snippet_seen: continue
    snippet_seen.add(norm)
    score=0
    term=hit["term"].lower(); text=hit["snippet"].lower()
    if term in {"fdh engineering","fdh velocitel","cory bauer","joseph borrelli","unknown foundation","parallel seismic"}: score += 5
    score += sum(1 for t in TERMS if t in text)
    if "wayback" in hit["source"]: score += 2
    ranked.append({"score": score, **hit})
ranked.sort(key=lambda x: (-x["score"], x["source"], x["url"]))
(OUT / "ranked_hits.json").write_text(json.dumps(ranked[:1000], indent=2), encoding="utf-8")

summary = [
    "# FDH technical trace",
    "",
    f"Fetches attempted: {len(manifest)}",
    f"Keyword/context hits: {len(all_hits)}",
    f"Unique ranked hits: {len(ranked)}",
    f"Wayback domains with rows: {sum(1 for v in wayback.values() if isinstance(v,list) and len(v)>1)}",
    f"External candidates discovered: {len(unique_candidates)}",
    "",
    "Inspect ranked_hits.json first, then wayback_cdx.json, search_results.json, patent_publication_results.json, and snapshots/.",
]
(OUT / "README.md").write_text("\n".join(summary), encoding="utf-8")
print("\n".join(summary))
