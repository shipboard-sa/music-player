"""
Purpose: Merge several .m3u playlists into one clean list: every song once, written as a
    literal path the phone resolves directly, dead lines moved to a "missing" report.
Version: v1 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player playlist tooling; writes NEW files only.
Architecture: uses catalog.Library (every audio file on the phone, from files.txt) to
    resolve each input line in whatever path style it was written (old SD card ids,
    "/SD card/...", Music/Music, ../ chains, wrong case). Keeps first-seen order (first
    list, then what the next adds). Collapses only TRUE copies: the same track saved
    twice in one folder ("07 - X.mp3" / "07-X.mp3" / "X.mp3"). Different recordings of the
    same song (several "Joy to the World"s) are all kept. Output is UTF-8 with LF,
    #EXTM3U header, paths relative to the playlist's phone folder.
Invocation: python tools/merge_playlists.py <files.txt> <phone-dir-of-output> <out.m3u> <missing.txt> <in1.m3u> [in2.m3u ...]
    e.g. ... /storage/emulated/0/Music Christmas.m3u Christmas_missing.txt Christmas.m3u Christmas1.m3u
"""
import os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from catalog import Library, m3u_lines, norm          # noqa: E402
from add_to_playlist import phone_relpath             # noqa: E402


def track_key(f: str):
    """(folder, title) plus the track number (None if the file has none). Two files are
    the same track only if folder and title match AND the numbers match or one is
    missing: "12 - Silent Night" = "12-Silent Night" = "Silent Night", but
    "08 - Miracles" and "18 - Miracles (Remix)" are different tracks."""
    name = os.path.splitext(os.path.basename(f))[0]
    m = re.match(r"^(\d+)\s*[-_.]?\s*", name)
    num = int(m.group(1)) if m else None
    return (os.path.dirname(f).lower(), norm(name[m.end():] if m else name)), num


def main(files_txt, out_dir, out, missing, *inputs):
    lib = Library([l.rstrip(chr(13) + chr(10)) for l in open(files_txt, encoding="utf-8")])
    seen_files, seen_tracks, keep, dead = set(), {}, [], []   # seen_tracks: key -> numbers
    stats = []
    for src in inputs:
        added = dup = gone = 0
        for line in m3u_lines(Path(src)):
            f = lib.resolve(re.sub(r"^/?SD card/", "", line, flags=re.I))
            if not f:
                dead.append(f"{Path(src).name}\t{line}"); gone += 1; continue
            k, num = track_key(f)
            nums = seen_tracks.get(k, set())
            if f in seen_files or (nums and (num is None or None in nums or num in nums)):
                dup += 1; continue
            seen_files.add(f); seen_tracks.setdefault(k, set()).add(num); keep.append(f); added += 1
        stats.append(f"{Path(src).name}: +{added} songs, {dup} repeats/copies skipped, {gone} dead lines")
    body = "#EXTM3U\n" + "".join(phone_relpath(f, out_dir) + "\n" for f in keep)
    Path(out).write_text(body, encoding="utf-8", newline="\n")
    Path(missing).write_text("".join(d + "\n" for d in dead), encoding="utf-8")
    print("\n".join(stats))
    print(f"-> {out}: {len(keep)} songs; {len(dead)} dead lines -> {missing}")


if __name__ == "__main__":
    if len(sys.argv) < 6:
        sys.exit(__doc__)
    main(*sys.argv[1:])
