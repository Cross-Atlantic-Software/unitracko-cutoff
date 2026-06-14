"""Tests for the Parquet storage layer."""

from __future__ import annotations

import pandas as pd

from cutoffs.schema import COLUMNS
from cutoffs.storage import append_parquet, read_parquet, write_parquet


def test_write_then_read_roundtrip(tmp_path, sample_rows):
    path = tmp_path / "cutoffs.parquet"
    write_parquet(sample_rows, path)
    assert path.exists()
    back = read_parquet(path)
    assert list(back.columns) == COLUMNS
    assert len(back) == len(sample_rows)
    assert set(back["Institute"]) == set(sample_rows["Institute"])


def test_write_normalizes_unordered_input(tmp_path):
    path = tmp_path / "c.parquet"
    messy = pd.DataFrame({"ClosingRank": ["1,000"], "Body": ["JoSAA"]})
    write_parquet(messy, path)
    back = read_parquet(path)
    assert list(back.columns) == COLUMNS
    assert back["ClosingRank"].iloc[0] == 1000
    assert back["Body"].iloc[0] == "JoSAA"


def test_read_missing_file_returns_empty_frame(tmp_path):
    back = read_parquet(tmp_path / "does_not_exist.parquet")
    assert list(back.columns) == COLUMNS
    assert len(back) == 0


def test_append_creates_then_grows(tmp_path, sample_rows):
    path = tmp_path / "c.parquet"
    append_parquet(sample_rows, path)
    assert len(read_parquet(path)) == len(sample_rows)
    append_parquet(sample_rows.head(1), path)
    assert len(read_parquet(path)) == len(sample_rows) + 1


def test_write_creates_parent_dirs(tmp_path, sample_rows):
    path = tmp_path / "nested" / "deep" / "c.parquet"
    write_parquet(sample_rows, path)
    assert path.exists()
