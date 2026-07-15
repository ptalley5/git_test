#!/usr/bin/env python3
"""Collect publicly accessible records for Velocitel v. Bauer, No. 5:15-cv-00628.

This script is intended for a one-off GitHub Actions research run. It queries
public mirrors and indexes, downloads accessible docket files, extracts text,
and writes a structured evidence bundle under research-output/.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path("research-output")
RAW = OUT / "raw"
PDF = OUT / "pdf"
TEXT = OUT / "text"
for p in (OUT, RAW, PDF, TEXT):
    p.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
            "OpenAI-public-records-research/1.0"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
)

CASE = {
    "name": "Velocitel, Inc. d/b/a FDH Velocitel v. Bauer et al",
    "court": "nced",
    "docket_number": "5:15-cv-00628",
    "pacer_case_id_candidate": "147135",
    "ia_identifier_candidate": "gov.uscourts.nced.147135",
}

KEYWORDS = [
    "flash drive",
    "thumb drive",
    "usb",
    "external drive",
    "foundation",
    "unknown foundation",
    "foundation investigation",
    "foundation mapping",
    "mapping",
    "software",
    "source code",
    "program",
    "proprietary",
    "confidential",
    "trade secret",
    "misappropriat",
    "computer forensic",
    "forensic",
    "spoliat",
    "downloaded",
    "copied",
    "deleted",
    "delta oaks",
    "cory bauer",
    "joseph borrelli",
]


@dataclass
class FetchRecord:
    label: str
    url: str
    status: int | None
    final_url: str | None
    content_type: str | None
    size: int
    sha256: str | None
    saved_path: str | None
    error: str | None = None


FETCHES: list[FetchRecord] = []


def slugify(value: str) -> str:
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value[:180].strip("_") or "item"


def fetch(label: str, url: str, *, save: bool = True, timeout: int = 45) -> requests.Response | None:
    try:
        r = SESSION.get(url, timeout=timeout, allow_redirects=True)
        data = r.content
        digest = hashlib.sha256(data).hexdigest() if data else None
        saved_path = None
        if save:
            ext = ".bin"
            ctype = (r.headers.get("content-type") or "").lower()
            if "json" in ctype:
                ext = ".json"
            elif "html" in ctype:
                ext = ".html"
            elif "xml" in ctype:
                ext = ".xml"
            elif "pdf" in ctype or data.startswith(b"%PDF"):
                ext = ".pdf"
            path = RAW / f"{slugify(label)}{ext}"
            path.write_bytes(data)
            saved_path = str(path)
        FETCHES.append(
            FetchRecord(
                label=label,
                url=url,
                status=r.status_code,
                final_url=r.url,
                content_type=r.headers.get("content-type"),
                size=len(data),
                sha256=digest,
                saved_path=saved_path,
            )
        )
        print(f"FETCH {label}: {r.status_code} {len(data)} {r.url}")
        return r
    except Exception as exc:
        FETCHES.append(
            FetchRecord(
                label=label,
                url=url,
                status=None,
                final_url=None,
                content_type=None,
                size=0,
                sha256=None,
                saved_path=None,
                error=repr(exc),
            )
        )
        print(f"ERROR {label}: {exc!r}", file=sys.stderr)
        return None


def json_or_none(r: requests.Response | None) -> Any:
    if r is None:
        return None
    try:
        return r.json()
    except Exception:
        return None


def extract_pdf(path: Path) -> tuple[str, list[str]]:
    errors: list[str] = []
    pages: list[str] = []
    try:
        reader = PdfReader(str(path), strict=False)
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                errors.append(f"page {i}: {exc!r}")
                text = ""
            pages.append(f"\n\n===== PAGE {i} =====\n{text}")
    except Exception as exc:
        errors.append(f"reader: {exc!r}")
    return "".join(pages), errors


def keyword_hits(text: str, source: str) -> list[dict[str, Any]]:
    lower = text.lower()
    hits: list[dict[str, Any]] = []
    for kw in KEYWORDS:
        start = 0
        count = 0
        while True:
            idx = lower.find(kw.lower(), start)
            if idx < 0:
                break
            count += 1
            if count <= 20:
                left = max(0, idx - 350)
                right = min(len(text), idx + len(kw) + 550)
                snippet = re.sub(r"\s+", " ", text[left:right]).strip()
                hits.append(
                    {
                        "source": source,
                        "keyword": kw,
                        "offset": idx,
                        "snippet": snippet,
                    }
                )
            start = idx + max(1, len(kw))
    return hits


def download_file(url: str, destination: Path, label: str) -> bool:
    r = fetch(label, url, save=False, timeout=90)
    if r is None or r.status_code != 200:
        return False
    if not r.content:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(r.content)
    return True


def parse_html_links(html: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href"))
        text = " ".join(a.get_text(" ", strip=True).split())
        out.append({"text": text, "href": href})
    return out


def search_engine_queries() -> None:
    queries = [
        '"Velocitel" "Cory Bauer"',
        '"FDH Velocitel" "Delta Oaks"',
        '"5:15-cv-00628"',
        '"5:15-CV-628-BO"',
        '"Velocitel v. Bauer"',
        '"Cory Bauer" "flash drive"',
        '"Delta Oaks" "flash drive"',
        '"Cory Bauer" foundation software',
        '"unknown foundation" telecom tower FDH',
        '"unknown foundation investigation" tower',
        'site:law360.com Velocitel Bauer',
        'site:pacermonitor.com Velocitel Bauer',
        'site:plainsite.org Velocitel Bauer',
        'site:law360.com "Delta Oaks Group"',
    ]
    results: list[dict[str, Any]] = []
    for i, q in enumerate(queries, start=1):
        encoded = quote_plus(q)
        for engine, url in [
            ("bing", f"https://www.bing.com/search?q={encoded}&count=50"),
            ("ddg", f"https://html.duckduckgo.com/html/?q={encoded}"),
        ]:
            r = fetch(f"search_{i}_{engine}", url)
            if r is None:
                continue
            links = parse_html_links(r.text, r.url)
            filtered = []
            for item in links:
                href = item["href"]
                text = item["text"]
                if any(d in href for d in ["courtlistener", "justia", "pacermonitor", "archive.org", "law360", "plainsite", "nced.uscourts", "googleusercontent", "casetext", "leagle", "law.justia"]):
                    filtered.append(item)
            results.append(
                {
                    "query": q,
                    "engine": engine,
                    "status": r.status_code,
                    "final_url": r.url,
                    "matches": filtered[:100],
                }
            )
            time.sleep(0.7)
    (OUT / "search_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def courtlistener_queries() -> None:
    endpoints = {
        "cl_api_search_velocitel": "https://www.courtlistener.com/api/rest/v3/search/?type=r&q=Velocitel",
        "cl_api_search_case": "https://www.courtlistener.com/api/rest/v3/search/?type=r&q=5%3A15-cv-00628",
        "cl_api_docket_num": "https://www.courtlistener.com/api/rest/v3/dockets/?court=nced&docket_number=5%3A15-cv-00628",
        "cl_api_docket_raw": "https://www.courtlistener.com/api/rest/v3/dockets/?court=nced&docket_number=5%3A2015cv00628",
        "cl_api_pacer_id": "https://www.courtlistener.com/api/rest/v3/dockets/?court=nced&pacer_case_id=147135",
        "cl_web_search_velocitel": "https://www.courtlistener.com/?type=r&q=Velocitel",
        "cl_web_search_case": "https://www.courtlistener.com/?type=r&q=5%3A15-cv-00628",
        "cl_recap_search_velocitel": "https://www.courtlistener.com/recap/?q=Velocitel",
        "cl_feed_velocitel": "https://www.courtlistener.com/feed/search/?type=r&q=Velocitel",
        "cl_feed_case": "https://www.courtlistener.com/feed/search/?type=r&q=5%3A15-cv-00628",
    }
    collected: dict[str, Any] = {}
    for label, url in endpoints.items():
        r = fetch(label, url)
        if r is None:
            continue
        data = json_or_none(r)
        if data is not None:
            collected[label] = data
        else:
            collected[label] = {
                "status": r.status_code,
                "final_url": r.url,
                "text_sample": re.sub(r"\s+", " ", BeautifulSoup(r.text, "lxml").get_text(" ", strip=True))[:5000],
                "links": parse_html_links(r.text, r.url)[:500],
            }
    (OUT / "courtlistener_results.json").write_text(json.dumps(collected, indent=2), encoding="utf-8")


def internet_archive_queries() -> list[dict[str, Any]]:
    identifier = CASE["ia_identifier_candidate"]
    endpoints = {
        "ia_metadata_candidate": f"https://archive.org/metadata/{identifier}",
        "ia_details_candidate": f"https://archive.org/details/{identifier}",
        "ia_advanced_identifier": "https://archive.org/advancedsearch.php?q=" + quote_plus(f'identifier:"{identifier}"') + "&fl[]=identifier,title,description&rows=50&page=1&output=json",
        "ia_advanced_case": "https://archive.org/advancedsearch.php?q=" + quote_plus('title:(Velocitel Bauer) OR description:(Velocitel Bauer)') + "&fl[]=identifier,title,description&rows=100&page=1&output=json",
        "ia_advanced_pacer": "https://archive.org/advancedsearch.php?q=" + quote_plus('identifier:(gov.uscourts.nced.147135*)') + "&fl[]=identifier,title,description&rows=100&page=1&output=json",
    }
    data_out: dict[str, Any] = {}
    candidate_files: list[dict[str, Any]] = []
    for label, url in endpoints.items():
        r = fetch(label, url)
        data = json_or_none(r)
        data_out[label] = data if data is not None else {"status": r.status_code if r else None}
        if label == "ia_metadata_candidate" and isinstance(data, dict):
            candidate_files = data.get("files") or []
    (OUT / "internet_archive_results.json").write_text(json.dumps(data_out, indent=2), encoding="utf-8")
    return candidate_files


def download_ia_files(files: list[dict[str, Any]]) -> None:
    identifier = CASE["ia_identifier_candidate"]
    manifest: list[dict[str, Any]] = []
    total = 0
    limit = 350 * 1024 * 1024
    interesting_ext = (".pdf", ".xml", ".json", ".html", ".txt", ".csv")
    for f in files:
        name = f.get("name")
        if not name or not name.lower().endswith(interesting_ext):
            continue
        try:
            size = int(f.get("size") or 0)
        except Exception:
            size = 0
        if total + size > limit:
            manifest.append({"name": name, "skipped": "size cap", "size": size})
            continue
        url = f"https://archive.org/download/{identifier}/{quote_plus(name, safe='/')}"
        dest_dir = PDF if name.lower().endswith(".pdf") else RAW
        dest = dest_dir / Path(name).name
        ok = download_file(url, dest, f"ia_file_{Path(name).name}")
        manifest.append({"name": name, "url": url, "size_reported": size, "downloaded": ok, "path": str(dest) if ok else None})
        if ok:
            total += dest.stat().st_size
    (OUT / "ia_download_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def justia_queries() -> None:
    docket = "https://dockets.justia.com/docket/north-carolina/ncedce/5%3A2015cv00628/147135"
    r = fetch("justia_docket", docket)
    links: list[dict[str, str]] = []
    if r is not None:
        links = parse_html_links(r.text, r.url)
        (OUT / "justia_links.json").write_text(json.dumps(links, indent=2), encoding="utf-8")
    # Known mirrored orders plus deterministic probes of docket-entry pages.
    for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100]:
        url = f"https://docs.justia.com/cases/federal/district-courts/north-carolina/ncedce/5%3A2015cv00628/147135/{n}"
        rr = fetch(f"justia_entry_{n}", url)
        if rr is None or rr.status_code != 200:
            continue
        visible = BeautifulSoup(rr.text, "lxml").get_text(" ", strip=True)
        if "Filing" not in visible or "Velocitel" not in visible:
            continue
        for link in parse_html_links(rr.text, rr.url):
            if link["href"].lower().endswith(".pdf") or "cases.justia.com" in link["href"]:
                name = f"justia_entry_{n}.pdf"
                download_file(link["href"], PDF / name, f"justia_pdf_{n}")
                break
        time.sleep(0.15)


def pacermonitor_queries() -> None:
    urls = {
        "pm_search_case": "https://www.pacermonitor.com/search/cases?q=" + quote_plus("5:15-cv-00628"),
        "pm_search_name": "https://www.pacermonitor.com/search/cases?q=" + quote_plus("Velocitel Bauer"),
        "pm_search_delta": "https://www.pacermonitor.com/search/cases?q=" + quote_plus("Delta Oaks Group"),
    }
    out: dict[str, Any] = {}
    for label, url in urls.items():
        r = fetch(label, url)
        if r is None:
            continue
        out[label] = {
            "status": r.status_code,
            "final_url": r.url,
            "text": re.sub(r"\s+", " ", BeautifulSoup(r.text, "lxml").get_text(" ", strip=True))[:20000],
            "links": parse_html_links(r.text, r.url)[:1000],
        }
    (OUT / "pacermonitor_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


def other_public_sources() -> None:
    urls = {
        "plainsite_search": "https://www.plainsite.org/search/?q=" + quote_plus("Velocitel Bauer"),
        "law360_search": "https://www.law360.com/search?q=" + quote_plus("Velocitel Bauer"),
        "google_patents_bauer_fdh": "https://patents.google.com/xhr/query?url=q%3D%2522Cory%2BBauer%2522%2BFDH&exp=",
        "nced_rss": "https://ecf.nced.uscourts.gov/cgi-bin/rss_outside.pl",
    }
    out: dict[str, Any] = {}
    for label, url in urls.items():
        r = fetch(label, url)
        if r is None:
            continue
        out[label] = {
            "status": r.status_code,
            "final_url": r.url,
            "text": re.sub(r"\s+", " ", BeautifulSoup(r.text, "lxml").get_text(" ", strip=True))[:20000],
            "links": parse_html_links(r.text, r.url)[:1000],
        }
    (OUT / "other_sources.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


def process_downloads() -> None:
    all_hits: list[dict[str, Any]] = []
    pdf_manifest: list[dict[str, Any]] = []
    for path in sorted(PDF.glob("*.pdf")):
        text, errors = extract_pdf(path)
        text_path = TEXT / f"{path.name}.txt"
        text_path.write_text(text, encoding="utf-8", errors="replace")
        hits = keyword_hits(text, path.name)
        all_hits.extend(hits)
        pdf_manifest.append(
            {
                "pdf": str(path),
                "size": path.stat().st_size,
                "text_path": str(text_path),
                "text_chars": len(text),
                "errors": errors,
                "keyword_hit_count": len(hits),
            }
        )
    # Search non-PDF raw text too.
    for path in sorted(RAW.iterdir()):
        if path.suffix.lower() not in {".html", ".json", ".xml", ".txt", ".csv"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        all_hits.extend(keyword_hits(text, path.name))
    (OUT / "pdf_manifest.json").write_text(json.dumps(pdf_manifest, indent=2), encoding="utf-8")
    (OUT / "keyword_hits.json").write_text(json.dumps(all_hits, indent=2), encoding="utf-8")
    with (OUT / "keyword_hits.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["source", "keyword", "offset", "snippet"])
        writer.writeheader()
        writer.writerows(all_hits)


def write_summary() -> None:
    (OUT / "fetch_manifest.json").write_text(json.dumps([asdict(x) for x in FETCHES], indent=2), encoding="utf-8")
    successes = [x for x in FETCHES if x.status == 200]
    failures = [x for x in FETCHES if x.status != 200]
    summary = [
        "# Velocitel v. Bauer public-record collection run",
        "",
        f"Case: {CASE['name']}",
        f"Docket: {CASE['docket_number']} ({CASE['court']})",
        "",
        f"Fetch attempts: {len(FETCHES)}",
        f"HTTP 200 responses: {len(successes)}",
        f"Non-200/errors: {len(failures)}",
        f"Downloaded PDFs: {len(list(PDF.glob('*.pdf')))}",
        "",
        "See `fetch_manifest.json`, `internet_archive_results.json`, `courtlistener_results.json`, `search_results.json`, `pdf_manifest.json`, and `keyword_hits.json`.",
    ]
    (OUT / "README.md").write_text("\n".join(summary), encoding="utf-8")


def main() -> None:
    print(json.dumps(CASE, indent=2))
    files = internet_archive_queries()
    if files:
        download_ia_files(files)
    courtlistener_queries()
    justia_queries()
    pacermonitor_queries()
    other_public_sources()
    search_engine_queries()
    process_downloads()
    write_summary()
    print((OUT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
