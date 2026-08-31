# PubTator3 → rare disease literature map

Ingests the NCBI **PubTator3** bulk annotation files, scopes them to one disease, and serves the
result as a dashboard and a JSON API.

Worked example: **Erdheim-Chester disease**, a rare histiocytosis usually driven by BRAF V600E.

```
NCBI PubTator3          Check              Read              Select           Serve
5 files, 4.9 GB   ->  size + checksum ->  438M rows     ->  papers naming ->  dashboard
updated monthly       record version      0 unreadable      the disease       + JSON API
                                                                 ^
                                                          NCBI PubMed
                                                          dates, journals
```

## What it found

| | |
|---|---|
| Papers tagged as this disease | **2,288** |
| PubMed, plain name search | 1,600 |
| Recall against the MeSH-indexed set | **98.3%** |

- **743 papers a name search will not return**, because the name is in the body text. 94% of them
  are in PubMed Central, against 39% of the papers both approaches find. But this is a **corpus
  effect, not a method effect** - PMC's own full-text string search returns 2,349, so reading more
  of each paper is the whole of the count difference. What the annotation adds is structure:
  identifiers you can count by gene, drug, year and relation.
- **One systematic error.** Jakob Erdheim described two unrelated conditions. 35 of 40
  ambiguous-eponym papers are Erdheim-**Gsell** aortic disease filed as Erdheim-**Chester**
  histiocytosis — including a Marfan syndrome paper. Reproduced against the live API.
- **The published README's relation vocabulary is wrong.** Two documented types are absent from the
  data; six undocumented ones are present, including `treat` at 18% of all relations.

- **It can say "I don't know" — but never about a disease.** Across 168,305,967 disease mentions,
  **zero** are marked unresolved or ambiguous. Chemicals decline to guess 10,749,370 times (7.31%);
  genes return multiple candidates 310,917 times; 56.6% of variants are raw coordinates never tied
  to dbSNP. The abstain option exists and is used heavily — just not where the names collide.
- **And the right answer was already in the vocabulary.** MeSH has `C536230`, "Cystic medial
  necrosis of aorta", and PubTator3 uses that record 618 times elsewhere in this corpus. So the
  eponym error is a disambiguation failure, not a coverage gap — a second ontology would not have
  prevented it.

Full write-up: **[RESULTS.md](RESULTS.md)**

## Running it

```bash
pip install duckdb httpx fastapi gradio uvicorn pandas plotly

python3 ingest/manifest.py     # HEAD only, downloads nothing
python3 ingest/fetch.py        # ~4.9 GB, resumable, verifies length + checksum
python3 ingest/parse.py 2026-08-17 disease2pubtator3.gz    # run this first
python3 ingest/parse.py 2026-08-17 gene2pubtator3.gz chemical2pubtator3.gz \
                                   mutation2pubtator3.gz relation2pubtator3.gz
python3 ingest/enrich.py       # publication years and journals
python3 experiments/run_all.py # writes experiments/*/result.json
python3 app/main.py            # http://127.0.0.1:7860
```

The disease file must be parsed first — it builds the paper set the others are filtered against.

`ingest/weekly.py` is the scheduled job. It HEADs the source and exits without downloading when
nothing changed; the bulk files are monthly, so an unconditional weekly pull would re-fetch 4.9 GB
three weeks in four.

## Another disease

Change `ECD_MESH` in `ingest/config.py` to another MeSH descriptor, set `PUBMED_DENOMINATORS` from
an E-utilities count, re-run from `parse.py`. Nothing else is disease-specific.

## Design notes

- **Build identity is a manifest, not a date.** The source serves no ETag and no checksum, and each
  month overwrites the same filename. The only version marker is `Last-Modified` at download time,
  so it is recorded per file with a local SHA256. One build's files are written ~96 s apart, so the
  ingest refuses a spread over 24 h rather than mix two builds.
- **Unparseable rows are counted, not skipped** — `store_rejects=true`, never `ignore_errors`. A
  measured zero and an unexamined zero are different claims.
- **`query/` is the only database reader**, shared by the dashboard, the API and the experiments, so
  a figure cannot disagree with a response. Each function returns its data paired with the build it
  came from.
- **No sampling.** The source is not PMID-sorted and skews recent, so a prefix estimate would
  undercount older literature. There is deliberately no `--sample` flag.
- **`quote=''` and `escape=''`** on CSV reads — biomedical surface forms contain double quotes and
  TSV has no quoting convention. DuckDB's defaults mis-split fields silently.
- **Concept labels come from the data**, taking the commonest surface form per identifier, so there
  is no external vocabulary to version.

## Layout

```
ingest/       manifest.py (HEAD gate) · fetch.py · parse.py · enrich.py · weekly.py · schema.sql
query/        the only database reader
app/          FastAPI + Gradio in one process
experiments/  run_all.py · validate.py
```

## Data

PubTator3 is public domain. Wei et.al, *Nucleic Acids Research* 52(W1):W540–W546, 2024. Dates via
NCBI E-utilities.

Not a clinical resource. Counts are of **papers, never patients** — published patient frequencies
for BRAF V600E in this disease range from roughly 10% to 70% depending on cohort and assay era.
