#!/usr/bin/env python3
"""Focused trace of historical FDH foundation-investigation technology."""
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
    "fdhengineering.com", "fdh-inc.com", "fdhvelocitel.com",
    "fdh-is.com", "velocitel.com", "fdhinfrastructure.com",
]
QUERIES = [
    '"FDH Engineering" "foundation investigation"',
    '"FDH Velocitel" foundation software',
    '"FDH" "parallel seismic" tower',
    '"FDH" "unknown foundation" tower',
    '"Cory Bauer" FDH tower',
    '"Joseph Borrelli" FDH tower',
    '"Delta Oaks" "parallel seismic"',
    '"unknown foundation investigation" telecom tower',
    '"tower foundation mapping" software',
    '"FDH Infrastructure Services" foundation',
]

manifest: list[dict[str, Any]] = []
all_hits: list[dict[str, Any]] = []


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")[:170] or "item"


def fetch(label: str, url: str, timeout: int = 30) -> requests.Response | None:
    try:
        response = S.get(url, timeout=timeout, allow_redirects=True)
        ctype = (response.headers.get("content-type") or "").lower()
        ext = ".bin"
        if "html" in ctype:
            ext = ".html"
        elif "json" in ctype:
            ext = ".json"
        elif "xml" in ctype:
            ext = ".xml"
        elif "pdf" in ctype or response.content.startswith(b"%PDF"):
            ext = ".pdf"
        path = RAW / f"{safe_name(label)}{ext}"
        path.write_bytes(response.content)
        manifest.append({
            "label": label,
            "requested_url": url,
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type"),
            "bytes": len(response.content),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "path": str(path),
        })
        print(label, response.status_code, len(response.content), response.url)
        return response
    except Exception as exc:
        manifest.append({"label": label, "requested_url": url, "error": repr(exc)})
        print(label, "ERROR", repr(exc))
        return None


def visible_text(response: requests.Response) -> str:
    raw = response.content.decode("utf-8", errors="replace")
    if "html" in (response.headers.get("content-type") or "").lower() or "<html" in raw[:500].lower():
        raw = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", raw).strip()


def collect_hits(text: str, source: str, url: str) -> None:
    lowered = text.lower()
    for term in TERMS:
        start = 0
        occurrences = 0
        while True:
            index = lowered.find(term.lower(), start)
            if index < 0:
                break
            occurrences += 1
            if occurrences <= 8:
                left = max(0, index - 350)
                right = min(len(text), index + len(term) + 600)
                all_hits.append({
                    "source": source,
                    "url": url,
                    "term": term,
                    "offset": index,
                    "snippet": re.sub(r"\s+", " ", text[left:right]).strip(),
                })
            start = index + max(1, len(term))


# Search engines: use one normal HTML result and one text proxy per query.
search_results: list[dict[str, Any]] = []
external_candidates: list[dict[str, str]] = []
for qi, query in enumerate(QUERIES, start=1):
    encoded = quote_plus(query)
    for engine, url in [
        ("bing", f"https://www.bing.com/search?q={encoded}&count=50"),
        ("jina_google", f"https://r.jina.ai/http://www.google.com/search?q={encoded}"),
    ]:
        response = fetch(f"search_{qi}_{engine}", url)
        if not response:
            continue
        text = visible_text(response)
        collect_hits(text, f"search:{engine}:{query}", response.url)
        links = []
        try:
            soup = BeautifulSoup(response.text, "lxml")
            for anchor in soup.find_all("a", href=True):
                href = urljoin(response.url, anchor.get("href"))
                label = " ".join(anchor.get_text(" ", strip=True).split())
                links.append({"text": label, "href": href})
                combined = (href + " " + label).lower()
                if href.startswith("http") and any(token in combined for token in [
                    "fdh", "velocitel", "deltaoaks", "delta-oaks", "parallel-seismic",
                    "foundation", "tower-mapping", "tower_mapping",
                ]):
                    if not any(host in href for host in ["bing.com/search", "google.com/search"]):
                        external_candidates.append({"href": href, "text": label, "query": query})
        except Exception:
            pass
        search_results.append({
            "query": query,
            "engine": engine,
            "status": response.status_code,
            "final_url": response.url,
            "text": text[:80000],
            "links": links[:500],
        })
        time.sleep(0.15)
(OUT / "search_results.json").write_text(json.dumps(search_results, indent=2), encoding="utf-8")

# Historical FDH/Velocitel pages, restricted to the relevant period and paths.
wayback: dict[str, Any] = {}
path_pattern = re.compile(
    r"foundation|tower|mapping|inspection|service|technology|software|seismic|engineering|about|history|news|press|capabilit",
    re.I,
)
for di, domain in enumerate(DOMAINS, start=1):
    cdx_url = (
        "https://web.archive.org/cdx/search/cdx?url=" + quote(domain + "/*", safe="")
        + "&output=json&fl=timestamp,original,statuscode,mimetype,digest,length"
        + "&filter=statuscode:200&collapse=urlkey&from=2010&to=2017"
    )
    response = fetch(f"cdx_{di}_{domain}", cdx_url, timeout=45)
    rows = None
    if response:
        try:
            rows = response.json()
        except Exception:
            rows = None
    wayback[domain] = rows
    if not isinstance(rows, list) or len(rows) < 2:
        continue
    header = rows[0]
    records = [dict(zip(header, row)) for row in rows[1:] if len(row) == len(header)]
    selected = []
    for record in records:
        original = record.get("original", "")
        path = urlparse(original).path or "/"
        if path_pattern.search(original) or path in {"", "/", "/index.html", "/index.htm", "/home"}:
            selected.append(record)
    # Prefer snapshots closest to the 2015 filing; one per URL, max 20 per domain.
    selected.sort(key=lambda record: abs(int(record.get("timestamp", "20150000000000")[:4]) - 2015))
    seen_urls: set[str] = set()
    picked = []
    for record in selected:
        original = record.get("original", "")
        if original in seen_urls:
            continue
        seen_urls.add(original)
        picked.append(record)
        if len(picked) >= 20:
            break
    for si, record in enumerate(picked, start=1):
        timestamp = record["timestamp"]
        original = record["original"]
        snapshot_url = f"https://web.archive.org/web/{timestamp}id_/{original}"
        snapshot = fetch(f"snapshot_{di}_{si}_{timestamp}_{safe_name(original)}", snapshot_url, timeout=45)
        if not snapshot or snapshot.status_code != 200:
            continue
        text = visible_text(snapshot)
        (SNAPS / f"{safe_name(domain)}_{timestamp}_{safe_name(original)}.txt").write_text(
            text, encoding="utf-8", errors="replace"
        )
        collect_hits(text, f"wayback:{domain}", original)
        time.sleep(0.1)
(OUT / "wayback_cdx.json").write_text(json.dumps(wayback, indent=2), encoding="utf-8")

# Patent, paper, and archive checks for names and the relevant techniques.
research_queries = [
    '"FDH Engineering"',
    '"FDH Velocitel"',
    '"Cory Bauer" tower',
    '"Joseph Borrelli" tower',
    '"unknown foundation" tower',
    '"parallel seismic" telecommunications',
]
research_results = []
for ri, query in enumerate(research_queries, start=1):
    encoded = quote_plus(query)
    endpoints = [
        ("google_patents", "https://patents.google.com/?q=" + encoded),
        ("crossref", "https://api.crossref.org/works?query=" + encoded + "&rows=25"),
        ("archive", "https://archive.org/advancedsearch.php?q=" + encoded + "&fl[]=identifier,title,description,creator,date&rows=50&page=1&output=json"),
    ]
    for source, url in endpoints:
        response = fetch(f"research_{ri}_{source}", url, timeout=45)
        if not response:
            continue
        text = visible_text(response)
        research_results.append({
            "query": query,
            "source": source,
            "status": response.status_code,
            "final_url": response.url,
            "text": text[:100000],
        })
        collect_hits(text, f"research:{source}:{query}", response.url)
        time.sleep(0.1)
(OUT / "research_results.json").write_text(json.dumps(research_results, indent=2), encoding="utf-8")

# Fetch a deduplicated, bounded set of promising search-result pages.
unique_candidates = []
seen = set()
for candidate in external_candidates:
    href = candidate["href"]
    if href in seen:
        continue
    seen.add(href)
    unique_candidates.append(candidate)
(OUT / "external_candidates.json").write_text(json.dumps(unique_candidates, indent=2), encoding="utf-8")
for ei, candidate in enumerate(unique_candidates[:50], start=1):
    response = fetch(f"external_{ei}_{safe_name(candidate['href'])}", candidate["href"], timeout=30)
    if response and response.status_code == 200:
        collect_hits(visible_text(response), "external", response.url)
    time.sleep(0.05)

# De-duplicate and rank context snippets.
ranked = []
seen_snippets = set()
for hit in all_hits:
    normalized = re.sub(r"\W+", " ", hit["snippet"].lower()).strip()[:400]
    if normalized in seen_snippets:
        continue
    seen_snippets.add(normalized)
    score = sum(1 for term in TERMS if term in hit["snippet"].lower())
    if hit["term"].lower() in {
        "fdh engineering", "fdh velocitel", "cory bauer", "joseph borrelli",
        "unknown foundation", "parallel seismic", "foundation software",
    }:
        score += 5
    if hit["source"].startswith("wayback:"):
        score += 3
    ranked.append({"score": score, **hit})
ranked.sort(key=lambda item: (-item["score"], item["source"], item["url"]))

(OUT / "keyword_hits.json").write_text(json.dumps(all_hits, indent=2), encoding="utf-8")
(OUT / "ranked_hits.json").write_text(json.dumps(ranked[:1000], indent=2), encoding="utf-8")
with (OUT / "ranked_hits.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["score", "source", "url", "term", "offset", "snippet"])
    writer.writeheader()
    writer.writerows(ranked[:1000])
(OUT / "fetch_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

summary = [
    "# FDH technical trace",
    "",
    f"Fetch attempts: {len(manifest)}",
    f"Raw term hits: {len(all_hits)}",
    f"Unique ranked hits: {len(ranked)}",
    f"Wayback domains with indexed captures: {sum(1 for rows in wayback.values() if isinstance(rows, list) and len(rows) > 1)}",
    f"Promising external candidates: {len(unique_candidates)}",
    "",
    "Inspect ranked_hits.json first, then wayback_cdx.json, research_results.json, search_results.json, and snapshots/.",
]
(OUT / "README.md").write_text("\n".join(summary), encoding="utf-8")
print("\n".join(summary))
