# PubTator3 → Erdheim-Chester disease: a literature map

A reproducible pipeline that ingests the NCBI **PubTator3** bulk annotation files, scopes them to a
single rare disease, and serves the result as a dashboard and a JSON API — with a build stamp that
survives the fact that the source files carry no version number.

Erdheim-Chester disease (ECD) is a rare histiocytosis, usually driven by BRAF V600E, with one
approved targeted therapy. It was chosen because it is small enough to check by hand and hard
enough to be interesting: a hyphenated eponym, a somatic driver, and — as it turned out — a name
collision that breaks automated normalisation.

```
NCBI PubTator3          Check              Read               Select            Serve
5 files, 4.9 GB   ->  size + checksum  ->  438M rows     ->  papers naming  ->  dashboard
updated monthly       record version       0 unreadable      ECD: 2,288         + JSON API
                                                                  ^
                                                          NCBI PubMed
                                                          dates, journals
```

## What it found

Full write-up in [`RESULTS.md`](RESULTS.md). The short version:

| | |
|---|---|
| Papers PubTator3 tags as ECD | **2,288** |
| PubMed, plain name search | 1,600 |
| PubMed, MeSH descriptor only | 965 |
| Recall against the MeSH-indexed set | **98.3%** |

1. **The eponym is handled well.** Unhyphenated, possessive, reversed word order and the
   misspellings *Erdhiem-* and *Edheim-* all normalise correctly.
2. **743 papers a PubMed name search will not return**, because the name is in the body text rather
   than the title or abstract. 94% of them are in PubMed Central, against 39% of the papers both
   approaches find — a 2.4-fold enrichment in exactly the population whose full text is readable.
3. **One systematic error class.** Jakob Erdheim described two unrelated conditions: Erdheim-Chester
   disease, and Erdheim-Gsell cystic medial necrosis (a degenerative aortic disease). 35 of 40
   ambiguous-eponym papers are the aortic disease filed as the histiocytosis — including a Marfan
   syndrome paper. About 1.5% of everything tagged. Reproduced against the live PubTator3 API on
   5 of 6 spot checks, so it is a property of the normaliser, not of the bulk files.
4. **The published README's relation vocabulary is wrong**, not merely incomplete. 12 relation
   types exist; two documented types are absent from the data, and six undocumented ones are
   present — including `treat`, at 7,316,131 rows, 18% of all relations.

## Design decisions worth reading

**Build identity is a manifest, not a date.** The FTP serves no ETag and no checksum (verified:
0 of 5 files), and filenames carry no version — each month overwrites the last under the same name.
The only version marker in existence is the HTTP `Last-Modified` header at download time. It is
recorded per file, alongside a locally computed SHA256. The five files of one build were written
**96 seconds apart**, so a build is a window, not an instant; the ingest refuses to run if the
spread exceeds 24 hours, which would mean catching the source mid-publication and silently mixing
two builds.

**Unparseable rows are counted, not skipped.** `store_rejects=true`, never `ignore_errors=true`.
Across 438,013,195 rows this build reports zero — but a measured zero and an unexamined zero are
different claims, and only one of them is worth making.

**One reader.** `query/` is the only module that touches the database; the dashboard, the API and
the experiments all call it. Built separately they would drift, and a figure disagreeing with an
API response is the failure mode this avoids. Every query function returns its data paired with the
build reference it came from — as a return value, so it cannot be dropped on the way out.

**Two streaming passes per file**, not a staging table: one for global aggregates and reject
capture, one for the disease-scoped slice. Nothing is sampled — the source files are not sorted by
PMID and skew recent, so a cheap prefix estimate would undercount older literature by an unknown
margin. There is deliberately no `--sample` flag.

**Non-default CSV settings that matter:** `quote=''` and `escape=''`, because biomedical surface
forms contain double quotes and TSV has no quoting convention. With DuckDB's defaults the parser
mis-splits fields silently.

**Concept labels come from the data.** A relation ships as `Chemical|MESH:D000077484 --
Disease|MESH:D031249`. The `Mentions` column already holds the surface text a human wrote, so the
most frequent form per concept becomes its label: no external vocabulary to version, and every
label is attested in the ingested corpus.

## Layout

```
ingest/   config.py · manifest.py (HEAD gate) · fetch.py (resumable + sha256)
          parse.py · enrich.py (publication dates) · weekly.py · schema.sql
query/    the only database reader
app/      FastAPI + Gradio in one process
experiments/  run_all.py (the three experiments) · validate.py (the checks behind them)
gold/     gold-standard placeholder — see gold/README.md for why it is empty
```

## Running it

```bash
pip install duckdb httpx fastapi gradio uvicorn pandas plotly

python3 ingest/manifest.py     # HEAD only; writes the manifest, downloads nothing
python3 ingest/fetch.py        # ~4.9 GB, resumable, verifies length and checksum
python3 ingest/parse.py 2026-08-17 disease2pubtator3.gz            # must run first
python3 ingest/parse.py 2026-08-17 gene2pubtator3.gz chemical2pubtator3.gz \
                                   mutation2pubtator3.gz relation2pubtator3.gz
python3 ingest/enrich.py       # publication years and journals
python3 experiments/run_all.py # writes experiments/*/result.json
python3 app/main.py            # http://127.0.0.1:7860
```

Parse order matters: the disease file builds the paper set every other file is filtered against.

`ingest/weekly.py` is the scheduled job — it HEADs the source, compares against the last manifest,
and exits without downloading when nothing has changed. The bulk files are monthly, so an
unconditional weekly download would re-pull 4.9 GB three weeks in four.

## Data and licence

PubTator3 is produced by the NCBI and is public domain. Wei et.al, *Nucleic Acids Research*
52(W1):W540–W546, 2024. Publication dates via NCBI E-utilities.

Nothing here is a clinical resource. Counts are of *papers*, never of patients — the 806 BRAF
figure counts publications, and published patient frequencies for BRAF V600E in ECD range from
roughly 10% to 70% depending on cohort and assay era.
