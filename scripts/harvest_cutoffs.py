"""Harvest pass: try to extract REAL cutoff rows from every official cutoff URL.

For each catalogued exam that has an official cutoff link, fetch it live and run
the appropriate parser (HTML tables -> generic scraper; PDF -> pdfplumber). Any
rows found are tagged with that exam's metadata and written to
data/harvested.parquet. Prints a per-source report so we see exactly which
official portals actually expose machine-readable cutoffs today.

Run:  python scripts/harvest_cutoffs.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pandas as pd

from cutoffs.adapters._pdf import parse_cutoff_pdf
from cutoffs.catalog import load_catalog
from cutoffs.schema import COLUMNS, empty_frame, normalize
from cutoffs.scrape import (
    extract_tables,
    is_cutoff_table,
    map_table,
    _flatten_columns,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "harvested.parquet"
REPORT = ROOT / "data" / "harvest_report.csv"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA,
           "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
           "Accept-Language": "en-US,en;q=0.9"}


async def fetch(client, sem, exam: str, url: str) -> dict:
    out = {"exam": exam, "url": url, "status": None, "ctype": "",
           "content": b"", "err": ""}
    async with sem:
        for attempt in range(2):
            try:
                r = await client.get(url, headers=HEADERS, timeout=20.0,
                                     follow_redirects=True)
                out["status"] = r.status_code
                out["ctype"] = r.headers.get("content-type", "").lower()
                out["content"] = r.content[:4_000_000]
                return out
            except Exception as e:  # noqa: BLE001
                out["err"] = type(e).__name__
        return out


def parse_one(meta: dict, resp: dict) -> pd.DataFrame:
    """Pick HTML vs PDF parser based on content; return normalized rows."""
    content = resp["content"]
    if not content:
        return empty_frame()
    is_pdf = "pdf" in resp["ctype"] or content[:5] == b"%PDF-"
    common = dict(exam=meta["Exam"], body=meta["Body"] or meta["Exam"],
                  level=meta["Level"], state=meta["State"])
    if is_pdf:
        try:
            return parse_cutoff_pdf(content, **common)
        except Exception:  # noqa: BLE001
            return empty_frame()
    # HTML
    try:
        text = content.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return empty_frame()
    frames = []
    for tbl in extract_tables(text):
        try:
            if is_cutoff_table(_flatten_columns(tbl)):
                m = map_table(tbl, **common)
                if not m.empty:
                    frames.append(m)
        except Exception:  # noqa: BLE001
            continue
    return normalize(pd.concat(frames, ignore_index=True)) if frames else empty_frame()


async def main() -> None:
    cat = load_catalog()
    work = cat[cat["CutoffURL"].astype(str).str.strip() != ""].copy()
    print(f"Harvesting {len(work)} official cutoff URLs…")

    sem = asyncio.Semaphore(16)
    async with httpx.AsyncClient(verify=False) as client:
        responses = await asyncio.gather(*[
            fetch(client, sem, r.Exam, str(r.CutoffURL)) for r in work.itertuples()
        ])
    by_exam = {r["exam"]: r for r in responses}

    all_rows, report = [], []
    for r in work.itertuples():
        meta = {"Exam": r.Exam, "Body": r.Body, "Level": r.Level, "State": r.State}
        resp = by_exam.get(r.Exam, {})
        df = parse_one(meta, resp) if resp else empty_frame()
        rows = len(df)
        kind = ("pdf" if ("pdf" in resp.get("ctype", "")
                          or resp.get("content", b"")[:5] == b"%PDF-") else "html")
        report.append({"Exam": r.Exam, "Body": r.Body, "url": r.CutoffURL,
                       "status": resp.get("status"), "kind": kind, "rows": rows,
                       "err": resp.get("err", "")})
        if rows:
            all_rows.append(df)

    rep = pd.DataFrame(report)
    rep.to_csv(REPORT, index=False)
    if all_rows:
        harvested = normalize(pd.concat(all_rows, ignore_index=True))
        harvested = harvested[harvested["ClosingRank"].notna()
                              | harvested["OpeningRank"].notna()]
        harvested.to_parquet(OUT, index=False)
    else:
        harvested = empty_frame()
        harvested.to_parquet(OUT, index=False)

    hit = rep[rep["rows"] > 0]
    print(f"\n=== RESULT ===")
    print(f"sources that yielded rows: {len(hit)} / {len(rep)}")
    print(f"total harvested rows: {len(harvested)}  -> {OUT}")
    print(f"\nstatus distribution:\n{rep['status'].value_counts(dropna=False).to_string()}")
    if len(hit):
        print(f"\n=== sources WITH data (top 30) ===")
        for _, x in hit.sort_values("rows", ascending=False).head(30).iterrows():
            print(f"  {int(x['rows']):5d}  [{x['kind']}]  {x['Exam'][:46]:46s} {str(x['url'])[:55]}")
    print(f"\nfull report -> {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
