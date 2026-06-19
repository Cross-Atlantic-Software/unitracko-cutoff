"""Phase-6 exam segmentation — partition every catalogued exam into 3 buckets.

The client's data-collection plan splits the ~320 exams into three
mutually-exclusive, priority-ordered categories:

1. **Specific link** — the exam has an official cutoff/merit-list link. A program
   visits that link and downloads the unified 14-column cutoff table.
2. **Competitor link** — no specific official cutoff, but at least one aggregator
   link (CollegeDunia / Shiksha / Careers360 / CollegeDekho, the column-F-onwards
   set). Each competitor is scraped into its own raw, site-specific table.
3. **No link** — neither a specific nor a competitor link. Per the client: check
   Google / a python script and, where possible, fill a *separate* table shaped
   like the cat-1 14-column deliverable ("just make another table, so we know").
   NOTE: this module only classifies; the cat-1-shaped backfill lives in
   ``cat3_provenance.run_cat3`` (writes data/cat3_cutoffs.csv + a provenance trail).

This module is the single source of truth for that partition. It is deliberately
**pure standard-library** (``csv`` only — no pandas / httpx), so the universe is
locked before any flaky network code runs, and so it builds in the most minimal
environment. ``scripts/segment_report.py`` writes the driver CSV every downstream
pipeline (cat-1 dispatch, cat-2 competitor list, cat-3 provenance) consumes.

Build/refresh::

    python -m cutoffs.segmentation              # prints the counts
    python scripts/segment_report.py            # writes data/segmentation.csv
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CUT_SHEET = ROOT / "cutoffexamsheet.csv"        # Exam, Homepage, CutoffURL
LINKS_SHEET = ROOT / "examlinkssheet.csv"       # Exam, CutoffStatus, + 4 competitors
SEGMENTATION_CSV = ROOT / "data" / "segmentation.csv"

# Competitor (aggregator) columns — "column F onwards" in the client's sheet.
COMPETITOR_COLS = ["CollegeDunia", "Shiksha", "Careers360", "CollegeDekho"]

# CutoffStatus values that mark a "specific link" (Category 1). A merit list is
# effectively a cutoff, so it counts by default; pass ``merit_list=False`` to
# require a hard cutoff only.
CAT1_STATUS_FULL = frozenset({"Official Cutoff", "Official Merit List"})
CAT1_STATUS_STRICT = frozenset({"Official Cutoff"})

# The links sheet collapses the five JEE counselling variants into a single
# "Joint Entrance Examination" row. Under a strict exact-name join these five fall
# to Category 3; ``jee_remap=True`` maps them onto the collapsed row (Official
# Cutoff) so they resolve to Category 1, matching the client's clear intent (each
# has a real JoSAA/CSAB/JAC-Delhi cutoff portal).
JEE_LINKS_KEY = "Joint Entrance Examination"
JEE_SPLIT = frozenset({
    "Joint Entrance Examination JoSAA Joint Seat Allocation (JEE Main and Advanced)",
    "Joint Entrance Examination Advanced IIT Joint Admission (JEE Advanced)",
    "Joint Entrance Examination CSAB Special Rounds (JEE Main)",
    "Joint Entrance Examination CSAB NEUT North Eastern States and Union Territories (JEE Main)",
    "Joint Entrance Examination JAC Delhi Joint Admission Counselling (JEE Main)",
})

# Aggregator domains: a Category-1 row whose "official" CutoffURL is actually one
# of these is flagged for review (the official link is really an aggregator).
_AGGREGATOR_DOMAINS = (
    "shiksha.com", "collegedekho.com", "careers360.com", "collegedunia.com",
)


@dataclass
class SegRow:
    """One exam's segmentation verdict plus the data downstream pipelines need."""

    exam: str
    category: str                 # "cat1" | "cat2" | "cat3"
    cutoff_status: str            # CutoffStatus from the links sheet ("" if unmatched)
    official_cutoff_url: str      # CutoffURL — the specific official cutoff link
    homepage: str                 # Homepage — official exam/body site
    collegedunia: str
    shiksha: str
    careers360: str
    collegedekho: str
    n_competitor_links: int
    aggregator_as_official: bool  # cat1, but CutoffURL host is an aggregator
    prose_cutoff_url: bool        # CutoffURL is prose, not a real URL
    prose_homepage: bool          # Homepage is prose, not a real URL
    jee_remapped: bool            # resolved via the JEE-collapse remap


# --------------------------------------------------------------------------
def _is_url(value: str) -> bool:
    """True if ``value`` parses as an http(s) URL with a host."""
    try:
        p = urlparse(value.strip())
    except (ValueError, AttributeError):
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def _host(value: str) -> str:
    """Lower-cased netloc of ``value`` (empty string if not a URL)."""
    try:
        return urlparse(value.strip()).netloc.lower()
    except (ValueError, AttributeError):
        return ""


def _is_aggregator(url: str) -> bool:
    host = _host(url)
    return any(host == d or host.endswith("." + d) for d in _AGGREGATOR_DOMAINS)


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV into a list of dict rows, stripping every value. Tolerant of a
    missing file (returns an empty list)."""
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(fh)]


def load_sheets(
    cut_path: Path = CUT_SHEET, links_path: Path = LINKS_SHEET,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    """Return ``(cutoff_rows, links_by_exam)``.

    ``cutoff_rows`` (cutoffexamsheet) is the canonical universe of exams; the links
    sheet is keyed by the trimmed exam name for lookup.
    """
    cut_rows = _read_csv(cut_path)
    links_rows = _read_csv(links_path)
    links_by_exam = {r["Exam"]: r for r in links_rows if r.get("Exam")}
    return cut_rows, links_by_exam


# --------------------------------------------------------------------------
def _classify_row(
    cut_row: dict[str, str],
    links_by_exam: dict[str, dict[str, str]],
    *,
    cat1_status: frozenset[str],
    jee_remap: bool,
) -> SegRow:
    exam = cut_row["Exam"].strip()
    cutoff_url = cut_row.get("CutoffURL", "").strip()
    homepage = cut_row.get("Homepage", "").strip()

    links_row = links_by_exam.get(exam)
    jee_remapped = False
    if links_row is None and jee_remap and exam in JEE_SPLIT:
        links_row = links_by_exam.get(JEE_LINKS_KEY)
        jee_remapped = links_row is not None

    status = (links_row or {}).get("CutoffStatus", "").strip()
    competitors = {c: (links_row or {}).get(c, "").strip() for c in COMPETITOR_COLS}
    n_competitor_links = sum(1 for v in competitors.values() if v)

    # Priority-ordered, evaluate 1 -> 2 -> 3, stop at first match. The order is
    # load-bearing: the many cat-1 rows that ALSO carry competitor links must
    # resolve to cat-1, not leak into cat-2.
    if links_row is not None and status in cat1_status:
        category = "cat1"
    elif links_row is not None and n_competitor_links > 0:
        category = "cat2"
    else:
        category = "cat3"

    return SegRow(
        exam=exam,
        category=category,
        cutoff_status=status,
        official_cutoff_url=cutoff_url,
        homepage=homepage,
        collegedunia=competitors["CollegeDunia"],
        shiksha=competitors["Shiksha"],
        careers360=competitors["Careers360"],
        collegedekho=competitors["CollegeDekho"],
        n_competitor_links=n_competitor_links,
        aggregator_as_official=(category == "cat1" and _is_aggregator(cutoff_url)),
        prose_cutoff_url=(bool(cutoff_url) and not _is_url(cutoff_url)),
        prose_homepage=(bool(homepage) and not _is_url(homepage)),
        jee_remapped=jee_remapped,
    )


def segment(
    *,
    merit_list: bool = True,
    jee_remap: bool = False,
    cut_path: Path = CUT_SHEET,
    links_path: Path = LINKS_SHEET,
) -> list[SegRow]:
    """Classify every exam in the canonical universe into cat1/cat2/cat3.

    Args:
        merit_list: count "Official Merit List" as a specific link (Category 1).
        jee_remap: map the 5 JEE-split exams onto the collapsed links row so they
            resolve to Category 1 instead of falling to Category 3.
    """
    cat1_status = CAT1_STATUS_FULL if merit_list else CAT1_STATUS_STRICT
    cut_rows, links_by_exam = load_sheets(cut_path, links_path)
    return [
        _classify_row(r, links_by_exam, cat1_status=cat1_status, jee_remap=jee_remap)
        for r in cut_rows if r.get("Exam")
    ]


def counts(rows: list[SegRow]) -> dict[str, int]:
    """Category tallies plus the total, e.g. ``{"cat1": 203, ..., "total": 321}``.

    The client target for cat1 ("Specific links") is ~160; the exact tally depends
    on the (forthcoming) updated sheet and whether "Official Merit List" counts as a
    specific link. Current sheet, defaults (merit_list=True, strict join): cat1=203,
    cat2=102, cat3=16. Without merit lists: cat1=139. With jee_remap=True: cat1=208,
    cat3=11. Treat this function's output — not any hard-coded prose — as the truth.
    """
    c = Counter(r.category for r in rows)
    return {"cat1": c["cat1"], "cat2": c["cat2"], "cat3": c["cat3"], "total": len(rows)}


def flag_summary(rows: list[SegRow]) -> dict[str, int]:
    """Counts of the review flags (aggregator-as-official, prose links, unmatched)."""
    return {
        "aggregator_as_official": sum(r.aggregator_as_official for r in rows),
        "prose_cutoff_url": sum(r.prose_cutoff_url for r in rows),
        "prose_homepage": sum(r.prose_homepage for r in rows),
        "jee_remapped": sum(r.jee_remapped for r in rows),
    }


def write_segmentation(
    rows: list[SegRow], path: Path = SEGMENTATION_CSV,
) -> Path:
    """Write the driver CSV every downstream pipeline reads. One row per exam."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(rows[0]).keys()) if rows else [f.name for f in SegRow.__dataclass_fields__.values()]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))
    return path


if __name__ == "__main__":
    rows = segment()
    c = counts(rows)
    print(f"Segmented {c['total']} exams (default: merit_list=True, strict join)")
    print(f"  cat1 (specific link)   : {c['cat1']}")
    print(f"  cat2 (competitor link) : {c['cat2']}")
    print(f"  cat3 (no link)         : {c['cat3']}")
    print("flags:", flag_summary(rows))
    alt = counts(segment(jee_remap=True))
    print(f"with --jee-remap        : cat1={alt['cat1']} cat2={alt['cat2']} cat3={alt['cat3']}")
    nm = counts(segment(merit_list=False))
    print(f"without merit list      : cat1={nm['cat1']} cat2={nm['cat2']} cat3={nm['cat3']}")
