"""Harvest the direct cutoff files found by the find-cutoff-pdf-files workflow.

Fetches each official PDF/HTML-table URL, parses it (KEAM matrix parser for
cee.kerala.gov.in last-rank files, generic pdfplumber/HTML otherwise), tags rows
with catalog metadata, and reports rows-per-source. Writes data/harvested2.parquet.

Usage:  python scripts/harvest_found_pdfs.py path/to/workflow_result.json
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pandas as pd

from cutoffs.adapters._pdf import parse_cutoff_pdf
from cutoffs.adapters.keam import parse_keam_pdf
from cutoffs.catalog import load_catalog
from cutoffs.schema import empty_frame, normalize
from cutoffs.scrape import extract_tables, is_cutoff_table, map_table, _flatten_columns

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "harvested2.parquet"
REPORT = ROOT / "data" / "harvested2_report.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "text/html,application/pdf,*/*"}


def load_records(path: Path) -> list[dict]:
    import json
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw.get("result", raw).get("records", [])
    return raw


async def fetch_all(urls: list[str]) -> dict[str, bytes]:
    sem = asyncio.Semaphore(10)
    out: dict[str, bytes] = {}

    async def one(client, u):
        async with sem:
            try:
                r = await client.get(u, headers=HEADERS, timeout=45.0,
                                     follow_redirects=True)
                if r.status_code < 400:
                    out[u] = r.content[:8_000_000]
            except Exception:  # noqa: BLE001
                pass

    async with httpx.AsyncClient(verify=False) as client:
        await asyncio.gather(*[one(client, u) for u in urls])
    return out


def parse(meta: dict, url: str, content: bytes) -> pd.DataFrame:
    if not content:
        return empty_frame()
    common = dict(exam=meta["Exam"], body=meta["Body"] or meta["Exam"],
                  level=meta["Level"], state=meta["State"])
    is_pdf = content[:5] == b"%PDF-"
    if is_pdf and "cee.kerala.gov.in" in url and "lastrank" in url:
        return normalize(parse_keam_pdf(content, exam=meta["Exam"]))
    if is_pdf:
        return parse_cutoff_pdf(content, **common)
    # HTML table
    text = content.decode("utf-8", errors="ignore")
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


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    recs = [r for r in load_records(Path(argv[1])) if r.get("pdf")]
    cat = load_catalog().set_index("Exam")
    urls = [r["pdf"] for r in recs]
    blobs = asyncio.run(fetch_all(urls))

    all_rows, report = [], []
    for r in recs:
        exam, url = r["exam"], r["pdf"]
        meta = {"Exam": exam,
                "Body": str(cat["Body"].get(exam, "") or ""),
                "Level": str(cat["Level"].get(exam, "UG") or "UG"),
                "State": str(cat["State"].get(exam, "") or "")}
        df = parse(meta, url, blobs.get(url, b""))
        df = df[df["ClosingRank"].notna() | df["OpeningRank"].notna()] if len(df) else df
        report.append({"Exam": exam, "url": url, "fetched": url in blobs,
                       "rows": len(df), "colleges": df["Institute"].nunique() if len(df) else 0})
        if len(df):
            all_rows.append(df)

    rep = pd.DataFrame(report).sort_values("rows", ascending=False)
    rep.to_csv(REPORT, index=False)
    harvested = normalize(pd.concat(all_rows, ignore_index=True)) if all_rows else empty_frame()
    harvested.to_parquet(OUT, index=False)

    hit = rep[rep["rows"] > 0]
    print(f"Found {len(recs)} file URLs; fetched {sum(rep['fetched'])}; "
          f"{len(hit)} yielded data -> {len(harvested)} rows, {OUT}\n")
    for _, x in hit.iterrows():
        print(f"  {int(x['rows']):5d} rows / {int(x['colleges']):3d} colleges  "
              f"{x['Exam'][:46]:46s} {str(x['url'])[:48]}")
    miss = rep[(rep["rows"] == 0) & rep["fetched"]]
    if len(miss):
        print(f"\nfetched but unparsed ({len(miss)} — odd layout/scanned/login):")
        for _, x in miss.head(15).iterrows():
            print(f"     {x['Exam'][:46]:46s} {str(x['url'])[:55]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
