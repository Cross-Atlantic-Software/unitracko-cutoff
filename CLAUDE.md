# CLAUDE.md — Indian Admission Cutoff Aggregator

## What this project is
A Python-only tool that collects admission cutoff data (opening & closing ranks
by college, branch, category, year) from Indian counseling bodies, stores it as
Parquet, and serves an interactive Streamlit UI to filter it.

Guiding principle: pluggable and NOT restricted. Users can query ALL bodies or
any INDIVIDUAL one. Adding a new exam/body = ONE new adapter; nothing else changes.

## Stack (do not introduce non-Python tools)
- Fetching: httpx (async) for HTML/forms; pdfplumber (Camelot fallback) for PDFs;
  playwright (python) ONLY for genuinely JS-rendered sites.
- Processing: pandas. Do NOT add Polars.
- Storage: Parquet via pyarrow (one normalized columnar file).
- Query: DuckDB python API over Parquet — all filtering/aggregation is DuckDB SQL.
- Frontend: Streamlit, backed by DuckDB.
- Scheduling: plain Python ingestion script, runnable locally and on a GitHub
  Actions cron.
- Env: venv + pinned requirements.txt.

## Architecture
Two decoupled stages joined by Parquet:
  adapters (right fetcher per source) -> normalize -> write Parquet
  Streamlit + DuckDB -> read Parquet -> filter instantly
No always-on server in the data path.

## Unified schema (every adapter emits EXACTLY these 18 columns)
Body, Exam, Website, Level, State, City, Institute, Program, Branch, Category,
CategoryGroup, Quota, Gender, Year, Round, OpeningRank, ClosingRank, SourceURL
(grew from the original 13; `Website`/`City`/`Program`/`CategoryGroup`/`SourceURL`
are derived/context columns populated by `enrich.py`.) The client's Category-1
deliverable is a 14-column projection of this — see `cutoffs/deliverable.py`.

## Adapter contract
Abstract base class `CutoffSource`:
- metadata: name, exam, level, states, data_format
- load_cached() -> DataFrame   # reuse existing public dataset (fast path)
- fetch_latest() -> DataFrame  # scrape newest (refresh path)
Both return the unified schema. Register every adapter in a central registry so
the UI can list them and iterate "all" or one.

## Conventions
- Type hints + docstrings; minimal inline comments.
- Polite scraping: realistic User-Agent, retries, randomized delays.
- Tolerant parsing: never crash on one bad row or a missing column.
- Keep it simple and fast; don't over-engineer.
- Write tests per module; verify before moving to the next phase.

## Phase map (update the "current" marker as you go)
1. [done] Contract & skeleton — schema, CutoffSource ABC, registry, Parquet
   writer, DuckDB query module, tests. (no network)
2. [done] JoSAA adapter — load_cached() from bundled public OR-CR snapshot;
   fetch_latest() best-effort live pull with graceful fallback to cached.
3. [done] Streamlit UI — body selector (all/individual) + cached/latest mode
   + filters + CSV export. Run: `streamlit run app.py`.
4. [done] MHT-CET adapter (PDF) — worked pdfplumber example in `adapters/_pdf.py`;
   fetch_latest() downloads + parses the configured cutoff PDF, falls back to cached.
5. [done] Breadth + depth (coladex-style):
   - Catalog (`cutoffs/catalog.py`): parse `cutoffexamsheet.xlsx` (317 exams),
     classify category/level/state, fold in the live probe + agent enrichment ->
     `data/catalog.parquet`.
   - Generic HTML scraper (`cutoffs/scrape.py`) + data-driven GenericHTMLSource.
   - Curated multi-year snapshots: JoSAA, MHT-CET, KCET, WBJEE
     (`scripts/build_snapshots.py`).
   - Playwright JS framework (`adapters/_js.py`).
   - 3-tab UI: Explore Exams / Cutoff Explorer + Rank Predictor + trends / Refresh.
   - Deep-test probe (`scripts/probe_sources.py`) — see README "honest scraping picture".
6. [done] Ops — GitHub Actions cron for scheduled ingestion (`.github/workflows/ingest.yml`).
7. [current] Client 3-category pipeline (~320 exams) — segment every exam, then
   collect per category. Driver: `data/segmentation.csv` (single source of truth),
   built by `cutoffs/segmentation.py` (pure stdlib) / `scripts/segment_report.py`.
   - Cat-1 "specific official link" (client target ~160; current sheet = 203 with
     merit lists / 139 without — exact figure depends on the forthcoming updated
     sheet and whether merit lists count): `cutoffs/dispatch.py` (probe-bucket ->
     fetcher) + `cutoffs/adapters/_bulk.py` `BulkOfficialSource` (opt-in, breadth
     insurance) -> unified schema. 14-col client export via `cutoffs/deliverable.py`.
   - Cat-2 "all exams with >=1 competitor link": `cutoffs/competitors/` — one raw,
     site-specific table per CollegeDunia/Shiksha/Careers360/CollegeDekho
     (`data/competitor_<name>.parquet`); NEVER merged into the unified schema. `run.py`
     defaults to EVERY exam with that competitor link (the client's cat-2, independent
     of cat-1); `--category cat2` narrows to the no-official-link bucket.
   - Cat-3 "no link" (~16): per the client, search Google/python and, WHERE POSSIBLE,
     produce a SEPARATE cat-1-shaped 14-column table ("make another table so we know").
     `cutoffs/cat3_provenance.run_cat3` does this — writes `data/cat3_cutoffs.csv`
     (the 14 deliverable columns, for exams whose page yielded rows) plus a
     `data/cat3_provenance.parquet` audit trail. Neither is merged into the unified schema.
   - Run all three via `python -m cutoffs.ingest --category all`.
   - Next: resolve competitor search-landing links to canonical pages; rebuild on
     the client's updated sheet; commit cached snapshots once links stabilize.

## Key reality check (verified live, do not relitigate)
Of the 317 source URLs, only ~28 even have HTML tables and almost none expose
cutoffs as *static* HTML — they hide behind ASP.NET forms / PDFs / JS. So live
HTML harvesting yields ~0 rows; depth comes from curated snapshots + per-format
adapters, exactly like coladex. The generic scraper is correct but only fires on
pages that genuinely publish rank tables.