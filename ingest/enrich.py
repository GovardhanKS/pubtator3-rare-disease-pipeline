"""Publication year and journal for the ECD papers.

The bulk PubTator3 files carry PMIDs and nothing else - no date, no journal, no
title. For a page a biologist is meant to read, the time axis matters more than
almost anything else in the ingest: it is what turns a pile of 2,288 papers into
a story with the BRAF discovery and the vemurafenib approval visible in it.

One E-utilities call per 200 PMIDs, cached to disk.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.config import DB_PATH
from ingest.manifest import connect

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
CACHE = Path.home() / "pubtator3-data" / "eutils-cache"
BATCH = 200


def _fetch_batch(pmids: list[int]) -> dict[int, tuple[int | None, str | None]]:
    key = CACHE / f"meta-{pmids[0]}-{len(pmids)}.json"
    if key.exists():
        return {int(k): tuple(v) for k, v in json.loads(key.read_text()).items()}
    r = httpx.post(EFETCH, data={"db": "pubmed", "id": ",".join(map(str, pmids)),
                                 "retmode": "xml"}, timeout=180)
    r.raise_for_status()
    out: dict[int, tuple] = {}
    for art in re.split(r"(?=<PubmedArticle>)", r.text):
        m = re.search(r"<PMID[^>]*>(\d+)</PMID>", art)
        if not m:
            continue
        pmid = int(m.group(1))
        # Prefer the article's own date; fall back to the PubMed record date.
        y = re.search(r"<PubDate>.*?<Year>(\d{4})</Year>", art, re.S) \
            or re.search(r"<PubDate>.*?<MedlineDate>(\d{4})", art, re.S) \
            or re.search(r"<PubMedPubDate[^>]*>\s*<Year>(\d{4})</Year>", art, re.S)
        j = re.search(r"<Title>(.*?)</Title>", art, re.S)
        out[pmid] = (int(y.group(1)) if y else None,
                     re.sub(r"\s+", " ", j.group(1)).strip() if j else None)
    CACHE.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps({str(k): list(v) for k, v in out.items()}))
    time.sleep(0.4)
    return out


def main(build_id: str = "2026-08-17") -> int:
    db = connect()
    try:
        pmids = [r[0] for r in db.execute(
            "SELECT pmid FROM ecd_pmids WHERE build_id = ? ORDER BY pmid",
            [build_id]).fetchall()]
        print(f"fetching year + journal for {len(pmids)} ECD papers "
              f"({(len(pmids)+BATCH-1)//BATCH} requests)", flush=True)
        got = {}
        for i in range(0, len(pmids), BATCH):
            got.update(_fetch_batch(pmids[i:i + BATCH]))
            print(f"  {min(i+BATCH, len(pmids))}/{len(pmids)}", flush=True)

        db.execute("DELETE FROM pmid_meta WHERE build_id = ?", [build_id])
        db.executemany("INSERT INTO pmid_meta VALUES (?, ?, ?, ?)",
                       [(build_id, p, y, j) for p, (y, j) in got.items()])
        n, miny, maxy, noyear = db.execute("""
            SELECT count(*), min(year), max(year), count(*) filter (year IS NULL)
            FROM pmid_meta WHERE build_id = ?""", [build_id]).fetchone()
        print(f"\nstored {n} records, years {miny}-{maxy}, {noyear} with no year")
        print(f"unresolved by PubMed: {len(pmids) - n}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
