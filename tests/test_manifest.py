"""Shape-only tests for the pure helpers in ingest/manifest.py.

No network, no DB: FileStamp objects are built by hand.
"""
from datetime import datetime, timezone

from ingest.manifest import FileStamp, build_id_of, span_seconds


def _stamps():
    return [
        FileStamp("a.gz", datetime(2026, 8, 17, 13, 41, 35, tzinfo=timezone.utc), 100, None),
        FileStamp("b.gz", datetime(2026, 8, 17, 13, 43, 11, tzinfo=timezone.utc), 200, None),
    ]


def test_build_id_is_a_string():
    assert isinstance(build_id_of(_stamps()), str)


def test_span_seconds_is_an_int():
    assert isinstance(span_seconds(_stamps()), int)
