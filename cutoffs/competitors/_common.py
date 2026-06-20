"""Shared toolkit for the competitor scrapers.

Two layers, deliberately separated so the parsing logic is unit-testable without
a network or pandas:

- **Pure stdlib** (testable here): ``extract_next_data`` / ``extract_initial_state``
  (+ ``balanced_json``), ``headings_before_tables`` (an ``html.parser`` walker that
  attributes the nearest preceding heading to each ``<table>``), ``coerce_rank``
  (sci-notation / comma tolerant), ``category_columns`` / ``detect_roles`` (column
  role detection by regex), ``harvest_pdf_links``.
- **Lazy heavy** (needs httpx/curl_cffi/pandas, runs in the build env):
  ``fetch_html``, ``tables_from_html``, ``rows_from_tables``.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

# A realistic desktop-Chrome UA — CollegeDunia gates bot UAs (403) but serves a
# browser UA (200); the other sites are happy with it too.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------------
# Network (lazy) — never raises; returns "" on any failure or non-200.
# --------------------------------------------------------------------------
def fetch_html(url: str, *, timeout: float = 30.0, impersonate: bool = False,
               follow_redirects: bool = True) -> str:
    """Fetch ``url`` and return its HTML, or "" on failure / block / non-200.

    ``impersonate`` first tries ``curl_cffi`` (chrome TLS fingerprint) for the
    Akamai-gated sites (Shiksha); falls back to httpx with a browser UA.
    """
    if not url:
        return ""
    if impersonate:
        try:
            from curl_cffi import requests as creq  # type: ignore

            r = creq.get(url, impersonate="chrome", timeout=timeout)
            if r.status_code == 200:
                return r.text
        except Exception:  # noqa: BLE001 — optional dep / blocked -> try httpx
            pass
    try:
        import httpx

        with httpx.Client(headers={"User-Agent": BROWSER_UA},
                          follow_redirects=follow_redirects, timeout=timeout) as client:
            r = client.get(url)
            return r.text if r.status_code == 200 else ""
    except Exception:  # noqa: BLE001 — tolerant by design
        return ""


def tables_from_html(html: str) -> list:
    """Parse every ``<table>`` into a DataFrame (lazy pandas). [] on failure."""
    if not html:
        return []
    try:
        import io

        import pandas as pd

        return pd.read_html(io.StringIO(html))
    except Exception:  # noqa: BLE001 — no tables / parse error -> []
        return []


# --------------------------------------------------------------------------
# JSON blob extraction (pure stdlib).
# --------------------------------------------------------------------------
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S)


def extract_next_data(html: str) -> dict | None:
    """Return the parsed ``__NEXT_DATA__`` JSON blob (CollegeDunia) or None."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except (ValueError, TypeError):
        return None


def balanced_json(text: str, start: int = 0) -> str | None:
    """Return the JSON object substring starting at the first ``{`` at/after ``start``.

    Scans with brace-depth tracking that respects strings/escapes, so it captures a
    full nested object (unlike a naive non-greedy regex). None if no balanced object.
    """
    i = text.find("{", start)
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


_INITIAL_STATE_RE = re.compile(r'window\.INITIAL_STATE\s*=\s*', re.S)


def extract_initial_state(html: str) -> dict | None:
    """Return the parsed ``window.INITIAL_STATE`` object (Careers360) or None."""
    m = _INITIAL_STATE_RE.search(html or "")
    if not m:
        return None
    blob = balanced_json(html, m.end())
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------
# Rank / number coercion (pure stdlib).
# --------------------------------------------------------------------------
# Ranks are positive; no leading sign (a stray "-" is a blank, not a negative rank).
_NUM_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
# A cell expressed as a "200-500" / "200 to 500" range rather than two columns.
_RANGE_RE = re.compile(r"^\s*(\d[\d,]*)\s*(?:-|–|—|to)\s*(\d[\d,]*)\s*$", re.I)


def coerce_rank(value: object) -> int | None:
    """Parse a rank cell to int, tolerating commas, blanks, and sci-notation.

    ``"3.16E+04"`` -> 31600, ``"1,234"`` -> 1234, ``"-"``/``""`` -> None. Negative
    inputs are read as their positive magnitude (ranks are never negative).
    """
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s or s.lower() in {"-", "na", "n/a", "nan", "none", "tba", "--"}:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        return int(round(float(m.group(0))))
    except (ValueError, OverflowError):
        return None


def rank_range(value: object) -> tuple[int, int] | None:
    """If ``value`` is a "200-500" style range, return ``(low, high)``; else None."""
    if value is None:
        return None
    m = _RANGE_RE.match(str(value).strip())
    if not m:
        return None
    lo, hi = coerce_rank(m.group(1)), coerce_rank(m.group(2))
    return (lo, hi) if lo is not None and hi is not None else None


def looks_like_percentile(value: object) -> bool:
    """True if ``value`` is a decimal in [0, 100] — a percentile/score, not a rank.

    Used so wide percentile tables (MHT-CET/KCET/NEET) don't get their ``99.87``
    rounded into ``closing_rank``. Requires a decimal point, so integer ranks
    (``"50"``, ``"99"``) are never misread as percentiles.
    """
    if value is None:
        return False
    s = str(value).strip().rstrip("%").replace(",", "")
    if "." not in s:
        return False
    try:
        f = float(s)
    except ValueError:
        return False
    return 0.0 <= f <= 100.0


# --------------------------------------------------------------------------
# Heading -> table attribution (pure stdlib html.parser).
# --------------------------------------------------------------------------
class _HeadingTableParser(HTMLParser):
    """Record, for each ``<table>`` in document order, the nearest preceding heading.

    A ``<caption>`` belongs to its OWN enclosing table (it is the table's first
    child), so it overwrites that table's heading rather than leaking to the next
    table as a preceding-sibling heading would.
    """

    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._cur = ""
        self._in_heading = False
        self._in_caption = False
        self._buf: list[str] = []
        self.table_headings: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in self._HEADING_TAGS:
            self._in_heading = True
            self._buf = []
        elif tag == "caption":
            self._in_caption = True
            self._buf = []
        elif tag == "table":
            self.table_headings.append(self._cur)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HEADING_TAGS and self._in_heading:
            self._in_heading = False
            self._cur = " ".join("".join(self._buf).split()).strip()
        elif tag == "caption" and self._in_caption:
            self._in_caption = False
            text = " ".join("".join(self._buf).split()).strip()
            if text and self.table_headings:
                self.table_headings[-1] = text  # caption -> its own table

    def handle_data(self, data: str) -> None:
        if self._in_heading or self._in_caption:
            self._buf.append(data)


def headings_before_tables(html: str) -> list[str]:
    """For each ``<table>`` (in order), the most recent preceding heading text."""
    parser = _HeadingTableParser()
    try:
        parser.feed(html or "")
    except Exception:  # noqa: BLE001 — malformed HTML still yields what we parsed
        pass
    return parser.table_headings


def harvest_pdf_links(html: str, base_url: str = "") -> list[str]:
    """Absolute URLs of every linked ``.pdf`` (dedup, order-preserving)."""
    found = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html or "", re.I)
    return list(dict.fromkeys(urljoin(base_url, h) for h in found))


# --------------------------------------------------------------------------
# Column role detection (pure stdlib regex).
# --------------------------------------------------------------------------
_ROLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("closing_rank", re.compile(r"clos|cr\b|last\s*rank|cutoff\s*rank", re.I)),
    ("opening_rank", re.compile(r"open|or\b|first\s*rank|start", re.I)),
    ("cutoff_percentile", re.compile(r"percentile", re.I)),
    ("cutoff_score_or_marks", re.compile(r"score|marks", re.I)),
    ("counselling_round", re.compile(r"round", re.I)),
    ("year", re.compile(r"\byear\b|^\s*20\d{2}\s*$", re.I)),
    ("category", re.compile(r"categor|caste|quota\s*type", re.I)),
    ("quota", re.compile(r"quota|region|domicile|home\s*state", re.I)),
    ("gender", re.compile(r"gender|female|male", re.I)),
    ("branch_or_course", re.compile(r"branch|course|program|specialis|stream|degree", re.I)),
    ("institute_name", re.compile(r"college|institut|university|nit|iit|nlu", re.I)),
]

# Column headers that are themselves a reservation category (wide tables where
# categories are columns and cells are ranks) — used for melt.
_CATEGORY_HEADER_RE = re.compile(
    r"^(general|open|gen|ur|obc(?:-ncl)?|sc|st|ews|pwd|ph|gm|"
    r"obc\s*ncl|general-ews|gen-ews|crl)$", re.I)


def detect_roles(columns: list[str]) -> dict[str, str]:
    """Map a role -> the first column name that matches it (best-effort)."""
    roles: dict[str, str] = {}
    for col in columns:
        name = str(col)
        for role, pat in _ROLE_PATTERNS:
            if role not in roles and pat.search(name):
                roles[role] = col
                break
    return roles


def category_columns(columns: list[str]) -> list[str]:
    """Columns whose header is itself a reservation category (for wide->long melt)."""
    return [c for c in columns if _CATEGORY_HEADER_RE.match(str(c).strip())]


# --------------------------------------------------------------------------
# Generic table -> raw rows (lazy pandas).
# --------------------------------------------------------------------------
def _is_na(value: object) -> bool:
    try:
        import pandas as pd

        return bool(pd.isna(value))
    except Exception:  # noqa: BLE001
        return value is None


def _row_cells(col_names: list[str], values: list) -> dict[str, str | None]:
    """Map column-name -> stringified cell, suffixing duplicate headers (``.1`` …)
    so no value is dropped and ``raw_cells`` stays lossless. The first occurrence
    keeps the bare name, so name-based role lookups (which pick the first match)
    still resolve.
    """
    cells: dict[str, str | None] = {}
    dup: dict[str, int] = {}
    for name, val in zip(col_names, values):
        key = name
        while key in cells:
            dup[name] = dup.get(name, 0) + 1
            key = f"{name}.{dup[name]}"
        cells[key] = None if _is_na(val) else str(val)
    return cells


def _melt_categories(columns: list[str], roles: dict[str, str]) -> list[str]:
    """Category-header columns to melt — with the rank/category collision resolved.

    ``"Open"``/``"Gen"`` matches both the opening-rank role and the category-header
    regex. A LONE such header sitting beside a real rank column is that rank column,
    not a reservation category, so it must not be melted. In a genuine wide table
    (>=2 category columns whose cells ARE the ranks) the category meaning wins and
    every category column is kept.
    """
    cat_cols = category_columns(columns)
    opening, closing = roles.get("opening_rank"), roles.get("closing_rank")
    if len(cat_cols) <= 1 and (opening in cat_cols or closing in cat_cols):
        cat_cols = [c for c in cat_cols if c != opening and c != closing]
    return cat_cols


def _fill_ranks(base: dict, cells: dict, roles: dict[str, str]) -> None:
    """Populate opening/closing rank on ``base`` from the detected rank columns,
    splitting a single ``"200-500"`` range cell and keeping it in ``rank_range_raw``.
    """
    open_cell = cells.get(roles.get("opening_rank", ""))
    close_cell = cells.get(roles.get("closing_rank", ""))
    for cell in (close_cell, open_cell):
        rng = rank_range(cell)
        if rng:
            base["rank_range_raw"] = str(cell).strip()
            base["opening_rank"], base["closing_rank"] = rng
            return
    base["opening_rank"] = coerce_rank(open_cell)
    base["closing_rank"] = coerce_rank(close_cell)


def _rows_from_table(tbl, *, idx: int, caption: str, default_pdf: str | None,
                     competitor: str, exam: str, slug: str, page_url: str,
                     page_type: str, year: object) -> list[dict]:
    """RAW_COLUMNS-shaped rows for one table object (``.columns`` + ``.iterrows()``).

    Split out from :func:`rows_from_tables` so the melt/role logic is unit-testable
    with a stub table — no network or pandas read_html needed.
    """
    from cutoffs.competitors import RAW_COLUMNS

    try:
        col_names = [str(c) for c in tbl.columns]
    except Exception:  # noqa: BLE001
        return []
    roles = detect_roles(col_names)
    cat_cols = _melt_categories(col_names, roles)

    out: list[dict] = []
    for _, series in tbl.iterrows():
        cells = _row_cells(col_names, list(series))
        institute = cells.get(roles.get("institute_name", ""), "") or caption
        branch = cells.get(roles.get("branch_or_course", ""), "")
        base = {c: None for c in RAW_COLUMNS}
        base.update(
            source_competitor=competitor, exam=exam, exam_slug=slug,
            page_url=page_url, page_type=page_type, table_index=idx,
            table_caption=caption, institute_name=institute, branch_or_course=branch,
            counselling_round=cells.get(roles.get("counselling_round", "")),
            year=cells.get(roles.get("year", "")) or (str(year) if year else None),
            gender=cells.get(roles.get("gender", "")),
            quota=cells.get(roles.get("quota", "")),
            raw_cells=json.dumps(cells, ensure_ascii=False), pdf_url=default_pdf,
        )

        if cat_cols:
            # Wide table: each category column is a separate (melted) row. A decimal
            # 0-100 cell is a percentile/score, not a rank, so route it accordingly.
            for cc in cat_cols:
                val = cells.get(cc)
                row = dict(base)
                row.update(category=cc, raw_header_label=cc, raw_cell_value=val)
                if looks_like_percentile(val):
                    row["cutoff_percentile"] = val
                else:
                    row["closing_rank"] = coerce_rank(val)
                out.append(row)
        else:
            base.update(
                category=cells.get(roles.get("category", "")),
                cutoff_percentile=cells.get(roles.get("cutoff_percentile", "")),
                cutoff_score_or_marks=cells.get(roles.get("cutoff_score_or_marks", "")),
            )
            _fill_ranks(base, cells, roles)
            out.append(base)
    return out


def rows_from_tables(html: str, *, competitor: str, exam: str, slug: str,
                     page_url: str, page_type: str, year: object = None) -> list[dict]:
    """Turn every table on a page into RAW_COLUMNS-shaped dict rows (best-effort).

    Wide category-column tables are melted (one row per category); otherwise the
    detected opening/closing/percentile/score columns are used. The full original
    row is always kept in ``raw_cells`` (JSON) so nothing is lost.
    """
    tables = tables_from_html(html)
    headings = headings_before_tables(html)
    pdf_links = harvest_pdf_links(html, page_url)
    default_pdf = pdf_links[0] if pdf_links else None

    out: list[dict] = []
    for idx, tbl in enumerate(tables):
        caption = headings[idx] if idx < len(headings) else ""
        out += _rows_from_table(
            tbl, idx=idx, caption=caption, default_pdf=default_pdf,
            competitor=competitor, exam=exam, slug=slug, page_url=page_url,
            page_type=page_type, year=year)
    return out
