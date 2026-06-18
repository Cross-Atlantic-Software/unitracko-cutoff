"""JoSAA adapter — Joint Seat Allocation Authority (IITs/NITs/IIITs/GFTIs).

- ``load_cached()``  reuses a bundled public OR-CR snapshot (the fast path).
- ``fetch_latest()`` makes a best-effort live attempt against the JoSAA OR-CR
  archive and falls back to the cached snapshot if the site is unreachable or
  its page shape has changed. This keeps the frontend working regardless.
"""

from __future__ import annotations

import io
import logging

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_ORCR_URL = (
    "https://josaa.admissions.nic.in/applicant/seatallotmentresult/"
    "currentallotmentresult.aspx"
)


@register
class JoSAA(CutoffSource):
    meta = SourceMeta(
        name="josaa",
        exam="JEE Advanced / JEE Main",
        level="UG",
        states=(),  # All India
        data_format="html",
        body_label="JoSAA",
        website="https://josaa.nic.in/",
        source_url="https://josaa.admissions.nic.in/applicant/seatallotmentresult/",
    )

    def load_cached(self) -> pd.DataFrame:
        """Return the bundled public OR-CR snapshot, conformed to the schema."""
        return self.normalize(read_bundled("josaa_cached.csv"))

    def fetch_latest(self) -> pd.DataFrame:
        """Best-effort live pull; fall back to cached on any problem.

        A full scrape of the cascading ASP.NET form is out of scope here; this
        verifies reachability and the parse path, then defers to the cached
        snapshot so the pipeline is never left empty.
        """
        try:
            resp = fetch(_ORCR_URL, timeout=15)
            # pandas 3.0 treats a bare string as a path/URL; wrap in StringIO so
            # the live HTML is parsed as literal markup (not silently swallowed).
            tables = pd.read_html(io.StringIO(resp.text))
            frames = [t for t in tables if self._looks_like_orcr(t)]
            if frames:
                return self.normalize(self._reshape(pd.concat(frames)))
        except Exception as exc:
            # Network error, page changed, or no parseable table: fall back.
            _log.debug("josaa fetch_latest fell back to cached: %s", exc)
        return self.load_cached()

    @staticmethod
    def _looks_like_orcr(table: pd.DataFrame) -> bool:
        cols = {str(c).strip().lower() for c in table.columns}
        return {"opening rank", "closing rank"}.issubset(cols)

    def _reshape(self, table: pd.DataFrame) -> pd.DataFrame:
        """Map a live OR-CR table's columns onto the unified schema."""
        rename = {
            "Institute": "Institute",
            "Academic Program Name": "Branch",
            "Seat Type": "Category",
            "Quota": "Quota",
            "Gender": "Gender",
            "Opening Rank": "OpeningRank",
            "Closing Rank": "ClosingRank",
        }
        out = table.rename(columns=rename)
        out["Body"] = self.meta.body_label
        out["Exam"] = self.meta.exam
        out["Level"] = self.meta.level
        out["State"] = "All India"
        return out
