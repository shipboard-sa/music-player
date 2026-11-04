"""
Purpose: Copy newly downloaded MP3s into a Plex-style staging tree (Artist/Album/Title.mp3)
    that matches the existing library's folder names, ready to copy to the NAS and phone.
Version: v1 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player library tooling. COPIES only; the source
    folder is left as it is.
Architecture: reads artist/album/title tags (mutagen). An artist already in the
    library (NAS listing from tools/nas/list_music.sh) keeps that folder's exact name
    ("Carpenters" vs "The Carpenters", duet names in either order -> whichever exists). No album -> "Singles".
    Skips files listed in --skip (already owned) and any target that already exists
    in the library. Writes staging-manifest.csv (source, staged path, status).
Invocation: python tools/stage_new_music.py <source-folder> <staging-folder> <nas_music_files.txt> [--skip "file1.mp3;file2.mp3"]
"""
import csv, os, re, shutil, sys
import mutagen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BAD = re.compile(r'[\/:*?"<>|]')


def akey(name):
    """Artist key that ignores word order and & / and: 'Barbra Streisand & Donna Summer'
    == 'Donna Summer & Barbra Streisand'."""
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " "))
    return " ".join(sorted(w for w in words if w not in ("and", "the")))


def clean(s):
    s = BAD.sub("-", s).strip().rstrip(".")
    return s or "Unknown"


def main(src, dst, nas_list, skip=()):
    lib = [l.rstrip(chr(13) + chr(10)).split("/Music/", 1)[-1] for l in open(nas_list, encoding="utf-8", errors="replace")]
    artists = {}
    for rel in lib:
        a = rel.split("/")[0]
        artists.setdefault(akey(a), a)
    existing = {r.lower() for r in lib}
    rows = []
    for f in sorted(os.listdir(src)):
        if not f.lower().endswith(".mp3"): continue
        if f in skip:
            rows.append([f, "", "skipped: already in library"]); continue
        t = mutagen.File(os.path.join(src, f), easy=True)
        g = lambda k: (t.get(k) or [""])[0]
        artist = g("albumartist") or g("artist")
        folder = artists.get(akey(artist), clean(artist))
        rel = f"{folder}/{clean(g('album')) if g('album') else 'Singles'}/{clean(g('title'))}.mp3"
        if rel.lower() in existing:
            rows.append([f, rel, "skipped: same path already in library"]); continue
        out = os.path.join(dst, *rel.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(os.path.join(src, f), out)
        rows.append([f, rel, "existing artist folder" if akey(artist) in artists else "new artist folder"])
    with open(os.path.join(dst, "staging-manifest.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["source", "staged (under Music/)", "status"]); w.writerows(rows)
    from collections import Counter
    print(Counter(r[2] for r in rows))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 3: sys.exit(__doc__)
    skip = a[a.index("--skip") + 1].split(";") if "--skip" in a else []
    main(a[0], a[1], a[2], skip)
