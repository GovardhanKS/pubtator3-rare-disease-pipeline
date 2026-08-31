"""Resumable download with our own SHA256.

The server offers no ETag and no digest (verified: 0 of 5 files), so the only
integrity check that exists is one we compute. bytes_received must equal the
advertised content_length or the file is marked failed - a truncated gzip that
still decompresses partway is exactly the failure this catches.

Range requests are supported (Accept-Ranges: bytes, 206 confirmed), so an
interrupted download resumes instead of restarting.
"""
from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.config import FTP_BASE, RAW_DIR
from ingest.manifest import connect, probe

CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK * 8), b""):
            h.update(block)
    return h.hexdigest()


def download(name: str, expected_length: int, force=False) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / name

    if dest.exists() and not force:
        have = dest.stat().st_size
        if have == expected_length:
            return {"filename": name, "bytes_received": have, "resumed_from": have,
                    "sha256": sha256_of(dest), "seconds": 0.0, "cached": True}
    else:
        have = 0
        if force and dest.exists():
            dest.unlink()

    have = dest.stat().st_size if dest.exists() else 0
    mode = "ab" if have else "wb"
    headers = {"Range": f"bytes={have}-"} if have else {}

    t0 = time.time()
    with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True) as c:
        with c.stream("GET", f"{FTP_BASE}/{name}", headers=headers) as r:
            r.raise_for_status()
            if have and r.status_code != 206:
                # Server ignored the range - start clean rather than append garbage.
                dest.unlink(missing_ok=True)
                have, mode = 0, "wb"
            with dest.open(mode) as fh:
                for chunk in r.iter_bytes(CHUNK):
                    fh.write(chunk)
    elapsed = time.time() - t0

    got = dest.stat().st_size
    if got != expected_length:
        raise RuntimeError(
            f"{name}: received {got} bytes, advertised {expected_length}. "
            "Refusing to parse a short file - it would decompress partway and "
            "silently undercount."
        )
    return {"filename": name, "bytes_received": got, "resumed_from": have,
            "sha256": sha256_of(dest), "seconds": elapsed, "cached": False}


def _record(name, bid, res, attempts=40, backoff=3.0):
    """Open the DB only to write, then close - and retry if it is locked.

    DuckDB is single-writer. A short write window was not enough: a 54-second
    parse of a file that already landed will still collide with the fetcher
    recording the next one. Downloading 4.86 GB and then losing the manifest row
    to a lock is the worst possible trade, so this waits the parser out.

    The bytes are already on disk and verified at this point, so retrying is
    always safe - there is nothing to redo, only a row to write.
    """
    last = None
    for i in range(attempts):
        try:
            db = connect()
            try:
                db.execute(
                    """UPDATE files SET bytes_received = ?, sha256 = ?, downloaded_at = ?
                       WHERE build_id = ? AND filename = ?""",
                    [res["bytes_received"], res["sha256"],
                     datetime.now(timezone.utc), bid, name],
                )
                return
            finally:
                db.close()
        except duckdb.IOException as e:
            last = e
            if i == 0:
                print(f"    db locked (parser busy) - retrying up to "
                      f"{int(attempts * backoff)}s", flush=True)
            time.sleep(backoff)
    raise RuntimeError(
        f"{name}: downloaded and verified, but could not write its manifest row "
        f"after {int(attempts * backoff)}s. Re-run fetch.py - the file is cached, "
        f"so it will only rewrite the row. Last error: {last}"
    )


def main(argv):
    stamps = {s.filename: s for s in probe()}
    wanted = argv or list(stamps)

    for name in wanted:
        s = stamps[name]
        print(f"--> {name}  ({s.content_length/2**20:.1f} MB)", flush=True)
        res = download(name, s.content_length)
        _record(name, s.last_modified.date().isoformat(), res)
        rate = "" if res["cached"] else f"  {res['bytes_received']/2**20/res['seconds']:.1f} MB/s"
        print(f"    {'cached' if res['cached'] else 'ok'}{rate}  sha256={res['sha256'][:16]}...",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
