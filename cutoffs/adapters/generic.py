"""Generic, catalog-driven HTML source.

Unlike the registered per-body adapters, this is *data-driven*: the UI builds one
from a catalog row (exam + cutoff URL) so any of the 317 catalogued exams can be
point-scraped on demand. It wraps :func:`cutoffs.scrape.scrape_cutoffs`, so it
returns real rows for sources that publish HTML rank tables and an empty frame
(never an error) for the many that hide data behind forms/PDFs/JS.
"""
from __future__ import annotations

import pandas as pd

from cutoffs.scrape import scrape_cutoffs
from cutoffs.source import CutoffSource, SourceMeta


class GenericHTMLSource(CutoffSource):
    """A CutoffSource backed by a single cutoff-page URL (not registry-bound)."""

    # Placeholder so the ABC's concrete-subclass check passes; real metadata is
    # set per-instance in __init__.
    meta = SourceMeta(name="generic", exam="Generic", level="UG")

    def __init__(self, exam: str, url: str, *, body: str = "",
                 level: str = "UG", state: str = "", year: int | None = None):
        self.url = url
        self.year = year
        self.body = body or exam
        self.level = level
        self.state = state
        self.meta = SourceMeta(
            name=f"generic:{exam}", exam=exam, level=level,
            states=(state,) if state else (), data_format="html",
        )

    def load_cached(self) -> pd.DataFrame:
        # No bundled cache for arbitrary catalog URLs; scrape on demand instead.
        return self.empty()

    def fetch_latest(self) -> pd.DataFrame:
        return self.normalize(
            scrape_cutoffs(self.url, exam=self.meta.exam, body=self.body,
                           year=self.year, level=self.level, state=self.state)
        )
