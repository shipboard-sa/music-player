"""
Purpose: After duplicate copies were moved out of the library, point every playlist line
    that referred to a moved copy at the copy that was kept. Writes NEW playlist files.
Version: v2 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player library tooling.
Architecture: a line is resolved against the phone's file list as it was BEFORE the moves
    (catalog.Library); if it lands on a moved file (map from the clean-up workbook:
    moved -> kept, paths under Music/), the line is replaced with a literal relative path
    to the kept copy on the same storage volume. Only those lines change: every other
    byte, the file's encoding (cp1252 / UTF-8 / UTF-16) and its line endings are kept.
    v2: a line is repointed only if its file is gone AND the kept copy is on the device.
    Afterwards every song line is checked against the phone's file list AFTER the moves.
Invocation: python tools/repoint_playlists.py <cleanup.xlsx> <files_before.txt> <files_after.txt> <out-dir> <list.m3u> [...]
"""
import os, sys
from pathlib import Path

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import Library, m3u_lines          # noqa: E402
from add_to_playlist import phone_relpath, detect   # noqa: E402

PLAYLIST_DIR = "/storage/emulated/0/Music"


def main(xlsx, before_txt, after_txt, out_dir, *lists):
    kept = {}
    for row in openpyxl.load_workbook(xlsx, read_only=True)["Moved"].iter_rows(min_row=2, values_only=True):
        if row[0] and row[1]: kept[row[0]] = row[1]
    before = Library([l.rstrip(chr(13) + chr(10)) for l in open(before_txt, encoding="utf-8")])
    after_files = [l.rstrip(chr(13) + chr(10)) for l in open(after_txt, encoding="utf-8")]
    after = Library(after_files)
    after_set = set(after_files)
    # Moved copies with no recorded keeper (the plan only noted keepers for copies in use
    # at planning time): the keeper is the remaining file in the same folder with the
    # same title once a track number is ignored.
    import re
    title = lambda p: re.sub(r"^\d+\s*[-_.]?\s*", "", os.path.splitext(os.path.basename(p))[0]).strip().lower()
    remaining = {}
    for f in after_files:
        rel = f.split("/Music/", 1)[-1]
        remaining.setdefault((os.path.dirname(rel).lower(), title(rel)), rel)
    for row in openpyxl.load_workbook(xlsx, read_only=True)["Moved"].iter_rows(min_row=2, values_only=True):
        if row[0] and not row[1]:
            k = remaining.get((os.path.dirname(row[0]).lower(), title(row[0])))
            if k: kept[row[0]] = k
    os.makedirs(out_dir, exist_ok=True)
    for pl in lists:
        raw = Path(pl).read_bytes()
        enc, bom = detect(raw)
        text = raw[len(bom):].decode(enc)
        nl = "\r\n" if "\r\n" in text else "\n"
        out, changed, nokeep = [], 0, 0
        for line in text.split(nl):
            s = line.strip()
            if s and not s.startswith("#"):
                f = before.resolve(s)
                if f:
                    vol, rel = f.split("/Music/", 1)
                    target = f"{vol}/Music/{kept[rel]}" if rel in kept else None
                    # only when the kept copy really is on this device (the plan came from
                    # the NAS, which holds files the phone never had)
                    if target and target in after_set and f not in after_set:
                        new = phone_relpath(target, PLAYLIST_DIR)
                        line = new.encode(enc, errors="replace").decode(enc)
                        changed += 1
            out.append(line)
        body = nl.join(out)
        Path(out_dir, Path(pl).name).write_bytes(bom + body.encode(enc))
        # verify: every song line must resolve on the phone as it is now
        dead = [l for l in m3u_lines(Path(out_dir, Path(pl).name)) if not after.resolve(l)]
        dead_before = [l for l in m3u_lines(Path(pl)) if not before.resolve(l)]
        print(f"{Path(pl).name}: {changed} lines repointed; lines matching no file: {len(dead)} (before: {len(dead_before)})")
        for d in dead[:5]:
            if d not in dead_before: print("   NEW DEAD:", d)


if __name__ == "__main__":
    if len(sys.argv) < 6: sys.exit(__doc__)
    main(*sys.argv[1:])
