"""Shared test fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from cutoffs.schema import COLUMNS


@pytest.fixture
def sample_rows() -> pd.DataFrame:
    """A small, already-canonical sample dataset."""
    data = [
        ("JoSAA", "JEE Advanced", "UG", "All India", 2024, "1",
         "IIT Bombay", "Computer Science and Engineering", "OPEN", "AI",
         "Gender-Neutral", 1, 66),
        ("JoSAA", "JEE Advanced", "UG", "All India", 2024, "1",
         "IIT Delhi", "Computer Science and Engineering", "OPEN", "AI",
         "Gender-Neutral", 67, 110),
        ("JoSAA", "JEE Advanced", "UG", "All India", 2024, "2",
         "IIT Madras", "Electrical Engineering", "OBC-NCL", "AI",
         "Gender-Neutral", 500, 1200),
        ("MHT-CET", "MHT-CET", "UG", "Maharashtra", 2024, "1",
         "COEP Pune", "Computer Engineering", "OPEN", "HS",
         "Gender-Neutral", 10, 350),
    ]
    return pd.DataFrame(data, columns=COLUMNS)
