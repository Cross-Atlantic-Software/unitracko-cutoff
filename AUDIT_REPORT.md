I have all the confirmed findings, the completeness critic output, and the additional defects. I'll write the audit report directly. No need for further investigation since the findings are pre-verified.

# Audit Report — Client 3-Category Exam-Cutoff Pipeline (Phases A–E)

## 1. Executive Summary & Overall Verdict

**Verdict: Architecturally sound, operationally incomplete, with a contained set of structured-output correctness bugs. Ship-able for cat1 (official) today; cat2/cat3 are not yet production-wired.**

The segmentation → dispatch → bulk/competitor/cat3 design is clean, the leaf parsing helpers are individually correct and well-tested, and the unified-schema/Parquet/DuckDB spine is solid. There are **no critical (data-loss or security-RCE) defects**. However, three classes of problem keep this from being "done":

1. **No unified 3-stage driver.** The cat1, cat2, and cat3 stages disagree on the JEE-remap partition, do not share an exit code, and — most importantly — **the scheduled cron only runs cat1** and commits only `data/cutoffs.parquet`. The "3-category pipeline" the audit is named for is not actually exercised by CI. The 14-column client deliverable is never produced or committed by any pipeline.

2. **A family of wide-table melt bugs** in `cutoffs/competitors/_common.py` that corrupt *structured* columns: percentile/score values rounded into `closing_rank`, an `Open`/`General` rank column double-classified as a category, captions leaking to the next table, year-substring header misclassification. Crucially, the standing mitigation "the raw value survives losslessly in `raw_cells`" is **false for duplicate-header tables** (the `cells` dict drops earlier duplicates), so this family is somewhat worse than each finding rated in isolation.

3. **Politeness contract not met** — CLAUDE.md mandates randomized delays; there is **zero jitter anywhere**, and no crawler loop throttles per host. The bulk circuit breaker is **dead code** (never trips), so a 5xx/timeout host keeps getting hammered.

Test coverage of the leaf helpers is good, but the load-bearing *compositions* (`rows_from_tables`, `run.py` orchestration, the pandas projection `to_cat1_deliverable`) have **zero coverage**. 45 new tests is respectable breadth but skewed toward the easy units.

Bottom line: the foundation is correct and the bugs are mostly "structured output is wrong but recoverable from raw," not "data destroyed." Fix the ops wiring and the melt/role-collision bugs before the client relies on cat2 output.

---

## 2. Findings by Severity

### Critical
*None.*

### High
- **No unified 3-stage driver / JEE-remap partition divergence** — `cutoffs/adapters/_bulk.py:62-63,77-78` (`segment(jee_remap=False)`) vs committed `data/segmentation.csv` (written with `jee_remap=True`). The 5 JEE-split exams are cat3 to bulk but cat1 in the CSV → scraped by **no** live pipeline. *Fix:* single source of truth — all stages read the same `segmentation.csv` (or call `segment()` with identical `jee_remap`); add a `--jee-remap` flag threaded through all three stages; at minimum default `BulkOfficialSource(jee_remap=True)`.
- **Cron runs cat1 only; cat2/cat3/deliverable never scheduled or committed** — `.github/workflows/ingest.yml` (`python -m cutoffs.ingest --mode latest`, `git add data/cutoffs.parquet`). `competitor_*.parquet`, `cat3_provenance.parquet`, and the deliverable CSV are never produced in CI. *Fix:* add cron steps for `--category all`, produce+commit the deliverable, and surface a non-zero exit on any stage failure.
- **Role-vs-category column collision corrupts rank semantics even for pure rank tables** — `cutoffs/competitors/_common.py:221` (`_ROLE_PATTERNS` opening) vs `:235` (`_CATEGORY_HEADER_RE`). `detect_roles(['Institute','Open','OBC','SC'])`→`{opening_rank:'Open'}` *and* `category_columns`→`['Open','OBC','SC']`; the melt branch then emits `Open` as a category row with `closing_rank=<opening value>`. Hits any JoSAA/coladex "Open/General/OBC/SC as columns" table. *Fix:* exclude columns already claimed as a rank role from `category_columns`, or resolve precedence so a detected rank column is never melted as a category.
- **`rows_from_tables` (cat2 wide→long melt) entirely untested** — `tests/test_competitors.py` (no reference; impl `_common.py:269`). The only nontrivial cat2 branch logic has zero coverage — which is why the melt/role/caption bugs went unnoticed. *Fix:* stub-table tests (object with `.columns` + `.iterrows()`) for wide-category and narrow Institute/Open/Close tables; assert melt target column, `raw_cells` round-trip, caption-institute fallback.

### Medium
- **Strategy `timeout`/`retries` silently ignored for HTML & JS fetches** — `cutoffs/dispatch.py:132,136`; `scrape_cutoffs` (`scrape.py:181`) and `scrape_js_cutoffs` (`_js.py:56`) take no such params, so defaults (15.0/2 and 20000ms) win over strategy's 30.0/1 and 25.0. Only the PDF branch forwards them — and PDF never fires on current data. *Fix:* thread `timeout`/`retries` through both, or drop the fields from HTML/JS Strategy entries and document PDF-only.
- **Bulk host circuit-breaker is dead code** — `cutoffs/adapters/_bulk.py:101-122` + `dispatch.py:107-146`. `dispatch_fetch` never raises (returns `empty_frame()`), so the `except` that increments `host_errors` (`_bulk.py:110`) is unreachable; failing hosts log as "empty" and keep getting hit. *Fix:* have `dispatch_fetch` raise/sentinel a real transport failure that `_bulk` counts, or count repeated empties from a non-dead strategy as soft failures; else drop the breaker and amend the polite-scraping comment.
- **`bulk_official` double-counts curated exams under `include_optin`** — `_bulk.py:77-78` + `ingest.py:80-89`. MHT-CET / Bihar Eng / KCET / WBJEE appear in cat1 with live HTML buckets and stack (no dedup) against curated adapter rows; bulk sets `Body=''`, curated sets real labels, so they cannot be reconciled. *Fix:* exclusion set of exam names owned by curated adapters in `_cat1_rows()`, or provenance-tag + dedup in ingest preferring curated.
- **Percentile/score exams melted into `closing_rank`** — `_common.py:312-319`. Melt branch unconditionally `closing_rank=coerce_rank(...)` and never fills `cutoff_percentile`/`cutoff_score_or_marks`; `coerce_rank('99.87')→100`. *Fix:* route by cell shape/exam type — floats in 0–100 → percentile/score field, leave `closing_rank` None.
- **`<caption>` leaks to the following table** — `_common.py:183-188`. Caption text becomes `self._cur` on `</caption>`, attaching to the *next* table; its own table gets `''`. *Fix:* on caption end-tag inside a `<table>`, overwrite `table_headings[-1]` rather than treat as preceding sibling.
- **`cells` dict drops duplicate column headers → `raw_cells` is NOT lossless** — `_common.py:295` (`{str(c): ... for c in tbl.columns}`). `pd.read_html` duplicate/MultiIndex headers collapse to last. This **invalidates the "recoverable from raw_cells" downgrade** on several findings below. *Fix:* key `cells` by index or dedupe-suffix duplicate header names before `json.dumps`.
- **`DEFAULT_YEARS` stale — omits 2025** — `cutoffs/competitors/collegedekho.py:16`; `run.py:61` passes no override. Freshest completed cycle never requested. *Fix:* `DEFAULT_YEARS = tuple(range(date.today().year-1, date.today().year-5, -1))`.
- **`run.py` orchestration untested** (`_targets`/`_load_segmentation`/`_CATEGORY_SETS`/CLI) — `tests/test_competitors.py:10-12`. A renamed/recased segmentation column would silently yield zero targets. *Fix:* fixture-CSV tests for target selection, category-set expansion, limit slicing, parquet+sidecar write.
- **14-column deliverable projection is an orphaned module** — `cutoffs/deliverable.py` referenced only by itself and its test; `ingest.py` writes the 18-col parquet and never projects. The contracted client CSV is never produced. *Fix:* call `write_deliverable(out)` in the cat1 ingest path or add an `--deliverable` subcommand.
- **`rank_range_raw` declared but never populated** — `_common.py` (`RAW_COLUMNS` `__init__.py:50`). careers360 "200-500" ranges survive only in `raw_cells`. *Fix:* add a rank-range role/regex and assign `rank_range_raw`; optionally split into opening/closing.
- **JSON-only structured fields dropped** — `collegedunia.py:38-50` (never calls `extract_next_data`; `institute_id` lost), `careers360.py:61-83` (uses INITIAL_STATE only for article HTML, discards structured cutoff nodes). *Fix:* harvest per-row JSON metadata into the raw row.
- **`to_cat1_deliverable` pandas path untested, incl. reindex-of-missing-columns** — `tests/test_deliverable.py`; impl `deliverable.py:71` (`df.reindex` materializes absent cols as NaN, diverging from `project_records`' `None`). *Fix:* `importorskip('pandas')` test on a DataFrame missing Website/SourceURL/City/Program.
- **No randomized delay anywhere** — `_common.py:32`, `_http.py:28`, `scrape.py:56`. CLAUDE.md mandates jitter; only failure-branch sleeps exist. *Fix:* `time.sleep(random.uniform(0.5,2.0))` after each successful fetch, centralized per-host.
- **Bulk cat1 loop has no inter-request throttle** — `_bulk.py:87-123`. *Fix:* per-netloc last-request timestamps + jittered delay.
- **Competitor cat2 loop has no throttle across hundreds of requests** — `run.py:58-64` (plus per-scraper multi-URL inner loops). *Fix:* centralized per-host delay in `fetch_html`.
- **SSRF: cat3 fetches arbitrary DDG result URLs, no scheme/host validation, follows redirects** — `cat3_provenance.py:107-126` → `_common.fetch_html:53-54`. Returns `169.254.169.254`/`localhost` verbatim; body persisted to provenance parquet. *Fix:* validate scheme∈{http,https}, reject loopback/private/link-local via `ipaddress`; disable or re-validate redirects on the cat3 path.
- **README schema stale (×2)** — `README.md:80` ("13-column") and `:102-103` (13-name list) vs actual 18-column `schema.COLUMNS`. *Fix:* update both to the 18-column list or reference `schema.COLUMNS`.
- **`app.py` does not surface cat2/cat3 outputs (audit gap)** — whether the UI presents competitor raw tables / cat3 provenance was never checked; if cat1-only, the 3-category deliverable has no presentation surface. *Action:* audit `app.py` consumption.
- **`enrich_frame`/`cutoffs/enrich.py` + `storage.write_parquet` never audited** — the actual normalize-to-18-columns path on every cat1 row (`ingest.py:86`). *Action:* audit before relying on shipped parquet.

### Low
- **bulk_official untested** (`_bulk.py` whole module) — circuit breaker, `_attach_links`, empty fallback, `report()`. *Fix:* `tests/test_bulk.py` monkeypatching `dispatch_fetch`.
- **RAW_COLUMNS superset test weak** — `test_competitors.py:133-136` omits `cutoff_score_or_marks`/`pdf_url`, no dup guard. *Fix:* add both + `assert len(RAW_COLUMNS)==len(set(RAW_COLUMNS))`.
- **`get_competitor`/`to_frame` untested** — `test_competitors.py`. *Fix:* assert import per name + `KeyError` on bogus; `to_frame` column shape.
- **`coerce_rank` accepts negatives, collapses ranges to first number** — `_common.py:146-165`. *Fix:* drop leading sign from `_NUM_RE`; detect ranges → `rank_range_raw`.
- **collegedekho ignores year in dated `-esp` link** — `collegedekho.py:19-30,39-54`. *Fix:* union the embedded year into requested set.
- **shiksha relative URL → malformed `:///path`** — `shiksha.py:33-34`. *Fix:* guard on `p.netloc`.
- **collegedunia scheme-less path → malformed `:///...`** — `collegedunia.py:28`; also falsely increments `run.py:59` resolved counter. *Fix:* `if not m or not p.netloc: return []`.
- **shiksha `_EXAM_RE` slug crosses path segments** — `shiksha.py:20`. `exam_slug`→`'sub/jee-main'`. *Fix:* restrict slug to one segment.
- **competitors `--limit 0` silently ignored** — `run.py:53-54` (`if limit:`). *Fix:* `if limit is not None:`.
- **`cat3_probe.py --limit 0` probes ALL** — `scripts/cat3_probe.py:28-29`. *Fix:* `if args.limit is not None:` + clamp negatives.
- **`--category 2/all` ignores `competitors_main` return code** — `ingest.py:118-120`; missing CSV silently no-ops, CLI exits 0. *Fix:* capture rc, accumulate, `sys.exit`.
- **`ingest --category 3/all` ignores `--path`; collision can clobber provenance** — `ingest.py:115-124`. *Fix:* assert `args.path` ∉ {provenance, competitor outputs}.
- **`_DDG_RESULT_RE` uddg-decode path untested** — `cat3_provenance.py:107-117`. *Fix:* unit test on sample DDG page string.
- **No test asserts cat3 records lack cutoff schema cols / never concatenated into unified frame** — `tests/test_cat3.py`. *Fix:* assert `PROVENANCE_COLUMNS ∩ schema.COLUMNS == ∅`; distinct out_path.
- **No SSRF/URL-validation tests** — `tests/`. *Fix:* once validator lands, assert rejection of metadata/loopback/`file://`/non-http.
- **`cat3_exams` (CSV reader) untested** — `cat3_provenance.py:68`. *Fix:* temp-CSV test + missing-path → `[]`.
- **Segmentation tests brittle + unasserted reallocation** — `test_segmentation.py`; `merit_list=False` cat2/cat3 growth unchecked. *Fix:* invariant asserts (cat1↓, cat2↑, cat3↑, total const, delta balances).
- **No response-size limit on any fetcher** — `_http.py:28-55`, `scrape.py:56-72`, `_common.py:32-58`; PDF consumers `mhtcet.py:54`/`biharpoly.py:48`/`statepdf.py:55`/`keam.py:100`. *Fix:* stream + cap (~25–50 MB).
- **No robots.txt compliance** — `_common.py:32` + callers, `_bulk.py`. No active breach today. *Fix:* cached per-host `RobotFileParser` gate.
- **`program` & `notes` RAW_COLUMNS dead** — no `program=`/`notes=` assignment anywhere (`branch_or_course` populated, `program` always None). *Fix:* populate or remove.
- **`year` role regex `20\d{2}` matches substrings** — `detect_roles(['Branch 2024'])→{year:'Branch 2024'}`. *Fix:* anchor to standalone year tokens.
- **`_load_segmentation` does not strip values** (writer strips) — `run.py:30-32`. Whitespace URL passes `if url:` then feeds un-stripped into `cutoff_urls`. *Fix:* `.strip()` on read.
- **`to_frame`/`DataFrame(..., columns=RAW_COLUMNS)` silently drops extra keys** — relevant when implementing the JSON-harvest fix. *Action:* note for implementer.
- **segmentation.py docstring says "Phase-6"; CLAUDE.md = Phase 7** — `segmentation.py:1`. *Fix:* update label.

### Nit
- **dispatch.py docstring misstates probe path** (`data/` is repo-root, not package-relative) — `dispatch.py:3,26`. *Fix:* `<repo-root>/data/source_probe.csv`.
- **shiksha `/search` guard over-excludes `/search-engine`** — `shiksha.py:27`. *Fix:* segment-exact check.
- **shiksha `exam_slug` lacks the `/search` exclusion `cutoff_urls` has** — `shiksha.py:37-39`. Inert today. *Fix:* derive slug from a resolved URL.
- **cat3 fetch-failed/blocked note branch untested** — `cat3_provenance.py:89-94`. *Fix:* `test_attempt_fetch_failed`.
- **app.py "Data taken from" diverges from deliverable "Link - Data Taken from"** — `app.py:81,401` vs `deliverable.py:34`. *Fix:* align label or derive from `deliverable_rename()`.
- **`run(names=None)` now excludes `bulk_official`; contract untested** — `ingest.py:79-81`. *Fix:* regression test on opt-in membership.
- **bulk_report "Category-1 official links: 203" double-counts shared URLs** (166 distinct) — `scripts/bulk_report.py:49`. *Fix:* relabel "exams"; optionally print distinct-link count.
- **cat3_probe missing-segmentation message misattributes a bad `--segmentation` path** — `scripts/cat3_probe.py:27,30-32`. *Fix:* check `args.segmentation.exists()` distinctly.
- **cat3 happy-path note is a loose substring check** — `test_cat3.py:40`. *Fix:* tighten to `==`.
- **`pd.read_html` on untrusted HTML — no pinned `flavor`** — `scrape.py:80`, `_common.py:70`, `_josaa_orcr.py:109`. Input is StringIO (no remote DTD), so hardening-only. *Fix:* pass explicit `flavor='bs4'`.
- **`pdf_url` is page-wide (first PDF) for every row** — `_common.py:281-282,309`. *Fix:* resolve PDF per row, fall back to `default_pdf`.
- **Dual qualifying-score min/max collapse to first** — `_common.py:240-249,326`. *Fix:* add min/max cols or concatenate.

---

## 3. Coverage Table — 30 Audit Angles

| # | Audit angle | Result |
|---|---|---|
| 1 | Segmentation counts (default) | Clean (correct today; tests brittle — low) |
| 2 | Segmentation merit_list reallocation | **Issue** (unasserted cat2/cat3 growth — low) |
| 3 | JEE-remap partition consistency across stages | **Issue (HIGH)** — bulk vs CSV divergence |
| 4 | `segment()` API / jee_remap threading | **Issue** — no shared setting |
| 5 | Dispatch strategy selection | Clean |
| 6 | Dispatch timeout/retries propagation | **Issue (medium)** — dead for HTML/JS |
| 7 | Dispatch never-raises contract | Clean (but causes #8) |
| 8 | Bulk circuit breaker | **Issue (medium)** — dead code |
| 9 | Bulk per-host throttling | **Issue (medium)** |
| 10 | Bulk vs curated double-counting | **Issue (medium)** |
| 11 | Bulk tests | **Issue (low)** — none |
| 12 | Competitor URL builders (4 scrapers) | **Issue (low/nit ×7)** — relative/slug/year edge cases |
| 13 | `rows_from_tables` melt correctness | **Issue (medium ×3 + HIGH role collision)** |
| 14 | `coerce_rank` / range / negatives | **Issue (low)** |
| 15 | Caption/heading attribution | **Issue (medium)** |
| 16 | `raw_cells` losslessness claim | **Issue (medium)** — duplicate headers break it |
| 17 | Dead RAW_COLUMNS (rank_range_raw/program/notes) | **Issue (medium+low)** |
| 18 | Role regex precision (year/score min-max) | **Issue (low)** |
| 19 | JSON-blob field extraction | **Issue (medium)** |
| 20 | Competitor run.py orchestration | **Issue (medium)** — untested |
| 21 | Competitor tests (helpers) | Clean |
| 22 | Competitor tests (composition/CLI) | **Issue (high/medium)** — none |
| 23 | cat3 provenance logic | Clean |
| 24 | cat3 SSRF / URL validation | **Issue (medium security)** |
| 25 | cat3 tests | **Issue (low/nit)** — uddg/fail-branch/reader gaps |
| 26 | Deliverable projection correctness | Clean (logic sound) |
| 27 | Deliverable wiring into pipeline | **Issue (medium)** — orphaned |
| 28 | Deliverable tests (pandas path) | **Issue (medium)** — none |
| 29 | Ingest orchestration / exit codes / path collision | **Issue (low ×3)** |
| 30 | Cron / CI actually runs all 3 stages | **Issue (HIGH)** — cat1 only |
| — | Politeness: jitter / robots / size-limit | **Issue (medium/low)** |
| — | Docs: README schema / phase label / labels | **Issue (medium/low/nit)** |
| — | enrich.py / storage.write_parquet | **Not audited (gap)** |
| — | app.py consumption of cat2/cat3 | **Not audited (gap)** |

---

## 4. Strengths / What Is Solid

- **Clean pluggable architecture** — segmentation → dispatch → per-format fetchers, with the unified 18-column schema and Parquet/DuckDB spine intact. Adding a body is still one adapter.
- **Leaf parsing helpers are correct and well-tested** — `balanced_json`, `category_columns`, `detect_roles`, `extract_initial_state`/`extract_next_data`, `harvest_pdf_links`, `headings_before_tables`, URL builders all have direct coverage and behave correctly in isolation.
- **Deliverable projection logic is sound and tested** — the 14-column mapping/rename/`project_records` is correct; the only gap is wiring, not logic.
- **cat3 provenance is correctly isolated** — separate columns, separate output path; provenance never enters the unified `pd.concat` (verified, just unasserted).
- **Tolerant parsing throughout** — `dispatch_fetch` never crashes the run on one bad source; empty-frame fallbacks are consistent.
- **Realistic UA + retries present** — two of three politeness requirements are met; only jitter is missing.
- **No data destruction and no RCE** — every "corruption" finding leaves the original cell in `raw_cells`/`raw_cell_value` (except the duplicate-header case), and the one SSRF writes only audit metadata.

---

## 5. Prioritized Action List

**Fix first (blocks correct 3-category output / CI):**
1. **Build one unified 3-stage driver** with a single `jee_remap` source of truth and a single accumulated exit code — collapses the HIGH JEE-remap divergence (#28) plus ingest exit-code/path-collision findings (#25/#30/#40) and the orphaned deliverable (#23) into one fix.
2. **Wire cron to run `--category all` and commit cat2/cat3 + the deliverable CSV** (`.github/workflows/ingest.yml`). Without this the pipeline the audit covers is not exercised.
3. **Fix the wide-table melt family in `_common.py`:** (a) stop melting a column already claimed as a rank role (HIGH role collision); (b) route percentile/score to their own fields; (c) caption-to-own-table; (d) duplicate-header `cells` keying so `raw_cells` is truly lossless.
4. **Add `rows_from_tables` + `run.py` orchestration + `to_cat1_deliverable` tests** — the highest-value missing coverage; these would have caught items 1 and 3.

**Fix next (hardening / correctness, non-blocking):**
5. Make the bulk circuit breaker live (or remove it) and add per-host throttling + randomized jitter across all fetch paths (politeness contract).
6. Add the SSRF/URL validator on the cat3 path + response-size caps; thread Strategy timeout/retries through HTML/JS or document PDF-only.
7. Bulk-vs-curated dedup under `include_optin`; dynamic `DEFAULT_YEARS`; populate/remove dead RAW_COLUMNS; tighten `year`/score role regexes.

**Cleanup (low/nit):**
8. README 18-column schema, phase-label and UI/deliverable label alignment, `--limit 0` guards (competitors + cat3_probe), bulk_report wording, audit the two untouched areas (`enrich.py`/`storage.write_parquet`, `app.py` cat2/cat3 consumption).

**Net:** sound foundation; do items 1–4 before the client depends on cat2 data, then 5–7 before any sustained live crawl.