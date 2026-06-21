"""OJEE adapter — Odisha Joint Entrance Examination (engineering counselling).

OJEE publishes a flat opening/closing-rank PDF: INSTITUTE NAME / STREAM / QUOTA /
CATEGORY / SEAT TYPE / OPENING RANK / CLOSING RANK. The table is *borderless*, so
pdfplumber's line-based grid only finds the header — the data rows are recovered by
position: each page's repeating header gives the column x-anchors, and every data
word is bucketed into a column by its x-coordinate (midpoint boundaries). Long
branch names overflow the STREAM column into QUOTA, so the branch is reconstructed
from both and the quota token (HS/OS/AI) is pulled back out.

``load_cached`` serves a bundled parsed snapshot; ``fetch_latest`` re-parses live.
"""
from __future__ import annotations

import io
import logging
import re
from collections import defaultdict

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.registry import register
from cutoffs.schema import empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_PDF_SPECS = [
    {"url": "https://cdnbbsr.s3waas.gov.in/s36832a7b24bc06775d02b7406880b93fc/uploads/2025/05/2025052291.pdf",
     "year": 2024, "round": "Final"},
]
# Header labels in column order (first word of each column header).
_HDR = ["INSTITUTE", "STREAM", "QUOTA", "CATEGORY", "SEAT", "OPENING", "CLOSING"]
# The QUOTA / CATEGORY / SEAT-TYPE columns are narrow and their data values don't
# line up with the header anchors, so they're extracted from the middle blob by
# their (fixed) vocabularies rather than by x-position.
_SEAT_RE = re.compile(r"(Gender Neutral|Female Only|Male Only|PWD)", re.I)
_CAT_RE = re.compile(
    r"\b(General|OBC[- ]?NCL|OBC|SEBC|SC|ST|EWS|PWD|PH|TFW|ESM|GC)\b", re.I)
_QUOTA_RE = re.compile(r"\b(HS|OS|AI|NRI|GC)\b")
_GENDER = {"gender neutral": "Gender-Neutral", "female only": "Female-only",
           "male only": "Male", "pwd": "PwD"}
_DEDUP_COLS = ["Institute", "Branch", "Category", "Quota", "Gender", "Year",
               "OpeningRank", "ClosingRank"]


def _rank(value: str) -> int | None:
    m = re.match(r"\d+", value or "")
    return int(m.group(0)) if m else None


def parse_ojee_pdf(data: bytes, *, year: int, round_label: str,
                   source_url: str) -> pd.DataFrame:
    """Parse the (borderless) OJEE OR-CR PDF into normalized unified-schema rows."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return empty_frame()
    records: list[dict] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                words = page.extract_words()
                inst = [w for w in words if w["text"].upper() == "INSTITUTE"]
                if not inst:
                    continue
                htop = inst[0]["top"]
                band = [w for w in words if htop - 12 <= w["top"] <= htop + 6]
                anchors: dict[str, float] = {}
                for w in band:
                    t = w["text"].upper()
                    if t in _HDR and t not in anchors:
                        anchors[t] = w["x0"]
                if len(anchors) < 7:
                    continue
                b = [anchors[h] for h in _HDR]
                rowmap: dict[int, list] = defaultdict(list)
                for w in words:
                    if w["top"] <= htop + 6:
                        continue
                    rowmap[round(w["top"])].append(w)
                for top in sorted(rowmap):
                    cells = [""] * 7
                    for w in sorted(rowmap[top], key=lambda x: x["x0"]):
                        # left-anchored: the column is the rightmost header whose
                        # anchor is at/left of the word, so a wide institute/branch
                        # that overflows keeps its words.
                        ci = max(i for i, x in enumerate(b) if w["x0"] >= x - 4)
                        cells[ci] = (cells[ci] + " " + w["text"]).strip()
                    institute, closing = cells[0].strip(), _rank(cells[6])
                    if not institute or closing is None:
                        continue
                    # QUOTA + CATEGORY + SEAT bleed together; pull each out of the
                    # combined blob by its fixed vocabulary, then the leftover is
                    # branch overflow to fold back onto the STREAM column.
                    blob = " ".join(c for c in cells[2:5] if c).strip()
                    seat = _SEAT_RE.search(blob)
                    cat = _CAT_RE.search(blob)
                    quota = _QUOTA_RE.search(blob)
                    leftover = blob
                    for m in (seat, cat, quota):
                        if m:
                            leftover = leftover.replace(m.group(0), " ", 1)
                    branch = " ".join(p for p in (cells[1].strip(),
                                                  " ".join(leftover.split())) if p)
                    records.append({
                        "Body": "OJEE", "Exam": "OJEE", "Level": "UG",
                        "State": "Odisha", "Institute": institute,
                        "Branch": branch or None,
                        "Quota": quota.group(1) if quota else None,
                        "Category": cat.group(1) if cat else None,
                        "Gender": _GENDER.get(seat.group(1).lower(), seat.group(1)) if seat else None,
                        "Year": year, "Round": round_label,
                        "OpeningRank": _rank(cells[5]), "ClosingRank": closing,
                        "SourceURL": source_url,
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
class OJEE(CutoffSource):
    meta = SourceMeta(
        name="ojee",
        exam="OJEE",
        level="UG",
        states=("Odisha",),
        data_format="pdf",
        body_label="OJEE",
        website="https://ojee.nic.in/",
        source_url="https://ojee.nic.in/",
    )

    def load_cached(self) -> pd.DataFrame:
        return _dedup(self.normalize(read_bundled("ojee_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            try:
                resp = fetch(spec["url"], timeout=90.0, retries=1)
                df = parse_ojee_pdf(resp.content, year=spec["year"],
                                    round_label=spec["round"], source_url=spec["url"])
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("ojee fetch_latest skipped %s: %s", spec["url"], exc)
        if not frames:
            return self.load_cached()
        return _dedup(pd.concat(frames, ignore_index=True))
