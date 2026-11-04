"""
Purpose: Append songs (phone file paths) to an .m3u playlist, keeping the file's own
    encoding and line endings, skipping songs already in it. Writes a NEW file; never
    edits in place.
Version: v1 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player playlist tooling.
Architecture: companion to tools/catalog.py (which says what's missing). Each added line
    is a path relative to the playlist's own folder, so it resolves literally on the
    phone with no lookup (e.g. ../../4A21-0000/Music/Artist/Album/Song.mp3 from
    /storage/emulated/0/Music/). Characters the playlist's encoding can't hold become '?',
    which the app's resolver treats as a one-character wildcard.
Invocation: python tools/add_to_playlist.py <in.m3u> <phone-dir-of-playlist> <paths.txt> <out.m3u>
    paths.txt = one absolute phone path per line (e.g. /storage/4A21-0000/Music/...).
    Push <out.m3u> to the phone yourself after checking it (adb push).
"""
import sys
from pathlib import Path


def phone_relpath(path: str, start: str) -> str:
    """Relative path between two absolute PHONE paths. (posixpath.relpath consults the
    laptop's current directory on Windows and produces garbage here.)"""
    p, s = path.strip("/").split("/"), start.strip("/").split("/")
    n = 0
    while n < min(len(p), len(s)) and p[n] == s[n]: n += 1
    return "/".join([".."] * (len(s) - n) + p[n:])


def detect(b: bytes):
    if b[:2] == b"\xff\xfe": return "utf-16-le", b[:2]
    if b[:3] == b"\xef\xbb\xbf": return "utf-8", b[:3]
    try: b.decode("utf-8"); return "utf-8", b""
    except UnicodeDecodeError: return "cp1252", b""


def main(src: Path, phone_dir: str, paths: Path, out: Path):
    raw = src.read_bytes()
    enc, bom = detect(raw)
    text = raw[len(bom):].decode(enc)
    nl = "\r\n" if "\r\n" in text else "\n"
    have = {l.strip().strip('"').lower() for l in text.splitlines() if l.strip() and not l.startswith("#")}

    added, skipped, lossy = [], 0, 0
    for p in (l.strip() for l in paths.read_text(encoding="utf-8").splitlines()):
        if not p: continue
        rel = phone_relpath(p, phone_dir)
        if rel.lower() in have: skipped += 1; continue
        safe = rel.encode(enc, errors="replace").decode(enc)   # unencodable -> '?'
        if safe != rel: lossy += 1
        added.append(safe); have.add(rel.lower())

    body = text if text.endswith(("\n", "\r")) or not text else text + nl
    body += nl.join(added) + (nl if added else "")
    out.write_bytes(bom + body.encode(enc))
    print(f"encoding {enc}, newline {'CRLF' if nl == chr(13)+chr(10) else 'LF'}; "
          f"added {len(added)}, already present {skipped}, with '?' substitutions {lossy}")


if __name__ == "__main__":
    if len(sys.argv) != 5: sys.exit(__doc__)
    main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
