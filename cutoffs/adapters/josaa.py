"""JoSAA adapter — Joint Seat Allocation Authority (IITs/NITs/IIITs/GFTIs).

- ``load_cached()``  reuses a bundled public OR-CR snapshot (the fast path).
- ``fetch_latest()`` makes a best-effort live attempt against the JoSAA OR-CR
  archive and falls back to the cached snapshot if the site is unreachable or
  its page shape has changed. This keeps the frontend working regardless.
"""

from __future__ import annotations

import logging

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._josaa_orcr import scrape_archive, scrape_current
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)


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
        """Return the bundled full OR-CR snapshot (gzipped), conformed.

        The snapshot is the real scrape (all institutes/programs/categories for
        recent years), built by ``scripts/scrape_josaa.py``. Falls back to the
        legacy uncompressed CSV if the gzip isn't present.
        """
        try:
            return self.normalize(read_bundled("josaa_cached.csv.gz"))
        except FileNotFoundError:
            return self.normalize(read_bundled("josaa_cached.csv"))

    def fetch_latest(self) -> pd.DataFrame:
        """Live pull of the full OR-CR grid; fall back to cached on any problem.

        Tries the current cycle first, then the most recent archived year, by
        driving the cascading ASP.NET form to "ALL" at every level. If the site
        is unreachable or has published nothing yet, returns the cached snapshot
        so the pipeline is never left empty.
        """
        for label, fn in (("current", scrape_current),
                          ("archive", scrape_archive)):
            try:
                df = fn()
                if df is not None and not df.empty:
                    return self.normalize(df)
            except Exception as exc:  # network error / page shape changed
                _log.debug("josaa fetch_latest %s path failed: %s", label, exc)
        return self.load_cached()
