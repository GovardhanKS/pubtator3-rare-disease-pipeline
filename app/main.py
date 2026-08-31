"""Erdheim-Chester disease - a literature map.

Reframed 31 Aug 2026. The first version led with the text-mining system: build
stamps, row counts, which model produced which annotation. That is the wrong
front page. A biologist or clinician opening this wants to know what is known
about the disease; how the page was assembled is a methods note, and it belongs
where methods notes belong.

So: the disease leads, the machinery is in the last tab, and the one place the
extraction method genuinely changes how you should read a number - the eponym
collision - is stated plainly under Data quality rather than buried.

The API is unchanged and still answers from the same query layer as the page.

Run:  python3 app/main.py   ->  http://127.0.0.1:7860
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gradio as gr
import pandas as pd
import plotly.graph_objects as go
from fastapi import FastAPI

import query

app = FastAPI(title="Erdheim-Chester disease - literature map", version="0.2")

INK = "#1f2933"
ACCENT = "#b4472e"
MUTED = "#8a9199"
GRID = "#e4e7eb"


# ---------------------------------------------------------------- API (unchanged)

@app.get("/api/build")
def api_build():
    return query.manifest().to_dict()


@app.get("/api/overview")
def api_overview():
    return query.overview().to_dict()


@app.get("/api/timeline")
def api_timeline():
    return query.timeline().to_dict()


@app.get("/api/genes")
def api_genes(limit: int = 25):
    return query.genes(limit=limit).to_dict()


@app.get("/api/treatments")
def api_treatments(limit: int = 25):
    return query.treatments(limit=limit).to_dict()


@app.get("/api/differential")
def api_differential(limit: int = 25):
    return query.co_mentioned_diseases(limit=limit).to_dict()


@app.get("/api/variants")
def api_variants(limit: int = 20):
    return query.variants(limit=limit).to_dict()


@app.get("/api/coverage")
def api_coverage():
    return query.coverage().to_dict()


@app.get("/api/relations")
def api_relations():
    return query.ecd_relations().to_dict()


# ---------------------------------------------------------------- figures

def timeline_figure() -> go.Figure:
    rows = query.timeline().data
    df = pd.DataFrame(rows)
    # 2026 is a partial year at the time of the data build; excluding it stops
    # the last point reading as a collapse in output.
    df = df[df["year"] <= 2025]
    fig = go.Figure()
    fig.add_bar(x=df["year"], y=df["papers"], name="All papers",
                marker_color="#c6cdd4", hovertemplate="%{x}: %{y} papers<extra></extra>")
    fig.add_scatter(x=df["year"], y=df["braf_papers"], name="Papers mentioning BRAF",
                    mode="lines", line=dict(color=ACCENT, width=2.5),
                    hovertemplate="%{x}: %{y} mention BRAF<extra></extra>")
    for yr, label in ((2010, "BRAF V600E found<br>in histiocytoses"),
                      (2017, "vemurafenib approved<br>for ECD")):
        fig.add_vline(x=yr, line=dict(color=MUTED, width=1, dash="dot"))
        fig.add_annotation(x=yr, y=1.02, yref="paper", text=label, showarrow=False,
                           font=dict(size=10, color=MUTED), yanchor="bottom")
    fig.update_layout(
        height=420, margin=dict(t=64, b=40, l=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(color=INK, size=12),
        legend=dict(orientation="h", y=-0.16, x=0),
        xaxis=dict(title="Year of publication", gridcolor=GRID, dtick=10),
        yaxis=dict(title="Papers", gridcolor=GRID),
        bargap=0.15,
    )
    return fig


def _bar(rows, label_key, value_key, title, n=12) -> go.Figure:
    df = pd.DataFrame(rows[:n]).iloc[::-1]
    fig = go.Figure(go.Bar(
        x=df[value_key], y=df[label_key], orientation="h",
        marker_color=ACCENT, hovertemplate="%{y}: %{x} papers<extra></extra>"))
    fig.update_layout(
        height=40 + 26 * len(df), margin=dict(t=36, b=30, l=10, r=20),
        title=dict(text=title, font=dict(size=13, color=INK)),
        plot_bgcolor="white", paper_bgcolor="white", font=dict(color=INK, size=12),
        xaxis=dict(title="Papers", gridcolor=GRID),
        yaxis=dict(title=None, automargin=True),
    )
    return fig


# ---------------------------------------------------------------- tab content

MARKER = re.compile(r"^(CD\d|S100|Ki-?67|langerin|factor XIII)", re.I)


def genes_table() -> pd.DataFrame:
    rows = query.genes(limit=30).data
    out = []
    for r in rows:
        role = ("recurrent driver" if r["known_driver"]
                else "diagnostic marker" if MARKER.match(str(r["gene"]))
                else "")
        out.append({"Gene / protein": r["gene"], "Papers": r["papers"], "Role": role})
    return pd.DataFrame(out)


def variants_table() -> pd.DataFrame:
    return pd.DataFrame([{"Variant": r["variant"], "Papers": r["papers"]}
                         for r in query.variants(limit=15).data])


def treatments_table() -> pd.DataFrame:
    return pd.DataFrame([{"Drug": r["drug_name"], "Papers stating it treats ECD": r["papers"]}
                         for r in query.treatments(limit=20).data])


def differential_table() -> pd.DataFrame:
    return pd.DataFrame([{"Condition also discussed": r["condition"], "Papers": r["papers"]}
                         for r in query.co_mentioned_diseases(limit=25).data])


def overview_text() -> str:
    o = query.overview().data
    return f"""
## Erdheim-Chester disease

A rare histiocytosis: the body accumulates abnormal foamy histiocytes in bone, around the
kidneys and aorta, in the central nervous system and elsewhere. Most cases carry an acquired
mutation in the **MAPK pathway** — usually **BRAF V600E** — which is what made it treatable.
**Vemurafenib**, a BRAF inhibitor, was approved for it in November 2017.

This page maps what the published literature says about it: **{o['papers']:,} papers**
from **{o['first_year']} to {o['last_year']}**, across **{o['journals']:,} journals**.

|  |  |
|---|---|
| Papers on the disease | **{o['papers']:,}** |
| Published since 2015 | **{o['since_2015']:,}** ({o['pct_since_2015']}%) |
| Mentioning BRAF | **{o['braf_papers']:,}** |
| Mentioning any gene | **{o['papers_with_any_gene']:,}** |

Seven in ten papers on this disease were published in the last decade. The chart below shows why.
"""


TIMELINE_NOTE = """
For fifty years this was a disease described one case at a time — four papers in the whole of the
1950s. Then BRAF V600E was identified in histiocytic disorders around 2010, and a disease that had
no molecular handle acquired one. The red line is papers mentioning BRAF: flat at zero for the
first five decades, then tracking the whole field.

2026 is left off the chart because the underlying data was assembled in August 2026 and a partial
year would read as a collapse in output rather than an incomplete count.
"""

MOLECULAR_NOTE = """
Two different kinds of thing appear in this list, and it is worth separating them.

**Recurrent drivers** are the mutated genes that cause the disease — BRAF far ahead of everything,
then MAP2K1, KRAS, NRAS, PIK3CA, ARAF. All sit in or beside the MAPK pathway.

**Diagnostic markers** — CD68, CD1a, S100, CD163, CD207 — are not drivers at all. They are the
immunostains a pathologist uses to tell one histiocytosis from another, so they appear constantly
in the literature for reasons of diagnosis rather than cause. CD1a and CD207 in particular are
usually cited to say what the cells are *not*: those two mark Langerhans cells, and
Erdheim-Chester histiocytes are typically negative for them.

A single list ranked by paper count cannot tell these apart, which is why the column is there.
"""

TREATMENT_NOTE = """
Each row means *some paper states this drug treats this disease*. That is not the same as approved,
and not the same as effective — an early case report of a failed therapy counts here too. The
ranking is how often the literature says it, nothing more.

Read that way the list is informative: **vemurafenib** leads, which matches it being the one
approved targeted therapy. **dabrafenib**, **cobimetinib** and **trametinib** are the other
MAPK-pathway inhibitors. **cladribine**, **cytarabine**, **methotrexate** and
**cyclophosphamide** are the older cytotoxic approaches, and **steroids** and **prednisolone**
the non-specific ones.

One row is simply wrong: **FDG** is a radiotracer used in PET imaging, not a treatment. It appears
because the sentences it occurs in look grammatically like treatment statements. Seven papers'
worth of noise in a list of twenty is a fair illustration of the error rate to expect.
"""

DIFFERENTIAL_NOTE = """
What else these papers talk about, which is largely the differential diagnosis. The three
conditions a clinician has to distinguish from Erdheim-Chester — **Langerhans cell histiocytosis**,
**non-Langerhans cell histiocytosis** and **Rosai-Dorfman disease** — come out at the top on their
own, without anyone specifying them.

Generic words like "tumor", "inflammatory" and "disease" rank high too. They are not useful, and
they are not errors either: they are what medical writing is made of.
"""

QUALITY_NOTE = """
## How to read these numbers

Everything on this page was extracted automatically from published text — 36 million abstracts
and 6.3 million full-text papers — rather than curated by hand. That buys coverage and costs
precision. Two consequences are worth knowing before you use any figure here.

### 1. Some of these papers are about a different disease

**Jakob Erdheim described two unrelated conditions.** One is Erdheim-Chester disease. The other is
**Erdheim-Gsell cystic medial necrosis**, a degenerative disease of the aortic wall. They share a
surname and nothing else — different organ, different cell, different treatment.

The extraction confuses them. Of 40 papers whose only evidence is an ambiguous form of the name
(*Erdheim-Gsell*, *Gsell-Erdheim syndrome*, *Erdheim's disease*, or a bare *Erdheim*), **35 are
about the aortic disease** and have been labelled as this histiocytosis. That is **about 1.5% of
the papers on this page**. Examples:

- *Cystic medionecrosis of the aorta (Gsell-Erdheim syndrome)*
- *Aortic rupture in idiopathic Gsell-Erdheim medionecrosis*
- *Aortic lesion in Marfan syndrome: the ultrastructure of cystic medial degeneration*

A **Marfan syndrome** paper is filed here as a rare histiocytosis.

The rate is low. What matters is the shape of the mistake: **the system never signalled that it was
unsure.** It did not flag *Erdheim's disease* as ambiguous and set it aside — it resolved it
confidently to the wrong condition. More data does not fix that, because the ambiguity is in the
name, not in the volume.

### 2. Being found is not the same as being about

A PubMed search for **Erdheim-Chester disease** returns about **1,600** papers. This page has
**2,288**. The difference is **743 papers PubMed's search for the name does not return** — and the
reason is where each system looks.

PubMed's text search reads titles, abstracts and keywords. It does not read the body of a paper.
The annotations behind this page cover the full text of papers held in PubMed Central. So a paper
that names this disease once in its discussion, or in a list of differential diagnoses, is
invisible to one and visible to the other.

Two separate checks say that is what is happening:

- In a sample of 120 of those 743 papers, **94% never mention the disease in their title, abstract
  or keywords** at all.
- **94% of them are in PubMed Central**, against **39%** of the papers both approaches find — the
  surplus is concentrated, about 2.4-fold, in exactly the papers whose full text can be read.

So the extra reach is real. But a single line in a differential list is still a single line: these
743 papers are *reachable*, and how substantively they discuss the disease has not been assessed.

**One caution when comparing against PubMed yourself.** PubMed's result count changes with the
filters applied, and the filter is easy to miss. Searching the disease name with *Free full text*
switched on returns **727** — not a total, but a subset of the ~1,600. It happens to sit close to
the 743 above, and the two have no papers in common.

### What is not claimed here

- No accuracy or completeness figure against a curated gold standard.
- **No statement about how often BRAF V600E occurs in patients.** The 806 figure counts *papers*,
  not people. Published patient frequencies range from roughly 10% to 70% depending on cohort size
  and assay era, and treating a literature count as a clinical rate would be exactly the error
  this section is about.
"""


WORKFLOW_SVG = """
<svg viewBox="0 0 880 210" width="100%" style="max-width:880px;color:#1f2933;
     font-family:system-ui,-apple-system,Segoe UI,sans-serif" role="img"
     aria-label="Five-step workflow from NCBI source files to this page">
  <defs>
    <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="currentColor" opacity="0.55"/>
    </marker>
  </defs>
  <g stroke="currentColor" fill="none" stroke-width="1.2" opacity="0.45">
    <rect x="0"   y="24" width="150" height="66" rx="6"/>
    <rect x="182" y="24" width="150" height="66" rx="6"/>
    <rect x="364" y="24" width="150" height="66" rx="6"/>
    <rect x="546" y="24" width="150" height="66" rx="6"/>
    <rect x="728" y="24" width="150" height="66" rx="6"/>
    <rect x="546" y="140" width="150" height="52" rx="6" stroke-dasharray="4 3"/>
  </g>
  <g stroke="currentColor" stroke-width="1.2" marker-end="url(#ar)" opacity="0.55">
    <line x1="152" y1="57" x2="178" y2="57"/>
    <line x1="334" y1="57" x2="360" y2="57"/>
    <line x1="516" y1="57" x2="542" y2="57"/>
    <line x1="698" y1="57" x2="724" y2="57"/>
    <path d="M696,166 L790,166 L790,94" fill="none"/>
  </g>
  <g fill="currentColor" font-size="12.5" text-anchor="middle">
    <text x="75"  y="47" font-weight="600">NCBI PubTator3</text>
    <text x="267" y="47" font-weight="600">Check</text>
    <text x="439" y="47" font-weight="600">Read</text>
    <text x="621" y="47" font-weight="600">Select</text>
    <text x="803" y="47" font-weight="600">This page</text>
    <text x="621" y="161" font-weight="600">NCBI PubMed</text>
  </g>
  <g fill="currentColor" font-size="11" text-anchor="middle" opacity="0.72">
    <text x="75"  y="65">5 files, 4.9 GB</text>
    <text x="75"  y="80">updated monthly</text>
    <text x="267" y="65">size + checksum</text>
    <text x="267" y="80">record the version</text>
    <text x="439" y="65">438 million rows</text>
    <text x="439" y="80">0 unreadable</text>
    <text x="621" y="65">papers naming this</text>
    <text x="621" y="80">disease: 2,288</text>
    <text x="803" y="65">counts, charts</text>
    <text x="803" y="80">and an API</text>
    <text x="621" y="179">dates and journals</text>
  </g>
</svg>
"""


def provenance_text() -> str:
    m = query.manifest()
    b = m.build
    return f"""
## How this page was built

Data build **`{b.build_id}`**. The source files are public domain and carry no version number —
each month's file overwrites the last under the same name — so the download timestamp is recorded
per file, with a checksum computed locally. Publication dates come from NCBI PubMed; everything
else comes from the files below.
"""


def sources_note() -> str:
    return """
Source: **PubTator3**, NCBI — Wei et.al, *Nucleic Acids Research* 52(W1):W540–W546, 2024.
Dates and journals: NCBI E-utilities.

Names are matched to standard identifiers — MeSH for diseases, NCBI Gene for genes — which is what
lets *Erdheim Chester disease*, *Erdheim-Chester's disease* and *ECD* count as one thing.
Relationships between them are extracted separately. See **Data quality** for where this goes wrong.

Every figure here is also available as JSON: `/api/overview`, `/api/timeline`, `/api/genes`,
`/api/treatments`, `/api/differential`, `/api/build`. Each response carries the data build it came
from.
"""


def build_table() -> pd.DataFrame:
    b = query.manifest().build
    return pd.DataFrame([{
        "Source file": f["filename"],
        "Published": str(f["last_modified"])[:16],
        "Size (MB)": round((f["content_length"] or 0) / 2**20, 1),
        "Rows read": f"{f['rows_parsed']:,}" if f["rows_parsed"] else "-",
        "Unreadable rows": f["rows_rejected"] if f["rows_rejected"] is not None else "-",
        "Checksum": (f["sha256"] or "")[:12],
    } for f in b.files])


CSS = """
.gradio-container {max-width: 1080px !important; margin: 0 auto !important;}
footer {display:none !important;}
"""


def dashboard() -> gr.Blocks:
    o = query.overview().data
    # Gradio 6 moved theme/css off the Blocks constructor. We mount onto FastAPI
    # rather than calling launch(), so they are passed to mount_gradio_app below.
    with gr.Blocks(title="Erdheim-Chester disease - literature map") as demo:
        gr.Markdown(f"# Erdheim-Chester disease\n### What {o['papers']:,} papers say, "
                    f"{o['first_year']}–{o['last_year']}")

        with gr.Tab("Overview"):
            gr.Markdown(overview_text())
            gr.Plot(timeline_figure())
            gr.Markdown(TIMELINE_NOTE)

        with gr.Tab("Genes and mutations"):
            gr.Markdown("## Genes and proteins in the ECD literature")
            gr.Plot(_bar(query.genes(limit=14).data, "gene", "papers",
                         "Most-discussed genes and proteins"))
            gr.Dataframe(genes_table(), wrap=True)
            gr.Markdown(MOLECULAR_NOTE)
            gr.Markdown("## Specific mutations reported")
            gr.Dataframe(variants_table(), wrap=True)
            gr.Markdown(
                "**V600E** dominates, as expected. **V600K** and **V600D** are the other "
                "positions-600 substitutions, and **G469A** is a BRAF mutation outside codon 600. "
                "Some entries — *T790M*, *G12C* — belong to other cancers entirely and appear "
                "because these papers discuss targeted therapy across tumour types.")

        with gr.Tab("Treatments"):
            gr.Markdown("## Drugs the literature links to this disease")
            gr.Plot(_bar(query.treatments(limit=12).data, "drug_name", "papers",
                         "Most-reported treatments"))
            gr.Dataframe(treatments_table(), wrap=True)
            gr.Markdown(TREATMENT_NOTE)

        with gr.Tab("Differential"):
            gr.Markdown("## What else these papers discuss")
            gr.Dataframe(differential_table(), wrap=True)
            gr.Markdown(DIFFERENTIAL_NOTE)

        with gr.Tab("Data quality"):
            gr.Markdown(QUALITY_NOTE)

        with gr.Tab("Source and methods"):
            gr.Markdown(provenance_text())
            gr.HTML(WORKFLOW_SVG)
            gr.Dataframe(build_table(), wrap=True)
            gr.Markdown(sources_note())
    return demo


app = gr.mount_gradio_app(app, dashboard(), path="/",
                          theme=gr.themes.Soft(), css=CSS)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7860)
