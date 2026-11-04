"""
Purpose: Turn the catalogue report's missing chart songs into a shopping list (.xlsx) with
    store search links, so buying them is quick.
Version: v1 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player playlist tooling; read-only, safe to re-run.
Architecture: reads the "Chart 1967-1990" sheet of a catalog.py report (status Missing),
    drops songs already found under damaged file names (an optional JSON list from the
    near-match pass), and writes one row per song: year, rank, artist, title, Amazon and
    Apple Music search links, a Got-it column. Double-A-side chart entries ("A"/"B") are
    split into one row per side. Re-run catalog.py after buying to see what's left.
    A "Same title on phone" column shows any file with the same title by another artist
    (a cover, or the same act under another name - Layla is filed under Eric Clapton).
Invocation: python tools/shopping_list.py <report.xlsx> <out.xlsx> [found_elsewhere.json] [phone files.txt]
"""
import json, re, sys
from datetime import date
from urllib.parse import quote_plus

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font


def sides(title: str):
    """'Maggie May"/"Reason to Believe' -> both titles; plain titles unchanged."""
    parts = [p.strip(' "') for p in re.split(r'"\s*/\s*"', title)]
    return [p for p in parts if p] or [title]


def main(report, out, found_json=None, files_txt=None):
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from catalog import norm, path_song
    same = {}
    if files_txt:
        for f in (l.rstrip(chr(13) + chr(10)) for l in open(files_txt, encoding="utf-8")):
            for sd in (True, False):
                a, t = path_song(f, sd)
                same.setdefault(norm(t), []).append(f.split("/Music/", 1)[-1])
    found = set()
    if found_json:
        found = {(str(c[0]), str(c[1])) for c in json.load(open(found_json, encoding="utf-8"))}
    wb = openpyxl.load_workbook(report, read_only=True)
    rows = []
    for y, rk, ar, ti, status, *_ in (wb["Year-End charts"] if "Year-End charts" in wb.sheetnames else wb["Chart 1967-1990"]).iter_rows(min_row=2, values_only=True):
        if status != "Missing" or (str(y), str(rk)) in found:
            continue
        for t in sides(ti):
            q = f"{ar} {t}"
            rows.append([y, rk, ar, t,
                         f"https://www.amazon.com/s?k={quote_plus(q)}&i=digital-music",
                         f"https://music.apple.com/us/search?term={quote_plus(q)}", "",
                         " | ".join(sorted(set(same.get(norm(t), [])))[:3])])

    out_wb = Workbook()
    ws = out_wb.active
    ws.title = "Shopping list"
    out_wb.properties.title = "Missing Billboard Year-End Hot 100 songs - shopping list"
    out_wb.properties.subject = "Music Player - D:/boat/music-player/tools/shopping_list.py v1 (STANDALONE UTILITY)"
    out_wb.properties.description = f"From {report}; generated {date.today().isoformat()}"
    ws.append(["Year", "Rank", "Artist", "Title", "Amazon", "Apple Music", "Got it", "Same title on phone (cover or alias?)"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r[:4] + ["Amazon", "Apple", "", r[7]])
        ws.cell(ws.max_row, 5).hyperlink = r[4]; ws.cell(ws.max_row, 5).style = "Hyperlink"
        ws.cell(ws.max_row, 6).hyperlink = r[5]; ws.cell(ws.max_row, 6).style = "Hyperlink"
    for col, w in zip("ABCDEFGH", [6, 6, 34, 44, 9, 11, 7, 90]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    out_wb.save(out)
    print(f"{len(rows)} songs -> {out}; {sum(1 for r in rows if r[7])} have a same-title file on the phone")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4, 5):
        sys.exit(__doc__)
    main(*sys.argv[1:])
