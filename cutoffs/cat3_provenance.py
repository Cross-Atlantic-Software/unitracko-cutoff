"""Category-3 — the "no link at all" exams.

Client rule for cat-3: for each exam with neither a specific official cutoff link
nor a competitor link, "check on google / python script — if able to fill the table
as first one (just make another table - so we know)." The goal is therefore to
produce, WHERE POSSIBLE, a SEPARATE table shaped like the cat-1 14-column deliverable
(Exam Name … Closing Rank, Link - Data Taken from), kept distinct from the cat-1
output.

``run_cat3`` does exactly this: it searches (Google/DuckDuckGo) for each exam and,
where a cutoff-like page is found, extracts its rows (via the project's scraper) and
projects them to the 14 deliverable columns, writing a SEPARATE
``data/cat3_cutoffs.csv``. Every attempt is also logged to a
``data/cat3_provenance.parquet`` audit trail (query, candidate URL, whether a table
was found, rows extracted). Neither output is ever merged into the unified cutoff
dataset — the cat-3 table is kept deliberately distinct ("so we know").

The query/record logic is pure stdlib (and the search/fetch functions are
injectable) so it is testable without a network.
"""
from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEG_CSV = ROOT / "data" / "segmentation.csv"
PROVENANCE_PATH = ROOT / "data" / "cat3_provenance.parquet"
# The cat-3 deliverable: a SEPARATE table shaped like the cat-1 14-column deliverable
# ("make another table so we know"), filled from the pages cat-3 manages to recover.
CAT3_CUTOFFS_CSV = ROOT / "data" / "cat3_cutoffs.csv"

PROVENANCE_COLUMNS = [
    "exam", "query", "candidate_url", "http_ok", "n_tables", "found", "note",
    "generated_at",
]
# Provenance + how many cat-1-shaped rows the find actually yielded.
CAT3_PROVENANCE_COLUMNS = PROVENANCE_COLUMNS + ["rows_extracted"]

# Keywords that suggest a fetched page actually carries cutoff/merit data.
_CUTOFF_WORDS_RE = re.compile(
    r"cut\s*off|closing\s*rank|opening\s*rank|merit\s*list|rank\s*list|"
    r"category\s*wise|round\s*\d", re.I)
_TABLE_RE = re.compile(r"<table", re.I)


@dataclass
class ProvenanceRecord:
    exam: str
    query: str
    candidate_url: str
    http_ok: bool
    n_tables: int
    found: bool
    note: str
    generated_at: str = ""


# --------------------------------------------------------------------------
# Pure helpers (testable without a network).
# --------------------------------------------------------------------------
def build_query(exam: str, year: int | None = None) -> str:
    """The search query for an exam's cutoff page."""
    y = f" {year}" if year else ""
    return f'"{exam.strip()}" cutoff OR "merit list" rank{y}'


def count_tables(html: str) -> int:
    return len(_TABLE_RE.findall(html or ""))


def looks_like_cutoff(html: str) -> bool:
    """True if the page has at least one table AND cutoff-ish wording."""
    return count_tables(html) > 0 and bool(_CUTOFF_WORDS_RE.search(html or ""))


def cat3_exams(seg_path: Path = SEG_CSV) -> list[str]:
    """Exam names classified cat-3 in the segmentation driver."""
    if not Path(seg_path).exists():
        return []
    with open(seg_path, encoding="utf-8") as fh:
        return [r["exam"] for r in csv.DictReader(fh) if r.get("category") == "cat3"]


def attempt(exam: str, *, year: int | None, search_fn, fetch_fn,
            when: str = "") -> ProvenanceRecord:
    """Run one search+inspect attempt. ``search_fn``/``fetch_fn`` are injectable.

    search_fn(query) -> list[str] candidate URLs.
    fetch_fn(url)    -> (http_ok: bool, n_tables: int, looks_like_cutoff: bool).
    """
    query = build_query(exam, year)
    candidates = search_fn(query) or []
    candidate = candidates[0] if candidates else ""
    if not candidate:
        return ProvenanceRecord(exam, query, "", False, 0, False,
                                "no search result", when)
    http_ok, n_tables, looks = fetch_fn(candidate)
    note = ("cutoff-like table found" if looks
            else "page fetched, no cutoff table" if http_ok
            else "fetch failed/blocked")
    return ProvenanceRecord(exam, query, candidate, http_ok, n_tables, bool(looks),
                            note, when)


def build_records(exams: list[str], *, year: int | None, search_fn, fetch_fn,
                  when: str = "") -> list[dict]:
    """Provenance dict rows for a list of exams (pure given the injected fns)."""
    return [asdict(attempt(e, year=year, search_fn=search_fn, fetch_fn=fetch_fn,
                           when=when)) for e in exams]


def fill_cat3(exams: list[str], *, year: int | None, search_fn, fetch_fn, extract_fn,
              when: str = "") -> tuple[list[dict], list[dict]]:
    """Find a cutoff page per exam and, where found, fill the cat-1-shaped table.

    Returns ``(provenance_records, deliverable_records)`` where deliverable rows use
    the client's 14 cat-1 column labels (via :func:`cutoffs.deliverable.project_records`).
    ``extract_fn(exam, url) -> list[dict]`` yields unified-schema-keyed rows for a
    confirmed page; injecting it (along with search_fn/fetch_fn) keeps this pure.
    """
    from cutoffs.deliverable import project_records

    provenance: list[dict] = []
    deliverable: list[dict] = []
    for exam in exams:
        rec = attempt(exam, year=year, search_fn=search_fn, fetch_fn=fetch_fn, when=when)
        n_rows = 0
        if rec.found and rec.candidate_url:
            try:
                raw = extract_fn(exam, rec.candidate_url) or []
            except Exception:  # noqa: BLE001 — a bad page never breaks the pass
                raw = []
            prepared = []
            for row in raw:
                row = dict(row)
                row.setdefault("Exam", exam)
                row["SourceURL"] = rec.candidate_url   # "Link - Data Taken from"
                prepared.append(row)
            deliverable += project_records(prepared)
            n_rows = len(prepared)
        record = asdict(rec)
        record["rows_extracted"] = n_rows
        provenance.append(record)
    return provenance, deliverable


# --------------------------------------------------------------------------
# Default network functions (lazy; used when nothing is injected).
# --------------------------------------------------------------------------
_DDG_RESULT_RE = re.compile(r'uddg=([^&"\']+)')


def _ddg_search(query: str) -> list[str]:
    """Top result URLs from DuckDuckGo's HTML endpoint (best-effort, [] on block)."""
    from urllib.parse import quote_plus, unquote

    from cutoffs.competitors._common import fetch_html

    html = fetch_html(f"https://duckduckgo.com/html/?q={quote_plus(query)}", timeout=20.0)
    return [unquote(m) for m in _DDG_RESULT_RE.findall(html)][:5]


def _fetch_and_inspect(url: str) -> tuple[bool, int, bool]:
    from cutoffs.competitors._common import fetch_html

    html = fetch_html(url, timeout=25.0)
    if not html:
        return (False, 0, False)
    return (True, count_tables(html), looks_like_cutoff(html))


def _extract_default(exam: str, url: str) -> list[dict]:
    """Extract cutoff rows from a found page into unified-schema dict rows (real env).

    Reuses the project's generic HTML scraper; returns [] when nothing parses.
    """
    from cutoffs.scrape import scrape_cutoffs

    df = scrape_cutoffs(url, exam=exam)
    if df is None or df.empty:
        return []
    return df.to_dict("records")


def run_provenance(exams: list[str] | None = None, *, out_path: Path = PROVENANCE_PATH,
                   year: int | None = None, when: str | None = None,
                   search_fn=None, fetch_fn=None):
    """Probe each exam and write the SEPARATE provenance parquet. Returns the frame."""
    from datetime import datetime, timezone

    import pandas as pd

    exams = exams if exams is not None else cat3_exams()
    stamp = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = build_records(
        exams, year=year, when=stamp,
        search_fn=search_fn or _ddg_search,
        fetch_fn=fetch_fn or _fetch_and_inspect)
    df = pd.DataFrame(records, columns=PROVENANCE_COLUMNS)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return df


def run_cat3(exams: list[str] | None = None, *, out_provenance: Path = PROVENANCE_PATH,
             out_cutoffs: Path = CAT3_CUTOFFS_CSV, year: int | None = None,
             when: str | None = None, search_fn=None, fetch_fn=None, extract_fn=None) -> dict:
    """Full cat-3 pass: find pages, fill the cat-1-shaped table, write both outputs.

    Writes a SEPARATE ``cat3_cutoffs.csv`` (the 14 client deliverable columns, only
    for exams whose page yielded rows) and the ``cat3_provenance.parquet`` audit
    trail (one row per exam attempted). Returns a small stats dict.
    """
    from datetime import datetime, timezone

    from cutoffs.deliverable import deliverable_columns

    exams = exams if exams is not None else cat3_exams()
    stamp = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
    provenance, deliverable = fill_cat3(
        exams, year=year, when=stamp,
        search_fn=search_fn or _ddg_search,
        fetch_fn=fetch_fn or _fetch_and_inspect,
        extract_fn=extract_fn or _extract_default)

    # cat-1-shaped deliverable -> stdlib CSV (no pandas needed for this one).
    labels = [label for _, label in deliverable_columns()]
    out_cutoffs = Path(out_cutoffs)
    out_cutoffs.parent.mkdir(parents=True, exist_ok=True)
    with open(out_cutoffs, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=labels)
        writer.writeheader()
        writer.writerows(deliverable)

    # provenance audit trail -> parquet (pandas, lazy).
    import pandas as pd

    out_provenance = Path(out_provenance)
    out_provenance.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(provenance, columns=CAT3_PROVENANCE_COLUMNS).to_parquet(
        out_provenance, index=False)

    return {
        "exams": len(exams),
        "provenance_rows": len(provenance),
        "found_pages": sum(1 for r in provenance if r["found"]),
        "exams_with_rows": sum(1 for r in provenance if r["rows_extracted"] > 0),
        "cutoff_rows": len(deliverable),
        "cutoffs_path": str(out_cutoffs),
        "provenance_path": str(out_provenance),
    }
