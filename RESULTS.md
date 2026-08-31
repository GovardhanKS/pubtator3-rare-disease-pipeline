# Results - PubTator3 on Erdheim-Chester disease

**Data build `2026-08-17`. Measured 31 August 2026. Every number below comes from
`experiments/*/result.json` or `experiments/validate.py`, not from prose.**

The working hypothesis going in was recall loss on a hyphenated eponym. That is not what happened,
and five of the findings below contradict an expectation held before the ingest ran.

---

## 1. The eponym is not the problem. PubTator3 is very good at it.

| Population | Count |
|---|---|
| PubTator3, tagged `MESH:D031249` | **2,288** |
| PubMed `"Erdheim-Chester"[All Fields]` | 1,599 |
| PubMed `"erdheim chester disease"[MeSH Terms]` | 965 |

- The MeSH set is a **strict subset** of the text set (`mesh - text` is empty), so the
  union is 1,599 and there was never a third population to reconcile.
- **Recall on the MeSH-indexed set: 949/965 = 98.3%.**
- **Recall on the text-matched set: 1,545/1,599 = 96.6%.**

The prediction in the project scope notes - "the gap between those two numbers is recall loss
on a hyphenated eponym" - was wrong in its direction. PubTator3 does not lose the eponym. It
handles orthographic variation well: `Erdheim Chester disease` (unhyphenated), `Erdheim-chester
disease` (case), `Erdheim-Chester's disease` (possessive), `Chester-Erdheim disease` (reversed),
and the misspellings `Erdhiem-Chester` and `Edheim-Chester` all normalise to the same MeSH ID.

**The count exceeding both denominators is the finding, and a count that exceeds its own
denominator is a prompt to investigate, not a result to report.** Findings 2 and 3 are that
investigation.

## 2. 743 papers are tagged that neither PubMed query returns - and 94% are full-text-only.

Sampled 120 of the 743 and fetched their PubMed records: **113 of 120 (94.2%) have no ECD eponym
anywhere in title, abstract or keywords.**

The mechanism is not subtle once stated: PubMed's `[All Fields]` does not index body text.
PubTator3 annotates the PMC Open Access Subset and Author Manuscript Collection - 6.3 million
full-text articles. A paper that discusses ECD in its differential diagnosis or its discussion
section is reachable by one system and invisible to the other.

Body-only examples, all genuinely ECD-relevant:

- 35413124 — *Tissue-Agnostic Activity of BRAF plus MEK Inhibitor in BRAF V600-Mutant Tumors*
- 28532436 — *Vinblastine chemotherapy in adult patients with Langerhans cell histiocytosis*
- 32889387 — *Rate of change in investigational treatment options: a large precision oncology dataset*
- 31388788 — *Primary myelofibrosis: spectrum of imaging features*

### Independently confirmed via PMC membership

The abstract check is consistent with full-text annotation but does not prove it. The direct test:
if the mechanism is full text, the surplus should be enriched for PMC membership against the papers
both systems find.

| | In PMC | In PMC open access |
|---|---|---|
| The 743 surplus papers | **94.3%** | **82.1%** |
| Papers both find (600 sampled) | 39.3% | 29.0% |

**A 2.4-fold enrichment.** The surplus is concentrated in precisely the papers whose full text is
readable. Two independent measures - absence of the eponym from the abstract, and PMC membership -
both land at 94%.

### The control that says how much of this is the annotation, and how much is the corpus

Both checks above establish that the surplus comes from body text. Neither establishes that
*entity recognition* is what reached it - and the obvious control had not been run.

**PubMed Central's own full-text search for `"Erdheim-Chester"` returns 2,349.** A plain string
match over full text reaches at least as many papers as the annotation does, over a smaller corpus.

So the count difference is a **corpus effect, not a method effect.** Reading more of each paper is
the whole of it. This is the opposite of the "recall loss" the plan expected, and it is a real
gain in reachable literature - but it is not evidence that entity recognition finds papers a
search cannot.

What entity recognition adds is not more papers. It is that every mention carries a standing
identifier, so the corpus can be counted by gene, by drug, by year and by relation. A string
search returns documents; this returns a table. Findings 6 and 7 are made of that, and no string
search produces them.

It also adds an error class a string search cannot have - finding 3.

### Reconciling PubMed's on-screen count - a trap worth documenting

A reviewer pointed at PubMed reporting **727** results and asked why ours is so much larger. 727 is
the **free-full-text-filtered** subset - visible in the URL as `filter=simsearch2.ffrt` and in the
green "Filters applied" banner - not PubMed's count for the disease.

Checked directly: PubMed's plain search for `Erdheim-Chester disease` returns **1,600**, against the
**1,599** we used as the text denominator. **The denominator was sound.** Also worth knowing: only
**421** papers *about* ECD are in PMC open access, which is a different population again from the
surplus.

**727 sits misleadingly close to our 743 and shares not one paper with it** - the surplus is by
definition outside what that search returns. Recorded because the same confusion will recur, and
because two near-identical numbers meaning unrelated things is exactly how a wrong sentence gets
into a post. Reproducible via `validate.py::check_screenshot_numbers`.

**Caveat to carry forward:** "reachable" is not "relevant". A body-only mention may be one
line in a differential list. The 743 have not been assessed for how substantively they discuss
ECD, and that should not be implied.

## 3. The one real error class: two diseases, one pathologist.

Jakob Erdheim described **Erdheim-Chester disease** (a histiocytic neoplasm) and
**Erdheim-Gsell cystic medial necrosis** (a degenerative disease of the aortic media). They share
the eponym and nothing else - different organ, different cell type, different century of
treatment.

Of 40 papers whose ECD evidence rests on an ambiguous form (`Erdheim-Gsell`, `Gsell-Erdheim
syndrome`, `Erdheim's disease`, bare `Erdheim`), **35 are aortic disease normalised to
`MESH:D031249`**. That is **1.53% of all 2,288 tagged papers**.

Unmistakable examples:

- 5091176 — *[Cystic medionecrosis of the aorta (Gsell-Erdheim syndrome)]*
- 11218568 — *[Aortic rupture in idiopathic Gsell-Erdheim medionecrosis]*
- 7638887 — *[Erdheim's disease as a cause of sudden death]*
- 35896809 — *Familial acute aortic dissection associated with a novel ACTA2 germline variant*
- 576392 — *Aortic lesion in Marfan syndrome: the ultrastructure of cystic medial degeneration*

A **Marfan syndrome** paper is tagged as a rare histiocytosis.

**Why the shape matters more than the rate.** 1.53% is a low error rate and the system is
right to be judged on the whole. What matters is the *shape* of the error: the normaliser was
never uncertain. It did not flag `Erdheim's disease` as ambiguous and defer; it resolved it
confidently to the wrong concept. Scale does not fix this - every additional aortic paper
containing the word "Erdheim" is one more false positive, because the ambiguity is in the
vocabulary, not in the volume.


### It is in the live service, not just the bulk dump

This distinction decides how the finding can be stated, so it was checked rather than assumed.
Queried the PubTator3 web API directly for six of the aortic papers: **5 of 6 reproduce the error
live.**

```
PMID 5091176   "Gsell-Erdheim syndrome"     -> MESH:D031249  Erdheim-Chester Disease
PMID 11218568  "Gsell-Erdheim medionecrosis" -> MESH:D031249  Erdheim-Chester Disease
PMID 14964967  "Gsell-Erdheim syndrome"     -> MESH:D031249  Erdheim-Chester Disease
PMID 7638887   "Erdheim's disease"          -> MESH:D031249  Erdheim-Chester Disease
PMID 576392    "Erdheim"                    -> MESH:D031249  Erdheim-Chester Disease
PMID 35896809   not reproduced live
```

So this is a property of the normaliser that every PubTator3 user meets, not an artefact of how the
bulk files are packaged. One of the six does not reproduce, and the honest statement is 5 of 6 -
the bulk dump and the live service are not perfectly identical.

**A second error in the same title.** On PMID 5091176 the live service also maps *"Cystic
medionecrosis of the aorta"* to `MESH:D018297`, **"Neoplasms Cystic Mucinous and Serous"**. Both
disease annotations in that one title are wrong, and neither is flagged as uncertain. On PMID
576392 it tags both `Marfan Syndrome` (correct) and `Erdheim-Chester Disease` (from the bare
surname) on the same paper.

**Method caveat:** classification of the 40 is a keyword heuristic on title and abstract (aortic
terms present, histiocytosis terms absent), not curated adjudication. The rule and all 40 per-paper
verdicts are written to `exp1_coverage/result.json` for inspection. 5 of 40 are "unclear" and are
not counted as errors. The live-service check covers 6 papers, not all 35 - it establishes the
error is in the normaliser, it does not re-measure the rate.

## 4. The README's relation vocabulary is wrong, not merely incomplete.

the build plan framed this as 8 (README) versus 12 (2024 NAR paper). The file says **12**, so the
paper is right on the count - but the disagreement is deeper than a number:

| README says | In the file as |
|---|---|
| `Association` | `associate` |
| `Positive_Correlation` | `positive_correlate` |
| `Negative_Correlation` | `negative_correlate` |
| `Co-treatment` | `cotreat` |
| `Drug_interaction` | `drug_interact` |
| `Comparison` | `compare` |
| `Conversion` | **absent** |
| `Binding` | **absent** |

And six types in the file appear nowhere in the README: **`treat`, `cause`, `inhibit`,
`stimulate`, `prevent`, `interact`**.

`treat` is the **second most common relation type in the entire corpus at 7,316,131 rows** — 18%
of all 40,094,383 relations. It is not a rare edge case the documentation reasonably omitted.

Anyone who coded against the README's eight capitalised names would match zero rows. The README is
dated 2023-09-09; the data is from 2026-08-17.

## 5. The bulk FTP offers no way to identify what you downloaded.

Verified by HEAD across all five files: **0 of 5 serve an ETag.** No checksum file is published.
Filenames carry no version. Every month the same name is overwritten.

So the only version marker in existence is the HTTP `Last-Modified` header at the moment of
fetching, and if it is not recorded then, the identity of the data is unrecoverable afterwards.
This project records it per file, plus a SHA256 we compute ourselves, and stamps it on every API
response and dashboard page.

Also: the five files of one build were written over a **96-second window** (13:41:35-13:43:11), so
a build is not a timestamp. Fetching across a publish boundary would silently mix two builds. The
ingest refuses when the spread exceeds 24 hours.

## 6. Two NER systems on one document set, measured cleanly.

Mutation is the only entity type that never passes through AIONER - it is tmVar3 end to end. So
one document set gives a direct comparison across four pipelines:

| Entity | NER | Normaliser | ECD papers | % of 2,288 | Distinct concepts |
|---|---|---|---|---|---|
| Disease | AIONER | TaggerOne | 2,288 | 100.0 | 4,160 |
| Chemical | AIONER | NLM-Chem | 1,508 | 65.9 | 2,293 |
| Gene | AIONER | GNorm2 | 1,367 | 59.7 | 3,175 |
| **Mutation** | **tmVar3** | **tmVar3** | **784** | **34.3** | 1,350 |

**Read this carefully, because the obvious reading is wrong.** Mutation coverage being lowest is
not evidence that tmVar3 is the weaker system. Not every ECD paper reports a variant - a case
report may name the disease and no mutation at all - so the denominators differ in what they could
possibly find. What the table establishes is that the *coverage profile* differs sharply by
pipeline, not that one pipeline is worse.

One structural observation that is safe: corpus-wide, `mutation2pubtator3.gz` holds 4,847,770
distinct concepts across 8,135,311 rows - nearly 60% of all mutation annotations are a unique
identifier. Variants are inherently high-cardinality in a way diseases (12,841 concepts across 168
million rows) are not, and that is a normalisation problem of a different kind rather than a
harder version of the same one.

## 7. Relation extraction succeeds on the easy case, and the recovered graph is the right one.

Per the project scope notes, ECD is close to the easiest possible case for relation extraction:
one dominant driver gene, one approved targeted drug. It passes cleanly. Concept labels below are
resolved from the `Mentions` column of our own ingest - no external vocabulary was consulted.

| Relation | Papers |
|---|---|
| vemurafenib **treat** ECD | 83 |
| cladribine **treat** ECD | 28 |
| steroids **treat** ECD | 21 |
| dabrafenib **treat** ECD | 18 |
| cobimetinib **treat** ECD | 17 |
| prednisolone **treat** ECD | 11 |
| ECD **associate** BRAF | 242 |
| ECD **associate** BRAF p.V600E | 127 |
| ECD **cause** BRAF p.V600E | 54 |
| ECD **associate** CD68 | 42 |
| ECD **associate** MEK | 25 |
| ECD **associate** MAP2K1 | 21 |
| ECD **associate** ERK | 13 |
| ECD **associate** IL-1 | 12 |
| ECD **associate** CD1a | 11 |
| FDG **associate** ECD | 25 |

The top edges are the MAPK pathway (BRAF, V600E, MAP2K1, MEK, ERK), the histiocyte markers
(CD68, CD1a), the actual therapeutic repertoire including the FDA-approved drug at the top of the
treatment list, IL-1 (the anakinra target), and FDG for PET staging. There is nothing spurious in
the top 20. 180 of 2,808 edges on ECD papers name ECD directly.

**Because this is the easy case, success here says little about the hard cases**, and should not be
generalised from. The interesting tension is that findings 3 and 7 sit together: on the well-described entity with a curated MeSH identifier the system is excellent, and
on the ambiguous eponym it is confidently wrong.

Note that only 1,367 of 2,288 ECD papers (59.7%) carry any gene annotation at all.

---

## Corpus-level counts, build 2026-08-17

| File | Rows | Distinct PMIDs | Distinct concepts | Rejected |
|---|---|---|---|---|
| `disease2pubtator3.gz` | 168,305,967 | 26,440,394 | 12,841 | 0 |
| `gene2pubtator3.gz` | 74,519,899 | 9,536,834 | 6,743,674 | 0 |
| `relation2pubtator3.gz` | 40,094,383 | 10,136,751 | 12 types | 0 |
| `chemical2pubtator3.gz` | 146,957,635 | 21,650,543 | 169,318 | 0 |
| `mutation2pubtator3.gz` | 8,135,311 | 1,414,337 | 4,847,770 | 0 |
| **total** | **438,013,195** | | | **0** |

**Zero rejected rows across 438 million parsed.** The rejects mechanism was built to report
malformed rows rather than skip them; on this build it reports none. A measured zero is worth
more than not having looked, and the mechanism has to exist before the number means anything.

---


## 8. How it handles ambiguity, and the record it did not use

The question underneath every finding above: what does this system do when it cannot decide? The
output format has two ways of saying so, neither of them documented.

| Entity | Mentions labelled | Could not place (`-`) | Two or more candidates |
|---|---|---|---|
| Diseases | 168,305,967 | **0** (0.00%) | **0** |
| Chemicals | 146,957,635 | **10,749,370** (7.31%) | 0 |
| Genes | 74,519,899 | 0 (0.00%) | 310,917 (0.42%) |
| Mutations | 8,135,311 | 0 (0.00%) | 0 |

**The ability to abstain exists and is used heavily - just never for diseases.** Chemicals decline
to guess 10.7 million times: `Ca2+` (58,260), `cAMP` (25,434), `O2` (20,763), `ROS` (14,978),
`PM2.5` (8,593), and `ketamine` 12,039 times, which is a surprise for a well-catalogued drug. Genes
never abstain but hand back multiple candidates 310,917 times - `6900;1491938` for *Tax*, a viral
gene name matching several records. Mutations are a third case again: 43.3% (3,522,742) carry a
dbSNP identifier, **56.6% (4,602,248) are raw coordinates only**, never tied to a catalogued variant.

Diseases return exactly one answer, every time, across 168 million mentions.

### The record that was available and not used

The obvious remedy for finding 3 is a richer reference vocabulary. That is not the problem here.

**MeSH already contains `C536230`, "Cystic medial necrosis of aorta"** - the correct concept for the
aortic disease. MeSH's own term search for *Erdheim-Gsell* returns both it and `D031249`. And
PubTator3 is not restricted to MeSH main descriptors: disease annotations use supplementary
C-records **7,840,325 times** (4.66% of all disease rows), including **`MESH:C536230` itself, 618
times** elsewhere in this same corpus.

So the right answer was in the vocabulary, in active use, and was not chosen. **This is a
disambiguation failure, not a coverage gap, and adding another ontology would not have prevented
it.**

Where a second reference *would* help is elsewhere, and the numbers say where: the 10.7 million
unresolved chemicals are largely ions, radicals and particulates that MeSH covers thinly and
ChEBI or PubChem cover well; the 4.6 million coordinate-only variants are what dbSNP and ClinVar
exist to ground. Those are harmonisation problems. The eponym is not.

---

## What is not established

- **No precision or recall against a curated gold standard.** `gold/ecd-genes.tsv` is deliberately
  empty; findings 1-7 are coverage and agreement measures, which need no gold standard.
- **No claim about how often BRAF V600E occurs in patients.** The 806 figure counts *papers*.
  Published patient frequencies range from roughly 10% to 70% depending on cohort size and assay
  era, and treating a literature count as a clinical rate would be the exact error finding 3 is about.
- **No claim that the 743 surplus papers discuss ECD substantively.** Reachability was measured;
  relevance was not.
- **The eponym error rate is a heuristic bound on 40 suspect papers**, not a corpus-wide precision
  audit. It names and sizes one error class; it does not measure PubTator3 overall.
