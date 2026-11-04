"""
Purpose: Repoint Windows Media .wpl playlists (Jazz, Ellen ...) after the 10-12 duplicate
    clean-up: a <media src> that names a moved copy is changed to the copy that was kept.
    Writes NEW .wpl files; the originals are not touched.
Version: v1 (2026-10-13)
Scope: STANDALONE UTILITY - Music Player library tooling; safe to re-run or delete.
Architecture: The .wpl sibling of repoint_playlists.py (which does .m3u). Map = the
    'Moved' sheet of the clean-up workbook (moved -> kept, paths under Music/), plus the
    same fallback for rows with no keeper: the remaining file in the same folder with the
    same title once a track number is ignored. A src is changed only if its file is NOT in
    the library listing AND the kept copy IS. Srcs are relative to Music/Playlists/
    ("../Artist/Album/Title.mp3"), XML-escaped; only the src values change, every other
    byte is kept. Prints repointed / still-dead counts per list.
Invocation: python tools/repoint_wpl.py <cleanup.xlsx> <library-listing.txt> <out-dir> <list.wpl> [...]
    library-listing.txt = one `size|Artist/Album/Title` per line (relative to Music/),
    e.g. the inventory of E:\\Media\\Music or of the music phone's card.
"""
import html, os, re, sys
from pathlib import Path

import openpyxl


def title(p):
    return re.sub(r"^\d+\s*[-_.]?\s*", "", os.path.splitext(os.path.basename(p))[0]).strip().lower()


def main(xlsx, listing, out_dir, *lists):
    lib = {}
    for l in open(listing, encoding="utf-8"):
        rel = l.rstrip("\r\n").split("|", 1)[-1]
        lib[rel.lower()] = rel
    remaining = {}
    for rel in lib.values():
        remaining.setdefault((os.path.dirname(rel).lower(), title(rel)), rel)
    kept = {}
    for row in openpyxl.load_workbook(xlsx, read_only=True)["Moved"].iter_rows(min_row=2, values_only=True):
        if not row[0]: continue
        k = row[1] or remaining.get((os.path.dirname(row[0]).lower(), title(row[0])))
        if k: kept[row[0].lower()] = k

    os.makedirs(out_dir, exist_ok=True)
    for pl in lists:
        text = Path(pl).read_bytes().decode("utf-8")
        escaped = bool(re.search(r'src="[^"]*&(amp|apos|quot);', text))
        stats = {"ok": 0, "repointed": 0, "dead": 0}
        dead = []

        def fix(m):
            raw = html.unescape(m.group(1))
            prefix = re.match(r"^(?:\.\./)*", raw.replace("\\", "/")).group(0)
            rel = raw.replace("\\", "/")[len(prefix):]
            if rel.lower() in lib:
                stats["ok"] += 1; return m.group(0)
            k = kept.get(rel.lower())
            if k and k.lower() in lib:
                stats["repointed"] += 1
                new = prefix + lib[k.lower()]
                # match the file's own style: Lee's lists carry bare '&' and apostrophes
                new = html.escape(new, quote=False) if escaped else new
                return 'src="' + new.replace('"', "&quot;") + '"'
            stats["dead"] += 1; dead.append(rel); return m.group(0)

        out = re.sub(r'src="([^"]+)"', fix, text)
        Path(out_dir, Path(pl).name).write_bytes(out.encode("utf-8"))
        print(f"{Path(pl).name}: {stats['ok']} fine, {stats['repointed']} repointed, {stats['dead']} still dead")
        for d in dead[:20]: print("   DEAD:", d)


if __name__ == "__main__":
    if len(sys.argv) < 5: sys.exit(__doc__)
    main(*sys.argv[1:])
