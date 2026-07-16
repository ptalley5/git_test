#!/usr/bin/env python3
"""Download and extract public FDH/Velocitel patent PDFs from Google Patent Images.

Patent documents are public records. This script only uses URLs disclosed by the
public Google Patents search response.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import requests
from pypdf import PdfReader

OUT = Path("research-output/fdh-patent-pdfs")
PDF = OUT / "pdf"
TEXT = OUT / "text"
for p in (OUT, PDF, TEXT):
    p.mkdir(parents=True, exist_ok=True)

PATENTS = {
    "US7548192B1": {
        "title": "Method of mapping steel reinforcements in concrete foundations",
        "inventor": "J. Darrin Holt",
        "assignee": "FDH Engineering, Inc.",
        "url": "https://patentimages.storage.googleapis.com/c3/76/bc/d1a1ab3f68a115/US7548192.pdf",
    },
    "US8176800B2": {
        "title": "Method for determining tension in a rod",
        "inventor": "Mark Cesare",
        "assignee": "FDH Engineering, Inc.",
        "url": "https://patentimages.storage.googleapis.com/6d/79/fc/aca0950129aa8e/US8176800.pdf",
    },
    "US20110130975A1": {
        "title": "Method of determining tension in a rod",
        "inventor": "Mark Cesare",
        "assignee": "FDH Engineering, Inc.",
        "url": "https://patentimages.storage.googleapis.com/61/f7/9f/c5877f648e6ce1/US20110130975A1.pdf",
    },
    "US20170335581A1": {
        "title": "Rod de-tensioning device and methods of operating the same",
        "inventor": "Robert Lindyberg",
        "assignee": "Velocitel, Inc. d/b/a FDH Velocitel",
        "url": "https://patentimages.storage.googleapis.com/65/99/ba/2d4d6357aba03a/US20170335581A1.pdf",
    },
    "US20220146259A1": {
        "title": "Systems and methods for estimating concrete thickness",
        "inventor": "David Milligan",
        "assignee": "FDH Infrastructure Services, LLC",
        "url": "https://patentimages.storage.googleapis.com/10/87/8d/44d5623ddf4321/US20220146259A1.pdf",
    },
    "US20230160855A1": {
        "title": "Systems and methods for estimating concrete strength using surface wave speed",
        "inventor": "Tej N. Pantha",
        "assignee": "FDH Infrastructure Services, LLC",
        "url": "https://patentimages.storage.googleapis.com/5e/c8/e8/ade92d31125a06/US20230160855A1.pdf",
    },
    "US11573135B2": {
        "title": "Tension in post-tensioned rods",
        "inventor": "Joshua Scott",
        "assignee": "FDH Infrastructure Services, Inc.",
        "url": "https://patentimages.storage.googleapis.com/5a/ad/7d/32a7f254419adb/US11573135.pdf",
    },
    "US11319715B2": {
        "title": "Method of de-tensioning a rod",
        "inventor": "Robert Lindyberg",
        "assignee": "FDH Infrastructure Services, LLC",
        "url": "https://patentimages.storage.googleapis.com/e0/54/12/990003a130efbf/US11319715.pdf",
    },
}

KEYWORDS = [
    "foundation", "existing concrete foundation", "steel reinforcement", "mapping",
    "radar", "ground penetrating radar", "depth", "buried", "without excavation",
    "software", "computer", "processor", "memory", "algorithm", "data", "map",
    "nondestructive", "non-destructive", "sonic", "seismic", "vibration", "accelerometer",
    "telecommunication", "tower", "rod", "anchor", "post-tensioned",
]

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 public-patent-research/1.0"
})
manifest = []
hits = []

for pid, meta in PATENTS.items():
    rec = {"patent": pid, **meta}
    try:
        r = S.get(meta["url"], timeout=120, allow_redirects=True)
        rec.update({
            "status": r.status_code, "final_url": r.url,
            "content_type": r.headers.get("content-type"), "size": len(r.content),
            "sha256": hashlib.sha256(r.content).hexdigest() if r.content else None,
        })
        print(pid, r.status_code, len(r.content), r.url, flush=True)
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            manifest.append(rec)
            continue
        pdf_path = PDF / f"{pid}.pdf"
        pdf_path.write_bytes(r.content)
        text_parts = []
        errors = []
        reader = PdfReader(str(pdf_path), strict=False)
        for i, page in enumerate(reader.pages, 1):
            try:
                text_parts.append(f"\n===== PAGE {i} =====\n" + (page.extract_text() or ""))
            except Exception as exc:
                errors.append(f"page {i}: {exc!r}")
        text = "".join(text_parts)
        text_path = TEXT / f"{pid}.txt"
        text_path.write_text(text, encoding="utf-8")
        patent_hits = []
        lower = text.lower()
        for keyword in KEYWORDS:
            pos = 0
            count = 0
            while True:
                idx = lower.find(keyword.lower(), pos)
                if idx < 0:
                    break
                count += 1
                if count <= 12:
                    patent_hits.append({
                        "keyword": keyword,
                        "snippet": re.sub(r"\s+", " ", text[max(0, idx-700):idx+2400]),
                    })
                pos = idx + max(1, len(keyword))
        hits.append({"patent": pid, "title": meta["title"], "hits": patent_hits})
        rec.update({
            "pdf_path": str(pdf_path), "text_path": str(text_path),
            "pages": len(reader.pages), "extraction_errors": errors,
        })
    except Exception as exc:
        rec["error"] = repr(exc)
        print(pid, "ERROR", repr(exc), flush=True)
    manifest.append(rec)

(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
(OUT / "keyword_hits.json").write_text(json.dumps(hits, indent=2), encoding="utf-8")
summary = {
    "requested": len(PATENTS),
    "pdfs_downloaded": sum(1 for r in manifest if r.get("pdf_path")),
    "total_pages": sum(int(r.get("pages") or 0) for r in manifest),
    "note": "Patent ownership and subject matter do not establish that a patented method was at issue in litigation.",
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
