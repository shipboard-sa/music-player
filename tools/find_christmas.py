"""
Purpose: Find Christmas music sitting in non-Christmas playlists (CCM, sailing), sorted
    into SURE and CHECK so nothing is removed on a keyword guess.
Version: v2 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player playlist tooling; read-only (writes a report).
Architecture: resolves each playlist line with catalog.Library. SURE = the ALBUM folder
    is a Christmas album ("WOW Christmas", "Merry Merry Christmas"...). CHECK = only the
    title says Christmas (a carol or Christmas phrase) - a human decides ("Joy to the
    World" by Three Dog Night is not the carol). Not used: the artist folder (Noel Paul
    Stookey), membership of the Christmas lists (they hold everyday worship songs too),
    same-title matches ("Thank You"), and lone words like Holiday / Santa Fe / Snow.
Invocation: python tools/find_christmas.py <files.txt> <christmas.m3u> <out.xlsx> <list1.m3u> [list2.m3u ...]
"""
import re, sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

sys.path.insert(0, str(Path(__file__).parent))
from catalog import Library, m3u_lines, norm, path_song   # noqa: E402

FOLDER = re.compile(r"christmas|xmas|x-mas|noel|navidad|winterlude|\bnativity\b|advent", re.I)
TITLE = re.compile(
    r"christmas|xmas|x-mas|santa claus|\bsanta\b(?! fe)|sleigh|jingle bell|\bnoel\b|nowell|"
    r"silent night|holy night|away in a manger|joy to the world|hark!? the herald|o come,? all ye|"
    r"deck the hall|rudolph|frosty the snowman|mistletoe|winter wonderland|little drummer boy|"
    r"mary,? did you know|we three kings|angels we have heard|it came upon|god rest ye|"
    r"o little town|feliz navidad|carol of the bells|what child is this|good king wenceslas|"
    r"twelve days of|go tell it on the mountain|do you hear what i hear|let it snow|"
    r"o come,? o come|emmanuel|immanuel|bethlehem|\bmanger\b|gloria in excelsis|"
    r"born (is )?the king|christ is born|first noel|we wish you a merry|happy holidays|"
    r"auld lang syne|chestnuts|i'll be home for|sleigh ride|feliz|navidad|nativity", re.I)


def main(files_txt, christmas, out, *lists):
    lib = Library([l.rstrip(chr(13) + chr(10)) for l in open(files_txt, encoding="utf-8")])
    xmas_files = {f for f in (lib.resolve(l) for l in m3u_lines(Path(christmas))) if f}
    xmas_titles = {norm(path_song(f)[1]) for f in xmas_files}
    wb = Workbook(); wb.remove(wb.active)
    wb.properties.title = "Christmas music found in other playlists"
    wb.properties.subject = "Music Player - D:/boat/music-player/tools/find_christmas.py v1 (STANDALONE UTILITY)"
    for lst in lists:
        rows = []
        for line in dict.fromkeys(m3u_lines(Path(lst))):
            f = lib.resolve(line)
            if not f:
                continue
            rel = f.split("/Music/", 1)[-1]
            a, t = path_song(f)
            parts = rel.split("/")
            album = parts[-2] if len(parts) >= 3 else ""     # Artist/Album/song
            if FOLDER.search(album):
                rows.append(["SURE", f"Christmas album: {album}", a, t, rel, line])
            elif TITLE.search(t):
                rows.append(["CHECK", "Christmas-sounding title", a, t, rel, line])
        rows = list({r[4]: r for r in rows}.values())
        ws = wb.create_sheet(Path(lst).stem[:30])
        ws.append(["Verdict", "Why", "Artist", "Title", "File (under Music/)", "Playlist line"])
        for c in ws[1]: c.font = Font(bold=True)
        for r in sorted(rows, key=lambda r: (r[0] != "SURE", r[2].lower(), r[3].lower())):
            ws.append(r)
        for col, w in zip("ABCDEF", [8, 26, 28, 44, 80, 60]):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = "A2"
        sure = sum(r[0] == "SURE" for r in rows)
        print(f"{Path(lst).name}: {sure} SURE, {len(rows) - sure} CHECK")
    wb.save(out)
    print("->", out)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
