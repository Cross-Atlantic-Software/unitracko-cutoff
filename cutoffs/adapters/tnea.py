"""TNEA adapter — Tamil Nadu Engineering Admissions (DoTE / Anna University).

TN admits on +2 marks (no entrance exam); DoTE publishes community-wise cutoffs as
a flat PDF table: COLLEGE CODE / COLLEGE NAME / BRANCH CODE / BRANCH NAME, then one
column per community (OC, BC, BCM, MBC, SC, SCA, ST) holding the closing value.

The main *academic* engineering cutoff lives only on the JS portal
(cutoff.tneaonline.org), which is Cloudflare-Turnstile + encrypted-API gated. The
open official PDFs — the Vocational and B.Arch **rank** cutoffs — are parsed here
(rank values, so they sit in ClosingRank cleanly). ``load_cached`` serves a bundled
parsed snapshot; ``fetch_latest`` re-parses the live PDFs.
"""
from __future__ import annotations

import io
import logging
import re

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.registry import register
from cutoffs.schema import empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_BASE = "https://static.tneaonline.org/docs/"
_PDF_SPECS = [
    {"file": "Vocational_2024_Rank_Cutoff.pdf", "year": 2024, "round": "Vocational"},
    {"file": "BArch_2024_Rank_Cutoff.pdf", "year": 2024, "round": "B.Arch"},
]
# The reservation-community columns to melt (others are meta columns).
_COMMUNITY = {"OC", "BC", "BCM", "MBC", "SC", "SCA", "ST", "MBCDNC", "DNC", "BCO"}
_DEDUP_COLS = ["Institute", "Branch", "Category", "Round", "Year", "ClosingRank"]


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()


def parse_tnea_pdf(data: bytes, *, year: int, round_label: str,
                   source_url: str) -> pd.DataFrame:
    """Parse one TNEA community-cutoff PDF into normalized unified-schema rows."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return empty_frame()
    records: list[dict] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table or len(table) < 2:
                        continue
                    cols = [_clean(c).upper() for c in table[0]]
                    name_i = next((i for i, c in enumerate(cols)
                                   if "COLLEGE NAME" in c), None)
                    branch_i = next((i for i, c in enumerate(cols)
                                     if "BRANCH NAME" in c), None)
                    comm = {i: c for i, c in enumerate(cols) if c in _COMMUNITY}
                    if name_i is None or not comm:
                        continue
                    for row in table[1:]:
                        if len(row) <= max(max(comm), name_i):
                            continue
                        institute = _clean(row[name_i])
                        if not institute:
                            continue
                        branch = _clean(row[branch_i]) if branch_i is not None else ""
                        for ci, community in comm.items():
                            v = _clean(row[ci])
                            if not re.fullmatch(r"\d+", v):
                                continue
                            records.append({
                                "Body": "TNEA", "Exam": "TNEA", "Level": "UG",
                                "State": "Tamil Nadu", "Institute": institute,
                                "Branch": branch, "Category": community,
                                "Round": round_label, "Year": year,
                                "ClosingRank": int(v), "SourceURL": source_url,
                            })
    except Exception:  # noqa: BLE001 — a malformed page never sinks the parse
        return normalize(pd.DataFrame(records)) if records else empty_frame()
    if not records:
        return empty_frame()
    return normalize(pd.DataFrame(records))


def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in _DEDUP_COLS if c in df.columns]
    return df.drop_duplicates(subset=cols).reset_index(drop=True)


@register
class TNEA(CutoffSource):
    meta = SourceMeta(
        name="tnea",
        exam="TNEA",
        level="UG",
        states=("Tamil Nadu",),
        data_format="pdf",
        body_label="TNEA",
        website="https://www.tneaonline.org/",
        source_url="https://cutoff.tneaonline.org/",
    )

    def load_cached(self) -> pd.DataFrame:
        return _dedup(self.normalize(read_bundled("tnea_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            url = _BASE + spec["file"]
            try:
                resp = fetch(url, timeout=90.0, retries=1)
                df = parse_tnea_pdf(resp.content, year=spec["year"],
                                    round_label=spec["round"], source_url=url)
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("tnea fetch_latest skipped %s: %s", url, exc)
        if not frames:
            return self.load_cached()
        return _dedup(pd.concat(frames, ignore_index=True))
