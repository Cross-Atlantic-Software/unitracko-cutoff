# Data Dictionary — `all_cutoffs.csv`

A flat, analysis-ready union of **every** cutoff source in this project, harmonized
to one schema. **193,449 rows × 19 columns**, 171 exams, 6,155 colleges.

> Derived export only. The canonical `data/cutoffs.parquet` (18-col unified schema)
> and the separate side tables are untouched. This file deliberately **mixes data of
> different fidelity** for convenience — always filter on the `Fidelity` column before
> drawing conclusions.

## How it was built
Five sources unioned, each mapped to the 14-column client deliverable shape plus
`Category` and `Cutoff Percentile/Score`:

| Source value | Fidelity | Rows | Origin |
|---|---|---|---|
| `official-adapter` | `official` | 159,025 | `data/cutoffs.parquet` — per-body PDF/portal-parsed cutoffs (19 bodies). **Trust this layer.** |
| `competitor-aggregator` | `aggregator` | 32,445 | `data/aggregator_cutoffs.csv` — distilled CollegeDunia/Shiksha/Careers360/CollegeDekho. Third-party, lower confidence. |
| `mp-aggregator` | `aggregator` | 180 | `data/mp_aggregator_cutoffs.csv` — MP gated-portal aggregator side table. |
| `cat3-web-research` | `web-research` | 1,799 | `data/cat3_web_cutoffs.csv` — web-research-recovered cutoffs for no-official-link exams. |
| `cat3-provenance` | `web-research` | 0* | `data/cat3_cutoffs.csv` — cat-3 provenance rows (currently header-only). |

\* present for completeness; the file holds no data rows at export time.

## Columns

| # | Column | Type | Notes |
|---|--------|------|-------|
| 1 | `Source` | category | Which sub-source the row came from (table above). |
| 2 | `Fidelity` | category | Coarse trust tier: `official` > `aggregator` > `web-research`. **Primary filter for any serious analysis.** |
| 3 | `Provenance Note` | category | Finer grade, only for `cat3-web-research` rows: `official` (read off an official page), `official-proxy`, `portal`, `derived`. Blank for all other sources. |
| 4 | `Exam Name` | string | Entrance exam / counselling body, e.g. `AP EAPCET`, `JoSAA`, `COMEDK`. |
| 5 | `Link of website` | url | Official site of the body (context, not the data source). |
| 6 | `College Name` | string | Institute. |
| 7 | `City` | string | May be blank for aggregator/web rows. |
| 8 | `State` | string | May be blank for aggregator/web rows. |
| 9 | `Program` | string | e.g. `B.E./B.Tech`. Often blank outside the official layer. |
| 10 | `Branch` | string | Specialization, e.g. `Computer Science Engineering`. |
| 11 | `Year - cutoff` | int-as-string | Cutoff year, normalized to a 4-digit integer string (`2013`–`2026`). Blank if unknown. |
| 12 | `Round #` | string | Counselling round/stage. Free-text and source-specific: `Final`, `Round 1`, `CAP1 Stage I`, etc. See caveats. |
| 13 | `Gender` | category | `Male` / `Female` / `Gender-Neutral` and variants. See caveats. |
| 14 | `Quota` | string | Seat quota / reservation code as published by the source (`OBC`, `EWS`, `All India_Rank`, …). Not normalized across bodies. |
| 15 | `Category` | string | Reservation category as published (`OC`, `SC`, `ST`, `BCA`…). Preserved from the official parquet and recovered for aggregator rows; blank where the source didn't expose it. |
| 16 | `Opening Rank` | number-as-string | Best (lowest) admitted rank. Blank for percentile/marks-based exams. |
| 17 | `Closing Rank` | number-as-string | Last admitted rank — the usual cutoff. Blank for percentile/marks-based exams. |
| 18 | `Cutoff Percentile/Score` | string | Percentile or marks for exams that don't use ranks (mostly `cat3-web-research`). |
| 19 | `Link - Data Taken from` | url | The exact page/PDF the row was scraped from — the provenance / audit link. |

## Caveats (known data-quality quirks — documented, not silently cleaned)
- **Filter by `Fidelity` first.** `aggregator` and `web-research` rows are third-party
  scrapes kept separate from the canonical dataset by design; treat them as hints, not truth.
- **`Quota` / `Category` are not cross-body normalized** — each body's reservation
  vocabulary is preserved verbatim. Group within an exam, not across exams.
- **`Round #` contains parser noise** in a few MHT-CET rows (e.g.
  `CAP1 Stage 85878 (68.28...)` where a percentile bled into the round label).
- **`Gender` has stray non-gender tokens** in some aggregator rows from column
  misalignment during scraping; the official layer is clean.
- **`Opening`/`Closing Rank` are strings**, not numbers — `pd.to_numeric(..., errors="coerce")`
  before computing. 192,487 rows carry at least one numeric rank.

## Quick start
```python
import pandas as pd
df = pd.read_csv("data/all_cutoffs.csv")

# trustworthy analysis only
official = df[df.Fidelity == "official"].copy()
official["Closing Rank"] = pd.to_numeric(official["Closing Rank"], errors="coerce")

# closing-rank trend for CSE by exam/year
official[official.Branch.str.contains("Computer", na=False)] \
    .groupby(["Exam Name", "Year - cutoff"])["Closing Rank"].median()
```

Regenerate: re-run the union script (reads the five sources listed above into
`data/all_cutoffs.csv`).
