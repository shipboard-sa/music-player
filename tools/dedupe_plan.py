"""
Purpose: Turn NAS fingerprints into a duplicate clean-up plan: which byte-identical copy
    to keep, which to move to a holding folder, plus a review sheet for look-alikes that
    are NOT identical. Writes the NAS move list and an undo list; moves nothing itself.
Version: v1 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player library tooling.
Architecture: inputs = hash_results.txt from tools/nas/hash_files.sh (md5, bytes, path
    under Music/), the candidate groups (same folder, same title once track numbers are
    ignored), and the phone playlists (to know which copies are in use). Within each
    group, files with the same md5 are one recording: keep the copy a playlist uses,
    else the "NN - Title" form, else the shortest name; the rest go to moves.txt
    (src <TAB> dst, dst under _duplicates_<date>/ with the same sub-folders) and
    undo.txt (the reverse). Different md5s in a group (Reprise, Allegro(1)/(2), edits)
    are never moved - they are listed on the review sheet.
Invocation: python tools/dedupe_plan.py <hash_results.txt> <groups.json> <files.txt> <out-dir> <playlist.m3u> [...]
    -> out-dir/moves.txt, undo.txt, Duplicate_Review.xlsx, playlist_rewrites.tsv
"""
import collections, json, os, re, sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import Library, m3u_lines   # noqa: E402

HOLD = f"_duplicates_{date.today().isoformat()}"


def main(hashes, groups_json, files_txt, out_dir, *playlists):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    fp = {}
    for line in open(hashes, encoding="utf-8", errors="replace"):
        h, size, path = line.rstrip("\n").split("\t", 2)
        fp[path] = (h, int(size))
    lib = Library([l.rstrip(chr(13) + chr(10)) for l in open(files_txt, encoding="utf-8")])
    used = collections.Counter()
    for pl in playlists:
        for l in m3u_lines(Path(pl)):
            f = lib.resolve(l)
            if f: used[f.split("/Music/", 1)[-1]] += 1

    moves, review, keepers = [], [], 0
    for g in json.load(open(groups_json, encoding="utf-8")):
        by_hash = collections.defaultdict(list)
        for p in g:
            if p in fp and fp[p][0] != "MISSING": by_hash[fp[p][0]].append(p)
        for h, same in by_hash.items():
            if len(same) < 2: continue
            numbered = lambda p: bool(re.match(r"^\d+\s*-\s+", os.path.basename(p)))
            keep = sorted(same, key=lambda p: (-used[p], not numbered(p), len(p)))[0]
            keepers += 1
            for p in same:
                if p != keep: moves.append((p, keep))
        if len(by_hash) > 1:   # look-alikes with different content: a person decides
            review.append(g)

    with open(out / "moves.txt", "w", encoding="utf-8", newline="\n") as m, \
         open(out / "undo.txt", "w", encoding="utf-8", newline="\n") as u, \
         open(out / "playlist_rewrites.tsv", "w", encoding="utf-8", newline="\n") as r:
        for p, keep in moves:
            m.write(f"{p}\t{HOLD}/{p}\n")
            u.write(f"{HOLD}/{p}\t{p}\n")
            if used[p]: r.write(f"{p}\t{keep}\n")   # step 3: point these lines at the keeper

    wb = Workbook(); ws = wb.active; ws.title = "Moved (identical copies)"
    wb.properties.title = "Library duplicate clean-up plan"
    wb.properties.subject = "Music Player - tools/dedupe_plan.py v1 (STANDALONE UTILITY)"
    ws.append(["Copy moved to holding folder", "Identical file kept", "MB", "In a playlist?"])
    for p, keep in moves:
        ws.append([p, keep, round(fp[p][1] / 1e6, 1), "yes - line will be repointed" if used[p] else ""])
    ws2 = wb.create_sheet("Look-alikes - review")
    ws2.append(["Folder", "Files with the same title but DIFFERENT content (left alone)"])
    for g in review:
        ws2.append([os.path.dirname(g[0]), " | ".join(os.path.basename(p) for p in g)])
    for w in (ws, ws2):
        for c in w[1]: c.font = Font(bold=True)
        w.freeze_panes = "A2"
    for col, wd in zip("ABCD", [90, 90, 8, 26]): ws.column_dimensions[col].width = wd
    ws2.column_dimensions["A"].width = 60; ws2.column_dimensions["B"].width = 120
    wb.save(out / "Duplicate_Review.xlsx")
    gb = sum(fp[p][1] for p, _ in moves) / 1e9
    print(f"identical sets {keepers}; copies to move {len(moves)} ({gb:.1f} GB); "
          f"of those used by a playlist {sum(1 for p, _ in moves if used[p])}; look-alike groups for review {len(review)}")


if __name__ == "__main__":
    if len(sys.argv) < 6: sys.exit(__doc__)
    main(*sys.argv[1:])
