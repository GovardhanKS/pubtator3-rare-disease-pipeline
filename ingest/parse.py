"""Parse the gzipped TSVs into DuckDB.

Two streaming passes per file rather than staging ~200M rows to disk:
  pass 1  global aggregates + reject capture (reads every row)
  pass 2  the ECD-scoped slice (tiny output)

Three parsing decisions that are not defaults:

quote='' / escape=''
    Biomedical surface forms contain double quotes. With DuckDB's default quote
    character the parser would swallow them and mis-split fields. TSV has no
    quoting convention, so it is switched off.

store_rejects=true, never ignore_errors=true
    Unparseable rows land in a rejects table with line number and reason, and
    the count is surfaced. A dashboard that silently drops rows is the thing the
    post is criticising.

mentions exploded on '|'
    31.7% of rows carry more than one surface form. Surface forms are the
    mechanism behind Experiment 1, so they get their own table.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.config import ECD_MESH, ENTITY_FILES, RAW_DIR, RELATION_FILE
from ingest.manifest import connect

ENTITY_COLS = ("pmid BIGINT, type VARCHAR, concept_id VARCHAR, "
               "mentions_raw VARCHAR, resource VARCHAR")
RELATION_COLS = "pmid BIGINT, rel_type VARCHAR, concept1 VARCHAR, concept2 VARCHAR"


def _reader(path: Path, cols: str) -> str:
    coldict = ", ".join(f"'{c.split()[0]}': '{c.split()[1]}'" for c in cols.split(", "))
    return (f"read_csv('{path}', delim='\\t', header=false, quote='', escape='', "
            f"columns={{{coldict}}}, store_rejects=true, "
            f"rejects_table='rj_errors', rejects_scan='rj_scans')")


def _drain_rejects(db, build_id: str, filename: str) -> int:
    try:
        rows = db.execute(
            "SELECT line, error_type, csv_line FROM rj_errors"
        ).fetchall()
    except Exception:
        return 0
    for line, reason, raw in rows:
        db.execute("INSERT INTO rejects VALUES (?, ?, ?, ?, ?)",
                   [build_id, filename, line, str(reason), (raw or "")[:500]])
    db.execute("DROP TABLE IF EXISTS rj_errors")
    db.execute("DROP TABLE IF EXISTS rj_scans")
    return len(rows)


def _agg(db, build_id, filename, metrics: dict):
    now = datetime.now(timezone.utc)
    for metric, value in metrics.items():
        db.execute("INSERT INTO agg_global VALUES (?, ?, ?, ?, ?)",
                   [build_id, filename, metric, value, now])


def parse_disease(db, build_id: str) -> dict:
    """Stage A. Emits the ECD PMID set - Experiment 1's headline - plus aggregates."""
    name = "disease2pubtator3.gz"
    src = _reader(RAW_DIR / name, ENTITY_COLS)
    t0 = time.time()

    rows, pmids, concepts = db.execute(
        f"SELECT count(*), count(DISTINCT pmid), count(DISTINCT concept_id) FROM {src}"
    ).fetchone()
    rejected = _drain_rejects(db, build_id, name)

    # Derive the ECD PMID set first, straight from the file.
    db.execute(f"DELETE FROM ecd_pmids WHERE build_id='{build_id}'")
    db.execute(
        f"""INSERT INTO ecd_pmids
            SELECT DISTINCT '{build_id}', pmid FROM {src}
            WHERE concept_id = '{ECD_MESH}'"""
    )
    _drain_rejects(db, build_id, name)

    # Then keep EVERY disease annotation on those papers, not just the ECD one.
    # gene/mutation/chemical all retain every concept on the ECD paper set; a
    # disease table holding one concept by construction would make the dashboard
    # report a tautology ("1 distinct disease") and would hide what ECD papers
    # are actually about - the co-mentioned diagnoses and differentials.
    db.execute(f"DELETE FROM entity WHERE build_id='{build_id}' AND source_file='{name}'")
    db.execute(
        f"""INSERT INTO entity
            SELECT '{build_id}', s.pmid, s.type, s.concept_id, s.mentions_raw,
                   s.resource, '{name}'
            FROM {src} s
            SEMI JOIN ecd_pmids e ON e.pmid = s.pmid AND e.build_id = '{build_id}'"""
    )
    ecd_pmids = db.execute(
        f"SELECT count(*) FROM ecd_pmids WHERE build_id='{build_id}'").fetchone()[0]
    ecd_rows = db.execute(
        f"SELECT count(*) FROM entity WHERE build_id='{build_id}' "
        f"AND source_file='{name}' AND concept_id='{ECD_MESH}'").fetchone()[0]
    all_disease_rows = db.execute(
        f"SELECT count(*) FROM entity WHERE build_id='{build_id}' "
        f"AND source_file='{name}'").fetchone()[0]

    _agg(db, build_id, name, {
        "rows_total": rows, "distinct_pmids": pmids, "distinct_concepts": concepts,
        "ecd_rows": ecd_rows, "ecd_distinct_pmids": ecd_pmids,
        "disease_rows_on_ecd_papers": all_disease_rows,
    })
    _finish(db, build_id, name, rows, rejected)
    return {"file": name, "rows": rows, "distinct_pmids": pmids,
            "distinct_concepts": concepts, "ecd_rows": ecd_rows,
            "ecd_distinct_pmids": ecd_pmids,
            "disease_rows_on_ecd_papers": all_disease_rows,
            "rejected": rejected, "seconds": round(time.time() - t0, 1)}


def parse_entity(db, build_id: str, name: str) -> dict:
    """Stage B. Semi-join against the ECD PMID set from Stage A."""
    src = _reader(RAW_DIR / name, ENTITY_COLS)
    t0 = time.time()

    rows, pmids, concepts = db.execute(
        f"SELECT count(*), count(DISTINCT pmid), count(DISTINCT concept_id) FROM {src}"
    ).fetchone()
    rejected = _drain_rejects(db, build_id, name)

    db.execute(f"DELETE FROM entity WHERE build_id='{build_id}' AND source_file='{name}'")
    db.execute(
        f"""INSERT INTO entity
            SELECT '{build_id}', s.pmid, s.type, s.concept_id, s.mentions_raw,
                   s.resource, '{name}'
            FROM {src} s
            SEMI JOIN ecd_pmids e ON e.pmid = s.pmid AND e.build_id = '{build_id}'"""
    )
    _drain_rejects(db, build_id, name)

    ecd_rows, ecd_pmids = db.execute(
        f"""SELECT count(*), count(DISTINCT pmid) FROM entity
            WHERE build_id='{build_id}' AND source_file='{name}'"""
    ).fetchone()
    _agg(db, build_id, name, {
        "rows_total": rows, "distinct_pmids": pmids, "distinct_concepts": concepts,
        "ecd_rows": ecd_rows, "ecd_distinct_pmids": ecd_pmids,
    })
    _finish(db, build_id, name, rows, rejected)
    return {"file": name, "rows": rows, "distinct_pmids": pmids,
            "distinct_concepts": concepts, "ecd_rows": ecd_rows,
            "ecd_distinct_pmids": ecd_pmids, "rejected": rejected,
            "seconds": round(time.time() - t0, 1)}


def parse_relation(db, build_id: str) -> dict:
    """Stage B. Keeps ECD-PMID rows AND any row naming ECD in either concept slot."""
    name = RELATION_FILE
    src = _reader(RAW_DIR / name, RELATION_COLS)
    t0 = time.time()

    rows, pmids = db.execute(f"SELECT count(*), count(DISTINCT pmid) FROM {src}").fetchone()
    rejected = _drain_rejects(db, build_id, name)

    # The open question from build-plan.md, answered by the file itself.
    db.execute(f"DELETE FROM relation_types WHERE build_id='{build_id}'")
    db.execute(
        f"""INSERT INTO relation_types
            SELECT '{build_id}', rel_type, count(*) FROM {src}
            GROUP BY rel_type ORDER BY 3 DESC"""
    )
    _drain_rejects(db, build_id, name)
    n_types = db.execute(
        f"SELECT count(*) FROM relation_types WHERE build_id='{build_id}'").fetchone()[0]

    db.execute(f"DELETE FROM relation WHERE build_id='{build_id}'")
    db.execute(
        f"""INSERT INTO relation
            SELECT '{build_id}', s.pmid, s.rel_type, s.concept1, s.concept2
            FROM {src} s
            WHERE s.pmid IN (SELECT pmid FROM ecd_pmids WHERE build_id='{build_id}')
               OR s.concept1 LIKE '%{ECD_MESH}%' OR s.concept2 LIKE '%{ECD_MESH}%'"""
    )
    _drain_rejects(db, build_id, name)

    ecd_rows = db.execute(
        f"SELECT count(*) FROM relation WHERE build_id='{build_id}'").fetchone()[0]
    _agg(db, build_id, name, {
        "rows_total": rows, "distinct_pmids": pmids,
        "distinct_relation_types": n_types, "ecd_rows": ecd_rows,
    })
    _finish(db, build_id, name, rows, rejected)
    return {"file": name, "rows": rows, "distinct_pmids": pmids,
            "distinct_relation_types": n_types, "ecd_rows": ecd_rows,
            "rejected": rejected, "seconds": round(time.time() - t0, 1)}


def explode_mentions(db, build_id: str) -> int:
    """Finding 4: pipe-delimited Mentions, 31.7% multi-value."""
    db.execute(f"DELETE FROM mentions WHERE build_id='{build_id}'")
    db.execute(
        f"""INSERT INTO mentions
            SELECT build_id, pmid, type, concept_id, trim(surface)
            FROM (SELECT build_id, pmid, type, concept_id,
                         unnest(str_split(mentions_raw, '|')) AS surface
                  FROM entity WHERE build_id='{build_id}')
            WHERE trim(surface) <> ''"""
    )
    return db.execute(
        f"SELECT count(*) FROM mentions WHERE build_id='{build_id}'").fetchone()[0]


def _finish(db, build_id, name, rows, rejected):
    db.execute(
        """UPDATE files SET rows_parsed = ?, rows_rejected = ?, parsed_at = ?
           WHERE build_id = ? AND filename = ?""",
        [rows, rejected, datetime.now(timezone.utc), build_id, name],
    )


def main(argv):
    build_id = argv[0] if argv else "2026-08-17"
    targets = argv[1:] or ["disease2pubtator3.gz"]
    db = connect()
    db.execute("SET preserve_insertion_order = false")

    for name in targets:
        if not (RAW_DIR / name).exists():
            print(f"skip {name} - not downloaded yet", flush=True)
            continue
        if name == "disease2pubtator3.gz":
            res = parse_disease(db, build_id)
        elif name == RELATION_FILE:
            res = parse_relation(db, build_id)
        else:
            res = parse_entity(db, build_id, name)
        print("  ".join(f"{k}={v}" for k, v in res.items()), flush=True)

    n = explode_mentions(db, build_id)
    print(f"mentions exploded: {n} surface-form rows", flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
