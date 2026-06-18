"""Shared test fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from cutoffs.schema import COLUMNS


@pytest.fixture
def sample_rows() -> pd.DataFrame:
    """A small, already-canonical sample dataset.

    Built column-keyed (not positional) so it stays valid as the schema grows;
    any canonical column not specified here is left null via reindex.
    """
    data = [
        {"Body": "JoSAA", "Exam": "JEE Advanced", "Level": "UG", "State": "All India",
         "Year": 2024, "Round": "1", "Institute": "IIT Bombay",
         "Branch": "Computer Science and Engineering", "Category": "OPEN",
         "Quota": "AI", "Gender": "Gender-Neutral", "OpeningRank": 1, "ClosingRank": 66},
        {"Body": "JoSAA", "Exam": "JEE Advanced", "Level": "UG", "State": "All India",
         "Year": 2024, "Round": "1", "Institute": "IIT Delhi",
         "Branch": "Computer Science and Engineering", "Category": "OPEN",
         "Quota": "AI", "Gender": "Gender-Neutral", "OpeningRank": 67, "ClosingRank": 110},
        {"Body": "JoSAA", "Exam": "JEE Advanced", "Level": "UG", "State": "All India",
         "Year": 2024, "Round": "2", "Institute": "IIT Madras",
         "Branch": "Electrical Engineering", "Category": "OBC-NCL",
         "Quota": "AI", "Gender": "Gender-Neutral", "OpeningRank": 500, "ClosingRank": 1200},
        {"Body": "MHT-CET", "Exam": "MHT-CET", "Level": "UG", "State": "Maharashtra",
         "Year": 2024, "Round": "1", "Institute": "COEP Pune",
         "Branch": "Computer Engineering", "Category": "OPEN",
         "Quota": "HS", "Gender": "Gender-Neutral", "OpeningRank": 10, "ClosingRank": 350},
    ]
    return pd.DataFrame(data).reindex(columns=COLUMNS)
