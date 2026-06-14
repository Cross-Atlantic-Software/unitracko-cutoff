"""Tests for the DuckDB query layer."""

from __future__ import annotations

import pytest

from cutoffs.query import CutoffQuery, distinct_values
from cutoffs.schema import COLUMNS
from cutoffs.storage import write_parquet


@pytest.fixture
def dataset(tmp_path, sample_rows):
    path = tmp_path / "cutoffs.parquet"
    write_parquet(sample_rows, path)
    return path


def test_no_filters_returns_everything(dataset):
    df = CutoffQuery(dataset).to_df()
    assert list(df.columns) == COLUMNS
    assert len(df) == 4


def test_equality_filter(dataset):
    df = CutoffQuery(dataset).where("Body", "MHT-CET").to_df()
    assert len(df) == 1
    assert df["Institute"].iloc[0] == "COEP Pune"


def test_empty_filter_value_is_ignored(dataset):
    df = CutoffQuery(dataset).where("Body", "").where("Year", None).to_df()
    assert len(df) == 4


def test_where_in(dataset):
    df = CutoffQuery(dataset).where_in("Branch", [
        "Computer Science and Engineering", "Computer Engineering",
    ]).to_df()
    assert len(df) == 3


def test_results_sorted_by_closing_rank(dataset):
    df = CutoffQuery(dataset).where(
        "Branch", "Computer Science and Engineering").to_df()
    assert df["ClosingRank"].tolist() == [66, 110]


def test_max_closing_rank_filter(dataset):
    df = CutoffQuery(dataset).max_closing_rank(120).to_df()
    # Rows whose ClosingRank >= 120: IIT Madras (1200), COEP (350).
    assert sorted(df["ClosingRank"].tolist()) == [350, 1200]


def test_limit(dataset):
    df = CutoffQuery(dataset).limit(2).to_df()
    assert len(df) == 2


def test_chained_filters(dataset):
    df = (
        CutoffQuery(dataset)
        .where("Body", "JoSAA")
        .where("Round", "1")
        .to_df()
    )
    assert len(df) == 2
    assert set(df["Institute"]) == {"IIT Bombay", "IIT Delhi"}


def test_unknown_column_raises(dataset):
    with pytest.raises(KeyError):
        CutoffQuery(dataset).where("Nope", "x")


def test_missing_file_returns_empty(tmp_path):
    df = CutoffQuery(tmp_path / "absent.parquet").to_df()
    assert list(df.columns) == COLUMNS
    assert len(df) == 0


def test_distinct_values(dataset):
    assert distinct_values("Body", dataset) == ["JoSAA", "MHT-CET"]
    assert distinct_values("Round", dataset) == ["1", "2"]


def test_distinct_values_missing_file(tmp_path):
    assert distinct_values("Body", tmp_path / "absent.parquet") == []
