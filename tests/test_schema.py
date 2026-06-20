"""Tests for the unified schema and tolerant normalization."""

from __future__ import annotations

import pandas as pd

from cutoffs.schema import COLUMNS, DTYPES, empty_frame, normalize


def test_columns_are_the_canonical_set():
    assert COLUMNS == [
        "Body", "Exam", "Website", "Level", "State", "City", "Institute",
        "Program", "Branch", "Category", "CategoryGroup", "Quota", "Gender",
        "Year", "Round", "OpeningRank", "ClosingRank", "SourceURL",
    ]


def test_empty_frame_has_canonical_columns_and_dtypes():
    df = empty_frame()
    assert list(df.columns) == COLUMNS
    assert len(df) == 0
    assert str(df["Year"].dtype) == "Int64"
    assert str(df["OpeningRank"].dtype) == "Int64"
    assert str(df["Body"].dtype) == "string"


def test_normalize_adds_missing_columns_as_null():
    df = pd.DataFrame({"Body": ["JoSAA"], "ClosingRank": [100]})
    out = normalize(df)
    assert list(out.columns) == COLUMNS
    assert out["Body"].iloc[0] == "JoSAA"
    assert pd.isna(out["Institute"].iloc[0])
    assert out["ClosingRank"].iloc[0] == 100


def test_normalize_drops_extra_columns():
    df = pd.DataFrame({"Body": ["X"], "Junk": [1], "Note": ["ignore me"]})
    out = normalize(df)
    assert "Junk" not in out.columns
    assert "Note" not in out.columns


def test_normalize_reorders_columns():
    scrambled = pd.DataFrame({c: ["x"] for c in reversed(COLUMNS)})
    out = normalize(scrambled)
    assert list(out.columns) == COLUMNS


def test_normalize_coerces_ranks_with_commas_and_blanks():
    df = pd.DataFrame({
        "OpeningRank": ["1,234", " 56 ", "", "-", "bad"],
        "ClosingRank": [1234.0, 56, None, 7, 8],
    })
    out = normalize(df)
    assert out["OpeningRank"].tolist()[:2] == [1234, 56]
    assert pd.isna(out["OpeningRank"].iloc[2])  # ""
    assert pd.isna(out["OpeningRank"].iloc[3])  # "-"
    assert pd.isna(out["OpeningRank"].iloc[4])  # "bad" -> NA, no crash
    assert out["ClosingRank"].iloc[0] == 1234


def test_normalize_never_crashes_on_empty():
    assert len(normalize(pd.DataFrame())) == 0
    assert list(normalize(pd.DataFrame()).columns) == COLUMNS


def test_normalize_trims_text_and_blanks_to_na():
    df = pd.DataFrame({"Institute": ["  IIT Bombay  ", "", "   "]})
    out = normalize(df)
    assert out["Institute"].iloc[0] == "IIT Bombay"
    assert pd.isna(out["Institute"].iloc[1])
    assert pd.isna(out["Institute"].iloc[2])


def test_normalize_never_crashes_on_duplicate_columns():
    # Regression: a repeated header made df[col] a DataFrame and crashed coercion.
    df = pd.DataFrame([["JoSAA", "extra", 100]],
                      columns=["Body", "Body", "ClosingRank"])
    out = normalize(df)
    assert list(out.columns) == COLUMNS
    assert out["Body"].iloc[0] == "JoSAA"   # first duplicate kept
    assert out["ClosingRank"].iloc[0] == 100


def test_dtypes_cover_every_column():
    assert set(DTYPES) == set(COLUMNS)
