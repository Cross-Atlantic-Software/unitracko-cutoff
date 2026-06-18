"""Generate curated cutoff snapshots used by the rank-predictor + trend charts.

These are *representative* public figures for marquee counseling bodies, in the
right ballpark for recent years and kept deliberately small. They are clearly
labelled as curated samples in the UI/README — refresh via the live adapters for
authoritative data. Multi-year so the year-over-year trend chart is meaningful.

Run:  python scripts/build_snapshots.py   (rewrites cutoffs/data/*_cached.csv)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from cutoffs.schema import COLUMNS as COLS  # single source of truth for the schema

DATA = Path(__file__).resolve().parent.parent / "cutoffs" / "data"


def _rows(base: list[dict], years: dict[int, float], body: str, exam: str,
          level: str, state: str, rnd: str, quota: str) -> list[dict]:
    """Expand per-institute base closing ranks across years with a yearly drift.

    Each base dict gives the *latest-year* opening/closing; older years scale by
    the factor in ``years`` so trends are monotone-ish but distinct per year.
    """
    out = []
    for yr, factor in years.items():
        for b in base:
            o = b["open"]
            c = b["close"]
            out.append({
                "Body": body, "Exam": exam, "Level": level, "State": state,
                "Year": yr, "Round": rnd, "Institute": b["inst"],
                "Branch": b["branch"], "Category": b["cat"], "Quota": quota,
                "Gender": "Gender-Neutral",
                "OpeningRank": int(round(o * factor)),
                "ClosingRank": int(round(c * factor)),
            })
    return out


# NOTE: JoSAA (JEE) is no longer a hand-curated stub. The full real OR-CR
# dataset (~130 institutes / ~1000 programs across recent years) is scraped by
# ``scripts/scrape_josaa.py`` into ``cutoffs/data/josaa_cached.csv.gz``. Run that
# script to refresh JEE; the bodies below remain small curated samples.

# --- MHT-CET (Maharashtra CET Cell), state engineering, Round 1 -------------
_MHTCET_BASE = [
    {"inst": "College of Engineering Pune (COEP)", "branch": "Computer Engineering", "cat": "OPEN", "open": 8, "close": 402},
    {"inst": "College of Engineering Pune (COEP)", "branch": "Information Technology", "cat": "OPEN", "open": 420, "close": 1180},
    {"inst": "Veermata Jijabai Technological Institute (VJTI)", "branch": "Computer Engineering", "cat": "OPEN", "open": 205, "close": 860},
    {"inst": "Veermata Jijabai Technological Institute (VJTI)", "branch": "Electronics and Telecommunication", "cat": "OPEN", "open": 910, "close": 2310},
    {"inst": "Sardar Patel Institute of Technology", "branch": "Computer Engineering", "cat": "OPEN", "open": 700, "close": 1850},
    {"inst": "Pune Institute of Computer Technology (PICT)", "branch": "Computer Engineering", "cat": "OPEN", "open": 950, "close": 2600},
]

# --- KCET (Karnataka Examination Authority), state engineering, Round 1 -----
_KCET_BASE = [
    {"inst": "University Visvesvaraya College of Engineering, Bengaluru", "branch": "Computer Science and Engineering", "cat": "GM", "open": 250, "close": 900},
    {"inst": "RV College of Engineering, Bengaluru", "branch": "Computer Science and Engineering", "cat": "GM", "open": 600, "close": 1500},
    {"inst": "BMS College of Engineering, Bengaluru", "branch": "Computer Science and Engineering", "cat": "GM", "open": 1200, "close": 2800},
    {"inst": "PES University, Bengaluru", "branch": "Computer Science and Engineering", "cat": "GM", "open": 1500, "close": 3500},
    {"inst": "National Institute of Engineering, Mysuru", "branch": "Computer Science and Engineering", "cat": "GM", "open": 3000, "close": 6500},
]

# --- WBJEE (West Bengal JEEB), state engineering, Round 1 -------------------
_WBJEE_BASE = [
    {"inst": "Jadavpur University", "branch": "Computer Science and Engineering", "cat": "OPEN", "open": 25, "close": 240},
    {"inst": "Jadavpur University", "branch": "Electronics and Telecommunication Engineering", "cat": "OPEN", "open": 300, "close": 720},
    {"inst": "Indian Institute of Engineering Science and Technology, Shibpur", "branch": "Computer Science and Technology", "cat": "OPEN", "open": 350, "close": 1100},
    {"inst": "Kalyani Government Engineering College", "branch": "Computer Science and Engineering", "cat": "OPEN", "open": 1800, "close": 4200},
]

# year -> scale factor applied to the latest-year base (older years a touch lower
# rank-number = slightly easier; produces a visible but modest trend)
_YEARS = {2022: 0.86, 2023: 0.93, 2024: 1.0}


def build() -> dict[str, pd.DataFrame]:
    out = {
        "mhtcet_cached.csv": _rows(_MHTCET_BASE, _YEARS, "MHT-CET", "MHT-CET", "UG", "Maharashtra", "1", "HS"),
        "kcet_cached.csv": _rows(_KCET_BASE, _YEARS, "KCET", "KCET", "UG", "Karnataka", "1", "HS"),
        "wbjee_cached.csv": _rows(_WBJEE_BASE, _YEARS, "WBJEE", "WBJEE", "UG", "West Bengal", "1", "HS"),
    }
    return {k: pd.DataFrame(v)[COLS] for k, v in out.items()}


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    for fname, df in build().items():
        df.to_csv(DATA / fname, index=False)
        yrs = sorted(df["Year"].unique())
        print(f"{fname:22s} {len(df):4d} rows | {df['Institute'].nunique()} institutes | years {yrs}")
