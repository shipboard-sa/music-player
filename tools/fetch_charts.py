"""
Purpose: Download the Billboard Year-End Hot 100 tables (1967-1990) from Wikipedia into one CSV.
Version: v1 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player playlist tooling; safe to re-run or delete.
Architecture: feeds tools/catalog.py (the playlist catalogue / report). Reads Wikipedia's
    parse API, one page per year ("Billboard Year-End Hot 100 singles of YYYY"), takes the
    first table with No./Title/Artist columns. Writes tools/data/yearend_hot100.csv
    (year, rank, title, artist).
Invocation: python tools/fetch_charts.py [first_year last_year]  (default 1967 1990);
    needs internet; generic User-Agent (no personal email).
"""
import csv, io, re, sys, time
from pathlib import Path
import pandas as pd
import requests

UA = {"User-Agent": "SailboatMusicCatalog/1.0 (personal playlist tool)"}
OUT = Path(__file__).parent / "data" / "yearend_hot100.csv"

RAW = Path(__file__).parent / "data" / "raw"

def year_html(year: int) -> str:
    cached = RAW / f"{year}.html"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    for attempt in range(6):  # Wikipedia rate-limits bursts (HTTP 429): back off and retry
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=30, params={
            "action": "parse", "page": f"Billboard Year-End Hot 100 singles of {year}",
            "prop": "text", "format": "json", "redirects": 1})
        if r.status_code != 429: break
        time.sleep(10 * (attempt + 1))
    r.raise_for_status()
    html = r.json()["parse"]["text"]["*"]
    RAW.mkdir(parents=True, exist_ok=True)
    cached.write_text(html, encoding="utf-8")
    time.sleep(3)
    return html

def year_table(year: int) -> pd.DataFrame:
    html = year_html(year)
    for t in pd.read_html(io.StringIO(html)):
        cols = [str(c).lower() for c in t.columns]
        if any("title" in c for c in cols) and any("artist" in c for c in cols):
            t.columns = cols
            rank = next((c for c in cols if c.startswith("no") or "rank" in c or c in ("#", "pos", "№")), None)  # № = "№"
            title = next(c for c in cols if "title" in c)
            artist = next(c for c in cols if "artist" in c)
            ranks = t[rank] if rank else range(1, len(t) + 1)  # some years have no rank column
            if not rank: print(f"  {year}: no rank column {cols} - using row order")
            return pd.DataFrame({"year": year, "rank": list(ranks), "title": t[title], "artist": t[artist]})
    raise ValueError(f"no chart table for {year}")

def clean(s: str) -> str:
    return re.sub(r"\[\w+\]", "", str(s)).strip().strip('"').strip()

def main():
    a, b = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (1967, 1990)
    rows = []
    for y in range(a, b + 1):
        df = year_table(y)
        for _, r in df.iterrows():
            rows.append({"year": y, "rank": clean(r["rank"]), "title": clean(r["title"]), "artist": clean(r["artist"])})
        print(y, len(df))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["year", "rank", "title", "artist"]); w.writeheader(); w.writerows(rows)
    print("wrote", OUT, len(rows), "rows")

if __name__ == "__main__":
    main()
