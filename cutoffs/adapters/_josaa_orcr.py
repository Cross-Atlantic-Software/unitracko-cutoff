"""Driver for the JoSAA opening/closing-rank (OR-CR) ASP.NET form.

JoSAA publishes OR-CR behind a cascading ASP.NET form (round -> institute type
-> institute -> branch -> seat type -> Submit). Choosing "ALL" at every level
and submitting returns the *entire* grid for a (year, round): every IIT / NIT /
IIIT / GFTI, every academic program, seat type and gender — ~10k-13k rows per
round, ~130 institutes / ~1000 institute+program "colleges".

Two endpoints share this exact form:
  - currentorcr.aspx                -> the live cycle (current year)
  - openingclosingrankarchieve.aspx -> past years (extra ddlYear dropdown)

The driver replays the __VIEWSTATE / __EVENTVALIDATION between each cascading
postback (the server validates posted option values against the last-rendered
control), parses the grid with pandas, and conforms it to the unified schema.

Used by both the one-shot snapshot builder (``scripts/scrape_josaa.py``) and the
JoSAA adapter's ``fetch_latest`` (live refresh).
"""
from __future__ import annotations

import io
import logging
import re
import time

import httpx
import pandas as pd

_log = logging.getLogger(__name__)

ARCHIVE_URL = (
    "https://josaa.admissions.nic.in/applicant/seatmatrix/"
    "openingclosingrankarchieve.aspx"
)
CURRENT_URL = (
    "https://josaa.admissions.nic.in/Applicant/SeatAllotmentResult/"
    "currentorcr.aspx"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_PREFIX = "ctl00$ContentPlaceHolder1$"
_HIDDEN = ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION",
           "__LASTFOCUS", "ctl00$hdnSecKey"]


def _hidden_fields(html: str) -> dict[str, str]:
    """Pull the ASP.NET state hidden inputs out of a rendered page."""
    out: dict[str, str] = {}
    for name in _HIDDEN:
        m = re.search(
            r'name=["\']' + re.escape(name) + r'["\'][^>]*value=["\']([^"\']*)["\']',
            html,
        )
        out[name] = m.group(1) if m else ""
    return out


def _options(html: str, ddl: str) -> list[tuple[str, str]]:
    """Return (value, label) option pairs for the named <select> dropdown."""
    m = re.search(
        r'<select[^>]*id=["\'][^"\']*' + ddl + r'["\'][^>]*>(.*?)</select>',
        html, re.I | re.S,
    )
    if not m:
        return []
    return re.findall(
        r'<option[^>]*value=["\']([^"\']*)["\'][^>]*>([^<]*)</option>', m.group(1)
    )


class _Form:
    """Stateful driver for one JoSAA OR-CR ASP.NET form (current or archive)."""

    def __init__(self, client: httpx.Client, url: str):
        self.c = client
        self.url = url
        self.sel: dict[str, str] = {}
        self.html = self.c.get(self.url).text
        self.hidden = _hidden_fields(self.html)

    def post(self, set_fields: dict[str, str], target: str) -> str:
        """Apply ``set_fields`` to the accumulated selection and post ``target``.

        Mirrors a browser: every previously-chosen dropdown value is resent so
        the server keeps the cascade state; ``target`` is the control whose
        change (or click) triggered this postback.
        """
        self.sel.update(set_fields)
        data = {
            "__EVENTTARGET": target, "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            "__VIEWSTATE": self.hidden["__VIEWSTATE"],
            "__VIEWSTATEGENERATOR": self.hidden["__VIEWSTATEGENERATOR"],
            "__EVENTVALIDATION": self.hidden["__EVENTVALIDATION"],
            "ctl00$hdnSecKey": self.hidden.get("ctl00$hdnSecKey", ""),
        }
        data.update(self.sel)
        self.html = self.c.post(self.url, data=data).text
        self.hidden = _hidden_fields(self.html)
        return self.html


def _parse_grid(html: str) -> pd.DataFrame:
    """Parse the OR-CR result grid out of the submitted page (empty if none)."""
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return pd.DataFrame()
    for t in tables:
        cols = {str(c).strip().lower() for c in t.columns}
        if {"opening rank", "closing rank"}.issubset(cols):
            return t
    return pd.DataFrame()


def to_schema(grid: pd.DataFrame, year: int, rnd: str) -> pd.DataFrame:
    """Map a raw OR-CR grid onto the unified cutoff schema columns."""
    rename = {
        "Academic Program Name": "Branch",
        "Seat Type": "Category",
        "Opening Rank": "OpeningRank",
        "Closing Rank": "ClosingRank",
    }
    out = grid.rename(columns=rename)
    out["Body"] = "JoSAA"
    out["Exam"] = "JEE Advanced / JEE Main"
    out["Level"] = "UG"
    out["State"] = "All India"
    out["Year"] = year
    out["Round"] = str(rnd)
    out["Website"] = "https://josaa.nic.in/"
    out["SourceURL"] = "https://josaa.nic.in/or-cr/"
    return out


def _fetch_round(form: _Form, *, year_field: str | None,
                 rnd_value: str) -> pd.DataFrame:
    """Drive the cascade to ALL/ALL/ALL/ALL for one round and parse the grid."""
    if year_field:  # archive form: pick the year first (autopostback)
        form.post({_PREFIX + "ddlYear": year_field}, _PREFIX + "ddlYear")
    form.post({_PREFIX + "ddlroundno": rnd_value}, _PREFIX + "ddlroundno")
    form.post({_PREFIX + "ddlInstype": "ALL"}, _PREFIX + "ddlInstype")
    form.post({_PREFIX + "ddlInstitute": "ALL"}, _PREFIX + "ddlInstitute")
    form.post({_PREFIX + "ddlBranch": "ALL"}, _PREFIX + "ddlBranch")
    # ddlSeattype has no autopostback; set it together with the Submit click.
    # (the archive renders it as ddlSeatType — send both casings harmlessly.)
    html = form.post(
        {_PREFIX + "ddlSeatType": "ALL", _PREFIX + "ddlSeattype": "ALL",
         _PREFIX + "btnSubmit": "Submit"},
        "",
    )
    return _parse_grid(html)


def _rounds_for(html: str) -> list[str]:
    """Real round values (drop the '--Select--' / '0' placeholder)."""
    return [v for v, lbl in _options(html, "ddlroundno")
            if v and v != "0" and lbl.strip() not in ("", "--Select--")]


def _select_rounds(rounds: list[str], mode: str) -> list[str]:
    """Pick which rounds to pull for a year.

    ``"all"``  every round; ``"ends"`` the first and final round only (round 1
    offers the widest program list before seats consolidate; the final round
    carries the authoritative closing ranks).
    """
    ordered = sorted(rounds, key=lambda v: int(v) if v.isdigit() else 0)
    if mode == "ends" and len(ordered) > 1:
        return [ordered[0], ordered[-1]]
    return ordered


def _client() -> httpx.Client:
    headers = {"User-Agent": _UA, "Referer": ARCHIVE_URL,
               "Content-Type": "application/x-www-form-urlencoded"}
    return httpx.Client(headers=headers, timeout=120, follow_redirects=True)


def scrape_archive(years: list[int] | None = None, rounds_mode: str = "ends",
                   delay: float = 0.6) -> pd.DataFrame:
    """Scrape OR-CR for the given years from the archive. Unified schema.

    years:       admission years (archive exposes ~2016..latest). None => latest.
    rounds_mode: ``"ends"`` (round 1 + final round) or ``"all"`` rounds.
    """
    frames: list[pd.DataFrame] = []
    with _client() as c:
        probe = _Form(c, ARCHIVE_URL)
        year_opts = {lbl.strip(): val for val, lbl in _options(probe.html, "ddlYear")
                     if val and val != "0"}
        avail = sorted((int(y) for y in year_opts if y.isdigit()), reverse=True)
        if not avail:
            raise RuntimeError("JoSAA archive exposed no year options")
        targets = [y for y in (years or [avail[0]]) if y in avail]
        _log.info("years available=%s targeting=%s", avail, targets)

        for yr in targets:
            form = _Form(c, ARCHIVE_URL)
            form.post({_PREFIX + "ddlYear": year_opts[str(yr)]}, _PREFIX + "ddlYear")
            rounds = _select_rounds(_rounds_for(form.html), rounds_mode)
            _log.info("year %s rounds=%s", yr, rounds)
            for rnd in rounds:
                form = _Form(c, ARCHIVE_URL)  # fresh state per round
                grid = _fetch_round(form, year_field=year_opts[str(yr)],
                                    rnd_value=rnd)
                if grid.empty:
                    _log.warning("year %s round %s: no grid", yr, rnd)
                    continue
                frames.append(to_schema(grid, yr, rnd))
                _log.info("year %s round %s: %d rows", yr, rnd, len(grid))
                time.sleep(delay)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def scrape_current(rounds_mode: str = "ends") -> pd.DataFrame:
    """Scrape the live cycle from currentorcr.aspx (no year dropdown).

    Returns the unified schema, or an empty frame if the current cycle has not
    published any round yet. The ``Year`` is taken from the page's footer year
    if present, else left blank for the caller to stamp.
    """
    frames: list[pd.DataFrame] = []
    with _client() as c:
        probe = _Form(c, CURRENT_URL)
        rounds = _select_rounds(_rounds_for(probe.html), rounds_mode)
        year = _current_year(probe.html)
        _log.info("current cycle rounds=%s year=%s", rounds, year)
        for rnd in rounds:
            form = _Form(c, CURRENT_URL)
            grid = _fetch_round(form, year_field=None, rnd_value=rnd)
            if grid.empty:
                continue
            frames.append(to_schema(grid, year, rnd))
            _log.info("current round %s: %d rows", rnd, len(grid))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _current_year(html: str) -> int | None:
    """Best-effort 4-digit year from the current OR-CR page (e.g. a heading)."""
    m = re.search(r"\b(20\d{2})\b", html)
    return int(m.group(1)) if m else None
