"""Category-3 — the "no link at all" exams.

Client rule for cat-3: for each exam with neither a specific official cutoff link
nor a competitor link, "check on google / python script — if able to fill the table
as first one (just make another table - so we know)." The goal is therefore to
produce, WHERE POSSIBLE, a SEPARATE table shaped like the cat-1 14-column deliverable
(Exam Name … Closing Rank, Link - Data Taken from), kept distinct from the cat-1
output.

``run_cat3`` does exactly this: it web-searches each exam (Ecosia — Google's SERP
is JS-walled to servers and DuckDuckGo's HTML endpoint is network-blocked from many
hosts; Ecosia returns static, scrapeable results), and where a cutoff page that is
genuinely about THIS exam is found, extracts its college×rank rows (competitor table
toolkit) and projects them to the 14 deliverable columns, writing a SEPARATE
``data/cat3_cutoffs.csv``. Two gates keep it honest: a relevance gate (the exam's
distinctive tokens must appear in the result URL/title, so an obscure exam can't be
filled with a different famous exam's cutoffs) and a per-row quality gate (real
rank/percentile + real branch + a cutoff-related table caption). Every attempt is
also logged to a ``data/cat3_provenance.parquet`` audit trail (query, candidate URL,
whether a table was found, rows extracted). Neither output is ever merged into the
unified cutoff dataset — the cat-3 table is kept deliberately distinct ("so we know").

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
# DuckDuckGo's HTML endpoint is network-blocked from many hosts (0 bytes /
# timeout); Google's SERP is JS-rendered and exposes no static result links to a
# server. Ecosia serves static, server-scrapeable HTML with real result links, so
# it is the working default. ``_ddg_search`` is kept as a fallback.
_DDG_RESULT_RE = re.compile(r'uddg=([^&"\']+)')
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')
# Aggregator domains we parse well (their cutoff pages carry clean college×rank
# tables); search results are ranked to prefer these and to drop junk domains.
_PREFERRED_DOMAINS = ("collegedekho.com", "collegedunia.com", "shiksha.com",
                      "careers360.com")
_JUNK_DOMAINS_RE = re.compile(
    r"ecosia|youtube|gstatic|amazonaws|syndicatedsearch|adsense|w3\.org|"
    r"schema\.org|quora|reddit|scribd|facebook|twitter|instagram|linkedin|"
    r"wikipedia|mozilla|pinterest|t\.me|whatsapp", re.I)

# Pace Ecosia so rapid sequential queries don't trip its rate limiter (which
# degrades to an empty results page). Module-level so it spans the whole pass.
_SEARCH_MIN_INTERVAL = 4.0
_last_search_at = [0.0]

# Generic exam words that carry no identity — stripped before relevance matching
# so only the distinctive tokens (institution / place names) are compared.
_EXAM_STOPWORDS = frozenset({
    "university", "entrance", "exam", "examination", "test", "common", "of",
    "the", "and", "for", "in", "a", "an", "cet", "cutoff", "rank", "merit",
    "list", "admission", "national", "state", "college", "institute", "school",
    "bachelor", "undergraduate", "graduate", "engineering", "management",
})
_QUOTED_EXAM_RE = re.compile(r'"([^"]+)"')


def _exam_tokens(exam: str) -> list[str]:
    """Distinctive lowercase tokens of an exam name (institution / place words)."""
    words = re.findall(r"[a-z0-9]+", (exam or "").lower())
    return [w for w in words if len(w) >= 3 and w not in _EXAM_STOPWORDS]


def _is_relevant(exam: str, text: str) -> bool:
    """True if ``text`` (a URL slug or page title) is plausibly THIS exam's page.

    Obscure exams make search surface a *different* famous exam's cutoff page
    (e.g. a Vogue design test returning NIFT Delhi). Requiring enough of the
    exam's distinctive tokens to appear in the result text rejects that
    misattribution — the difference between honest 0 rows and wrong data.
    """
    tokens = _exam_tokens(exam)
    if not tokens:
        return False
    hay = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    hits = sum(1 for t in tokens if t in hay)
    return hits >= min(2, len(tokens))


def _relax_query(query: str) -> str:
    """Turn the precise ``build_query`` string into a higher-recall engine query.

    Ecosia returns nothing for the strict phrase-quoted ``"Exam" cutoff OR ...``
    form, so drop the quotes/operators and bias toward college rank tables.
    """
    bare = query.replace('"', " ").replace(" OR ", " ")
    bare = re.sub(r'\bmerit\s+list\b', " ", bare, flags=re.I)
    return f"{' '.join(bare.split())} college closing rank"


def _rank_urls(urls: list[str], exam: str = "") -> list[str]:
    """Drop junk domains; sort so an exam-relevant aggregator cutoff page leads.

    Relevance (the exam's distinctive tokens appearing in the URL slug) is the
    strongest sort key so a page that is actually about THIS exam beats a generic
    cutoff page for a different, more famous exam.
    """
    seen: set[str] = set()
    clean: list[str] = []
    for u in urls:
        if _JUNK_DOMAINS_RE.search(u):
            continue
        key = u.split("?")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        clean.append(u)
    return sorted(clean, key=lambda u: (
        0 if (exam and _is_relevant(exam, u)) else 1,
        0 if "cutoff" in u.lower() else 1,
        0 if any(d in u for d in _PREFERRED_DOMAINS) else 1))


def _exam_from_query(query: str) -> str:
    """Recover the exam name from a ``build_query`` string (the quoted phrase)."""
    m = _QUOTED_EXAM_RE.search(query or "")
    return m.group(1) if m else (query or "")


def _ecosia(query: str) -> list[str]:
    """Result URLs from Ecosia's static HTML SERP (best-effort, [] on failure)."""
    import time
    from urllib.parse import quote_plus

    wait = _SEARCH_MIN_INTERVAL - (time.time() - _last_search_at[0])
    if wait > 0:
        time.sleep(wait)
    _last_search_at[0] = time.time()
    try:
        from curl_cffi import requests as creq  # type: ignore

        r = creq.get("https://www.ecosia.org/search?q=" + quote_plus(query),
                     impersonate="chrome", timeout=20.0)
        if r.status_code != 200:
            return []
        return _HREF_RE.findall(r.text)
    except Exception:  # noqa: BLE001 — optional dep / blocked -> caller falls back
        return []


def _web_search(query: str) -> list[str]:
    """Working web search for cat-3: Ecosia (relaxed query, then precise), then DDG.

    Returns ranked candidate URLs (aggregator cutoff pages first). [] only when
    every backend is unreachable or genuinely returns nothing.
    """
    urls = _ecosia(_relax_query(query)) or _ecosia(query) or _ddg_search(query)
    return _rank_urls(urls, exam=_exam_from_query(query))[:5]


def _ddg_search(query: str) -> list[str]:
    """Top result URLs from DuckDuckGo's HTML endpoint (fallback; [] on block)."""
    from urllib.parse import quote_plus, unquote

    from cutoffs.competitors._common import fetch_html

    html = fetch_html(f"https://duckduckgo.com/html/?q={quote_plus(query)}", timeout=20.0)
    return [unquote(m) for m in _DDG_RESULT_RE.findall(html)][:5]


def _fetch_and_inspect(url: str) -> tuple[bool, int, bool]:
    from cutoffs.competitors._common import fetch_html

    # impersonate=True works for every aggregator (Akamai-gated Shiksha included)
    # and falls back to plain httpx for the rest.
    html = fetch_html(url, timeout=25.0, impersonate=True) or fetch_html(url, timeout=25.0)
    if not html:
        return (False, 0, False)
    return (True, count_tables(html), looks_like_cutoff(html))


# Reservation categories that may appear only in a table caption / heading.
_CAT_IN_CAPTION_RE = re.compile(
    r"\b(GOPEN[SH]?|OPEN|GENERAL|OBC(?:-NCL)?|SC|ST|EWS|PWD|VJ|NT|SEBC|TFWS|"
    r"LOPEN[SH]?|HOME\s*STATE|OTHER\s*STATE)\b", re.I)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_ROUND_RE = re.compile(r"\bround[\s-]*([0-9IVX]+)\b", re.I)


def _clean_institute(caption: str, exam: str) -> str:
    """A readable college name from a table caption, falling back to the exam."""
    name = re.split(r"\bcut[\s-]*off\b", caption or "", flags=re.I)[0].strip(" -–—")
    return name or (exam or "")


def _raw_to_unified(raw: dict, exam: str) -> dict | None:
    """Map one competitor RAW_COLUMNS row to a unified-schema dict, or None.

    Quality gate: keep only rows that carry an actual rank/percentile AND a real
    branch/program AND come from a table whose caption/heading is cutoff-related
    (so courses/admission-date tables that merely sit on a cutoff page are
    dropped). Year/round/category are recovered from the caption when absent.
    """
    closing = raw.get("closing_rank")
    opening = raw.get("opening_rank")
    pct = raw.get("cutoff_percentile")
    if closing is None and opening is None and not pct:
        return None
    if isinstance(closing, int) and not (0 < closing <= 2_000_000):
        return None
    branch = (raw.get("branch_or_course") or "").strip()
    caption = raw.get("table_caption") or ""
    institute_raw = (raw.get("institute_name") or "").strip()
    if not branch or branch == institute_raw or branch == caption:
        return None
    # The table itself must be a cutoff/rank table, not a courses or dates table
    # that happens to share a cutoff page.
    if not _CUTOFF_WORDS_RE.search(caption):
        return None

    category = raw.get("category")
    if not category:
        m = _CAT_IN_CAPTION_RE.search(caption)
        category = m.group(1) if m else None
    year = raw.get("year")
    if not year:
        m = _YEAR_RE.search(caption)
        year = m.group(1) if m else None
    rnd = raw.get("counselling_round")
    if not rnd:
        m = _ROUND_RE.search(caption)
        rnd = f"Round {m.group(1)}" if m else None

    return {
        "Exam": exam,
        "Institute": _clean_institute(institute_raw or caption, exam),
        "Program": branch,
        "Branch": branch,
        "Category": category,
        "Year": year,
        "Round": rnd,
        "Gender": raw.get("gender"),
        "Quota": raw.get("quota"),
        "OpeningRank": opening,
        "ClosingRank": closing,
        "CutoffPercentile": pct,
    }


def _extract_default(exam: str, url: str) -> list[dict]:
    """Extract college×rank rows from a found page into unified-schema dict rows.

    Reuses the competitor table toolkit (robust per-table parsing) and the quality
    gate above; returns [] when nothing real parses.
    """
    from cutoffs.competitors._common import fetch_html, rows_from_tables

    html = fetch_html(url, timeout=25.0, impersonate=True) or fetch_html(url, timeout=25.0)
    if not html:
        return []
    # Relevance gate: an obscure exam often surfaces a different famous exam's
    # cutoff page. Only extract when the URL slug OR the page <title> actually
    # matches this exam — otherwise we'd attribute the wrong college's ranks.
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = m.group(1)
    if not (_is_relevant(exam, url) or _is_relevant(exam, title)):
        return []

    raw_rows = rows_from_tables(html, competitor="cat3", exam=exam, slug="",
                               page_url=url, page_type="cat3_search")
    out: list[dict] = []
    seen: set[tuple] = set()
    for raw in raw_rows:
        unified = _raw_to_unified(raw, exam)
        if unified is None:
            continue
        key = (unified["Institute"], unified["Branch"], unified["Category"],
               unified["Year"], unified["OpeningRank"], unified["ClosingRank"],
               unified["CutoffPercentile"])
        if key in seen:
            continue
        seen.add(key)
        out.append(unified)
    return out


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
        search_fn=search_fn or _web_search,
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
        search_fn=search_fn or _web_search,
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
