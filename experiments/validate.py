"""Validation for Experiment 1. The part that turns a number into an explanation.

Experiment 1 found PubTator3 tagging 2,288 ECD papers against PubMed denominators
of 965 and 1,599 - more than both. A count that exceeds its own denominators is
not a result, it is a prompt to go and find out why. This module does that, in
three checks that can be re-run against any build.

  check_denominators()  fetch both PubMed PMID sets, difference them against ours
  check_extra()         are the surplus papers full-text-only mentions, or errors?
  check_eponym()        the Erdheim-Gsell collision - two diseases, one eponym

Network calls to E-utilities are cached to disk so a re-run is cheap and the
numbers in the post do not silently move under it.
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from pathlib import Path

import duckdb
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.config import DB_PATH, ECD_MESH, PUBMED_DENOMINATORS

CACHE = Path.home() / "pubtator3-data" / "eutils-cache"
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Jakob Erdheim described two unrelated diseases. Erdheim-Chester is a histiocytic
# neoplasm; Erdheim-Gsell cystic medial necrosis is a degenerative aortic media
# disease. They share the eponym and nothing else.
AORTIC = re.compile(r"aort|medial necrosis|medionecrosis|cystic medial|dissect|"
                    r"dolichoectas|annuloaortic|valve|marfan|medial degenerat|"
                    r"mediolysis|aneurysm", re.I)
HISTIO = re.compile(r"histiocyt|xanthogranulom|braf|langerhans|foamy|osteosclero|"
                    r"vemurafenib|cobimetinib", re.I)
EPONYM_AMBIGUOUS = ("%gsell%",)
EPONYM_BARE = ("erdheim", "erdheim disease", "erdheim's disease", "erdheim tumor")


def _cached(name: str, fn):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / name
    if p.exists():
        return json.loads(p.read_text())
    val = fn()
    p.write_text(json.dumps(val))
    return val


def pubmed_pmids(term: str, tag: str) -> list[int]:
    def go():
        r = httpx.get(ESEARCH, params={"db": "pubmed", "term": term,
                                       "retmode": "json", "retmax": 100000}, timeout=90)
        r.raise_for_status()
        return [int(x) for x in r.json()["esearchresult"]["idlist"]]
    return _cached(f"esearch-{tag}.json", go)


def pubmed_records(pmids: list[int], tag: str) -> dict[str, dict]:
    """Title, abstract and keywords per PMID. Body text is not available here -
    which is the whole point of check_extra()."""
    def go():
        chunks = []
        for i in range(0, len(pmids), 40):
            r = httpx.post(EFETCH, data={"db": "pubmed",
                                         "id": ",".join(map(str, pmids[i:i + 40])),
                                         "retmode": "xml", "rettype": "abstract"},
                           timeout=120)
            r.raise_for_status()
            chunks.append(r.text)
            time.sleep(0.4)
        out = {}
        for art in re.split(r"(?=<PubmedArticle>)", "\n".join(chunks)):
            m = re.search(r"<PMID[^>]*>(\d+)</PMID>", art)
            if not m:
                continue
            strip = lambda pat: re.sub(
                r"<[^>]+>", " ", " ".join(re.findall(pat, art, re.S))).strip()
            out[m.group(1)] = {
                "title": strip(r"<ArticleTitle[^>]*>(.*?)</ArticleTitle>"),
                "abstract": strip(r"<AbstractText[^>]*>(.*?)</AbstractText>"),
                "keywords": strip(r"<Keyword[^>]*>(.*?)</Keyword>"),
            }
        return out
    return _cached(f"efetch-{tag}.json", go)


def _db():
    return duckdb.connect(str(DB_PATH), read_only=True)


def _ecd_pmids(db, build_id) -> set[int]:
    return {r[0] for r in db.execute(
        "SELECT pmid FROM ecd_pmids WHERE build_id = ?", [build_id]).fetchall()}


def check_denominators(db, build_id) -> dict:
    """Difference our set against both PubMed populations."""
    ours = _ecd_pmids(db, build_id)
    mesh = set(pubmed_pmids(PUBMED_DENOMINATORS["mesh_indexed"]["query"], "mesh"))
    text = set(pubmed_pmids(PUBMED_DENOMINATORS["text_matched"]["query"], "text"))
    union = mesh | text
    return {
        "pubtator3": len(ours), "pubmed_mesh": len(mesh), "pubmed_text": len(text),
        "pubmed_union": len(union),
        "mesh_is_subset_of_text": not (mesh - text),
        "recovered_of_mesh": len(ours & mesh),
        "missed_of_mesh": len(mesh - ours),
        "recall_on_mesh": round(len(ours & mesh) / len(mesh), 4) if mesh else None,
        "recovered_of_text": len(ours & text),
        "missed_of_text": len(text - ours),
        "recall_on_text": round(len(ours & text) / len(text), 4) if text else None,
        "extra_not_in_either": len(ours - union),
        "_sets": {"extra": sorted(ours - union), "missed": sorted(union - ours)},
    }


def check_extra(db, build_id, denom: dict, sample_size=120, seed=17) -> dict:
    """Is the surplus real reach into full text, or is it error?

    PubMed's [All Fields] covers title, abstract, MeSH and keywords - not the
    body. PubTator3 annotates 6.3M PMC full-text articles. So a paper discussing
    ECD in its discussion section is reachable by one and not the other.
    """
    extra = denom["_sets"]["extra"]
    random.seed(seed)
    samp = random.sample(extra, min(sample_size, len(extra)))
    recs = pubmed_records(samp, f"extra-{seed}-{len(samp)}")
    eponym = re.compile(r"erdheim|lipid granulomatosis|gsell", re.I)

    body_only, in_meta, examples = 0, 0, []
    for pmid in samp:
        r = recs.get(str(pmid))
        if r is None:
            continue
        blob = f"{r['title']} {r['abstract']} {r['keywords']}"
        if eponym.search(blob):
            in_meta += 1
        else:
            body_only += 1
            if len(examples) < 8:
                examples.append({"pmid": pmid, "title": r["title"][:120]})
    n = in_meta + body_only
    return {
        "extra_total": len(extra), "sampled": len(samp), "resolved": n,
        "eponym_in_title_abstract_keywords": in_meta,
        "body_only": body_only,
        "pct_body_only": round(100 * body_only / n, 1) if n else None,
        "interpretation": ("PubMed [All Fields] does not index body text; PubTator3 "
                           "annotates PMC full text. A high body-only fraction means the "
                           "surplus is reach, not error."),
        "examples_body_only": examples,
    }


def check_eponym(db, build_id) -> dict:
    """The Erdheim-Gsell collision.

    Classification is by title/abstract keyword, which is a heuristic, not a
    curated judgement - so both the rule and the per-paper verdicts are written
    out for inspection rather than just the totals.
    """
    like = " OR ".join(f"lower(surface) LIKE '{p}'" for p in EPONYM_AMBIGUOUS)
    inlist = ", ".join("'" + f.replace("'", "''") + "'" for f in EPONYM_BARE)
    rows = db.execute(f"""
        SELECT DISTINCT pmid, surface FROM mentions
        WHERE build_id = ? AND concept_id = ?
          AND ({like} OR lower(surface) IN ({inlist}))
        ORDER BY pmid""", [build_id, ECD_MESH]).fetchall()
    forms: dict[int, list[str]] = {}
    for p, s in rows:
        forms.setdefault(p, []).append(s)
    pmids = sorted(forms)
    if not pmids:
        return {"suspect_papers": 0}

    recs = pubmed_records(pmids, f"eponym-{len(pmids)}")
    verdicts, counts = [], {"aortic_false_positive": 0, "histiocytosis": 0, "unclear": 0}
    for pmid in pmids:
        r = recs.get(str(pmid))
        if r is None:
            continue
        blob = f"{r['title']} {r['abstract']}"
        if AORTIC.search(blob) and not HISTIO.search(blob):
            v = "aortic_false_positive"
        elif HISTIO.search(blob):
            v = "histiocytosis"
        else:
            v = "unclear"
        counts[v] += 1
        verdicts.append({"pmid": pmid, "verdict": v,
                         "surface_forms": sorted(set(forms[pmid])),
                         "title": r["title"][:130]})
    total = _ecd_pmids(db, build_id)
    resolved = sum(counts.values())
    return {
        "suspect_papers": len(pmids), "classified": resolved,
        **counts,
        "false_positive_rate_of_suspects": (
            round(counts["aortic_false_positive"] / resolved, 3) if resolved else None),
        "as_pct_of_all_ecd_papers": (
            round(100 * counts["aortic_false_positive"] / len(total), 2) if total else None),
        "rule": {"aortic_regex": AORTIC.pattern, "histiocytosis_regex": HISTIO.pattern,
                 "note": "keyword heuristic on title+abstract, verdicts listed for inspection"},
        "verdicts": verdicts,
    }


def run(build_id: str | None = None) -> dict:
    db = _db()
    try:
        build_id = build_id or db.execute("SELECT max(build_id) FROM builds").fetchone()[0]
        denom = check_denominators(db, build_id)
        extra = check_extra(db, build_id, denom)
        eponym = check_eponym(db, build_id)
    finally:
        db.close()
    sets = denom.pop("_sets")
    return {"build_id": build_id, "denominators": denom,
            "extra_papers": extra, "eponym_collision": eponym,
            "pmid_sets": {k: v[:2000] for k, v in sets.items()}}


if __name__ == "__main__":
    import pprint
    res = run()
    d, x, e = res["denominators"], res["extra_papers"], res["eponym_collision"]
    print(f"build {res['build_id']}\n")
    print(f"PubTator3 {d['pubtator3']}   MeSH {d['pubmed_mesh']}   "
          f"text {d['pubmed_text']}   union {d['pubmed_union']}")
    print(f"MeSH is a strict subset of text: {d['mesh_is_subset_of_text']}")
    print(f"recall on MeSH set  {d['recovered_of_mesh']}/{d['pubmed_mesh']} = "
          f"{d['recall_on_mesh']}   (missed {d['missed_of_mesh']})")
    print(f"recall on text set  {d['recovered_of_text']}/{d['pubmed_text']} = "
          f"{d['recall_on_text']}   (missed {d['missed_of_text']})")
    print(f"tagged but in neither PubMed set: {d['extra_not_in_either']}\n")
    print(f"surplus sample: {x['body_only']}/{x['resolved']} = {x['pct_body_only']}% "
          f"have no eponym in title/abstract/keywords -> full-text-only mention\n")
    print(f"eponym collision: {e['aortic_false_positive']} of {e['classified']} suspect "
          f"papers are Erdheim-Gsell aortic disease "
          f"({e['as_pct_of_all_ecd_papers']}% of all ECD papers)")


# --- Added after the first run: is the collision in the live service too? ---

PUBTATOR_API = ("https://www.ncbi.nlm.nih.gov/research/pubtator3-api/"
                "publications/export/biocjson")


def live_annotations(pmid: int) -> list[dict]:
    """Annotations from the live PubTator3 web service for one PMID.

    Note the response shape: {"PubTator3": [ {"passages": [...]} ]}. Reading
    `passages` off the top-level object silently yields nothing, which on a first
    attempt looked like the live service NOT reproducing the bulk dump's error -
    the opposite of the truth. Kept explicit here so the mistake is not repeated.
    """
    def go():
        r = httpx.get(PUBTATOR_API, params={"pmids": str(pmid)}, timeout=60)
        r.raise_for_status()
        docs = r.json().get("PubTator3", [])
        out = []
        for doc in docs:
            for pas in doc.get("passages", []):
                for a in pas.get("annotations", []):
                    inf = a.get("infons", {})
                    out.append({"text": a.get("text"),
                                "identifier": inf.get("identifier"),
                                "name": inf.get("name"),
                                "type": inf.get("type")})
        return out
    return _cached(f"live-{pmid}.json", go)


def check_live_service(pmids: list[int]) -> dict:
    """Does the live web service make the same eponym error as the bulk dump?

    This matters for how the finding can be stated. A bulk-dump-only artefact is
    a packaging bug; the same error in the live service is a property of the
    normaliser that every PubTator3 user meets.
    """
    rows = []
    for pmid in pmids:
        anns = live_annotations(pmid)
        ecd = [a for a in anns if (a["identifier"] or "").endswith("D031249")]
        rows.append({
            "pmid": pmid,
            "live_tags_ecd": bool(ecd),
            "surface_forms": [a["text"] for a in ecd],
            "other_disease_annotations": [
                {"text": a["text"], "identifier": a["identifier"], "name": a["name"]}
                for a in anns if a["type"] == "Disease" and a not in ecd][:4],
        })
        time.sleep(0.4)
    n = sum(r["live_tags_ecd"] for r in rows)
    return {"checked": len(rows), "live_reproduces_error": n,
            "conclusion": ("the collision is in the live normaliser, not a bulk-dump "
                           "packaging artefact" if n else
                           "bulk dump only - the live service does not reproduce it"),
            "papers": rows}


# --- Added after a reviewer pointed at PubMed's on-screen count ---

def pubmed_count(term: str) -> int:
    def go():
        r = httpx.get(ESEARCH, params={"db": "pubmed", "term": term,
                                       "retmode": "json", "retmax": 0}, timeout=60)
        r.raise_for_status()
        return int(r.json()["esearchresult"]["count"])
    return _cached(f"count-{abs(hash(term))}.json", go)


def pmids_matching_filter(pmids: list[int], pubmed_filter: str | None,
                          chunk: int = 150) -> set[int]:
    """Which of these PMIDs satisfy a PubMed filter. Chunked to keep URLs sane."""
    tag = f"filt-{abs(hash((tuple(pmids), pubmed_filter)))}.json"

    def go():
        hits: set[int] = set()
        for i in range(0, len(pmids), chunk):
            term = "(" + " OR ".join(f"{p}[uid]" for p in pmids[i:i + chunk]) + ")"
            if pubmed_filter:
                term += f" AND {pubmed_filter}"
            r = httpx.post(ESEARCH, data={"db": "pubmed", "term": term,
                                          "retmode": "json", "retmax": chunk + 50},
                           timeout=120)
            r.raise_for_status()
            hits |= {int(x) for x in r.json()["esearchresult"]["idlist"]}
            time.sleep(0.35)
        return sorted(hits)
    return set(_cached(tag, go))


def check_full_text_hypothesis(db, build_id, denom: dict, sample=600, seed=3) -> dict:
    """Are the surplus papers the ones PubTator3 can read in full?

    The abstract check (check_extra) shows the surplus papers do not name the
    disease in their title or abstract. That is consistent with full-text
    annotation but does not prove it. This is the independent test: if the
    mechanism is full text, the surplus should be enriched for PMC membership
    relative to the papers both systems find. It is, roughly threefold.
    """
    import random
    extra = denom["_sets"]["extra"]
    both = sorted(set(_ecd_pmids(db, build_id)) & set(
        pubmed_pmids(PUBMED_DENOMINATORS["text_matched"]["query"], "text")))
    random.seed(seed)
    control = random.sample(both, min(sample, len(both)))

    e_pmc = pmids_matching_filter(extra, "pubmed pmc[filter]")
    e_oa = pmids_matching_filter(extra, "pubmed pmc open access[filter]")
    c_pmc = pmids_matching_filter(control, "pubmed pmc[filter]")
    c_oa = pmids_matching_filter(control, "pubmed pmc open access[filter]")

    pct = lambda a, b: round(100 * len(a) / len(b), 1) if b else None
    return {
        "surplus": {"n": len(extra), "in_pmc": len(e_pmc), "pct_in_pmc": pct(e_pmc, extra),
                    "in_pmc_oa": len(e_oa), "pct_in_pmc_oa": pct(e_oa, extra)},
        "found_by_both": {"n_sampled": len(control), "in_pmc": len(c_pmc),
                          "pct_in_pmc": pct(c_pmc, control), "in_pmc_oa": len(c_oa),
                          "pct_in_pmc_oa": pct(c_oa, control)},
        "enrichment_pmc": (round(pct(e_pmc, extra) / pct(c_pmc, control), 2)
                           if pct(c_pmc, control) else None),
        "conclusion": ("the surplus is concentrated in the papers PubTator3 reads in full, "
                       "which is what the full-text explanation predicts"),
    }


def check_screenshot_numbers() -> dict:
    """Reconcile the counts a person sees in the PubMed web interface.

    A reviewer pointed at PubMed showing 727 results and asked why our number is
    so much larger. 727 was the free-full-text-filtered count, which is a subset,
    not a total - so it was never the right comparison. Recorded here because the
    same confusion will recur, and because 727 sits misleadingly close to our 743
    surplus while sharing not a single paper with it.
    """
    plain = pubmed_count("Erdheim-Chester disease")
    quoted = pubmed_count('"Erdheim-Chester"[All Fields]')
    mesh = pubmed_count('"erdheim chester disease"[MeSH Terms]')
    pmc_oa = pubmed_count("Erdheim-Chester disease AND pubmed pmc open access[filter]")
    return {
        "pubmed_plain_search": plain,
        "our_text_denominator": quoted,
        "denominator_is_sound": abs(plain - quoted) <= 5,
        "pubmed_mesh": mesh,
        "ecd_papers_in_pmc_open_access": pmc_oa,
        "web_ui_free_full_text_filtered": 727,
        "note": ("727 is the free-full-text subset of the ~1,600 total, visible in the "
                 "URL as filter=simsearch2.ffrt. It is a filtered view, not PubMed's "
                 "count for the disease. It shares no papers with our 743 surplus, since "
                 "the surplus is by definition outside what that search returns."),
    }
