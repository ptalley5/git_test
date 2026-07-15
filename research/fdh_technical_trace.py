#!/usr/bin/env python3
"""Bounded open-source trace of historical FDH foundation technology."""
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
for directory in (OUT, RAW, SNAPS):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
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
hits: list[dict[str, Any]] = []


def safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")[:160] or "item"


def fetch(label: str, url: str, timeout: int = 12) -> requests.Response | None:
    try:
        response = SESSION.get(url, timeout=timeout, allow_redirects=True)
        ctype = (response.headers.get("content-type") or "").lower()
        suffix = ".html" if "html" in ctype else ".json" if "json" in ctype else ".xml" if "xml" in ctype else ".pdf" if "pdf" in ctype or response.content.startswith(b"%PDF") else ".bin"
        path = RAW / f"{safe(label)}{suffix}"
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


def text_of(response: requests.Response) -> str:
    raw = response.content.decode("utf-8", errors="replace")
    if "html" in (response.headers.get("content-type") or "").lower() or "<html" in raw[:500].lower():
        raw = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", raw).strip()


def capture_hits(text: str, source: str, url: str) -> None:
    lowered = text.lower()
    for term in TERMS:
        start = 0
        count = 0
        while True:
            index = lowered.find(term.lower(), start)
            if index < 0:
                break
            count += 1
            if count <= 6:
                hits.append({
                    "source": source,
                    "url": url,
                    "term": term,
                    "offset": index,
                    "snippet": text[max(0, index - 320):min(len(text), index + len(term) + 520)],
                })
            start = index + max(1, len(term))


search_results = []
candidates: list[dict[str, str]] = []
for number, query in enumerate(QUERIES, start=1):
    url = "https://r.jina.ai/http://www.google.com/search?q=" + quote_plus(query)
    response = fetch(f"search_{number}", url)
    if not response:
        continue
    text = text_of(response)
    capture_hits(text, f"search:{query}", response.url)
    search_results.append({"query": query, "status": response.status_code, "url": response.url, "text": text[:100000]})
    for match in re.finditer(r"https?://[^\s\])>\"']+", text):
        href = match.group(0).rstrip(".,;:")
        combined = href.lower()
        if any(token in combined for token in ["fdh", "velocitel", "deltaoaks", "delta-oaks", "foundation", "parallel-seismic"]):
            if not any(host in href for host in ["google.com/search", "r.jina.ai/http://www.google.com/search"]):
                candidates.append({"href": href, "query": query})
(OUT / "search_results.json").write_text(json.dumps(search_results, indent=2), encoding="utf-8")

# Retrieve only the five most relevant archived URLs per candidate domain.
wayback: dict[str, Any] = {}
relevant_path = re.compile(r"foundation|tower|mapping|inspection|service|technology|software|seismic|engineering|capabilit|about|history", re.I)
for domain_number, domain in enumerate(DOMAINS, start=1):
    cdx_url = (
        "https://web.archive.org/cdx/search/cdx?url=" + quote(domain + "/*", safe="")
        + "&output=json&fl=timestamp,original,statuscode,mimetype,digest,length"
        + "&filter=statuscode:200&collapse=urlkey&from=2010&to=2017"
    )
    response = fetch(f"cdx_{domain_number}_{domain}", cdx_url, timeout=20)
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
    relevant = []
    for record in records:
        original = record.get("original", "")
        path = urlparse(original).path or "/"
        if relevant_path.search(original) or path in {"", "/", "/index.html", "/index.htm", "/home"}:
            relevant.append(record)
    relevant.sort(key=lambda item: (0 if relevant_path.search(item.get("original", "")) else 1, abs(int(item.get("timestamp", "20150000000000")[:4]) - 2015)))
    chosen = []
    seen_urls = set()
    for record in relevant:
        original = record.get("original", "")
        if original in seen_urls:
            continue
        seen_urls.add(original)
        chosen.append(record)
        if len(chosen) == 5:
            break
    for snapshot_number, record in enumerate(chosen, start=1):
        timestamp = record["timestamp"]
        original = record["original"]
        snapshot_url = f"https://web.archive.org/web/{timestamp}id_/{original}"
        snapshot = fetch(f"snapshot_{domain_number}_{snapshot_number}_{timestamp}_{safe(original)}", snapshot_url, timeout=15)
        if not snapshot or snapshot.status_code != 200:
            continue
        text = text_of(snapshot)
        (SNAPS / f"{safe(domain)}_{timestamp}_{safe(original)}.txt").write_text(text, encoding="utf-8", errors="replace")
        capture_hits(text, f"wayback:{domain}", original)
(OUT / "wayback_cdx.json").write_text(json.dumps(wayback, indent=2), encoding="utf-8")

research_results = []
for query_number, query in enumerate([
    '"FDH Engineering"', '"FDH Velocitel"', '"Cory Bauer" tower',
    '"Joseph Borrelli" tower', '"unknown foundation" tower',
    '"parallel seismic" telecommunications',
], start=1):
    encoded = quote_plus(query)
    for source, url in [
        ("patents", "https://patents.google.com/?q=" + encoded),
        ("crossref", "https://api.crossref.org/works?query=" + encoded + "&rows=20"),
    ]:
        response = fetch(f"research_{query_number}_{source}", url, timeout=15)
        if not response:
            continue
        text = text_of(response)
        research_results.append({"query": query, "source": source, "status": response.status_code, "url": response.url, "text": text[:100000]})
        capture_hits(text, f"research:{source}:{query}", response.url)
(OUT / "research_results.json").write_text(json.dumps(research_results, indent=2), encoding="utf-8")

# Bounded follow-up of URLs named in search text.
unique_candidates = []
seen = set()
for candidate in candidates:
    if candidate["href"] in seen:
        continue
    seen.add(candidate["href"])
    unique_candidates.append(candidate)
(OUT / "external_candidates.json").write_text(json.dumps(unique_candidates, indent=2), encoding="utf-8")
for index, candidate in enumerate(unique_candidates[:20], start=1):
    response = fetch(f"external_{index}_{safe(candidate['href'])}", candidate["href"], timeout=10)
    if response and response.status_code == 200:
        capture_hits(text_of(response), "external", response.url)

# Deduplicate and rank snippets.
ranked = []
seen_snippets = set()
for hit in hits:
    normalized = re.sub(r"\W+", " ", hit["snippet"].lower()).strip()[:350]
    if normalized in seen_snippets:
        continue
    seen_snippets.add(normalized)
    score = sum(1 for term in TERMS if term in hit["snippet"].lower())
    if hit["term"].lower() in {"fdh engineering", "fdh velocitel", "cory bauer", "joseph borrelli", "unknown foundation", "parallel seismic", "foundation software"}:
        score += 5
    if hit["source"].startswith("wayback:"):
        score += 3
    ranked.append({"score": score, **hit})
ranked.sort(key=lambda item: (-item["score"], item["source"], item["url"]))

(OUT / "keyword_hits.json").write_text(json.dumps(hits, indent=2), encoding="utf-8")
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
    f"Raw term hits: {len(hits)}",
    f"Unique ranked hits: {len(ranked)}",
    f"Wayback domains with indexed captures: {sum(1 for value in wayback.values() if isinstance(value, list) and len(value) > 1)}",
    f"Promising external candidates: {len(unique_candidates)}",
    "",
    "Inspect ranked_hits.json first, followed by wayback_cdx.json, research_results.json, search_results.json, and snapshots/.",
]
(OUT / "README.md").write_text("\n".join(summary), encoding="utf-8")
print("\n".join(summary))
