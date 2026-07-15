#!/usr/bin/env python3
"""Retrieve and analyze specific archived FDH Velocitel technical materials."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path("fdh-technical-trace-output")
RAW = OUT / "raw"
PDF = OUT / "pdf"
TEXT = OUT / "text"
for directory in (OUT, RAW, PDF, TEXT):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 OpenAI-public-records-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

TARGETS = {
    "nde_unknown_foundations_pdf": "https://web.archive.org/web/20170127090518id_/http://www.fdhvelocitel.com/wp-content/uploads/2016/08/NDE_Unknown-Foundations_2016.pdf",
    "anchor_rod_inspections_pdf": "https://web.archive.org/web/20170126235944id_/http://www.fdhvelocitel.com/wp-content/uploads/2016/08/Anchor-Rod-Inspections_2016.pdf",
    "mobile_software_article": "https://web.archive.org/web/20160110224755id_/http://www.fdhvelocitel.com/new-mobile-software-improves-climber-safety/",
    "tools_page": "https://web.archive.org/web/20150313122627id_/http://www.fdhvelocitel.com/resources/tools/",
    "white_papers_page": "https://web.archive.org/web/20150313122538id_/http://www.fdhvelocitel.com/resources/white-papers/",
    "engineering_inspections": "https://web.archive.org/web/20150817222033id_/http://www.fdhvelocitel.com/services/engineering/engineering-inspections/",
    "geotechnical_engineering": "https://web.archive.org/web/20150817222038id_/http://www.fdhvelocitel.com/services/engineering/geotechnical-engineering/",
    "structural_engineering": "https://web.archive.org/web/20150817222043id_/http://www.fdhvelocitel.com/services/engineering/structural-engineering/",
    "services_page": "https://web.archive.org/web/20150313122631id_/http://www.fdhvelocitel.com/services/",
}

KEYWORDS = [
    "unknown foundation", "non-destructive", "nondestructive", "nde",
    "parallel seismic", "ultraseismic", "sonic echo", "impulse response",
    "foundation depth", "foundation geometry", "foundation type",
    "magnetometer", "seismic", "radar", "gpr", "ground penetrating",
    "software", "mobile", "application", "algorithm", "database", "mapping",
    "cory bauer", "joseph borrelli", "delta oaks", "fdh velocitel",
]

manifest = []
findings = []


def fetch(label: str, url: str) -> requests.Response | None:
    try:
        response = SESSION.get(url, timeout=45, allow_redirects=True)
        content_type = (response.headers.get("content-type") or "").lower()
        suffix = ".pdf" if "pdf" in content_type or response.content.startswith(b"%PDF") else ".html" if "html" in content_type else ".bin"
        destination = (PDF if suffix == ".pdf" else RAW) / f"{label}{suffix}"
        destination.write_bytes(response.content)
        manifest.append({
            "label": label,
            "requested_url": url,
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type"),
            "bytes": len(response.content),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "path": str(destination),
        })
        print("FETCH", label, response.status_code, len(response.content), response.url, flush=True)
        return response
    except Exception as exc:
        manifest.append({"label": label, "requested_url": url, "error": repr(exc)})
        print("ERROR", label, repr(exc), flush=True)
        return None


def extract_pdf(label: str, path: Path) -> str:
    pages = []
    try:
        reader = PdfReader(str(path), strict=False)
        for number, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception as exc:
                page_text = f"[Extraction error on page {number}: {exc!r}]"
            pages.append(f"\n\n===== PAGE {number} =====\n{page_text}")
    except Exception as exc:
        pages.append(f"[PDF reader error: {exc!r}]")
    text = "".join(pages)
    (TEXT / f"{label}.txt").write_text(text, encoding="utf-8", errors="replace")
    return text


def extract_html(label: str, response: requests.Response) -> tuple[str, list[dict[str, str]]]:
    soup = BeautifulSoup(response.text, "lxml")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    links = []
    for anchor in soup.find_all("a", href=True):
        links.append({
            "text": " ".join(anchor.get_text(" ", strip=True).split()),
            "href": urljoin(response.url, anchor.get("href")),
        })
    (TEXT / f"{label}.txt").write_text(text, encoding="utf-8", errors="replace")
    return text, links


def keyword_findings(label: str, url: str, text: str) -> None:
    lower = text.lower()
    for keyword in KEYWORDS:
        start = 0
        count = 0
        while True:
            index = lower.find(keyword.lower(), start)
            if index < 0:
                break
            count += 1
            if count <= 20:
                findings.append({
                    "source": label,
                    "url": url,
                    "keyword": keyword,
                    "offset": index,
                    "snippet": re.sub(r"\s+", " ", text[max(0, index - 450):min(len(text), index + len(keyword) + 850)]).strip(),
                })
            start = index + max(1, len(keyword))


all_links = []
for label, url in TARGETS.items():
    response = fetch(label, url)
    if not response or response.status_code != 200:
        continue
    saved_path = Path(manifest[-1]["path"])
    if saved_path.suffix.lower() == ".pdf":
        text = extract_pdf(label, saved_path)
        links = []
    else:
        text, links = extract_html(label, response)
    keyword_findings(label, response.url, text)
    all_links.extend({"source": label, **link} for link in links)

# Follow technical PDFs linked by the archived tools/white-paper/service pages.
seen_urls = set(TARGETS.values())
for item in all_links:
    href = item["href"]
    combined = (item["text"] + " " + href).lower()
    if href in seen_urls:
        continue
    if not href.startswith("http"):
        continue
    if not (href.lower().endswith(".pdf") or any(term in combined for term in ["foundation", "seismic", "inspection", "mapping", "tool", "white paper", "software"])):
        continue
    seen_urls.add(href)
    label = "linked_" + str(len(seen_urls))
    response = fetch(label, href)
    if not response or response.status_code != 200:
        continue
    saved_path = Path(manifest[-1]["path"])
    if saved_path.suffix.lower() == ".pdf":
        text = extract_pdf(label, saved_path)
    else:
        text, _ = extract_html(label, response)
    keyword_findings(label, response.url, text)
    if len(seen_urls) >= 25:
        break

(OUT / "fetch_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
(OUT / "all_links.json").write_text(json.dumps(all_links, indent=2), encoding="utf-8")
(OUT / "keyword_findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")

print("\n=== TARGETED TECHNICAL FINDINGS ===", flush=True)
print(json.dumps(findings[:200], indent=2, ensure_ascii=False), flush=True)
print("\n=== FETCH SUMMARY ===", flush=True)
print(json.dumps(manifest, indent=2), flush=True)

summary = [
    "# Targeted FDH technical trace",
    "",
    f"Targets attempted: {len(TARGETS)}",
    f"Files/pages successfully fetched: {sum(1 for item in manifest if item.get('status') == 200)}",
    f"Keyword/context findings: {len(findings)}",
    "",
    "Primary target: NDE_Unknown-Foundations_2016.pdf.",
    "See text/, pdf/, keyword_findings.json, and fetch_manifest.json.",
]
(OUT / "README.md").write_text("\n".join(summary), encoding="utf-8")
print("\n".join(summary), flush=True)
