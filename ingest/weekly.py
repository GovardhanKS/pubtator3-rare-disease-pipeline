"""The weekly job. Decision 3 made this real rather than decorative.

The bulk FTP is monthly - the README says so and every target file is dated
2026-08-17 - while the web interface and API update weekly. A weekly job that
downloaded unconditionally would re-pull 4.86 GB three weeks out of four.

So: HEAD first, act only on a change. The HEAD costs nothing, we still catch a
new build within 7 days, and every check is logged to head_checks - which makes
this an audit trail of when NCBI actually publishes, more trustworthy than a
README that is three years stale.

Exit codes:  0 no change or ingest done · 1 aborted (mid-publish risk) · 2 error

Schedule:  0 6 * * 1  cd <repo> && python3 ingest/weekly.py >> ~/pubtator3-data/weekly.log 2>&1
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.config import ENTITY_FILES, RELATION_FILE
from ingest.manifest import connect, gate, probe, record_manifest


def main(dry_run: bool = False) -> int:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        stamps = probe()
    except Exception as e:
        print(f"[{stamp}] ERROR probing FTP: {e}")
        traceback.print_exc()
        return 2

    db = connect()
    try:
        decision = gate(db, stamps)
        record_manifest(db, stamps, decision)
    finally:
        db.close()

    action = decision["action"]
    print(f"[{stamp}] build={decision['build_id']} span={decision['span_seconds']}s "
          f"action={action} {decision.get('reason', '')}")

    if action == "skip":
        return 0
    if action == "abort":
        print(f"[{stamp}] NOT ingesting. Re-check next week; if the span persists, "
              "the publish layout has changed and the gate needs revisiting.")
        return 1
    if dry_run:
        print(f"[{stamp}] dry run - would ingest: {', '.join(decision['changed'])}")
        return 0

    from ingest.fetch import main as fetch_main
    from ingest.parse import main as parse_main

    fetch_main(decision["changed"])
    ordered = (["disease2pubtator3.gz"]
               + [f for f in ENTITY_FILES if f != "disease2pubtator3.gz"]
               + [RELATION_FILE])
    parse_main([decision["build_id"]] + [f for f in ordered if f in decision["changed"]])

    db = connect()
    try:
        db.execute("UPDATE builds SET status='complete' WHERE build_id=?",
                   [decision["build_id"]])
    finally:
        db.close()
    print(f"[{stamp}] ingest complete for {decision['build_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry_run="--dry-run" in sys.argv))
