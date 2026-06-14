"""One-off deep-test probe of every cutoff URL in cutoffexamsheet.xlsx.

Concurrently fetches each "Specific Cutoff Page Link", classifies how scrapeable
it is right now (HTML tables with rank-like headers? PDF? JS-only? blocked?),
and writes a coverage report to data/source_probe.csv.

Run:  python scripts/probe_sources.py
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "cutoffexamsheet.xlsx"
OUT = ROOT / "data" / "source_probe.csv"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"}

RANK_WORDS = re.compile(r"opening rank|closing rank|cut\s*off|cutoff|last rank|"
                        r"rank|merit", re.I)
TABLE_RE = re.compile(r"<table", re.I)
SCRIPT_RE = re.compile(r"<script", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def classify(status: int | None, ctype: str, text: str, err: str) -> tuple[str, dict]:
    """Return (bucket, details) describing scrapeability."""
    info: dict = {"n_tables": 0, "rank_headers": 0, "text_len": 0, "n_scripts": 0}
    if err:
        return ("error", info)
    if status and status >= 400:
        return (f"http_{status}", info)
    ctype = (ctype or "").lower()
    if "pdf" in ctype or text[:5] == "%PDF-":
        return ("pdf", info)
    if "html" not in ctype and "xml" not in ctype and "<html" not in text.lower():
        return ("non_html", info)

    n_tables = len(TABLE_RE.findall(text))
    n_scripts = len(SCRIPT_RE.findall(text))
    visible = TAG_RE.sub(" ", text)
    text_len = len(visible.split())
    # count tables whose surrounding markup mentions rank/cutoff words
    rank_headers = len(RANK_WORDS.findall(text))
    info.update(n_tables=n_tables, rank_headers=rank_headers,
                text_len=text_len, n_scripts=n_scripts)

    if n_tables >= 1 and rank_headers >= 1:
        return ("html_table_rank", info)
    if n_tables >= 1:
        return ("html_table_norank", info)
    # very little visible text but lots of script => SPA / JS-rendered
    if text_len < 250 and n_scripts >= 3:
        return ("js_only", info)
    if rank_headers >= 1:
        return ("html_rank_notable", info)
    return ("html_other", info)


async def probe(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                exam: str, url: str) -> dict:
    row = {"exam": exam, "url": url, "host": "", "status": None,
           "ctype": "", "bucket": "", "n_tables": 0, "rank_headers": 0,
           "text_len": 0, "n_scripts": 0, "err": ""}
    s = str(url).strip()
    if not s.lower().startswith("http"):
        row["bucket"] = "no_url"
        return row
    row["host"] = urlparse(s).netloc.lower().replace("www.", "")
    async with sem:
        try:
            r = await client.get(s, headers=HEADERS, timeout=12.0,
                                  follow_redirects=True)
            row["status"] = r.status_code
            row["ctype"] = r.headers.get("content-type", "")
            text = r.text[:600_000]
            bucket, info = classify(r.status_code, row["ctype"], text, "")
            row.update(bucket=bucket, **info)
        except Exception as e:  # noqa: BLE001
            row["err"] = type(e).__name__
            row["bucket"] = "error"
    return row


async def main() -> None:
    df = pd.read_excel(XLSX)
    df.columns = ["exam", "home", "cutoff"]
    sem = asyncio.Semaphore(24)
    async with httpx.AsyncClient(verify=False) as client:
        tasks = [probe(client, sem, r.exam, r.cutoff)
                 for r in df.itertuples(index=False)]
        rows = await asyncio.gather(*tasks)
    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    print(f"Probed {len(out)} URLs -> {OUT}\n")
    print("=== bucket counts ===")
    print(out["bucket"].value_counts().to_string())
    print("\n=== top scrapeable (html_table_rank), by host ===")
    good = out[out.bucket == "html_table_rank"]
    print(f"{len(good)} URLs with HTML tables + rank headers")
    print(good["host"].value_counts().head(25).to_string())
    print("\n=== sample html_table_rank rows ===")
    for _, r in good.head(20).iterrows():
        print(f"  {r.exam[:48]:48s} | tbl={r.n_tables:3d} rk={r.rank_headers:4d} | {r.url[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
