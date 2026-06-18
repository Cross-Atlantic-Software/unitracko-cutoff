# 🎓 Indian Admission Cutoff Aggregator

A **Python-only** tool that catalogs Indian entrance exams and serves their
admission cutoffs (opening/closing ranks by college, branch, category, year)
through an interactive Streamlit + DuckDB UI — inspired by
[coladex.in](https://coladex.in).

It works on two decoupled layers:

| Layer | Question it answers | Source | Size |
|-------|---------------------|--------|------|
| **Breadth — Catalog** | *What exams exist, who runs them, where do their cutoffs live?* | `cutoffexamsheet.xlsx` + `EXAMlinkssheet.xlsx` → classified + enriched + official-link-verified + cutoff status & aggregator fallbacks | **317 exams**, 25 categories, 36 states/UTs |
| **Depth — Cutoffs** | *What are the actual opening/closing ranks?* | real PDF-parsed data + curated snapshots | **~12,900 rows / ~500 colleges**, 10 bodies |

```
adapters / scrapers ─▶ normalize ─▶ Parquet ─┐
                                              ├─▶ Streamlit + DuckDB ─▶ filter / predict instantly
exam sheet ─▶ classify + enrich ─▶ Parquet ───┘
```

No always-on server in the data path; everything reads Parquet.

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r requirements.txt
streamlit run app.py                                # http://localhost:8501
```

The app has three tabs:

1. **🧭 Explore Exams** — browse all 317 catalogued exams; filter by
   category / level / state, search by name, open homepage & cutoff pages, and
   see each source's live **scrapeability** status.
2. **📊 Cutoff Explorer & Rank Predictor** — filter real opening/closing ranks,
   enter your rank to see seats within reach, and view multi-year closing-rank
   trends.
3. **🔄 Refresh / Scrape** — regenerate the dataset from adapters (cached or
   live) or point the generic scraper at any catalogued source.

## The honest scraping picture

We **deep-tested all 317 cutoff URLs live** (`scripts/probe_sources.py`):

| Result | Count |
|--------|------:|
| Dead link (404) | 73 |
| Rank words, no table | 56 |
| Generic HTML | 47 |
| Connection error | 33 |
| Blocked (403) | 29 |
| Tables + rank words | 28 |
| Tables, no rank words | 21 |
| "No official cutoff" / non-URL | 15 |
| JS-only SPA | 10 |
| 500/503 / non-HTML | 5 |

**Finding:** the official portals almost never expose cutoffs as static HTML —
they sit behind ASP.NET cascading forms (JoSAA), PDFs (most state boards), or
JS. So a generic *landing-page* scrape harvests ~0 real rows. This is exactly
why tools like coladex use **curated** datasets. We therefore:

- ship **curated real snapshots** for JoSAA, MHT-CET, KCET, WBJEE
  (`scripts/build_snapshots.py`) for the rank predictor + trends;
- provide a **correct, tolerant generic HTML scraper** (`cutoffs/scrape.py`)
  that returns real rows for any page that *does* publish a rank table, and an
  empty frame (never an error) for the many that don't;
- provide **framework adapters** for the hard formats — pdfplumber
  (`cutoffs/adapters/_pdf.py`, worked example in `mhtcet.py`) and Playwright
  (`cutoffs/adapters/_js.py`).

Curated snapshots are *representative public figures*, clearly labelled — refresh
via the adapters for authoritative data.

## Architecture

```
cutoffs/
  schema.py        unified 13-column schema + tolerant normalizer
  source.py        CutoffSource ABC (load_cached / fetch_latest)
  registry.py      @register; list/iterate "all" or one body
  storage.py       Parquet read/write
  query.py         DuckDB query builder (all filtering is SQL over Parquet)
  catalog.py       breadth: parse sheet, classify, enrich -> catalog.parquet
  scrape.py        generic HTML table -> schema scraper (httpx + pandas)
  adapters/
    josaa, mhtcet, kcet, wbjee   curated snapshots (mhtcet = worked PDF example)
    _pdf.py        pdfplumber framework
    _js.py         Playwright framework
    generic.py     data-driven GenericHTMLSource (point at any catalog URL)
app.py             3-tab Streamlit UI
scripts/
  probe_sources.py     live deep-test of all 317 cutoff URLs
  build_snapshots.py   (re)generate curated cutoff snapshots
  enrich_workflow.js   multi-agent catalog enrichment workflow
  merge_enrichment.py  fold workflow output into catalog.parquet
```

### Unified schema (every adapter emits exactly these)

`Body, Exam, Level, State, Year, Round, Institute, Branch, Category, Quota,
Gender, OpeningRank, ClosingRank`

### Official links first, aggregator fallbacks alongside

Every homepage / cutoff link is **live-verified** (`scripts/probe_links.py`) and
classified official vs aggregator. A `find-official-links` agent workflow
researches the gaps (using shiksha / careers360 / collegedekho / getmyuni /
entrancezone / collegepravesh / collegeforme **only to locate** the official
source), each result is re-validated live (`scripts/apply_links.py`), and only
working **official** URLs are stored in `cutoffs/data/links.json` (291 homepages,
225 cutoff pages, 124 acronyms). Unofficial/aggregator and dead links are never
shown in the official `Homepage`/`Cutoff page` columns.

Separately, `EXAMlinkssheet.xlsx` (mirrored to `examlinkssheet.csv`) adds a
curated **`CutoffStatus`** per exam — *Official Cutoff* (140), *Official Merit
List* (64), *No Cutoff Exists* (113) — plus four **aggregator fallback** columns
(CollegeDunia / Shiksha / Careers360 / CollegeDekho). These are surfaced in their
own columns as a deliberate fallback (especially for the 113 exams with no
official cutoff), kept strictly separate from the official link columns. Rebuild
applies both overlays automatically.

### Adding a new body

One new adapter file + one import line in `cutoffs/adapters/__init__.py`.
Nothing else changes — the registry, ingest, and UI pick it up automatically.

## Development

```bash
pytest -q                              # full suite
python -m cutoffs.catalog              # rebuild data/catalog.parquet
python scripts/build_snapshots.py      # rebuild curated snapshots
python scripts/probe_sources.py        # re-run the live source probe
```

## Stack

httpx · pdfplumber · playwright (optional) · pandas · pyarrow · DuckDB ·
Streamlit — pinned in `requirements.txt`. Python-only by design (no Polars,
no non-Python tools).
