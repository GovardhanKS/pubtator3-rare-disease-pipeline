"""Would a second reference vocabulary resolve what PubTator3 left unresolved?

Written to test a claim this project made and had not checked: that the
unresolved chemicals are ChEBI/PubChem territory and the coordinate-only
variants are dbSNP/ClinVar territory. Sampling says both are mostly wrong.

  chemicals  sample surface forms by mention frequency, look each up in
             PubChem (name -> CID) and ChEBI (via EBI OLS, label-validated)
  variants   sample those with a position, a real change and a gene - the
             subset that is resolvable in principle - and look for them in
             ClinVar

Two traps this code works around:

  OLS `exact=true` is not exact. It returned CHEBI:16136 (hydrogen sulfide)
  for "organic matter". Every hit is re-checked against the label and synonyms.

  PubChem's name endpoint also parses SMILES, so "CC" resolves to ethane and
  "OC" to methanol. Short all-caps strings are flagged rather than trusted.
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

import duckdb
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.config import RAW_DIR

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/cids/JSON"
OLS = "https://www.ebi.ac.uk/ols4/api/search"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
COLS = ("{'pmid':'BIGINT','type':'VARCHAR','concept_id':'VARCHAR',"
        "'mentions_raw':'VARCHAR','resource':'VARCHAR'}")
SUBPAT = r'tmVar:[cp]\|SUB\|([A-Za-z*]+)\|([0-9]+)\|([A-Za-z*]+)'

norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())


def _read(f: str) -> str:
    return (f"read_csv('{RAW_DIR / f}', delim='\\t', header=false, quote='', "
            f"escape='', columns={COLS}, ignore_errors=true)")


def pubchem(name: str):
    """Returns (cid, suspect). suspect=True when the string is short and all-caps,
    where a hit is more likely SMILES parsing than a name match."""
    suspect = bool(re.fullmatch(r"[A-Za-z0-9]{1,3}", name))
    try:
        r = httpx.get(PUG.format(urllib.parse.quote(name, safe="")), timeout=25)
        if r.status_code == 200:
            return r.json()["IdentifierList"]["CID"][0], suspect
    except Exception:
        pass
    return None, suspect


def chebi(name: str):
    try:
        r = httpx.get(OLS, params={"q": name, "ontology": "chebi", "rows": 5}, timeout=25)
        for doc in r.json()["response"]["docs"]:
            for cand in [doc.get("label", "")] + (doc.get("synonym") or []):
                if norm(cand) == norm(name):
                    return doc["obo_id"], doc.get("label", "")
    except Exception:
        pass
    return None


def sample_chemicals(db, k=40, seed=77):
    db.execute(f"""CREATE OR REPLACE TABLE u AS
        SELECT trim(unnest(str_split(mentions_raw,'|'))) AS surface
        FROM {_read('chemical2pubtator3.gz')} WHERE concept_id='-'""")
    forms = db.execute("""SELECT surface, count(*) n FROM u WHERE surface<>''
                          GROUP BY 1 ORDER BY n DESC LIMIT 20000""").fetchall()
    total = db.execute("SELECT count(*) FROM u WHERE surface<>''").fetchone()[0]
    random.seed(seed)
    samp = random.choices([s for s, _ in forms], weights=[n for _, n in forms], k=k)
    return total, len(forms), samp


def variant_breakdown(db) -> dict:
    r = db.execute(f"""
        WITH x AS (SELECT concept_id,
                          regexp_extract(concept_id,'{SUBPAT}',1) ref,
                          regexp_extract(concept_id,'{SUBPAT}',2) pos,
                          regexp_extract(concept_id,'{SUBPAT}',3) alt
                   FROM {_read('mutation2pubtator3.gz')} WHERE concept_id LIKE 'tmVar:%')
        SELECT count(*),
               count(*) FILTER (pos<>''),
               count(*) FILTER (pos<>'' AND ref=alt),
               count(*) FILTER (concept_id LIKE '%|Allele|%'),
               count(*) FILTER (pos<>'' AND ref<>alt AND concept_id LIKE '%CorrespondingGene:%')
        FROM x""").fetchone()
    co, pos, ident, allele, good = r
    pc = lambda n: round(100 * n / co, 2)
    return {"coordinate_only_rows": co, "with_position": pos, "pct_with_position": pc(pos),
            "identity_substitution": ident, "pct_identity": pc(ident),
            "allele_form": allele, "pct_allele": pc(allele),
            "resolvable_in_principle": good, "pct_resolvable_in_principle": pc(good)}


def gene_symbol(gid):
    try:
        r = httpx.get(EUTILS + "esummary.fcgi",
                      params={"db": "gene", "id": gid, "retmode": "json"}, timeout=30)
        return r.json()["result"][str(gid)]["name"]
    except Exception:
        return None


def clinvar_count(term):
    try:
        r = httpx.get(EUTILS + "esearch.fcgi",
                      params={"db": "clinvar", "term": term, "retmode": "json", "retmax": 1},
                      timeout=30)
        return int(r.json()["esearchresult"]["count"])
    except Exception:
        return -1


def main():
    db = duckdb.connect()
    db.execute("SET preserve_insertion_order = false")
    total, nforms, chem_samp = sample_chemicals(db)
    print(f"unresolved chemical MENTIONS {total:,} across {nforms:,}+ distinct forms\n")

    chem_rows, pc_ok, ch_ok, suspect = [], 0, 0, 0
    for s in chem_samp:
        cid, susp = pubchem(s); time.sleep(0.2)
        ch = chebi(s); time.sleep(0.2)
        pc_ok += bool(cid); ch_ok += bool(ch); suspect += bool(cid and susp)
        chem_rows.append({"surface": s, "pubchem_cid": cid,
                          "pubchem_suspect_smiles": bool(cid and susp),
                          "chebi": ch})
    n = len(chem_samp)
    print(f"chemicals: PubChem {pc_ok}/{n}, of which {suspect} are short strings that "
          f"PubChem may have parsed as SMILES; ChEBI {ch_ok}/{n}")

    vb = variant_breakdown(db)
    print(f"\ncoordinate-only variants {vb['coordinate_only_rows']:,}; "
          f"resolvable in principle {vb['pct_resolvable_in_principle']}%")

    rows = db.execute(f"""
        SELECT mentions_raw,
               regexp_extract(concept_id,'{SUBPAT}',1) r,
               regexp_extract(concept_id,'{SUBPAT}',2) p,
               regexp_extract(concept_id,'{SUBPAT}',3) a,
               regexp_extract(concept_id,'CorrespondingGene:([0-9]+)',1) g, count(*) n
        FROM {_read('mutation2pubtator3.gz')}
        WHERE concept_id LIKE 'tmVar:%' AND concept_id LIKE '%CorrespondingGene:%'
          AND regexp_extract(concept_id,'{SUBPAT}',2) <> ''
          AND regexp_extract(concept_id,'{SUBPAT}',1) <> regexp_extract(concept_id,'{SUBPAT}',3)
        GROUP BY 1,2,3,4,5 ORDER BY n DESC LIMIT 3000""").fetchall()
    db.close()

    random.seed(9)
    var_rows, found = [], 0
    for men, r_, p_, a_, g, cnt in random.sample(rows, 10):
        sym = gene_symbol(g); time.sleep(0.34)
        var = f"{r_}{p_}{a_}"
        c = clinvar_count(f"{sym}[gene] AND {var}" if sym else var); time.sleep(0.34)
        found += c > 0
        var_rows.append({"mention": men, "gene": sym, "variant": var, "clinvar_hits": c})
    print(f"variants found in ClinVar: {found}/10")

    out = Path(__file__).resolve().parent / "ontology_probe" / "result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "chemicals": {"unresolved_mentions": total, "sampled": n,
                      "pubchem_hits": pc_ok, "pubchem_suspect_smiles": suspect,
                      "chebi_hits": ch_ok, "rows": chem_rows},
        "variants": {**vb, "clinvar_found": found, "clinvar_sampled": 10,
                     "rows": var_rows}}, indent=2))
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
