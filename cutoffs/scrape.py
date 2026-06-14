"""Generic HTML cutoff scraper — the *depth* layer for plain-table sources.

Given a cutoff-page URL, politely fetch it, find HTML ``<table>``s that look like
cutoff tables (opening/closing/cut-off rank columns), and map their columns onto
the unified schema heuristically. Deliberately tolerant: any failure (network,
SSL, no parseable table, weird columns) yields an empty schema-frame, never an
exception — so it is safe to point at hundreds of heterogeneous sources.

This covers the ~15-20 sources that publish real HTML rank tables today. PDF and
JS-rendered sources are handled by dedicated framework adapters instead.
"""
from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass

import httpx
import pandas as pd

from cutoffs.schema import empty_frame, normalize

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Header-name fragments mapped to schema columns. Order within a target matters:
# the first fragment that appears in a column name wins.
_OPENING = re.compile(r"open", re.I)
_CLOSING = re.compile(r"clos|cut.?off|last rank|closing", re.I)
_RANK = re.compile(r"rank|merit|cut.?off", re.I)
_INSTITUTE = re.compile(r"institut|college|university|campus|name of (the )?(institut|college)", re.I)
_BRANCH = re.compile(r"branch|course|program|programme|stream|discipline|subject|"
                     r"specialis|specializ|academic program", re.I)
_CATEGORY = re.compile(r"categor|seat type|caste|community|reservation", re.I)
_QUOTA = re.compile(r"quota|seat pool|home state|all india", re.I)
_GENDER = re.compile(r"gender|female|male", re.I)
_YEAR = re.compile(r"\byear\b", re.I)
_ROUND = re.compile(r"round|phase|allotment", re.I)


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None
    error: str
    html: str


def fetch(url: str, *, retries: int = 2, timeout: float = 15.0,
          delay: float = 0.6) -> FetchResult:
    """Polite GET with retries; tolerates bad TLS. Never raises."""
    last = ""
    for attempt in range(retries + 1):
        try:
            with httpx.Client(headers=_HEADERS, timeout=timeout,
                              follow_redirects=True, verify=False) as client:
                r = client.get(url)
            if r.status_code < 400 and r.text:
                return FetchResult(url, True, r.status_code, "", r.text)
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        if attempt < retries:
            time.sleep(delay * (attempt + 1))  # simple backoff
    return FetchResult(url, False, None, last, "")


def extract_tables(html: str) -> list[pd.DataFrame]:
    """Parse every HTML table; tolerate malformed markup. Empty list on failure."""
    if not html:
        return []
    try:
        return pd.read_html(io.StringIO(html))  # lxml backend
    except Exception:  # noqa: BLE001
        return []


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse MultiIndex headers to single strings and de-duplicate names.

    Duplicate column names are made unique (``name``, ``name.1``, …) so a later
    ``df[name]`` always returns a Series, never a DataFrame.
    """
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [" ".join(str(p) for p in tup if str(p) != "nan").strip()
                      for tup in df.columns]
    names = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    seen: dict[str, int] = {}
    unique = []
    for n in names:
        if n in seen:
            seen[n] += 1
            unique.append(f"{n}.{seen[n]}")
        else:
            seen[n] = 0
            unique.append(n)
    df = df.copy()
    df.columns = unique
    return df


def _find(cols: list[str], rx: re.Pattern, *, exclude: re.Pattern | None = None) -> str | None:
    for c in cols:
        if rx.search(c) and (exclude is None or not exclude.search(c)):
            return c
    return None


def _series(df: pd.DataFrame, col: str | None):
    """Return column ``col`` as a Series (first match if duplicated), else <NA>."""
    if not col:
        return pd.NA
    s = df[col]
    if isinstance(s, pd.DataFrame):  # belt-and-braces: duplicate name slipped through
        s = s.iloc[:, 0]
    return s


def is_cutoff_table(df: pd.DataFrame) -> bool:
    """A table is a cutoff table if it has any rank/cut-off-like column."""
    cols = [str(c) for c in df.columns]
    return any(_RANK.search(c) for c in cols) and len(df) >= 1


def map_table(df: pd.DataFrame, *, exam: str, body: str, year: int | None = None,
              level: str | None = None, state: str | None = None) -> pd.DataFrame:
    """Map one raw table's columns onto the unified schema (best effort).

    Never raises: malformed/duplicate columns degrade to <NA>, not exceptions.
    """
    try:
        df = _flatten_columns(df)
    except Exception:  # noqa: BLE001
        return empty_frame()
    cols = list(df.columns)

    # Closing must exclude opening columns ("Opening Cutoff" matches _CLOSING via
    # the cut-off alternative), else the opening value overwrites the closing one.
    closing = _find(cols, _CLOSING, exclude=_OPENING)
    opening = _find(cols, _OPENING)
    # Fall back: a lone "rank"/"merit" column is the closing rank.
    if closing is None:
        closing = _find(cols, _RANK, exclude=_OPENING)
    if closing is None and opening is None:
        return empty_frame()

    try:
        out = pd.DataFrame(index=df.index)
        out["Institute"] = _series(df, _find(cols, _INSTITUTE))
        out["Branch"] = _series(df, _find(cols, _BRANCH))
        out["Category"] = _series(df, _find(cols, _CATEGORY))
        out["Quota"] = _series(df, _find(cols, _QUOTA))
        out["Gender"] = _series(df, _find(cols, _GENDER))
        out["Round"] = _series(df, _find(cols, _ROUND))
        out["OpeningRank"] = _series(df, opening)
        out["ClosingRank"] = _series(df, closing)

        year_col = _find(cols, _YEAR)
        out["Year"] = _series(df, year_col) if year_col else year
        out["Body"] = body or exam
        out["Exam"] = exam
        out["Level"] = level if level else pd.NA
        out["State"] = state if state else pd.NA

        norm = normalize(out)
    except Exception:  # noqa: BLE001 - honor the never-raise contract
        return empty_frame()
    # Keep only rows that carry at least one usable rank — drops header/footer junk.
    has_rank = norm["ClosingRank"].notna() | norm["OpeningRank"].notna()
    return norm[has_rank].reset_index(drop=True)


def scrape_cutoffs(url: str, *, exam: str, body: str = "", year: int | None = None,
                   level: str | None = None, state: str | None = None) -> pd.DataFrame:
    """Top-level: fetch ``url`` and return all cutoff rows found, normalized."""
    res = fetch(url)
    if not res.ok:
        return empty_frame()
    frames = []
    for tbl in extract_tables(res.html):
        if is_cutoff_table(_flatten_columns(tbl)):
            mapped = map_table(tbl, exam=exam, body=body, year=year,
                               level=level, state=state)
            if not mapped.empty:
                frames.append(mapped)
    if not frames:
        return empty_frame()
    return normalize(pd.concat(frames, ignore_index=True))
