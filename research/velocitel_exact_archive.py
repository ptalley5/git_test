#!/usr/bin/env python3
"""Exact archive/crawl probe for missing Velocitel v. Bauer filings.

Queries Wayback, Arquivo.pt, Memento, and Common Crawl using exact PACER IDs and
known RECAP/Internet Archive filenames. It does not authenticate to PACER or
circumvent paywalls; it only retrieves publicly archived responses.
"""
from __future__ import annotations

import concurrent.futures as cf
import gzip
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from warcio.archiveiterator import ArchiveIterator

OUT = Path("research-output/velocitel-exact-archive")
RAW = OUT / "raw"
FOUND = OUT / "found"
for p in (OUT, RAW, FOUND):
    p.mkdir(parents=True, exist_ok=True)

DOCS = {
    1: "13104645147", 7: "13104687977", 13: "13104696383", 14: "13104696400",
    15: "13104696466", 16: "13104696485", 17: "13104698737", 22: "13104709952",
    25: "13104713008", 26: "13104713031", 27: "13104714690", 30: "13104721692",
    57: "13105515113", 58: "13105515142", 59: "13105533867", 63: "13105558489",
    64: "13105558508", 66: "13105558553", 67: "13105558557", 70: "13105558604",
    71: "13105558614", 72: "13105559282", 73: "13105560840", 77: "13105567016",
    78: "13105569002", 82: "13105581061",
}
KEY_DES = {1, 13, 14, 15, 16, 30, 57, 58, 59, 63, 64, 66, 67, 72, 73, 77, 78, 82}
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 public-archive-research/1.0",
    "Accept-Language": "en-US,en;q=0.9",
})
records = []
archive_hits = []
recovered = []


def safe(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", v).strip("_")[:190] or "item"


def fetch(label: str, url: str, *, params=None, timeout=35, save=False, headers=None):
    try:
        r = S.get(url, params=params, timeout=timeout, allow_redirects=True, headers=headers)
        data = r.content
        ctype = r.headers.get("content-type", "")
        path = None
        if save:
            ext = ".pdf" if data.startswith(b"%PDF") or "pdf" in ctype.lower() else ".json" if "json" in ctype.lower() else ".html" if "html" in ctype.lower() or data.lstrip().startswith(b"<") else ".bin"
            path = RAW / f"{safe(label)}{ext}"
            path.write_bytes(data)
        rec = {
            "label": label, "requested_url": r.request.url, "status": r.status_code,
            "final_url": r.url, "content_type": ctype, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest() if data else None,
            "saved": str(path) if path else None,
        }
        records.append(rec)
        print(label, r.status_code, len(data), r.url, flush=True)
        return r
    except Exception as exc:
        records.append({"label": label, "requested_url": url, "error": repr(exc)})
        print(label, "ERROR", repr(exc), flush=True)
        return None


def exact_urls(de: int, pid: str):
    return [
        f"https://ecf.nced.uscourts.gov/doc1/{pid}",
        f"https://ecf.nced.uscourts.gov/doc1/{pid}?caseid=147135",
        f"http://ecf.nced.uscourts.gov/doc1/{pid}",
        f"http://ecf.nced.uscourts.gov/doc1/{pid}?caseid=147135",
        f"https://storage.courtlistener.com/recap/gov.uscourts.nced.147135/gov.uscourts.nced.147135.{de}.0.pdf",
        f"https://archive.org/download/gov.uscourts.nced.147135/gov.uscourts.nced.147135.{de}.0.pdf",
    ]


def probe_temporal_archives():
    tasks = []
    for de in sorted(KEY_DES):
        pid = DOCS[de]
        for ui, url in enumerate(exact_urls(de, pid), 1):
            tasks.extend([
                (f"wb_de{de}_{ui}", "https://web.archive.org/cdx/search/cdx", {
                    "url": url, "output": "json", "fl": "timestamp,original,statuscode,mimetype,digest,length",
                    "filter": "statuscode:200", "collapse": "digest", "limit": "1000",
                }),
                (f"arquivo_cdx_de{de}_{ui}", "https://arquivo.pt/wayback/cdx", {
                    "url": url, "output": "json", "filter": "statuscode:200", "limit": "1000",
                }),
                (f"arquivo_text_de{de}_{ui}", "https://arquivo.pt/textsearch", {
                    "versionHistory": url, "maxItems": "50",
                }),
            ])
        # Memento only for the direct PACER URL to limit traffic.
        direct = f"https://ecf.nced.uscourts.gov/doc1/{pid}?caseid=147135"
        tasks.append((f"memento_de{de}", "https://timetravel.mementoweb.org/api/json/" + direct, None))

    def one(task):
        label, url, params = task
        r = fetch(label, url, params=params, timeout=45, save=True)
        if not r:
            return
        try:
            body = r.json()
        except Exception:
            body = None
        if body not in (None, [], {}, ""):
            archive_hits.append({"label": label, "request_url": r.request.url, "body": body})

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, tasks))


def commoncrawl_index_hits():
    r = fetch("cc_collections", "https://index.commoncrawl.org/collinfo.json", timeout=45, save=True)
    if not r:
        return []
    try:
        cols = r.json()
    except Exception:
        return []
    # Latest 18 plus selected historical collections around the litigation.
    selected = cols[:18]
    for c in cols:
        cid = c.get("id", "")
        if re.search(r"CC-MAIN-201[5-8]", cid) and c not in selected:
            selected.append(c)
    selected = selected[:34]
    prefixes = [
        "ecf.nced.uscourts.gov/doc1/131046*",
        "ecf.nced.uscourts.gov/doc1/131047*",
        "ecf.nced.uscourts.gov/doc1/131055*",
        "storage.courtlistener.com/recap/gov.uscourts.nced.147135/*",
        "archive.org/download/gov.uscourts.nced.147135/*",
    ]
    tasks = []
    for c in selected:
        endpoint = c.get("cdx-api") or f"https://index.commoncrawl.org/{c['id']}-index"
        for pi, prefix in enumerate(prefixes, 1):
            tasks.append((c["id"], endpoint, pi, prefix))
    hits = []

    def one(task):
        cid, endpoint, pi, prefix = task
        rr = fetch(f"ccidx_{cid}_{pi}", endpoint, params={
            "url": prefix, "output": "json", "matchType": "prefix", "filter": "status:200",
        }, timeout=40, save=False)
        if not rr or rr.status_code != 200:
            return []
        out = []
        for line in rr.text.splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            row["collection"] = cid
            u = row.get("url", "")
            if any(pid in u for pid in DOCS.values()) or "gov.uscourts.nced.147135." in u:
                out.append(row)
        return out

    with cf.ThreadPoolExecutor(max_workers=14) as ex:
        for batch in ex.map(one, tasks):
            hits.extend(batch)
    uniq = {}
    for h in hits:
        uniq[(h.get("filename"), h.get("offset"), h.get("length"))] = h
    return list(uniq.values())


def recover_cc(hits):
    for idx, h in enumerate(hits[:250], 1):
        try:
            off = int(h["offset"]); length = int(h["length"])
            rr = fetch(f"ccpayload_{idx}", "https://data.commoncrawl.org/" + h["filename"],
                       headers={"Range": f"bytes={off}-{off+length-1}"}, timeout=75, save=False)
            if not rr:
                continue
            data = rr.content
            candidates = [data]
            if data[:2] == b"\x1f\x8b":
                try:
                    candidates.append(gzip.decompress(data))
                except Exception:
                    pass
            payload = b""; hdrs = {}
            for candidate in candidates:
                try:
                    for rec in ArchiveIterator(io.BytesIO(candidate)):
                        if rec.rec_type == "response":
                            payload = rec.content_stream().read()
                            hdrs = dict(rec.http_headers.headers) if rec.http_headers else {}
                            break
                except Exception:
                    continue
                if payload:
                    break
            if not payload:
                continue
            ctype = hdrs.get("Content-Type") or hdrs.get("content-type") or h.get("mime-detected", "")
            ext = ".pdf" if payload.startswith(b"%PDF") or "pdf" in ctype.lower() else ".html" if payload.lstrip().startswith(b"<") or "html" in ctype.lower() else ".bin"
            path = FOUND / f"cc_{idx}_{safe(h.get('url',''))}{ext}"
            path.write_bytes(payload)
            text = ""
            if ext == ".html":
                text = re.sub(r"\s+", " ", BeautifulSoup(payload, "lxml").get_text(" ", strip=True))[:30000]
            recovered.append({
                "hit": h, "content_type": ctype, "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(), "saved": str(path),
                "is_pdf": payload.startswith(b"%PDF"), "text_sample": text,
            })
        except Exception as exc:
            records.append({"label": "cc_recover", "url": h.get("url"), "error": repr(exc)})


def main():
    probe_temporal_archives()
    cc_hits = commoncrawl_index_hits()
    recover_cc(cc_hits)
    (OUT / "fetch_records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (OUT / "temporal_archive_hits.json").write_text(json.dumps(archive_hits, indent=2), encoding="utf-8")
    (OUT / "commoncrawl_hits.json").write_text(json.dumps(cc_hits, indent=2), encoding="utf-8")
    (OUT / "commoncrawl_recovered.json").write_text(json.dumps(recovered, indent=2), encoding="utf-8")
    summary = {
        "temporal_archive_nonempty_responses": len(archive_hits),
        "commoncrawl_exact_hits": len(cc_hits),
        "commoncrawl_payloads_recovered": len(recovered),
        "pdf_payloads_recovered": sum(1 for x in recovered if x.get("is_pdf")),
        "note": "Only public archive/crawl endpoints were queried; PACER authentication was not attempted.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
