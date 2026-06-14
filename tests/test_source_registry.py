"""Tests for the CutoffSource contract and the central registry."""

from __future__ import annotations

import pandas as pd
import pytest

from cutoffs.registry import (
    all_sources, clear, get_source, register, source_names,
)
from cutoffs.schema import COLUMNS
from cutoffs.source import CutoffSource, SourceMeta


@pytest.fixture(autouse=True)
def _clean_registry():
    clear()
    yield
    clear()


def _make_source(name: str):
    @register
    class _S(CutoffSource):
        meta = SourceMeta(name=name, exam="Exam", level="UG")

        def load_cached(self) -> pd.DataFrame:
            return self.normalize(pd.DataFrame({"Body": [name]}))

        def fetch_latest(self) -> pd.DataFrame:
            return self.empty()

    return _S


def test_subclass_without_meta_raises():
    with pytest.raises(TypeError):
        class _Bad(CutoffSource):
            def load_cached(self):
                return self.empty()

            def fetch_latest(self):
                return self.empty()


def test_register_and_get_source():
    _make_source("josaa")
    src = get_source("josaa")
    assert isinstance(src, CutoffSource)
    assert src.meta.name == "josaa"


def test_load_cached_returns_unified_schema():
    _make_source("josaa")
    df = get_source("josaa").load_cached()
    assert list(df.columns) == COLUMNS
    assert df["Body"].iloc[0] == "josaa"


def test_duplicate_name_raises():
    _make_source("dup")
    with pytest.raises(ValueError):
        @register
        class _Other(CutoffSource):
            meta = SourceMeta(name="dup", exam="X", level="UG")

            def load_cached(self):
                return self.empty()

            def fetch_latest(self):
                return self.empty()


def test_source_names_sorted_and_all_sources():
    _make_source("zeta")
    _make_source("alpha")
    assert source_names() == ["alpha", "zeta"]
    instances = all_sources()
    assert [s.meta.name for s in instances] == ["alpha", "zeta"]


def test_get_unknown_source_raises():
    with pytest.raises(KeyError):
        get_source("nope")


def test_empty_helper_is_schema_conformant():
    _make_source("e")
    df = get_source("e").empty()
    assert list(df.columns) == COLUMNS
    assert len(df) == 0
