"""Madhya Pradesh (DTE MP) cutoffs from aggregator articles — SEPARATE, non-official.

MP DTE's official cutoff is behind a session-stateful ASP.NET-AJAX form (no
downloadable PDF/HTML report), so it can't join the official cat-1 dataset like the
other states. Per the client's call, MP is sourced from CollegeDekho's DTE-MP cutoff
articles and kept in a SEPARATE deliverable-shaped table — deliberately NOT merged
into the unified official schema (mirrors how cat-2/cat-3 keep aggregator data
distinct, "so we know" what is official vs aggregator-sourced).

``run_mp`` scrapes the configured article pages, extracts the college x branch x
closing-rank rows (the competitor table toolkit), projects them to the client's 14
deliverable columns, and writes ``data/mp_aggregator_cutoffs.csv``. The fetch/extract
functions are injectable so the projection is testable without a network.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MP_CUTOFFS_CSV = ROOT / "data" / "mp_aggregator_cutoffs.csv"

# CollegeDekho DTE-MP B.Tech cutoff articles (government + private colleges).
SOURCES = [
    "https://www.collegedekho.com/articles/dte-mp-btech-cutoff-ranks-for-government-colleges/",
    "https://www.collegedekho.com/articles/dte-mp-btech-cutoff-ranks-for-private-colleges/",
]
EXAM = "MP DTE"
STATE = "Madhya Pradesh"


def _default_extract(url: str) -> list[dict]:
    """Extract college x branch x closing-rank rows from one MP article page."""
    from cutoffs.competitors._common import fetch_html, rows_from_tables

    html = fetch_html(url, impersonate=True) or fetch_html(url)
    if not html:
        return []
    rows = rows_from_tables(html, competitor="mp", exam=EXAM, slug="",
                            page_url=url, page_type="mp_cutoff")
    return [r for r in rows if r.get("closing_rank") and r.get("branch_or_course")]


def _to_unified(raw: dict, url: str, year: int | None) -> dict:
    """One competitor RAW row -> a unified-schema-keyed dict for projection."""
    return {
        "Exam": EXAM, "State": STATE,
        "Institute": (raw.get("institute_name") or "").strip(),
        "Branch": (raw.get("branch_or_course") or "").strip(),
        "Category": raw.get("category"),
        "Year": year,
        "OpeningRank": raw.get("opening_rank"),
        "ClosingRank": raw.get("closing_rank"),
        "SourceURL": url,
    }


def collect(extract_fn=None, *, year: int | None = 2024) -> list[dict]:
    """Deliverable-shaped rows (14 client columns) for every MP article source."""
    from cutoffs.deliverable import project_records

    extract_fn = extract_fn or _default_extract
    prepared: list[dict] = []
    seen: set[tuple] = set()
    for url in SOURCES:
        for raw in extract_fn(url) or []:
            row = _to_unified(raw, url, year)
            key = (row["Institute"], row["Branch"], row["Category"],
                   row["ClosingRank"])
            if not row["Institute"] or key in seen:
                continue
            seen.add(key)
            prepared.append(row)
    return project_records(prepared)


def run_mp(out_csv: Path = MP_CUTOFFS_CSV, *, extract_fn=None,
           year: int | None = 2024) -> dict:
    """Scrape the MP articles, write the SEPARATE deliverable-shaped CSV. Stats dict."""
    from cutoffs.deliverable import deliverable_columns

    rows = collect(extract_fn=extract_fn, year=year)
    labels = [label for _, label in deliverable_columns()]
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=labels)
        writer.writeheader()
        writer.writerows(rows)
    colleges = len({r["College Name"] for r in rows})
    return {"rows": len(rows), "colleges": colleges, "path": str(out_csv)}


if __name__ == "__main__":  # pragma: no cover - manual run
    stats = run_mp()
    print(f"[mp] wrote {stats['rows']} rows ({stats['colleges']} colleges) "
          f"-> {stats['path']}")
