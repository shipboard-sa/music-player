"""
Purpose: Read-only playlist catalogue report - tags every song in the big sailing list as
    Core (the original ~550) and/or Chart (Billboard Year-End Hot 100, 1967-1990), and
    lists what's missing, dropped, duplicated and removed. Changes nothing on the phone.
Version: v3 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player playlist tooling; safe to re-run or delete.
Architecture: inputs pulled from the phone into one folder (sailing_2.m3u = current list,
    Sailing_orig.m3u = core list, sailing.m3u = damaged earlier merge, removed.log from the
    app, files.txt = `find` of every audio file on the phone), plus
    tools/data/yearend_hot100.csv from fetch_charts.py. Matching is by normalised
    artist + title taken from the Plex-style path (Music/<Artist>/<Album>/<Title>.mp3).
    v3: chart years come from the CSV (1960-1999 since 10-12); sheet 'Year-End charts'.
    v2: digit-led titles kept; near-spelling title matches flagged 'close title - check'.
    Writes an .xlsx report. Lee's rule: charts only TAG songs, never drop them.
Invocation: python tools/catalog.py <phone-dump-folder> <out.xlsx>
    (dump folder made with adb pull - see D:/boat/music-player/CHECKPOINT.md).
"""
import collections, csv, difflib, os, re, sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

HERE = Path(__file__).parent
SD_MUSIC = "/storage/4A21-0000/Music/"
INT_MUSIC = "/storage/emulated/0/Music/"
JUNK = "Doors/The Best Of The Doors/When the "   # prefix damage in sailing.m3u (08-16)


# ---------- reading ----------
def m3u_lines(p: Path):
    b = p.read_bytes()
    t = b[2:].decode("utf-16-le") if b[:2] == b"\xff\xfe" else (
        b.decode("utf-8") if _is_utf8(b) else b.decode("cp1252"))
    return [l.strip() for l in t.splitlines() if l.strip() and not l.startswith("#")]

def _is_utf8(b):
    try: b.decode("utf-8"); return True
    except UnicodeDecodeError: return False

class Library:
    """Every audio file on the phone, findable by playlist-line tail (case-insensitive)."""
    def __init__(self, files):
        self.files = files
        self.low = {f.lower(): f for f in files}
        self.wild = {re.sub(r"[^\x00-\x7f]", "?", f.lower()): f for f in files}

    def resolve(self, line):
        p = line.strip().strip('"').replace("\\", "/")
        while p.startswith("../") or p.startswith("./"): p = p.split("/", 1)[1]
        p = re.sub(r"^/?(storage/)?([0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}|emulated/\d+)/", "", p)
        tails = [p]
        while tails[-1].lower().startswith("music/"): tails.append(tails[-1][6:])
        for t in tails:
            for root in (SD_MUSIC, INT_MUSIC):
                k = (root + t).lower()
                f = self.low.get(k) or self.wild.get(re.sub(r"[^\x00-\x7f]", "?", k))
                if f: return f
        return None


# ---------- song identity ----------
def norm(s):
    s = s.lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)                       # (Remastered), [Disc 1]
    s = re.sub(r"\b(feat\.?|featuring|ft\.?|with)\b.*$", " ", s)  # featured artists
    s = s.replace("&", " and ")
    s = re.sub(r"^the\s+", "", s.strip())
    return re.sub(r"[^a-z0-9]", "", s)

def path_song(f, strip_digits=True):
    """(artist, title) from Music/<Artist>/<Album>/<NN - Title>.mp3 or a loose 'Artist - Title.mp3'.
    strip_digits=True treats any leading number as a track number ("04 Proud Mary");
    False keeps a number that may be the title ("25 or 6 to 4") unless it is clearly a
    track number ("01 - ", "01. "). Matching tries both."""
    rel = f.split("/Music/", 1)[-1]
    parts = rel.split("/")
    name = os.path.splitext(parts[-1])[0]
    # Strip a track number only in track-number form ("01 - ", "01. ", "1-03 "), never
    # a title that starts with digits ("25 or 6 to 4", "9 to 5", "99 Luftballons").
    if strip_digits:
        name = re.sub(r"^\d+[\s._-]*-?\s*", "", name)
    else:
        name = re.sub(r"^(\d{1,2}-)?\d{1,3}(\s*-\s+|\.\s+|_)", "", name)
    if len(parts) == 1 or (len(parts) == 2 and " - " in name):
        if " - " in name:
            bits = name.split(" - ")
            return bits[0], bits[-1]
        return "", name
    artist = parts[0] if parts[0].lower() not in ("kids", "music") else (parts[1] if len(parts) > 3 else parts[0])
    if " - " in name and norm(name.split(" - ")[0]) == norm(artist):
        name = name.split(" - ")[-1]
    return artist, name

def artist_ok(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb: return False
    if na in nb or nb in na: return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.7


# ---------- report ----------
def main(dump: Path, out: Path):
    files = [l.rstrip("\r\n") for l in (dump / "files.txt").open(encoding="utf-8")]
    lib = Library(files)

    current = [lib.resolve(l) for l in m3u_lines(dump / "sailing_2.m3u")]
    cur_files = list(dict.fromkeys(f for f in current if f))
    cur_unres = [l for l, f in zip(m3u_lines(dump / "sailing_2.m3u"), current) if not f]
    core_lines = m3u_lines(dump / "Sailing_orig.m3u")
    core = [lib.resolve(l) for l in core_lines]
    core_files = list(dict.fromkeys(f for f in core if f))
    old = [lib.resolve(l[len(JUNK):] if l.startswith(JUNK) else l) for l in m3u_lines(dump / "sailing.m3u")]         if (dump / "sailing.m3u").exists() else []   # retired 10-12; optional
    dropped = sorted(set(f for f in old if f) - set(cur_files))

    removed = []
    if (dump / "removed.log").exists():
        for l in (dump / "removed.log").read_text(encoding="utf-8").splitlines():
            if l.startswith("\t") and not l.strip().startswith("#"):
                f = lib.resolve(l.strip())
                if f and f not in removed: removed.append(f)

    # index the whole library by normalised title -> files
    by_title = collections.defaultdict(list)
    for f in files:
        for sd in (True, False):
            a, t = path_song(f, sd)
            if (a, f) not in by_title[norm(t)]: by_title[norm(t)].append((a, f))

    cur_set, core_set = set(cur_files), set(core_files)

    def find(artist, title):
        """Best file for a chart entry: prefer the current list, then the core, then anywhere."""
        cands = [(a, f) for a, f in by_title.get(norm(title), []) if artist_ok(a, artist)]
        quality = "exact"
        if not cands:   # small spelling differences: Ya/You, Lovin'/Loving, Pt. 2/Part II
            nt = norm(title)
            close = difflib.get_close_matches(nt, by_title.keys(), n=5, cutoff=0.88)
            cands = [(a, f) for k in close for a, f in by_title[k] if artist_ok(a, artist)]
            if cands: quality = "close title - check"
        if not cands:   # chart artist spelt differently (e.g. John Cougar vs John Mellencamp)
            same = by_title.get(norm(title), [])
            if len(set(a for a, _ in same)) == 1 and len(norm(title)) >= 8:
                cands, quality = same, "title only - check"
        if not cands: return None, ""
        cands.sort(key=lambda af: (af[1] not in cur_set, af[1] not in core_set, len(af[1])))
        return cands[0][1], quality

    charts = list(csv.DictReader((HERE / "data" / "yearend_hot100.csv").open(encoding="utf-8")))
    yrs = sorted({int(r["year"]) for r in charts})
    span = f"{yrs[0]}-{yrs[-1]}"
    # Chart tags go by SONG (artist + title), not by file: the same song is often held as
    # several copies (other album, live version), and every copy counts as charted.
    chart_idx = collections.defaultdict(list)
    for r in charts: chart_idx[norm(r["title"])].append((r["artist"], f'{r["year"]}#{r["rank"]}'))
    def chart_tags(f):
        out = []
        for sd in (True, False):
            a, t = path_song(f, sd)
            out += [yr for ca, yr in chart_idx.get(norm(t), []) if artist_ok(a, ca) and yr not in out]
        return out
    chart_of = {f: chart_tags(f) for f in set(cur_files) | set(core_files) | set(dropped)}
    chart_of = {f: v for f, v in chart_of.items() if v}

    def song_key(f):
        a, t = path_song(f); return norm(a), norm(t)
    cur_songs = {song_key(f) for f in cur_files}
    removed_songs = {song_key(f) for f in removed}

    chart_rows = []
    for r in charts:
        f, q = find(r["artist"], r["title"])
        if f and song_key(f) in removed_songs: status = "Removed by you"
        elif f and (f in cur_set or song_key(f) in cur_songs): status = "In list"
        elif f: status = "On phone, not in list"
        else: status = "Missing"
        chart_rows.append([int(r["year"]), r["rank"], r["artist"], r["title"], status, q,
                           f.split("/Music/", 1)[-1] if f else ""])

    # duplicates: the same artist+title as two different files in the current list
    groups = collections.defaultdict(list)
    for f in cur_files:
        a, t = path_song(f); groups[(norm(a), norm(t))].append(f)
    dupes = [g for g in groups.values() if len(g) > 1]

    # ---------- workbook ----------
    wb = Workbook()
    wb.properties.title = "Sailing playlist catalogue report"
    wb.properties.subject = "Music Player - D:/boat/music-player/tools/catalog.py v1 (STANDALONE UTILITY)"
    wb.properties.description = ("Read-only report: current sailing list tagged Core / Chart "
                                 f"(Billboard Year-End Hot 100 {span}); generated " + date.today().isoformat())
    bold = Font(bold=True)

    def sheet(title, header, rows, widths=None):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]: c.font = bold
        for r in rows: ws.append(r)
        ws.freeze_panes = "A2"
        if rows: ws.auto_filter.ref = ws.dimensions
        for i, w in enumerate(widths or [], 1): ws.column_dimensions[get_column_letter(i)].width = w
        return ws

    core_charted = [f for f in core_files if f in chart_of]
    core_in_cur = [f for f in core_files if f in cur_set or song_key(f) in cur_songs]
    core_songs = {song_key(f) for f in core_files}
    other = [f for f in cur_files if song_key(f) not in core_songs and f not in chart_of]
    st = collections.Counter(r[4] for r in chart_rows)
    ws = wb.active; ws.title = "Summary"
    summary = [
        ("Current list (sailing_2.m3u)", ""),
        ("  distinct songs (files)", len(cur_files)),
        ("  lines that match no file on the phone", len(cur_unres)),
        ("  ...of which in the core list", sum(song_key(f) in core_songs for f in cur_files)),
        (f"  ...of which on a {span} year-end chart", sum(f in chart_of for f in cur_files)),
        ("  ...in neither (other additions)", len(other)),
        ("Core list (Sailing_orig.m3u)", ""),
        ("  distinct songs", len(core_files)),
        ("  lines that match no file on the phone", sum(1 for f in core if not f)),
        ("  ...also on a year-end chart", len(core_charted)),
        (f"  ...never charted {span} (Buffett, Gilligan's Island...)", len(core_files) - len(core_charted)),
        ("  ...NOT in the current list", len(core_files) - len(core_in_cur)),
        (f"Year-End Hot 100, {span}", ""),
        ("  chart entries", len(chart_rows)),
        ("  in the current list", st["In list"]),
        ("  on the phone but not in the list", st["On phone, not in list"]),
        ("  removed by you", st["Removed by you"]),
        ("  missing from the phone", st["Missing"]),
        ("Housekeeping", ""),
        ("  in the damaged sailing.m3u but not in sailing_2 (dropped?)", len(dropped)),
        ("  songs held as 2+ files in the current list", len(dupes)),
        ("  removed with the Remove button", len(removed)),
    ]
    for k, v in summary:
        ws.append([k, v])
        if v == "": ws.cell(ws.max_row, 1).font = bold
    ws.append([]); ws.append(["Year", "In list", "On phone, not in list", "Removed", "Missing"])
    for c in ws[ws.max_row]: c.font = bold
    for y in sorted(set(r[0] for r in chart_rows)):
        c = collections.Counter(r[4] for r in chart_rows if r[0] == y)
        ws.append([y, c["In list"], c["On phone, not in list"], c["Removed by you"], c["Missing"]])
    ws.column_dimensions["A"].width = 62; ws.column_dimensions["B"].width = 10

    def row_for(f):
        a, t = path_song(f)
        return [a, t, "yes" if song_key(f) in core_songs else "", ", ".join(chart_of.get(f, [])),
                "yes" if (f in cur_set or song_key(f) in cur_songs) else "", f.split("/Music/", 1)[-1]]
    hdr = ["Artist", "Title", "Core", "Chart (year#rank)", "In current list", "File (under Music/)"]
    w = [28, 40, 6, 18, 8, 80]
    sheet("Current list", hdr, sorted((row_for(f) for f in cur_files), key=lambda r: (r[0].lower(), r[1].lower())), w)
    sheet("Year-End charts", ["Year", "Rank", "Artist", "Title", "Status", "Match", "File (under Music/)"],
          chart_rows, [6, 6, 28, 40, 22, 16, 80])
    sheet("Core list", hdr, sorted((row_for(f) for f in core_files), key=lambda r: (r[0].lower(), r[1].lower())), w)
    sheet("Other additions", hdr, sorted((row_for(f) for f in other), key=lambda r: (r[0].lower(), r[1].lower())), w)
    sheet("Dropped (sailing.m3u only)", hdr, [row_for(f) for f in dropped], w)
    sheet("Duplicates", ["Artist", "Title", "Files"],
          [[*path_song(g[0]), " | ".join(x.split("/Music/", 1)[-1] for x in g)] for g in dupes], [28, 40, 120])
    sheet("Removed", hdr, [row_for(f) for f in removed], w)
    sheet("Unmatched lines", ["Playlist line (current list)"], [[l] for l in cur_unres], [120])

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    for k, v in summary: print(f"{k}: {v}")
    print("wrote", out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
