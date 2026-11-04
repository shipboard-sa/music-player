"""
Purpose: Re-base the music phone's .m3u playlists for a library copy on disk (E:\\Media\\Music,
    the NAS): every song line becomes "../Artist/Album/Title" relative to <library>/Playlists/.
Version: v2 (2026-10-13) - writes UTF-8 .m3u8 (real file names, no '?' stand-ins)
Scope: STANDALONE UTILITY - Music Player library tooling; safe to re-run or delete.
Architecture: The phone's lists live in /storage/emulated/0/Music and point at the SD card
    (../../../4A21-0000/Music/...); on a PC copy that path means nothing. Each line is
    resolved with catalog.Library against the phone's file listing, then rewritten relative
    to the library's Playlists folder. Comments (#EXTM3U, #EXTINF) and line
    endings are kept (v2: re-encoded as UTF-8); lines that resolve to nothing are kept unchanged and counted. Every
    rewritten line is checked against the library listing.
    v2: output is UTF-8 with the real file name from the listing, saved as <name>.m3u8 -
    cp1252 lists turned characters like U+2011 into '?', which only the phone app's
    wildcard matching tolerates (Jellyfin / Windows do not).
Invocation: python tools/m3u_for_library.py <phone_files.txt> <library_listing.txt> <out-dir> <list.m3u> [...]
    phone_files.txt = `size|/storage/...` per audio file on the phone (or bare paths);
    library_listing.txt = `size|Artist/Album/Title` per file under the library root.
    Copy the output files into <library>\\Playlists\\.
"""
import os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import Library            # noqa: E402
from add_to_playlist import detect     # noqa: E402

ROOTS = ("/storage/4A21-0000/Music/", "/storage/emulated/0/Music/")


def main(phone_txt, listing, out_dir, *lists):
    phone = [l.rstrip("\r\n").split("|", 1)[-1] for l in open(phone_txt, encoding="utf-8")]
    lib = Library(phone)
    have = {}                      # lowercased -> real name as on disk
    for l in open(listing, encoding="utf-8"):
        rel = l.rstrip("\r\n").split("|", 1)[-1]
        have[rel.lower()] = rel
    os.makedirs(out_dir, exist_ok=True)
    for pl in lists:
        raw = Path(pl).read_bytes()
        enc, bom = detect(raw)
        text = raw[len(bom):].decode(enc)
        nl = "\r\n" if "\r\n" in text else "\n"
        out, ok, dead, missing = [], 0, 0, 0
        for line in text.split(nl):
            s = line.strip()
            if s and not s.startswith("#"):
                f = lib.resolve(s)
                rel = next((f[len(r):] for r in ROOTS if f and f.startswith(r)), None)
                if rel is None:
                    dead += 1
                else:
                    ok += 1
                    if rel.lower() not in have: missing += 1
                    line = "../" + have.get(rel.lower(), rel)
            out.append(line)
        Path(out_dir, Path(pl).stem + ".m3u8").write_bytes(nl.join(out).encode("utf-8"))
        print(f"{Path(pl).name}: {ok} rewritten, {dead} already dead on the phone, "
              f"{missing} rewritten but not in the library")


if __name__ == "__main__":
    if len(sys.argv) < 5: sys.exit(__doc__)
    main(*sys.argv[1:])
