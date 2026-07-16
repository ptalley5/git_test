#!/usr/bin/env python3
"""Recover archived FDH/Velocitel/Delta Oaks service and technology pages.

Uses the Internet Archive CDX/replay endpoints and public current websites only.
No authentication or restricted content is accessed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("research-output/fdh-website-archive")
RAW = OUT / "raw"
FOUND = OUT / "found"
for p in (OUT, RAW, FOUND):
    p.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 public-archive-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

DOMAINS = [
    "fdh-inc.com", "www.fdh-inc.com",
    "fdhengineering.com", "www.fdhengineering.com",
    "fdhvelocitel.com", "www.fdhvelocitel.com",
    "velocitel.com", "www.velocitel.com",
    "deltaoaksgroup.com", "www.deltaoaksgroup.com",
]

TERMS = [
    "unknown foundation", "foundation investigation", "foundation mapping",
    "foundation depth", "foundation condition", "forensic foundation",
    "below grade", "below-grade", "parallel seismic", "sonic echo",
    "impulse response", "dispersive", "pulse echo", "nondestructive",
    "non-destructive", "NDE", "NDT", "reinforcing steel", "reinforcement mapping",
    "concrete coring", "ground penetrating radar", "GPR", "embedded length",
    "software", "source code", "mapping", "inspection", "technology",
    "Cory Bauer", "Joseph Borrelli", "Joe Borrelli", "Rhett Butler",
]

records = []
discoveries = []


def safe(v: str, limit: int = 170) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", v).strip("_")[:limit] or "item"


def text_of(data: bytes, ctype: str = "", limit: int = 500000) -> str:
    try:
        if "html" in ctype.lower() or data.lstrip().startswith(b"<"):
            return re.sub(r"\s+", " ", BeautifulSoup(data, "lxml").get_text(" ", strip=True))[:limit]
        return data.decode("utf-8", "replace")[:limit]
    except Exception:
        return ""


def fetch(label: str, url: str, params=None, timeout=80, save_dir=RAW):
    try:
        r = S.get(url, params=params, timeout=timeout, allow_redirects=True)
        data = r.content
        ct = r.headers.get("content-type", "")
        ext = ".pdf" if data.startswith(b"%PDF") or "pdf" in ct.lower() else \
              ".json" if "json" in ct.lower() else \
              ".xml" if "xml" in ct.lower() else \
              ".html" if "html" in ct.lower() or data.lstrip().startswith(b"<") else ".bin"
        path = save_dir / f"{safe(label)}{ext}"
        path.write_bytes(data)
        rec = {
            "label": label, "url": url, "request_url": r.request.url,
            "status": r.status_code, "final_url": r.url, "content_type": ct,
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest() if data else None,
            "saved": str(path), "text_sample": text_of(data, ct, 25000),
        }
        records.append(rec)
        print(label, r.status_code, len(data), r.url, flush=True)
        return r, path
    except Exception as exc:
        records.append({"label": label, "url": url, "error": repr(exc)})
        print(label, "ERROR", repr(exc), flush=True)
        return None, None


def hits(source: str, original_url: str, text: str):
    lower = text.lower()
    out = []
    for term in TERMS:
        start = 0
        count = 0
        while True:
            idx = lower.find(term.lower(), start)
            if idx < 0:
                break
            count += 1
            if count <= 8:
                out.append({
                    "source": source, "url": original_url, "term": term,
                    "snippet": re.sub(r"\s+", " ", text[max(0, idx-600):idx+2000]),
                })
            start = idx + max(1, len(term))
    return out


all_captures = []
selected = []
for domain in DOMAINS:
    r, _ = fetch(
        "cdx_" + safe(domain),
        "https://web.archive.org/cdx/search/cdx",
        params={
            "url": domain + "/*", "output": "json",
            "fl": "timestamp,original,statuscode,mimetype,digest,length",
            "filter": "statuscode:200", "from": "2008", "to": "2021",
            "collapse": "digest", "limit": "10000",
        },
        timeout=120,
    )
    if not r or r.status_code != 200:
        continue
    try:
        rows = r.json()
    except Exception:
        continue
    if not isinstance(rows, list) or len(rows) < 2:
        continue
    header = rows[0]
    for row in rows[1:]:
        cap = dict(zip(header, row))
        cap["domain"] = domain
        all_captures.append(cap)
        original = (cap.get("original") or "")
        u = original.lower()
        mime = (cap.get("mimetype") or "").lower()
        url_score = sum(4 for x in [
            "foundation", "below-grade", "below_grade", "inspection", "mapping",
            "nondestruct", "non-destruct", "parallel-seismic", "sonic", "seismic",
            "reinforc", "concrete", "geotechnical", "technology", "service", "patent",
        ] if x in u)
        url_score += 3 if "pdf" in mime or u.endswith(".pdf") else 0
        url_score += 1 if any(x in u for x in ["about", "leadership", "team", "company", "history", "news", "project"]) else 0
        # Include a bounded number of home/service pages even without obvious terms.
        if url_score or re.search(r"/(?:$|index\.|home|services?/?$|about/?$)", u):
            selected.append({"score": url_score, **cap})

# Deduplicate originals while preferring captures around 2014-2017 for litigation context.
def capture_rank(cap):
    ts = cap.get("timestamp", "")
    year = int(ts[:4]) if len(ts) >= 4 and ts[:4].isdigit() else 0
    context_bonus = 5 if 2014 <= year <= 2017 else 0
    return (cap.get("score", 0) + context_bonus, ts)

best_by_url = {}
for cap in selected:
    key = cap.get("original")
    if not key:
        continue
    if key not in best_by_url or capture_rank(cap) > capture_rank(best_by_url[key]):
        best_by_url[key] = cap
selected = sorted(best_by_url.values(), key=lambda c: (-capture_rank(c)[0], c.get("original", "")))[:450]

replays = []
for idx, cap in enumerate(selected, 1):
    ts = cap.get("timestamp")
    original = cap.get("original")
    if not ts or not original:
        continue
    r, saved = fetch(
        f"replay_{idx}_{ts}_{safe(original, 90)}",
        f"https://web.archive.org/web/{ts}id_/{original}",
        timeout=100,
        save_dir=FOUND,
    )
    if not r or r.status_code != 200:
        continue
    text = text_of(r.content, r.headers.get("content-type", ""), 600000)
    term_hits = hits("wayback", original, text)
    # Also retain likely relevant service/technical pages even if terms are in images.
    if term_hits or cap.get("score", 0) >= 3 or r.content.startswith(b"%PDF"):
        links = []
        if "html" in (r.headers.get("content-type") or "").lower() or r.content.lstrip().startswith(b"<"):
            soup = BeautifulSoup(r.content, "lxml")
            links = [{"text": " ".join(a.get_text(" ", strip=True).split()), "href": urljoin(original, a.get("href"))} for a in soup.find_all("a", href=True)][:1000]
        replays.append({
            "capture": cap, "saved": str(saved), "hits": term_hits,
            "text_sample": text[:150000], "links": links,
        })
        discoveries.extend(term_hits)

# Current DOG pages, useful for comparing publicly described services.
CURRENT = {
    "dog_home": "https://www.deltaoaksgroup.com/",
    "dog_about": "https://www.deltaoaksgroup.com/about-us/",
    "dog_leadership": "https://www.deltaoaksgroup.com/leadership/",
    "dog_cory": "https://www.deltaoaksgroup.com/leadership/cory-bauer/",
    "dog_joe": "https://www.deltaoaksgroup.com/leadership/joe-borrelli/",
    "dog_field": "https://www.deltaoaksgroup.com/field-services/",
    "dog_geotech": "https://www.deltaoaksgroup.com/geotechnical/",
    "dog_structural": "https://www.deltaoaksgroup.com/structural-services/",
    "dog_name": "https://www.deltaoaksgroup.com/whats-in-a-name/",
}
current_pages = []
for label, url in CURRENT.items():
    r, saved = fetch(label, url, timeout=75, save_dir=FOUND)
    if not r:
        continue
    text = text_of(r.content, r.headers.get("content-type", ""), 300000)
    term_hits = hits("current_site", url, text)
    current_pages.append({"label": label, "url": r.url, "saved": str(saved), "hits": term_hits, "text": text})
    discoveries.extend(term_hits)

(OUT / "all_captures.json").write_text(json.dumps(all_captures, indent=2), encoding="utf-8")
(OUT / "selected_captures.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
(OUT / "replayed_pages.json").write_text(json.dumps(replays, indent=2), encoding="utf-8")
(OUT / "current_delta_oaks_pages.json").write_text(json.dumps(current_pages, indent=2), encoding="utf-8")
(OUT / "discoveries.json").write_text(json.dumps(discoveries, indent=2), encoding="utf-8")
(OUT / "fetch_records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
summary = {
    "domains": len(DOMAINS),
    "captures": len(all_captures),
    "selected_urls": len(selected),
    "successful_relevant_replays": len(replays),
    "keyword_occurrences": len(discoveries),
    "current_pages": len(current_pages),
    "note": "Archived/current marketing descriptions establish public service offerings, not ownership or copying of technology.",
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
