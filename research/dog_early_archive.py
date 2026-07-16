#!/usr/bin/env python3
"""Recover the earliest public Delta Oaks website wording and build a chronology."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("research-output/dog-early-archive")
RAW = OUT / "raw"
FOUND = OUT / "found"
for p in (OUT, RAW, FOUND):
    p.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 public-record-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

URLS = [
    "http://www.deltaoaksgroup.com/",
    "http://www.deltaoaksgroup.com/about-us/",
    "http://www.deltaoaksgroup.com/about-us/whats-in-a-name/",
    "http://www.deltaoaksgroup.com/leadership/",
    "http://www.deltaoaksgroup.com/leadership/cory-bauer/",
    "http://www.deltaoaksgroup.com/leadership/joe-borrelli/",
    "http://www.deltaoaksgroup.com/leadership/rhett-butler/",
    "http://www.deltaoaksgroup.com/services/field-services/",
    "http://www.deltaoaksgroup.com/services/structural-engineering/",
    "http://www.deltaoaksgroup.com/geotechnical-engineering/",
    "http://www.deltaoaksgroup.com/about-us/the-bright-side-of-patents/",
    "http://www.deltaoaksgroup.com/contact-us/",
    "https://www.deltaoaksgroup.com/",
    "https://www.deltaoaksgroup.com/about-us/",
    "https://www.deltaoaksgroup.com/about-us/whats-in-a-name/",
    "https://www.deltaoaksgroup.com/leadership/",
    "https://www.deltaoaksgroup.com/leadership/cory-bauer/",
    "https://www.deltaoaksgroup.com/leadership/joe-borrelli/",
    "https://www.deltaoaksgroup.com/leadership/rhett-butler/",
    "https://www.deltaoaksgroup.com/services/field-services/",
    "https://www.deltaoaksgroup.com/services/structural-engineering/",
    "https://www.deltaoaksgroup.com/geotechnical-engineering/",
    "https://www.deltaoaksgroup.com/about-us/the-bright-side-of-patents/",
    "https://www.deltaoaksgroup.com/contact-us/",
]
TERMS = [
    "below grade foundation mapping", "unknown foundation investigations",
    "foundation investigation", "foundation mapping", "proprietary", "patent pending",
    "patent", "non-destructive", "nondestructive", "Cory Bauer", "Joe Borrelli",
    "Joseph Borrelli", "Rhett Butler", "founding member", "co-founder", "October 2015",
    "previous jobs", "Delta", "Oaks", "geotechnical investigation", "pull testing",
]
records = []
captures = []
pages = []
hits = []


def safe(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", v).strip("_")[:190] or "item"


def fetch(label: str, url: str, *, params=None, timeout=75, save=False):
    try:
        r = S.get(url, params=params, timeout=timeout, allow_redirects=True)
        data = r.content; ctype = r.headers.get("content-type", "")
        path = None
        if save:
            ext = ".json" if "json" in ctype.lower() else ".html" if "html" in ctype.lower() or data.lstrip().startswith(b"<") else ".bin"
            path = RAW / f"{safe(label)}{ext}"; path.write_bytes(data)
        records.append({
            "label": label, "requested_url": r.request.url, "status": r.status_code,
            "final_url": r.url, "content_type": ctype, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest() if data else None,
            "saved": str(path) if path else None,
        })
        print(label, r.status_code, len(data), r.url, flush=True)
        return r
    except Exception as exc:
        records.append({"label": label, "requested_url": url, "error": repr(exc)})
        print(label, "ERROR", repr(exc), flush=True)
        return None


def clean_text(data: bytes) -> tuple[str, str | None]:
    soup = BeautifulSoup(data, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    return text, title


def scan(source: str, original: str, timestamp: str, text: str):
    low = text.lower()
    for term in TERMS:
        start = 0; count = 0
        while True:
            i = low.find(term.lower(), start)
            if i < 0:
                break
            count += 1
            if count <= 12:
                hits.append({
                    "source": source, "original": original, "timestamp": timestamp,
                    "term": term,
                    "snippet": re.sub(r"\s+", " ", text[max(0, i-600):i+len(term)+1700]),
                })
            start = i + max(1, len(term))


def main():
    by_url = defaultdict(list)
    for idx, url in enumerate(URLS, 1):
        r = fetch(f"cdx_{idx}", "https://web.archive.org/cdx/search/cdx", params={
            "url": url, "output": "json",
            "fl": "timestamp,original,statuscode,mimetype,digest,length",
            "filter": "statuscode:200", "filter": "timestamp:2015-2024",
            "collapse": "digest", "limit": "1000",
        }, timeout=100, save=True)
        if not r:
            continue
        try:
            rows = r.json()
        except Exception:
            continue
        if not isinstance(rows, list) or len(rows) < 2:
            continue
        head = rows[0]
        for row in rows[1:]:
            cap = dict(zip(head, row)); cap["query_url"] = url
            captures.append(cap); by_url[cap.get("original") or url].append(cap)

    # Select earliest capture, first capture in each year, and all distinct captures through 2021.
    selected = {}
    for original, rows in by_url.items():
        rows = sorted(rows, key=lambda x: x.get("timestamp", ""))
        if rows:
            selected[(original, rows[0]["timestamp"])] = rows[0]
        years = set()
        for cap in rows:
            y = cap.get("timestamp", "")[:4]
            if y and y not in years:
                years.add(y); selected[(original, cap["timestamp"])] = cap
            if cap.get("timestamp", "") < "20220101000000":
                selected[(original, cap["timestamp"])] = cap

    for idx, cap in enumerate(sorted(selected.values(), key=lambda x: x.get("timestamp", "")), 1):
        url = f"https://web.archive.org/web/{cap['timestamp']}id_/{cap['original']}"
        r = fetch(f"replay_{idx}_{cap['timestamp']}", url, timeout=100, save=False)
        if not r or r.status_code != 200 or not r.content:
            continue
        text, title = clean_text(r.content)
        path = FOUND / f"{cap['timestamp']}_{safe(cap['original'])}.html"
        path.write_bytes(r.content)
        page = {
            "timestamp": cap["timestamp"], "original": cap["original"], "replay_url": url,
            "final_url": r.url, "title": title, "size": len(r.content),
            "sha256": hashlib.sha256(r.content).hexdigest(), "saved": str(path),
            "text": text[:250000],
        }
        pages.append(page); scan("wayback", cap["original"], cap["timestamp"], text)

    # Capture current public pages for comparison.
    current_urls = sorted(set(u.replace("http://", "https://") for u in URLS if "www.deltaoaksgroup.com" in u))
    for idx, url in enumerate(current_urls, 1):
        r = fetch(f"current_{idx}", url, timeout=75, save=False)
        if not r or r.status_code != 200:
            continue
        text, title = clean_text(r.content)
        path = FOUND / f"current_{safe(url)}.html"; path.write_bytes(r.content)
        page = {"timestamp": "current", "original": url, "replay_url": url, "final_url": r.url,
                "title": title, "size": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                "saved": str(path), "text": text[:250000]}
        pages.append(page); scan("current", url, "current", text)

    (OUT / "captures.json").write_text(json.dumps(captures, indent=2), encoding="utf-8")
    (OUT / "pages.json").write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "hits.json").write_text(json.dumps(hits, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "fetch_records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    summary = {
        "captures": len(captures), "selected_pages_recovered": len(pages), "keyword_hits": len(hits),
        "earliest_capture": min((x.get("timestamp", "") for x in captures), default=None),
        "note": "Public Wayback and current pages only.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
