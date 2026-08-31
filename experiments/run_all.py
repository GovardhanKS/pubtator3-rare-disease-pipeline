"""The three ECD experiments. Each writes result.json, stamped with the build.

The post is written from these files, not from anything retyped by hand. That is
what makes every claim traceable: a number in the post has a build_id attached
to it and a function that produced it.

Nothing here reads the database directly - it all goes through query/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import query

OUT = Path(__file__).resolve().parent


def _write(subdir: str, payload: dict):
    d = OUT / subdir
    d.mkdir(parents=True, exist_ok=True)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    (d / "result.json").write_text(json.dumps(payload, indent=2, default=str))
    return d / "result.json"


def exp1():
    cov = query.coverage()
    forms = query.surface_forms(limit=100)
    d = cov.data
    payload = {
        "experiment": "1 - coverage",
        "question": ("How many ECD papers does PubTator3 tag, against the two "
                     "different PubMed denominators?"),
        "coverage": d,
        "surface_forms": forms.data,
        "build": cov.build.to_dict(),
        "caveat": ("The two denominators measure different things and the gaps are "
                   "reported separately, never summed. 634 papers mention ECD in text "
                   "but carry no ECD MeSH descriptor."),
    }
    p = _write("exp1_coverage", payload)
    print(f"\n=== Experiment 1 - coverage ===")
    print(f"PubTator3 ECD PMIDs      {d['pubtator3_ecd_pmids']:>6}")
    print(f"PubMed MeSH-indexed      {d['pubmed_mesh_indexed']['count']:>6}   "
          f"delta {d['vs_mesh_indexed']['delta']:+}  ratio {d['vs_mesh_indexed']['ratio']}")
    print(f"PubMed text-matched      {d['pubmed_text_matched']['count']:>6}   "
          f"delta {d['vs_text_matched']['delta']:+}  ratio {d['vs_text_matched']['ratio']}")
    print(f"\ntop surface forms ({len(forms.data)} distinct):")
    for r in forms.data[:15]:
        print(f"  {r['n_pmids']:>5} pmids  {r['surface']}")
    print(f"-> {p}")
    return payload


def exp2():
    ec = query.entity_coverage()
    d = ec.data
    payload = {
        "experiment": "2 - entity coverage, two NER systems on one document set",
        "question": ("Across the ECD paper set, what does AIONER find versus what "
                     "tmVar3 finds? Mutation never touches AIONER."),
        "entity_coverage": d,
        "build": ec.build.to_dict(),
    }
    p = _write("exp2_entities", payload)
    print(f"\n=== Experiment 2 - entity coverage ===")
    print(f"ECD papers: {d['ecd_papers']}\n")
    print(f"{'type':<10} {'ner':<8} {'normaliser':<11} {'pmids':>7} {'% papers':>9} {'concepts':>9}")
    for r in d["by_type"]:
        print(f"{r['type']:<10} {r['ner']:<8} {r['normaliser']:<11} "
              f"{r['n_pmids']:>7} {str(r['pct_of_ecd_papers']):>9} {r['n_concepts']:>9}")
    print("\ndriver genes found:")
    for g in d["driver_genes"]:
        print(f"  {g['symbol']:<8} {g['n_pmids']:>5} pmids")
    print(f"-> {p}")
    return payload


def exp3():
    rt = query.relation_types()
    rel = query.ecd_relations()
    payload = {
        "experiment": "3 - relation recovery",
        "question": ("Does PubTator3 recover BRAF-ECD, V600E-ECD and vemurafenib-ECD, "
                     "and how many relation types actually exist in the file?"),
        "relation_types": rt.data,
        "ecd_subgraph": rel.data,
        "build": rt.build.to_dict(),
    }
    p = _write("exp3_relations", payload)
    print(f"\n=== Experiment 3 - relations ===")
    print(f"distinct relation types in file: {rt.data['n_types']}  "
          f"(README says {rt.data['readme_claims']}, NAR 2024 says "
          f"{rt.data['nar_2024_paper_claims']})")
    for r in rt.data["types"]:
        print(f"  {r['n_rows']:>12,}  {r['rel_type']}")
    print(f"\nedges on ECD papers: {rel.data['edges_on_ecd_papers']}   "
          f"naming ECD directly: {rel.data['edges_naming_ecd']}")
    for e in rel.data["ecd_edges"][:18]:
        print(f"  {e['n_pmids']:>4} pmids  {e['rel_type']:<20} "
              f"{e['concept1_label']}  --  {e['concept2_label']}")
    print(f"-> {p}")
    return payload


if __name__ == "__main__":
    which = sys.argv[1:] or ["1", "2", "3"]
    if "1" in which: exp1()
    if "2" in which: exp2()
    if "3" in which: exp3()
