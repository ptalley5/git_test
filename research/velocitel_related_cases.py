#!/usr/bin/env python3
"""Collect public records for Velocitel companion/related litigation.

Focuses on Velocitel, Inc. v. Hardy, No. 5:15-cv-00624 (E.D.N.C.),
then discovers other Velocitel/FDH cases through public CourtListener, Justia,
PlainSite, Internet Archive, and search pages. No authenticated or paywall-
bypassing access is attempted.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path("research-output/related-cases")
RAW = OUT / "raw"
PDF = OUT / "pdf"
TEXT = OUT / "text"
for p in (OUT, RAW, PDF, TEXT):
    p.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 public-record-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

CASES = {
    "hardy": {
        "name": "Velocitel, Inc. v. Hardy",
        "courtlistener_id": "5688345",
        "slug": "velocitel-inc-v-hardy",
        "pacer_case_id": "147131",
        "ia": "gov.uscourts.nced.147131",
        "justia_case": "5%3A2015cv00624/147131",
    },
    "bauer": {
        "name": "Velocitel, Inc. d/b/a FDH Velocitel v. Bauer",
        "courtlistener_id": "5670822",
        "slug": "velocitel-inc-dba-fdh-velocitel-v-bauer",
        "pacer_case_id": "147135",
        "ia": "gov.uscourts.nced.147135",
        "justia_case": "5%3A2015cv00628/147135",
    },
}

TERMS = [
    "complaint", "amended complaint", "injunction", "expedited discovery",
    "protective order", "confidential", "proprietary", "trade secret",
    "misappropriation", "computer", "hard drive", "storage", "electronic",
    "software", "source code", "foundation", "mapping", "inspection",
    "nondestructive", "non-destructive", "sonic", "seismic", "forensic",
    "flash drive", "thumb drive", "usb", "spoliation", "sanction", "compel",
    "settlement", "stipulation", "dismissal", "Corbin Hardy", "Wave Inspection",
    "Shane Boone", "Cory Bauer", "Joseph Borrelli", "Delta Oaks",
]

records: list[dict] = []
found_pdfs: list[dict] = []


def safe(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", v).strip("_")[:180] or "item"


def clean_text(data: bytes, ctype: str = "", limit: int = 250000) -> str:
    try:
        if "html" in ctype.lower() or data.lstrip().startswith(b"<"):
            return re.sub(r"\s+", " ", BeautifulSoup(data, "lxml").get_text(" ", strip=True))[:limit]
        return data.decode("utf-8", "replace")[:limit]
    except Exception:
        return ""


def fetch(label: str, url: str, timeout: int = 60, save: bool = True):
    try:
        r = S.get(url, timeout=timeout, allow_redirects=True)
        data = r.content
        ct = r.headers.get("content-type", "")
        ext = ".pdf" if data.startswith(b"%PDF") or "pdf" in ct.lower() else \
              ".json" if "json" in ct.lower() else \
              ".xml" if "xml" in ct.lower() or "rss" in ct.lower() or "atom" in ct.lower() else \
              ".html" if "html" in ct.lower() or data.lstrip().startswith(b"<") else ".bin"
        fp = None
        if save:
            fp = RAW / f"{safe(label)}{ext}"
            fp.write_bytes(data)
        rec = {
            "label": label, "url": url, "request_url": r.request.url,
            "status": r.status_code, "final_url": r.url, "content_type": ct,
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest() if data else None,
            "saved": str(fp) if fp else None, "text_sample": clean_text(data, ct, 30000),
        }
        records.append(rec)
        print(label, r.status_code, len(data), r.url, flush=True)
        if r.status_code == 200 and data.startswith(b"%PDF"):
            dst = PDF / f"{safe(label)}.pdf"
            dst.write_bytes(data)
            found_pdfs.append({**rec, "pdf_path": str(dst)})
        return r
    except Exception as exc:
        records.append({"label": label, "url": url, "error": repr(exc)})
        print(label, "ERROR", repr(exc), flush=True)
        return None


def t(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def parse_docket(case_key: str, case: dict) -> list[dict]:
    base = f"https://www.courtlistener.com/docket/{case['courtlistener_id']}/{case['slug']}/"
    r = fetch(f"{case_key}_courtlistener_docket_asc", base + "?order_by=asc", 90)
    if not r or r.status_code != 200 or not r.content:
        r = fetch(f"{case_key}_courtlistener_docket", base, 90)
    entries: list[dict] = []
    if not r or r.status_code != 200:
        return entries
    soup = BeautifulSoup(r.text, "lxml")
    table = soup.select_one("#docket-entry-table")
    rows = table.select(":scope > div.row") if table else soup.select("div.row[id^='entry-'],div.row[id^='minute-entry-']")
    for row in rows:
        rid = row.get("id") or ""
        if not (rid.startswith("entry-") or rid.startswith("minute-entry-")):
            continue
        cols = row.find_all("div", recursive=False)
        number = t(cols[0]) if len(cols) > 0 else ""
        date = t(cols[1]) if len(cols) > 1 else ""
        body = cols[2] if len(cols) > 2 else row
        description = ""
        for p in body.find_all("p"):
            if not p.find_parent(class_="recap-documents") and t(p):
                description = t(p)
                break
        links = []
        for a in row.find_all("a", href=True):
            href = urljoin(r.url, a.get("href"))
            links.append({"text": t(a), "href": href})
        docs = []
        for d in body.select(".recap-documents"):
            docs.append({
                "text": t(d),
                "links": [{"text": t(a), "href": urljoin(r.url, a.get("href"))} for a in d.find_all("a", href=True)],
                "forms": [{k: (" ".join(v) if isinstance(v, list) else v) for k, v in f.attrs.items()} for f in d.find_all("form")],
            })
        row_text = t(row)
        hits = [term for term in TERMS if term.lower() in row_text.lower()]
        pacer_ids = []
        for link in links:
            m = re.search(r"/doc1/(\d+)", link["href"])
            if m:
                pacer_ids.append(m.group(1))
        entries.append({
            "row_id": rid, "entry_number": number, "date": date,
            "description": description, "row_text": row_text,
            "links": links, "documents": docs, "term_hits": hits,
            "pacer_document_ids": sorted(set(pacer_ids)),
        })
    (OUT / f"{case_key}_docket_entries.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    (OUT / f"{case_key}_docket.tsv").write_text("\n".join(f"{e['entry_number']}\t{e['date']}\t{e['row_text']}" for e in entries), encoding="utf-8")
    return entries


def fetch_public_documents(case_key: str, case: dict, entries: list[dict]) -> None:
    # Public docket mirrors and IA item metadata.
    justia = f"https://dockets.justia.com/docket/north-carolina/ncedce/{case['justia_case']}"
    jr = fetch(f"{case_key}_justia_docket", justia, 75)
    if jr and jr.status_code == 200:
        soup = BeautifulSoup(jr.text, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(jr.url, a.get("href"))
            label = t(a)
            if any(x in href for x in ["docs.justia.com/cases/", "law.justia.com/cases/", "cases.justia.com/"]):
                links.append({"text": label, "href": href})
        (OUT / f"{case_key}_justia_document_links.json").write_text(json.dumps(links, indent=2), encoding="utf-8")
        for i, link in enumerate(links[:80], 1):
            rr = fetch(f"{case_key}_justia_doc_{i}", link["href"], 60)
            if rr and rr.status_code == 200:
                ss = BeautifulSoup(rr.text, "lxml")
                for j, a in enumerate(ss.find_all("a", href=True), 1):
                    href = urljoin(rr.url, a.get("href"))
                    if "cases.justia.com" in href and (href.lower().endswith(".pdf") or "pdf" in t(a).lower()):
                        fetch(f"{case_key}_justia_pdf_{i}_{j}", href, 90)
    meta = fetch(f"{case_key}_ia_metadata", f"https://archive.org/metadata/{case['ia']}", 75)
    files = []
    if meta:
        try:
            files = meta.json().get("files") or []
        except Exception:
            pass
    (OUT / f"{case_key}_ia_files.json").write_text(json.dumps(files, indent=2), encoding="utf-8")
    for i, f in enumerate(files, 1):
        name = f.get("name") or ""
        if name.lower().endswith((".pdf", ".json", ".xml", ".txt", ".html")):
            fetch(f"{case_key}_ia_file_{i}_{name}", f"https://archive.org/download/{case['ia']}/{name}", 90)

    # Probe missing but predictable public-document locations for all numbered entries.
    for e in entries:
        n = (e.get("entry_number") or "").strip()
        if not n.isdigit():
            continue
        if e.get("term_hits") or n in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}:
            fetch(f"{case_key}_cl_page_{n}", f"https://www.courtlistener.com/docket/{case['courtlistener_id']}/{n}/{case['slug']}/", 45)
            fetch(f"{case_key}_cl_storage_{n}", f"https://storage.courtlistener.com/recap/{case['ia']}/{case['ia']}.{n}.0.pdf", 45)
            fetch(f"{case_key}_ia_guess_{n}", f"https://archive.org/download/{case['ia']}/{case['ia']}.{n}.0.pdf", 45)
            time.sleep(0.08)


def discover_other_cases() -> None:
    queries = [
        "Velocitel", '"FDH Velocitel"', '"Velocitel, Inc."', '"FDH Engineering"',
        '"Cory Bauer"', '"Corbin Hardy"', '"Wave Inspection Technologies"',
    ]
    cases = []
    seen = set()
    for qi, q in enumerate(queries, 1):
        for page in range(1, 5):
            url = "https://www.courtlistener.com/?type=r&q=" + quote_plus(q) + f"&page={page}"
            r = fetch(f"courtlistener_search_{qi}_{page}", url, 75)
            if not r or r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = urljoin(r.url, a.get("href"))
                m = re.search(r"courtlistener\.com/docket/(\d+)/([^/?#]+)/?", href)
                if not m:
                    continue
                key = m.group(1)
                if key in seen:
                    continue
                seen.add(key)
                cases.append({"source_query": q, "docket_id": key, "slug": m.group(2), "text": t(a), "url": href})
            time.sleep(0.1)
    (OUT / "discovered_velocitel_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")

    # Fetch likely relevant dockets, keeping the cap conservative.
    relevant = []
    for c in cases:
        combo = (c.get("text", "") + " " + c.get("slug", "")).lower()
        if any(term in combo for term in ["velocitel", "fdh", "hardy", "bauer", "wave-inspection"]):
            r = fetch(f"related_docket_{c['docket_id']}", c["url"] + ("&" if "?" in c["url"] else "?") + "order_by=asc", 75)
            if r and r.status_code == 200:
                txt = clean_text(r.content, r.headers.get("content-type", ""), 100000)
                relevant.append({**c, "status": r.status_code, "text_sample": txt})
    (OUT / "relevant_related_dockets.json").write_text(json.dumps(relevant, indent=2), encoding="utf-8")


def extract_pdf_texts() -> None:
    manifest = []
    hits = []
    for p in sorted(PDF.glob("*.pdf")):
        text_parts = []
        errors = []
        try:
            reader = PdfReader(str(p), strict=False)
            for idx, page in enumerate(reader.pages, 1):
                try:
                    text_parts.append(f"\n===== PAGE {idx} =====\n" + (page.extract_text() or ""))
                except Exception as exc:
                    errors.append(f"page {idx}: {exc!r}")
        except Exception as exc:
            errors.append(f"reader: {exc!r}")
        text = "".join(text_parts)
        tp = TEXT / (p.name + ".txt")
        tp.write_text(text, encoding="utf-8")
        matched = []
        lower = text.lower()
        for term in TERMS:
            pos = lower.find(term.lower())
            if pos >= 0:
                matched.append({"term": term, "snippet": re.sub(r"\s+", " ", text[max(0, pos-500):pos+1600])})
        if matched:
            hits.append({"pdf": str(p), "matches": matched})
        manifest.append({"pdf": str(p), "text": str(tp), "bytes": p.stat().st_size, "errors": errors})
    (OUT / "pdf_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT / "pdf_keyword_hits.json").write_text(json.dumps(hits, indent=2), encoding="utf-8")


def main() -> None:
    all_entries = {}
    for key, case in CASES.items():
        entries = parse_docket(key, case)
        all_entries[key] = entries
        fetch_public_documents(key, case, entries)
    discover_other_cases()
    extract_pdf_texts()
    (OUT / "fetch_records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    summary = {
        "cases": {k: len(v) for k, v in all_entries.items()},
        "fetch_attempts": len(records),
        "http_200": sum(1 for r in records if r.get("status") == 200),
        "downloaded_pdfs": len(found_pdfs),
        "note": "Public, unauthenticated sources only; docket allegations are not findings of liability.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
