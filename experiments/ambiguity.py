"""How often does PubTator3 admit it could not resolve a name?

The question this project keeps circling: what does a system do when it does not
know? PubTator3 has two ways of saying so in the bulk files, and neither is
documented in the README:

  identifier "-"        the mention was found, but not resolved to any concept
  identifier "a;b;c"    resolved to more than one candidate, not disambiguated

Both are emitted rather than dropped, which means the ambiguity is *visible* to
anyone who looks. Counting it is the difference between "the system is 98%
accurate" and knowing where the remaining mass actually sits.

Run: python3 experiments/ambiguity.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.config import DB_PATH, ECD_MESH, ENTITY_FILES, RAW_DIR

COLS = ("{'pmid':'BIGINT','type':'VARCHAR','concept_id':'VARCHAR',"
        "'mentions_raw':'VARCHAR','resource':'VARCHAR'}")


def reader(path: Path) -> str:
    return (f"read_csv('{path}', delim='\\t', header=false, quote='', escape='', "
            f"columns={COLS}, ignore_errors=true)")


def scan(db, filename: str) -> dict:
    src = reader(RAW_DIR / filename)
    t0 = time.time()
    # A semicolon does NOT mean ambiguity everywhere. Mutation identifiers are a
    # compound key - tmVar:...;HGVS:...;CorrespondingGene:... - so a naive
    # LIKE '%;%' counts 4.6M of them as ambiguous, which is simply wrong. Only
    # treat it as multi-candidate when every part is itself a standalone id.
    ID = r"([0-9]+|MESH:[A-Za-z0-9]+|OMIM:[0-9]+)"
    row = db.execute(f"""
        SELECT count(*)                                              AS rows,
               count(*) FILTER (concept_id = '-')                    AS unresolved,
               count(*) FILTER (regexp_full_match(concept_id, '{ID}(;{ID})+'))
                                                                     AS multi,
               count(*) FILTER (concept_id IS NULL OR concept_id='') AS blank,
               count(DISTINCT CASE WHEN concept_id='-' THEN lower(mentions_raw) END)
                                                                     AS distinct_unresolved_forms
        FROM {src}""").fetchone()
    rows, unresolved, multi, blank, forms = row
    return {"file": filename, "rows": rows,
            "unresolved": unresolved, "pct_unresolved": round(100 * unresolved / rows, 2),
            "multi_candidate": multi, "pct_multi": round(100 * multi / rows, 3),
            "blank": blank, "distinct_unresolved_surface_forms": forms,
            "seconds": round(time.time() - t0, 1)}


def mutation_grounding(db, filename="mutation2pubtator3.gz") -> dict:
    """Mutations cannot be tested like the others - the identifier is a compound
    key, never '-'. The closest equivalent of "could not place it" is whether the
    variant was tied to a dbSNP rs number rather than left as raw coordinates."""
    src = reader(RAW_DIR / filename)
    # dbSNP-grounded rows carry a BARE 'rs123...', not 'RS#:...'. Testing for the
    # latter reports 0% grounded; the real figure is 43%. The 'RS#:' form appears
    # only in the relation file's rendering of the same concept.
    rows, with_rs, coords, with_gene = db.execute(f"""
        SELECT count(*),
               count(*) FILTER (regexp_full_match(concept_id, 'rs[0-9]+')),
               count(*) FILTER (concept_id LIKE 'tmVar:%'),
               count(*) FILTER (concept_id LIKE '%CorrespondingGene:%')
        FROM {src}""").fetchone()
    return {"rows": rows, "dbsnp_grounded": with_rs,
            "pct_dbsnp_grounded": round(100 * with_rs / rows, 2),
            "coordinates_only": coords,
            "pct_coordinates_only": round(100 * coords / rows, 2),
            "with_corresponding_gene": with_gene,
            "pct_with_gene": round(100 * with_gene / rows, 2)}


def top_unresolved(db, filename: str, limit=12) -> list[dict]:
    src = reader(RAW_DIR / filename)
    return [{"surface": s, "mentions": n} for s, n in db.execute(f"""
        SELECT mentions_raw, count(*) n FROM {src}
        WHERE concept_id = '-' GROUP BY 1 ORDER BY n DESC LIMIT {limit}""").fetchall()]


def ecd_scoped(db, build_id="2026-08-17") -> dict:
    """The same question, restricted to the papers on this one disease."""
    out = {}
    for typ in ("Disease", "Gene", "Chemical", "Mutation"):
        r = db.execute("""
            SELECT count(*), count(*) FILTER (concept_id='-'),
                   count(*) FILTER (regexp_full_match(concept_id,
                       '([0-9]+|MESH:[A-Za-z0-9]+|OMIM:[0-9]+)(;([0-9]+|MESH:[A-Za-z0-9]+|OMIM:[0-9]+))+'))
            FROM entity WHERE build_id = ? AND type = ?""", [build_id, typ]).fetchone()
        if r[0]:
            out[typ] = {"rows": r[0], "unresolved": r[1], "multi_candidate": r[2],
                        "pct_unresolved": round(100 * r[1] / r[0], 2)}
    return out


def main():
    db = duckdb.connect()          # in-memory; reads the gz files directly
    db.execute("SET preserve_insertion_order = false")
    results, examples = [], {}
    for f in ENTITY_FILES:
        if not (RAW_DIR / f).exists():
            print(f"skip {f}"); continue
        r = scan(db, f)
        results.append(r)
        print(f"{r['file']:<26} rows={r['rows']:>12,}  unresolved={r['unresolved']:>10,} "
              f"({r['pct_unresolved']:>5}%)  multi={r['multi_candidate']:>8,}  "
              f"{r['seconds']}s", flush=True)
        if r["unresolved"]:
            examples[f] = top_unresolved(db, f)
    db.close()

    db2 = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        scoped = ecd_scoped(db2)
    finally:
        db2.close()

    db3 = duckdb.connect()
    db3.execute("SET preserve_insertion_order = false")
    mut = mutation_grounding(db3)
    db3.close()
    print(f"\nmutations grounded to a dbSNP id: {mut['dbsnp_grounded']:,} of "
          f"{mut['rows']:,} ({mut['pct_dbsnp_grounded']}%); "
          f"{mut['pct_coordinates_only']}% are raw coordinates only")

    payload = {"corpus": results, "top_unresolved_forms": examples,
               "ecd_scoped": scoped, "mutation_grounding": mut,
               "note": ("multi_candidate counts identifiers that are a list of standalone "
                        "ids. Mutation identifiers are a compound key and are excluded from "
                        "that test by construction.")}
    out = Path(__file__).resolve().parent / "ambiguity" / "result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))

    print("\n--- on the ECD paper set ---")
    for typ, v in scoped.items():
        print(f"  {typ:<10} rows={v['rows']:>7,}  unresolved={v['unresolved']:>6,} "
              f"({v['pct_unresolved']}%)  multi={v['multi_candidate']}")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
