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

## Unified schema (every adapter emits EXACTLY these columns)
Body, Exam, Level, State, Year, Round, Institute, Branch, Category, Quota,
Gender, OpeningRank, ClosingRank

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
6. [next] Ops — GitHub Actions cron for scheduled ingestion; more curated bodies;
   per-source form/PDF adapters for the high-value state portals.

## Key reality check (verified live, do not relitigate)
Of the 317 source URLs, only ~28 even have HTML tables and almost none expose
cutoffs as *static* HTML — they hide behind ASP.NET forms / PDFs / JS. So live
HTML harvesting yields ~0 rows; depth comes from curated snapshots + per-format
adapters, exactly like coladex. The generic scraper is correct but only fires on
pages that genuinely publish rank tables.