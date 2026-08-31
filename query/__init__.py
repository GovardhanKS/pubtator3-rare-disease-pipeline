"""The only module that reads the database.

The dashboard, the API and the three experiments all call these functions, so
the number in the post and the number on the page come from one code path and
cannot drift.

Every function returns a Result, which pairs the data with the build it was
computed from. The build reference is a return value, not a decoration, so it
cannot be forgotten on the way to a page or a JSON file.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import re

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.config import DB_PATH, ECD_GENES, ECD_MESH, PUBMED_DENOMINATORS


@dataclass(frozen=True)
class BuildRef:
    """What build a number came from. The FTP carries no version string, so this
    is reconstructed from per-file Last-Modified headers captured at ingest."""
    build_id: str
    span_seconds: int
    ingested_at: datetime | None
    files: list[dict] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["ingested_at"] = self.ingested_at.isoformat() if self.ingested_at else None
        for f in d["files"]:
            for k in ("last_modified", "downloaded_at", "parsed_at"):
                if f.get(k) is not None:
                    f[k] = f[k].isoformat()
        return d


@dataclass(frozen=True)
class Result:
    data: Any
    build: BuildRef

    def to_dict(self):
        return {"data": self.data, "build": self.build.to_dict()}


def _con():
    return duckdb.connect(str(DB_PATH), read_only=True)


def _rows(db, sql, params=None) -> list[dict]:
    cur = db.execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def latest_build_id(db=None) -> str | None:
    own = db is None
    db = db or _con()
    try:
        r = db.execute("SELECT max(build_id) FROM builds").fetchone()
        return r[0] if r else None
    finally:
        if own:
            db.close()


def build_ref(db, build_id: str | None = None) -> BuildRef:
    build_id = build_id or latest_build_id(db)
    b = db.execute(
        "SELECT span_seconds, ingested_at FROM builds WHERE build_id = ?", [build_id]
    ).fetchone()
    files = _rows(db, """SELECT filename, last_modified, content_length, bytes_received,
                                sha256, etag, rows_parsed, rows_rejected,
                                downloaded_at, parsed_at
                         FROM files WHERE build_id = ? ORDER BY last_modified""", [build_id])
    return BuildRef(build_id=build_id,
                    span_seconds=b[0] if b else 0,
                    ingested_at=b[1] if b else None,
                    files=files)


def manifest(build_id: str | None = None) -> Result:
    db = _con()
    try:
        ref = build_ref(db, build_id)
        return Result({"etags_served": sum(f["etag"] is not None for f in ref.files),
                       "files": len(ref.files),
                       "rows_parsed": sum(f["rows_parsed"] or 0 for f in ref.files),
                       "rows_rejected": sum(f["rows_rejected"] or 0 for f in ref.files)}, ref)
    finally:
        db.close()


def coverage(build_id: str | None = None) -> Result:
    """Experiment 1. Three numbers, two gaps, never summed.

    PubTator3 normalises to MeSH, so comparing its output only to the 1,599 text
    match conflates PubTator3 failing to tag a paper with NLM never having
    MeSH-indexed it. Those point in opposite directions.
    """
    db = _con()
    try:
        ref = build_ref(db, build_id)
        found = db.execute(
            "SELECT count(*) FROM ecd_pmids WHERE build_id = ?", [ref.build_id]
        ).fetchone()[0]
        mesh = PUBMED_DENOMINATORS["mesh_indexed"]
        text = PUBMED_DENOMINATORS["text_matched"]
        return Result({
            "pubtator3_ecd_pmids": found,
            "pubmed_mesh_indexed": mesh, "pubmed_text_matched": text,
            "vs_mesh_indexed": {
                "delta": found - mesh["count"],
                "ratio": round(found / mesh["count"], 3) if mesh["count"] else None,
                "means": "does PubTator3 recover what NLM already curated",
            },
            "vs_text_matched": {
                "delta": found - text["count"],
                "ratio": round(found / text["count"], 3) if text["count"] else None,
                "means": "does PubTator3 find ECD papers NLM never MeSH-indexed",
            },
            "mesh_key": ECD_MESH,
        }, ref)
    finally:
        db.close()


def surface_forms(build_id: str | None = None, limit: int = 50) -> Result:
    """The mechanism behind the coverage number. Exploded from the pipe-delimited
    Mentions column, which is multi-value in ~32% of rows."""
    db = _con()
    try:
        ref = build_ref(db, build_id)
        return Result(_rows(db, """
            SELECT surface, count(*) AS n_rows, count(DISTINCT pmid) AS n_pmids
            FROM mentions WHERE build_id = ? AND concept_id = ?
            GROUP BY surface ORDER BY n_pmids DESC, surface LIMIT ?""",
            [ref.build_id, ECD_MESH, limit]), ref)
    finally:
        db.close()


def entity_coverage(build_id: str | None = None) -> Result:
    """Experiment 2. Split by which NER system produced the annotation - mutation
    is tmVar3 end to end and never touches AIONER, so this is a clean comparison
    of two independent systems over one document set."""
    ner = {"Gene": ("AIONER", "GNorm2"), "Disease": ("AIONER", "TaggerOne"),
           "Chemical": ("AIONER", "NLM-Chem"), "Mutation": ("tmVar3", "tmVar3")}
    db = _con()
    try:
        ref = build_ref(db, build_id)
        total = db.execute("SELECT count(*) FROM ecd_pmids WHERE build_id = ?",
                           [ref.build_id]).fetchone()[0]
        by_type = _rows(db, """
            SELECT type, count(*) AS n_rows, count(DISTINCT pmid) AS n_pmids,
                   count(DISTINCT concept_id) AS n_concepts
            FROM entity WHERE build_id = ? GROUP BY type ORDER BY n_pmids DESC""",
            [ref.build_id])
        for r in by_type:
            r["ner"], r["normaliser"] = ner.get(r["type"], ("?", "?"))
            r["pct_of_ecd_papers"] = round(100 * r["n_pmids"] / total, 1) if total else None
        drivers = _rows(db, f"""
            SELECT concept_id, count(DISTINCT pmid) AS n_pmids
            FROM entity WHERE build_id = ? AND type = 'Gene'
              AND concept_id IN ({','.join("'" + g + "'" for g in ECD_GENES)})
            GROUP BY concept_id ORDER BY n_pmids DESC""", [ref.build_id])
        for d in drivers:
            d["symbol"] = ECD_GENES.get(d["concept_id"], "?")
        return Result({"ecd_papers": total, "by_type": by_type, "driver_genes": drivers}, ref)
    finally:
        db.close()


def relation_types(build_id: str | None = None) -> Result:
    """The README says 8 relation types, the 2024 NAR paper says 12. This counts
    the distinct values in column 2 of the file and lets it settle the question."""
    db = _con()
    try:
        ref = build_ref(db, build_id)
        rows = _rows(db, """SELECT rel_type, n_rows FROM relation_types
                            WHERE build_id = ? ORDER BY n_rows DESC""", [ref.build_id])
        return Result({"n_types": len(rows), "types": rows,
                       "readme_claims": 8, "nar_2024_paper_claims": 12}, ref)
    finally:
        db.close()


def concept_labels(build_id: str | None = None) -> dict[str, str]:
    """Human labels for concept identifiers, taken from our own annotations.

    A relation edge ships as `Chemical|MESH:D000077484 -- Disease|MESH:D031249`,
    which is unreadable. The label is recoverable without any external lookup:
    the Mentions column already carries the surface text a human wrote, so the
    most frequent surface form per concept is its label. No API call, no second
    vocabulary to version, and the label is by construction attested in the
    literature we ingested.
    """
    db = _con()
    try:
        build_id = build_id or latest_build_id(db)
        rows = db.execute("""
            SELECT concept_id, type, surface, count(*) AS n
            FROM mentions WHERE build_id = ?
            GROUP BY concept_id, type, surface
            QUALIFY row_number() OVER (PARTITION BY concept_id ORDER BY n DESC, surface) = 1
        """, [build_id]).fetchall()
        out = {}
        for cid, typ, surface, _ in rows:
            out[cid] = surface
            out[f"{typ}|{cid}"] = surface
        return out
    finally:
        db.close()


def _label_concept(raw: str, labels: dict[str, str]) -> str:
    """Render `Gene|673` or `ProteinMutation|RS#:...;HGVS:p.V600E;...` readably."""
    if not raw:
        return raw
    if raw in labels:
        return f"{labels[raw]} ({raw})"
    typ, _, ident = raw.partition("|")
    if ident in labels:
        return f"{labels[ident]} ({raw})"
    # tmVar3 packs several keys into one identifier; HGVS is the readable one.
    m = re.search(r"HGVS:([^;]+)", ident)
    if m:
        gene = re.search(r"CorrespondingGene:(\d+)", ident)
        g = labels.get(gene.group(1), "") if gene else ""
        return f"{(g + ' ') if g else ''}{m.group(1)} ({typ})"
    return raw


def ecd_relations(build_id: str | None = None) -> Result:
    """Experiment 3. The ECD subgraph - small enough to render honestly and to
    eyeball for errors."""
    db = _con()
    try:
        ref = build_ref(db, build_id)
        edges = _rows(db, """
            SELECT rel_type, concept1, concept2,
                   count(DISTINCT pmid) AS n_pmids
            FROM relation WHERE build_id = ?
            GROUP BY rel_type, concept1, concept2
            ORDER BY n_pmids DESC""", [ref.build_id])
        labels = concept_labels(ref.build_id)
        for e in edges:
            e["concept1_label"] = _label_concept(e["concept1"], labels)
            e["concept2_label"] = _label_concept(e["concept2"], labels)
        touching = [e for e in edges
                    if ECD_MESH in (e["concept1"] or "") or ECD_MESH in (e["concept2"] or "")]
        return Result({"edges_on_ecd_papers": len(edges),
                       "edges_naming_ecd": len(touching),
                       "ecd_edges": touching[:200],
                       "all_edges": edges[:500]}, ref)
    finally:
        db.close()


def build_deltas() -> Result:
    """Month-on-month. Requires agg_global to be append-only - it cannot be
    backfilled, which is why the schema fixes it from the first ingest."""
    db = _con()
    try:
        ref = build_ref(db)
        return Result(_rows(db, """
            SELECT build_id, source_file, metric, value,
                   value - lag(value) OVER (PARTITION BY source_file, metric
                                            ORDER BY build_id) AS delta
            FROM agg_global ORDER BY source_file, metric, build_id"""), ref)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Disease-facing queries.
#
# Everything above answers "what did the text-mining system do". These answer
# "what does the literature on this disease say", which is what a biologist
# opening the page actually wants. Same data, same build stamp, different
# question - and the second question is the one the page leads with.
# ---------------------------------------------------------------------------

ECD_DRIVER_IDS = tuple(ECD_GENES)


def overview(build_id: str | None = None) -> Result:
    db = _con()
    try:
        ref = build_ref(db, build_id)
        papers, first, last = db.execute("""
            SELECT count(*), min(year), max(year) FROM pmid_meta WHERE build_id = ?
        """, [ref.build_id]).fetchone()
        recent, = db.execute("""
            SELECT count(*) FROM pmid_meta WHERE build_id = ? AND year >= 2015
        """, [ref.build_id]).fetchone()
        braf, = db.execute("""
            SELECT count(DISTINCT pmid) FROM entity
            WHERE build_id = ? AND type = 'Gene' AND concept_id = '673'
        """, [ref.build_id]).fetchone()
        with_gene, = db.execute("""
            SELECT count(DISTINCT pmid) FROM entity WHERE build_id = ? AND type = 'Gene'
        """, [ref.build_id]).fetchone()
        journals, = db.execute("""
            SELECT count(DISTINCT journal) FROM pmid_meta WHERE build_id = ?
        """, [ref.build_id]).fetchone()
        return Result({"papers": papers, "first_year": first, "last_year": last,
                       "since_2015": recent,
                       "pct_since_2015": round(100 * recent / papers, 1) if papers else None,
                       "braf_papers": braf, "papers_with_any_gene": with_gene,
                       "journals": journals}, ref)
    finally:
        db.close()


def timeline(build_id: str | None = None) -> Result:
    """Papers per year, and how many of them mention BRAF.

    The BRAF line is the point of the chart: it is flat at zero for fifty years
    of the disease's literature and then takes off, which is what the molecular
    era looks like from the outside.
    """
    db = _con()
    try:
        ref = build_ref(db, build_id)
        rows = _rows(db, """
            SELECT m.year AS year,
                   count(DISTINCT m.pmid) AS papers,
                   count(DISTINCT CASE WHEN g.pmid IS NOT NULL THEN m.pmid END) AS braf_papers
            FROM pmid_meta m
            LEFT JOIN (SELECT DISTINCT pmid FROM entity
                       WHERE build_id = ? AND type='Gene' AND concept_id='673') g
                   ON g.pmid = m.pmid
            WHERE m.build_id = ? AND m.year IS NOT NULL
            GROUP BY m.year ORDER BY m.year""", [ref.build_id, ref.build_id])
        return Result(rows, ref)
    finally:
        db.close()


def genes(build_id: str | None = None, limit: int = 25) -> Result:
    """Genes mentioned in the ECD literature, most-discussed first."""
    db = _con()
    try:
        ref = build_ref(db, build_id)
        labels = concept_labels(ref.build_id)
        rows = _rows(db, """
            SELECT concept_id, count(DISTINCT pmid) AS papers
            FROM entity WHERE build_id = ? AND type = 'Gene'
            GROUP BY concept_id ORDER BY papers DESC LIMIT ?""",
            [ref.build_id, limit])
        for r in rows:
            r["gene"] = ECD_GENES.get(r["concept_id"]) or labels.get(r["concept_id"], r["concept_id"])
            r["known_driver"] = r["concept_id"] in ECD_DRIVER_IDS
        return Result(rows, ref)
    finally:
        db.close()


def treatments(build_id: str | None = None, limit: int = 25) -> Result:
    """Drugs the literature links to treating this disease.

    Read from the extracted `treat` relations, so a row means "some paper states
    this drug treats this disease" - not that it is approved, and not that it
    worked. The ranking is by how many papers say it.
    """
    db = _con()
    try:
        ref = build_ref(db, build_id)
        labels = concept_labels(ref.build_id)
        rows = _rows(db, """
            SELECT CASE WHEN concept1 LIKE 'Chemical%' THEN concept1 ELSE concept2 END AS drug,
                   count(DISTINCT pmid) AS papers
            FROM relation
            WHERE build_id = ? AND rel_type = 'treat'
              AND (concept1 LIKE '%' || ? || '%' OR concept2 LIKE '%' || ? || '%')
              AND (concept1 LIKE 'Chemical%' OR concept2 LIKE 'Chemical%')
            GROUP BY drug ORDER BY papers DESC LIMIT ?""",
            [ref.build_id, ECD_MESH, ECD_MESH, limit])
        for r in rows:
            r["drug_name"] = _label_concept(r["drug"], labels).split(" (")[0]
        return Result(rows, ref)
    finally:
        db.close()


def co_mentioned_diseases(build_id: str | None = None, limit: int = 25) -> Result:
    """What else these papers discuss - largely the differential diagnosis.

    Also where the eponym problem becomes visible from the biology side: aortic
    entries appearing high in this list are a symptom of the Erdheim-Gsell
    confusion described under Data quality, not a real clinical association.
    """
    db = _con()
    try:
        ref = build_ref(db, build_id)
        labels = concept_labels(ref.build_id)
        rows = _rows(db, """
            SELECT concept_id, count(DISTINCT pmid) AS papers
            FROM entity
            WHERE build_id = ? AND type = 'Disease' AND concept_id <> ?
            GROUP BY concept_id ORDER BY papers DESC LIMIT ?""",
            [ref.build_id, ECD_MESH, limit])
        for r in rows:
            r["condition"] = labels.get(r["concept_id"], r["concept_id"])
        return Result(rows, ref)
    finally:
        db.close()


def variants(build_id: str | None = None, limit: int = 20) -> Result:
    """Specific mutations reported, most-cited first."""
    db = _con()
    try:
        ref = build_ref(db, build_id)
        rows = _rows(db, """
            SELECT concept_id, count(DISTINCT pmid) AS papers
            FROM entity WHERE build_id = ? AND type = 'Mutation'
            GROUP BY concept_id ORDER BY papers DESC LIMIT ?""",
            [ref.build_id, limit])
        labels = concept_labels(ref.build_id)
        for r in rows:
            surf = db_label = labels.get(r["concept_id"])
            m = re.search(r"HGVS:([^;]+)", r["concept_id"] or "")
            r["variant"] = surf or (m.group(1) if m else r["concept_id"])
        return Result(rows, ref)
    finally:
        db.close()
