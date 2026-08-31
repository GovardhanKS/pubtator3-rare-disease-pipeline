"""HEAD gate and build manifest.

Step 1 of the build order. Costs one HEAD per file and downloads nothing.

Two jobs:
  probe()  - HEAD every target file, return the observed manifest
  gate()   - compare against the last ingested manifest and decide whether to ingest

The span check exists because the 2026-08-17 build's files were written 96 seconds
apart (13:41:35 - 13:43:11). A build caught mid-publish would show a much larger
spread, and pulling it would silently mix two builds.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import duckdb
import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from ingest.config import (DB_PATH, DATA_ROOT, FTP_BASE, MAX_BUILD_SPAN_HOURS,
                           PROJECT_ROOT, TARGET_FILES)


@dataclass(frozen=True)
class FileStamp:
    filename: str
    last_modified: datetime
    content_length: int
    etag: str | None      # None for this FTP; recorded to make the absence evidence

    def as_row(self):
        return (self.filename, self.last_modified, self.content_length, self.etag)


def connect(path=None):
    db = duckdb.connect(str(path or DB_PATH))
    db.execute((PROJECT_ROOT / "ingest" / "schema.sql").read_text())
    return db


def probe(files=None, timeout=45.0) -> list[FileStamp]:
    """HEAD each target file. No bytes of payload transferred."""
    files = files or TARGET_FILES
    stamps = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for name in files:
            r = client.head(f"{FTP_BASE}/{name}")
            r.raise_for_status()
            lm = r.headers.get("last-modified")
            if lm is None:
                raise RuntimeError(
                    f"{name}: no Last-Modified header. It is the only version marker "
                    "this server offers - without it a build cannot be identified."
                )
            stamps.append(FileStamp(
                filename=name,
                last_modified=parsedate_to_datetime(lm).astimezone(timezone.utc),
                content_length=int(r.headers["content-length"]),
                etag=r.headers.get("etag"),
            ))
    return stamps


def build_id_of(stamps) -> str:
    return max(s.last_modified for s in stamps).date().isoformat()


def span_seconds(stamps) -> int:
    times = [s.last_modified for s in stamps]
    return int((max(times) - min(times)).total_seconds())


def gate(db, stamps) -> dict:
    """Decide whether to ingest. Logs every check to head_checks either way."""
    bid, span = build_id_of(stamps), span_seconds(stamps)
    now = datetime.now(timezone.utc)

    known = {
        r[0]: (r[1], r[2]) for r in db.execute(
            "SELECT filename, last_modified, content_length FROM files "
            "WHERE bytes_received IS NOT NULL"
        ).fetchall()
    }

    changed = []
    for s in stamps:
        prev = known.get(s.filename)
        is_new = prev is None or prev[0].replace(tzinfo=timezone.utc) != s.last_modified \
                 or prev[1] != s.content_length
        if is_new:
            changed.append(s.filename)
        db.execute(
            "INSERT INTO head_checks VALUES (?, ?, ?, ?, ?)",
            [now, s.filename, s.last_modified, s.content_length, is_new],
        )

    if not changed:
        return {"action": "skip", "reason": "no new build", "build_id": bid, "span_seconds": span}
    if span > MAX_BUILD_SPAN_HOURS * 3600:
        return {"action": "abort",
                "reason": (f"last_modified spans {span}s (> {MAX_BUILD_SPAN_HOURS}h) - "
                           "likely a mid-publish fetch, refusing to mix two builds"),
                "build_id": bid, "span_seconds": span, "changed": changed}
    return {"action": "ingest", "build_id": bid, "span_seconds": span, "changed": changed}


def record_manifest(db, stamps, decision) -> str:
    """Write the observed stamps. bytes_received stays NULL until a real download."""
    bid = decision["build_id"]
    db.execute(
        "INSERT OR REPLACE INTO builds VALUES (?, ?, ?, ?, ?)",
        [bid, decision["span_seconds"], len(stamps),
         "manifest_only" if decision["action"] != "skip" else "complete",
         datetime.now(timezone.utc)],
    )
    for s in stamps:
        db.execute(
            """INSERT INTO files (build_id, filename, last_modified, content_length, etag)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (build_id, filename) DO UPDATE SET
                 last_modified = excluded.last_modified,
                 content_length = excluded.content_length,
                 etag = excluded.etag""",
            [bid, *s.as_row()],
        )
    return bid


def main():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    db = connect()
    stamps = probe()
    decision = gate(db, stamps)
    bid = record_manifest(db, stamps, decision)

    total = sum(s.content_length for s in stamps)
    print(f"build_id      {bid}")
    print(f"span          {decision['span_seconds']}s across {len(stamps)} files")
    print(f"total payload {total/2**30:.2f} GiB")
    print(f"etags served  {sum(s.etag is not None for s in stamps)} of {len(stamps)}")
    print()
    print(f"{'file':<26} {'last-modified (UTC)':<21} {'MB':>8}  etag")
    for s in sorted(stamps, key=lambda x: x.last_modified):
        print(f"{s.filename:<26} {s.last_modified:%Y-%m-%d %H:%M:%S}   "
              f"{s.content_length/2**20:>8.1f}  {s.etag or '-'}")
    print()
    print(f"DECISION: {decision['action']} - {decision.get('reason', 'new build')}")
    if decision.get("changed"):
        print(f"changed:  {', '.join(decision['changed'])}")
    db.close()
    return 0 if decision["action"] != "abort" else 1


if __name__ == "__main__":
    raise SystemExit(main())
