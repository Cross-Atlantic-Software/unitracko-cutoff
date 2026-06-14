"""The adapter contract: every data source implements ``CutoffSource``.

A source has descriptive metadata plus two ways to produce data, both returning
the unified schema:

- ``load_cached()``  — reuse an existing public dataset (the fast path).
- ``fetch_latest()`` — scrape the newest data from the source (the refresh path).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

import pandas as pd

from cutoffs.schema import empty_frame, normalize


@dataclass(frozen=True)
class SourceMeta:
    """Static description of a cutoff source, used by the UI to list/iterate."""

    name: str               # unique key, e.g. "josaa"
    exam: str               # e.g. "JEE Advanced"
    level: str              # "UG" or "PG"
    states: tuple[str, ...] = field(default_factory=tuple)  # scope; () => All India
    data_format: str = "html"  # "html", "pdf", "json", ...


class CutoffSource(abc.ABC):
    """Abstract base class for all cutoff adapters."""

    #: Subclasses MUST set this to a SourceMeta instance.
    meta: SourceMeta

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Allow abstract intermediates, but concrete subclasses need meta.
        if not getattr(cls, "__abstractmethods__", None):
            if not isinstance(getattr(cls, "meta", None), SourceMeta):
                raise TypeError(
                    f"{cls.__name__} must define a class attribute "
                    f"`meta: SourceMeta`"
                )

    @abc.abstractmethod
    def load_cached(self) -> pd.DataFrame:
        """Return cached/public data conformed to the unified schema."""
        raise NotImplementedError

    @abc.abstractmethod
    def fetch_latest(self) -> pd.DataFrame:
        """Scrape and return the newest data conformed to the unified schema."""
        raise NotImplementedError

    def empty(self) -> pd.DataFrame:
        """Convenience: an empty, schema-conformant frame for fallbacks."""
        return empty_frame()

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convenience: conform an arbitrary frame to the unified schema."""
        return normalize(df)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        m = self.meta
        return f"<{type(self).__name__} name={m.name!r} exam={m.exam!r}>"
