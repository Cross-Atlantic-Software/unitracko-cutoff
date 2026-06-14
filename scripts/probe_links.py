"""Probe every catalog Homepage + CutoffURL: live status + official vs aggregator.

Writes data/link_probe.csv with, per exam, the status and an 'official' flag for
both links. A link counts as *shown-worthy* only if it is reachable (<400) AND
not an aggregator domain. Aggregators are research aids, never displayed.

Run:  python scripts/probe_links.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

from cutoffs.catalog import load_catalog

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "link_probe.csv"

# Unofficial aggregators/blogs — discovered links from these are never shown.
AGGREGATORS = {
    "shiksha.com", "careers360.com", "collegedekho.com", "getmyuni.com",
    "entrancezone.com", "collegepravesh.com", "collegeforme.in", "collegedunia.com",
    "embibe.com", "mbauniverse.com", "collegesearch.in", "successcds.net",
    "aglasem.com", "jagranjosh.com", "careerindia.com", "competishun.com",
    "vedantu.com", "byjus.com", "testbook.com", "oswaalbooks.com", "adda247.com",
    "catestseries.org", "aspirantmitraa.com", "finance.careers360.com",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"}


def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:  # noqa: BLE001
        return ""


def is_aggregator(url: str) -> bool:
    h = host_of(url)
    return any(h == a or h.endswith("." + a) for a in AGGREGATORS)


async def probe_one(client, sem, url: str) -> dict:
    out = {"url": url, "status": None, "final_host": "", "err": "", "ok": False}
    s = str(url).strip()
    if not s.lower().startswith("http"):
        out["err"] = "no_url"
        return out
    async with sem:
        try:
            r = await client.get(s, headers=HEADERS, timeout=12.0,
                                 follow_redirects=True)
            out["status"] = r.status_code
            out["final_host"] = host_of(str(r.url))
            out["ok"] = r.status_code < 400
        except Exception as e:  # noqa: BLE001
            out["err"] = type(e).__name__
    return out


async def main() -> None:
    cat = load_catalog()
    urls = sorted({u for col in ("Homepage", "CutoffURL")
                   for u in cat[col].dropna().astype(str)
                   if u.strip().lower().startswith("http")})
    sem = asyncio.Semaphore(24)
    async with httpx.AsyncClient(verify=False) as client:
        results = await asyncio.gather(*[probe_one(client, sem, u) for u in urls])
    by_url = {r["url"]: r for r in results}

    def info(url: str) -> tuple[bool, str, bool]:
        u = str(url).strip()
        r = by_url.get(u, {})
        ok = bool(r.get("ok"))
        agg = is_aggregator(u)
        showable = ok and not agg and u.lower().startswith("http")
        kind = "aggregator" if agg else ("dead" if (u.lower().startswith("http") and not ok)
                                         else ("none" if not u.lower().startswith("http") else "official"))
        return showable, kind, ok

    rows = []
    for r in cat.itertuples():
        hs, hk, _ = info(r.Homepage)
        cs, ck, _ = info(r.CutoffURL)
        rows.append({
            "Exam": r.Exam, "Body": r.Body,
            "Homepage": r.Homepage, "home_kind": hk, "home_show": hs,
            "CutoffURL": r.CutoffURL, "cutoff_kind": ck, "cutoff_show": cs,
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    print(f"Probed {len(urls)} unique URLs for {len(cat)} exams -> {OUT}\n")
    print("=== Homepage ===")
    print(df["home_kind"].value_counts().to_string())
    print("showable homepages:", df["home_show"].sum())
    print("\n=== Cutoff page ===")
    print(df["cutoff_kind"].value_counts().to_string())
    print("showable cutoff pages:", df["cutoff_show"].sum())
    need = df[~df["home_show"] | ~df["cutoff_show"]]
    print(f"\nExams needing research (home or cutoff not showable): {len(need)}")


if __name__ == "__main__":
    asyncio.run(main())
