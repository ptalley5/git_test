#!/usr/bin/env python3
"""Exhaust legitimate free/open-web routes for Velocitel v. Bauer records.

This intentionally avoids authentication circumvention and fee-avoiding access to
PACER. It checks public archives, caches, mirrors, search indexes, repositories,
and court/opinion sources, then records reproducible negative and positive results.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

try:
    from warcio.archiveiterator import ArchiveIterator
except Exception:
    ArchiveIterator = None

OUT = Path("research-output/exhaustive-free-options")
RAW = OUT / "raw"
FOUND = OUT / "found"
for p in (OUT, RAW, FOUND):
    p.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
                  "public-court-record-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})

CASE_TERMS = [
    '"5:15-cv-00628"', '"5:2015cv00628"', '"5:15-CV-628-BO"', '"5:15-CV-628-D"',
    '"Velocitel, Inc." "Cory Bauer"', '"FDH Velocitel" "Delta Oaks"',
    '"Velocitel v. Bauer"', '"Cory Bauer" "flash drive"', '"Cory Bauer" USB FDH',
    '"Delta Oaks Group" "flash drive"', '"unknown foundation" telecom tower FDH',
    '"foundation investigation" FDH Velocitel', '"foundation mapping" FDH telecom',
]
DOCS = {
    1:  {"name": "Complaint", "pacer": "13104645147", "plainsite_entry": "217779141"},
    7:  {"name": "Counterclaim and Answer", "pacer": "13104687977", "plainsite_entry": "218478332"},
    13: {"name": "Motion for Preliminary Injunction", "pacer": "13104696383", "plainsite_entry": "221947042"},
    14: {"name": "Memorandum Supporting Preliminary Injunction", "pacer": "13104696400", "plainsite_entry": "221947101"},
    15: {"name": "Motion to Expedite Discovery", "pacer": "13104696466", "plainsite_entry": "221947149"},
    16: {"name": "Memorandum Supporting Expedited Discovery", "pacer": "13104696485", "plainsite_entry": "221947165"},
    17: {"name": "Counterclaim and Answer", "pacer": "13104698737", "plainsite_entry": "226709329"},
    22: {"name": "Counterclaim and Answer", "pacer": "13104709952", "plainsite_entry": "231221596"},
    25: {"name": "Motion for Reconsideration", "pacer": "13104713008", "plainsite_entry": "231289340"},
    26: {"name": "Memorandum Supporting Reconsideration", "pacer": "13104713031", "plainsite_entry": "231289344"},
    27: {"name": "Opposition to Reconsideration", "pacer": "13104714690", "plainsite_entry": "231331874"},
    30: {"name": "Opposition to Preliminary Injunction", "pacer": "13104721692", "plainsite_entry": "231462245"},
    57: {"name": "Motion for Sanctions", "pacer": "13105515113", "plainsite_entry": "245863830"},
    58: {"name": "Memorandum Supporting Sanctions", "pacer": "13105515142", "plainsite_entry": "245863837"},
    59: {"name": "Proposed Sealed Response", "pacer": "13105533867", "plainsite_entry": "246143328"},
    63: {"name": "Motion to Compel", "pacer": "13105558489", "plainsite_entry": None},
    64: {"name": "Memorandum Supporting Motion to Compel", "pacer": "13105558508", "plainsite_entry": None},
    66: {"name": "Second Motion to Compel", "pacer": "13105558553", "plainsite_entry": None},
    67: {"name": "Memorandum Supporting Second Motion to Compel", "pacer": "13105558557", "plainsite_entry": None},
    70: {"name": "Motion to Stay", "pacer": "13105558604", "plainsite_entry": None},
    71: {"name": "Memorandum Supporting Stay", "pacer": "13105558614", "plainsite_entry": None},
    72: {"name": "Opposition", "pacer": "13105559282", "plainsite_entry": None},
    73: {"name": "Reply", "pacer": "13105560840", "plainsite_entry": None},
    77: {"name": "Opposition", "pacer": "13105567016", "plainsite_entry": None},
    78: {"name": "Proposed Sealed Response", "pacer": "13105569002", "plainsite_entry": None},
    82: {"name": "Stipulation of Dismissal", "pacer": "13105581061", "plainsite_entry": None},
}
KEYWORDS = ["flash drive", "thumb drive", "usb drive", "external drive", "foundation mapping",
            "unknown foundation", "foundation investigation", "source code", "trade secret",
            "misappropriation", "forensic", "spoliation", "cory bauer", "delta oaks"]
records: list[dict[str, Any]] = []
found_files: list[dict[str, Any]] = []


def safe_name(value: str, limit: int = 190) -> str:
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return (value or "item")[:limit]


def text_sample(data: bytes, content_type: str = "", limit: int = 12000) -> str:
    try:
        if "html" in content_type.lower() or data.lstrip().startswith(b"<"):
            return re.sub(r"\s+", " ", BeautifulSoup(data, "lxml").get_text(" ", strip=True))[:limit]
        return data.decode("utf-8", "replace")[:limit]
    except Exception:
        return ""


def fetch(label: str, url: str, *, params: dict[str, Any] | None = None,
          headers: dict[str, str] | None = None, method: str = "GET", timeout: int = 50,
          save: bool = True) -> requests.Response | None:
    try:
        r = S.request(method, url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
        ctype = r.headers.get("content-type", "")
        data = r.content
        ext = ".pdf" if data.startswith(b"%PDF") or "pdf" in ctype.lower() else \
              ".json" if "json" in ctype.lower() else \
              ".xml" if "xml" in ctype.lower() else \
              ".html" if "html" in ctype.lower() or data.lstrip().startswith(b"<") else ".bin"
        saved = None
        if save:
            saved = RAW / f"{safe_name(label)}{ext}"
            saved.write_bytes(data)
        rec = {"label": label, "url": url, "request_url": r.request.url, "status": r.status_code,
               "final_url": r.url, "content_type": ctype, "size": len(data),
               "sha256": hashlib.sha256(data).hexdigest() if data else None,
               "saved": str(saved) if saved else None, "text_sample": text_sample(data, ctype)}
        records.append(rec)
        print(f"{label}: {r.status_code} {len(data)} {r.url}", flush=True)
        if r.status_code == 200 and data.startswith(b"%PDF"):
            dst = FOUND / f"{safe_name(label)}.pdf"
            dst.write_bytes(data)
            found_files.append({**rec, "found_path": str(dst)})
        return r
    except Exception as exc:
        records.append({"label": label, "url": url, "error": repr(exc)})
        print(f"{label}: ERROR {exc!r}", flush=True)
        return None


def parse_json_lines(r: requests.Response | None) -> list[dict[str, Any]]:
    if not r or r.status_code != 200:
        return []
    out = []
    for line in r.text.splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def discover_direct_public_routes() -> None:
    urls = {
        "courtlistener_docket": "https://www.courtlistener.com/docket/5670822/velocitel-inc-dba-fdh-velocitel-v-bauer/",
        "courtlistener_docket_asc": "https://www.courtlistener.com/docket/5670822/velocitel-inc-dba-fdh-velocitel-v-bauer/?order_by=asc",
        "courtlistener_feed": "https://www.courtlistener.com/feed/search/?type=r&q=5%3A15-cv-00628",
        "justia_docket": "https://dockets.justia.com/docket/north-carolina/ncedce/5%3A2015cv00628/147135",
        "plainsite_docket": "https://www.plainsite.org/courts/north-carolina-eastern-district-court/velocitel-inc-d-b-a-fdh-velocitel-v-bauer/2oq2ge1o9/",
        "pacermonitor_search": "https://www.pacermonitor.com/search/cases?q=Velocitel+Bauer",
        "docketbird_search": "https://www.docketbird.com/search?q=Velocitel+Bauer",
        "unicourt_search": "https://unicourt.com/case/pc-db5-velocitel-inc-dba-fdh-velocitel-v-bauer-et-al-137977",
        "trellis_search": "https://trellis.law/search?q=Velocitel%20Bauer",
        "law360_search": "https://www.law360.com/search?q=Velocitel%20Bauer",
        "govinfo_search": "https://www.govinfo.gov/app/search/%7B%22query%22%3A%225%3A15-cv-00628%22%7D",
        "google_scholar": "https://scholar.google.com/scholar?q=%225%3A15-cv-00628%22",
    }
    for label, url in urls.items():
        fetch(label, url)
    for de, meta in DOCS.items():
        candidates = {
            f"de{de}_courtlistener_page": f"https://www.courtlistener.com/docket/5670822/{de}/velocitel-inc-dba-fdh-velocitel-v-bauer/",
            f"de{de}_courtlistener_storage": f"https://storage.courtlistener.com/recap/gov.uscourts.nced.147135/gov.uscourts.nced.147135.{de}.0.pdf",
            f"de{de}_archive_pdf": f"https://archive.org/download/gov.uscourts.nced.147135/gov.uscourts.nced.147135.{de}.0.pdf",
            f"de{de}_pacer": f"https://ecf.nced.uscourts.gov/doc1/{meta['pacer']}?caseid=147135",
        }
        if meta.get("plainsite_entry"):
            candidates[f"de{de}_plainsite_request"] = f"https://www.plainsite.org/pro/index.html?docketid=8068743&entryid={meta['plainsite_entry']}"
        for label, url in candidates.items():
            fetch(label, url, timeout=35)


def search_public_web() -> None:
    domains = ["courtlistener.com", "archive.org", "justia.com", "plainsite.org", "pacermonitor.com",
               "docketbird.com", "unicourt.com", "trellis.law", "law360.com", "documentcloud.org",
               "scribd.com", "govinfo.gov", "casetext.com", "vlex.com", "leagle.com", "findlaw.com",
               "courthousenews.com", "jdsupra.com", "mondaq.com", "sec.gov", "googleusercontent.com",
               "drive.google.com", "dropbox.com", "github.com"]
    queries = list(CASE_TERMS) + [f'"{m["pacer"]}"' for m in DOCS.values()] + [
        '"gov.uscourts.nced.147135.1.0.pdf"', '"Velocitel" "Preliminary Injunction" Bauer',
        '"Velocitel" "Motion for Sanctions" Bauer', '"FDH Velocitel" trade secret Bauer']
    search_results = []
    for i, q in enumerate(queries, 1):
        engines = {
            "google_jina": "https://r.jina.ai/http://www.google.com/search?q=" + quote_plus(q),
            "bing_jina": "https://r.jina.ai/http://www.bing.com/search?q=" + quote_plus(q),
            "ddg_html": "https://html.duckduckgo.com/html/?q=" + quote_plus(q),
            "brave": "https://search.brave.com/search?q=" + quote_plus(q),
        }
        for engine, url in engines.items():
            r = fetch(f"search_{i}_{engine}", url, timeout=60)
            if not r:
                continue
            links = []
            try:
                soup = BeautifulSoup(r.text, "lxml")
                for a in soup.find_all("a", href=True):
                    href = urljoin(r.url, a.get("href")); txt = " ".join(a.get_text(" ", strip=True).split())
                    if any(d in href.lower() for d in domains) or any(k in (txt + " " + href).lower() for k in ["velocitel", "bauer", "00628", "147135"]):
                        links.append({"text": txt, "href": href})
            except Exception:
                pass
            search_results.append({"query": q, "engine": engine, "status": r.status_code, "links": links[:100]})
        time.sleep(0.25)
    (OUT / "search_results.json").write_text(json.dumps(search_results, indent=2), encoding="utf-8")


def query_wayback() -> None:
    targets = [
        "https://www.courtlistener.com/docket/5670822/*",
        "https://storage.courtlistener.com/recap/gov.uscourts.nced.147135/*",
        "https://archive.org/download/gov.uscourts.nced.147135/*",
        "https://www.plainsite.org/courts/north-carolina-eastern-district-court/velocitel-inc-d-b-a-fdh-velocitel-v-bauer/*",
        "https://ecf.nced.uscourts.gov/doc1/*",
    ]
    for de, meta in DOCS.items():
        targets += [
            f"https://storage.courtlistener.com/recap/gov.uscourts.nced.147135/gov.uscourts.nced.147135.{de}.0.pdf",
            f"https://archive.org/download/gov.uscourts.nced.147135/gov.uscourts.nced.147135.{de}.0.pdf",
            f"https://ecf.nced.uscourts.gov/doc1/{meta['pacer']}*",
        ]
    all_captures = []; replayed = set()
    for i, target in enumerate(targets, 1):
        r = fetch(f"wayback_cdx_{i}", "https://web.archive.org/cdx/search/cdx",
                  params={"url": target, "output": "json", "fl": "timestamp,original,statuscode,mimetype,digest,length",
                          "filter": "statuscode:200", "collapse": "digest", "limit": "100"}, timeout=70)
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
            cap = dict(zip(header, row)); cap["query_target"] = target; all_captures.append(cap)
            key = (cap.get("timestamp"), cap.get("original")); mime = (cap.get("mimetype") or "").lower()
            if key in replayed or len(replayed) >= 100:
                continue
            if "pdf" in mime or any(x in (cap.get("original") or "") for x in ["courtlistener", "plainsite", "doc1/"]):
                replayed.add(key)
                fetch(f"wayback_replay_{len(replayed)}", f"https://web.archive.org/web/{cap['timestamp']}id_/{cap['original']}", timeout=90)
    (OUT / "wayback_captures.json").write_text(json.dumps(all_captures, indent=2), encoding="utf-8")


def query_common_crawl() -> None:
    r = fetch("commoncrawl_collections", "https://index.commoncrawl.org/collinfo.json", timeout=60)
    if not r or r.status_code != 200:
        return
    try:
        collections = r.json()
    except Exception:
        return
    collections = [c for c in collections if re.search(r"CC-MAIN-(20(?:1[5-9]|2[0-6]))", c.get("id", ""))][:85]
    patterns = [
        ("cl_docket", "www.courtlistener.com/docket/5670822/", "prefix"),
        ("cl_storage", "storage.courtlistener.com/recap/gov.uscourts.nced.147135/", "prefix"),
        ("ia_item", "archive.org/download/gov.uscourts.nced.147135/", "prefix"),
        ("plainsite_case", "www.plainsite.org/courts/north-carolina-eastern-district-court/velocitel-inc-d-b-a-fdh-velocitel-v-bauer/", "prefix"),
        ("justia_case", "dockets.justia.com/docket/north-carolina/ncedce/5:2015cv00628/147135", "exact"),
    ]
    for de, meta in DOCS.items():
        patterns.append((f"pacer_de{de}", f"ecf.nced.uscourts.gov/doc1/{meta['pacer']}", "prefix"))
    cc_hits = []
    for cnum, collection in enumerate(collections, 1):
        endpoint = collection.get("cdx-api") or f"https://index.commoncrawl.org/{collection['id']}-index"
        for label, pattern, match_type in patterns:
            rr = fetch(f"cc_{collection['id']}_{label}", endpoint,
                       params={"url": pattern, "output": "json", "matchType": match_type, "filter": "status:200"},
                       timeout=45, save=False)
            for hit in parse_json_lines(rr):
                hit["collection"] = collection["id"]; hit["query_label"] = label; cc_hits.append(hit)
        print(f"Common Crawl collection {cnum}/{len(collections)} complete", flush=True)
    unique = {(h.get("filename"), h.get("offset"), h.get("length")): h for h in cc_hits}
    cc_hits = list(unique.values())
    (OUT / "commoncrawl_hits.json").write_text(json.dumps(cc_hits, indent=2), encoding="utf-8")
    payload_count = 0
    for hit in cc_hits:
        if payload_count >= 120:
            break
        mime = (hit.get("mime-detected") or hit.get("mime") or "").lower(); url = hit.get("url", "")
        if not ("pdf" in mime or any(token in url for token in ["courtlistener", "plainsite", "doc1/"])):
            continue
        try:
            offset = int(hit["offset"]); length = int(hit["length"])
            wr = S.get("https://data.commoncrawl.org/" + hit["filename"],
                       headers={"Range": f"bytes={offset}-{offset + length - 1}"}, timeout=90)
            data = wr.content; payload = b""; headers = {}
            if ArchiveIterator:
                for candidate in (data, gzip.decompress(data) if data[:2] == b"\x1f\x8b" else b""):
                    if not candidate:
                        continue
                    try:
                        for record in ArchiveIterator(io.BytesIO(candidate)):
                            if record.rec_type == "response":
                                payload = record.content_stream().read()
                                headers = dict(record.http_headers.headers) if record.http_headers else {}
                                break
                    except Exception:
                        pass
                    if payload:
                        break
            if not payload:
                continue
            ctype = headers.get("Content-Type") or headers.get("content-type") or mime
            ext = ".pdf" if payload.startswith(b"%PDF") or "pdf" in ctype.lower() else ".html" if "html" in ctype.lower() or payload.lstrip().startswith(b"<") else ".bin"
            dst = FOUND / f"commoncrawl_{payload_count + 1}_{safe_name(url, 120)}{ext}"; dst.write_bytes(payload)
            payload_count += 1
            found_files.append({"source": "commoncrawl", "url": url, "collection": hit.get("collection"),
                                "mime": ctype, "size": len(payload), "found_path": str(dst),
                                "text_sample": text_sample(payload, ctype)})
        except Exception as exc:
            records.append({"label": "commoncrawl_payload", "url": hit.get("url"), "error": repr(exc)})


def query_other_archives_and_repositories() -> None:
    target = "https://www.courtlistener.com/docket/5670822/velocitel-inc-dba-fdh-velocitel-v-bauer/"
    candidates = {
        "memento_timetravel": "https://timetravel.mementoweb.org/api/json/" + quote(target, safe=""),
        "arquivo_text_velocitel": "https://arquivo.pt/textsearch?maxItems=100&q=" + quote_plus('"Velocitel" "Cory Bauer"'),
        "arquivo_versions_cl": "https://arquivo.pt/textsearch?maxItems=100&versionHistory=" + quote_plus(target),
        "documentcloud_api_1": "https://api.www.documentcloud.org/api/documents/?q=Velocitel",
        "documentcloud_api_2": "https://api.documentcloud.org/api/documents/?q=Velocitel",
        "documentcloud_search": "https://www.documentcloud.org/search?q=Velocitel%20Bauer",
        "internet_archive_metadata": "https://archive.org/metadata/gov.uscourts.nced.147135",
        "internet_archive_advanced": "https://archive.org/advancedsearch.php?q=" + quote_plus('(Velocitel AND Bauer) OR "5:15-cv-00628" OR "13104645147"') + "&fl[]=identifier,title,description,mediatype&rows=200&page=1&output=json",
        "sec_fulltext": "https://efts.sec.gov/LATEST/search-index?q=" + quote_plus('"Velocitel" "Bauer"'),
        "crossref": "https://api.crossref.org/works?query.bibliographic=" + quote_plus('Velocitel Bauer Delta Oaks') + "&rows=100",
        "openalex": "https://api.openalex.org/works?search=" + quote_plus('Velocitel Bauer Delta Oaks') + "&per-page=100",
        "google_books": "https://www.googleapis.com/books/v1/volumes?q=" + quote_plus('"Velocitel" "Bauer"'),
        "github_code_search_web": "https://github.com/search?q=" + quote_plus('"5:15-cv-00628"') + "&type=code",
    }
    for label, url in candidates.items():
        fetch(label, url, timeout=75)
    for de in DOCS:
        filename = f"gov.uscourts.nced.147135.{de}.0.pdf"
        fetch(f"ia_exact_filename_de{de}", "https://archive.org/advancedsearch.php",
              params={"q": f'filename:"{filename}" OR identifier:"{filename}"',
                      "fl[]": "identifier,title,description", "rows": 100, "page": 1, "output": "json"}, timeout=60)


def analyze_found_material() -> None:
    hits = []
    for p in FOUND.rglob("*"):
        if not p.is_file():
            continue
        data = p.read_bytes(); ctype = "application/pdf" if data.startswith(b"%PDF") else "text/html"
        txt = text_sample(data, ctype, limit=500000); lower = txt.lower(); matched = []
        for kw in KEYWORDS:
            if kw in lower:
                idx = lower.find(kw)
                matched.append({"keyword": kw, "snippet": re.sub(r"\s+", " ", txt[max(0, idx-500):idx+1200])})
        if matched:
            hits.append({"path": str(p), "matches": matched})
    (OUT / "keyword_hits_found_material.json").write_text(json.dumps(hits, indent=2), encoding="utf-8")


def write_summary() -> None:
    (OUT / "fetch_records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (OUT / "found_files.json").write_text(json.dumps(found_files, indent=2), encoding="utf-8")
    by_status = defaultdict(int)
    for r in records:
        by_status[str(r.get("status", "error"))] += 1
    summary = {"fetch_attempts": len(records), "status_counts": dict(by_status),
               "found_file_count": len(found_files),
               "found_pdf_count": sum(1 for x in found_files if str(x.get("found_path", "")).lower().endswith(".pdf")),
               "note": "All probes used public, unauthenticated routes. No PACER authentication or paywall bypass was attempted."}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "README.md").write_text("# Exhaustive free-source audit\n\n" + json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


def main() -> None:
    discover_direct_public_routes()
    search_public_web()
    query_wayback()
    query_common_crawl()
    query_other_archives_and_repositories()
    analyze_found_material()
    write_summary()


if __name__ == "__main__":
    main()
