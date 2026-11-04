"""
Purpose: Copy only the songs the music phone's playlists use (not the whole library) from
    the phone to a laptop folder, keeping the Artist/Album/Title layout, plus the playlists.
Version: v1 (2026-10-13)
Scope: STANDALONE UTILITY - Music Player library tooling; safe to re-run (skips files
    already copied at the right size) or delete.
Architecture: Inputs = a dump folder holding files_sizes.txt (`size|/storage/...` per
    audio file, from `find | xargs stat -c "%s|%n"` on the phone) and lists/*.m3u (the
    phone's playlists, adb pull). Resolves playlist lines with catalog.Library, then runs
    one `adb pull` per song into <dest>/<path under Music/>. Writes <dest>/_manifest.tsv
    (size, phone path) and copies the playlists into <dest>/_playlists/ unchanged (their
    lines still point at the music phone's layout - rewrite per target device later).
Invocation: python tools/pull_playlist_songs.py <dump-folder> <dest-folder>
    [--serial RFCRA124PMH] [--dry-run]
    Needs the music phone on USB with debugging on; adb from the Android SDK.
    Example dest: D:\\music\\Playlist_Library_2026-10-13
"""
import argparse, os, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from catalog import Library, m3u_lines

# The SDK was installed from a Claude desktop (MSIX) session, so it really lives in the
# Claude package's LocalCache; other programs (e.g. store Python) can't see the redirect.
_SDK_ADB = r"Android\Sdk\platform-tools\adb.exe"
ADB = shutil.which("adb") or next(
    (str(p) for p in [Path.home() / "AppData/Local" / _SDK_ADB,
                      *(Path.home() / "AppData/Local/Packages").glob(f"Claude_*/LocalCache/Local/{_SDK_ADB}")]
     if p.exists()), "adb")
ROOTS = ("/storage/4A21-0000/Music/", "/storage/emulated/0/Music/")


def rel(p):
    for r in ROOTS:
        if p.startswith(r): return p[len(r):]
    raise ValueError(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path); ap.add_argument("dest", type=Path)
    ap.add_argument("--serial", default="RFCRA124PMH"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    size = {}
    for l in (a.dump / "files_sizes.txt").open(encoding="utf-8"):
        s, p = l.rstrip("\r\n").split("|", 1); size[p] = int(s)
    lib = Library(list(size))
    songs = set()
    for m in sorted((a.dump / "lists").glob("*.m3u")):
        songs |= {f for f in (lib.resolve(x) for x in m3u_lines(m)) if f}
    songs = sorted(songs)
    print(f"{len(songs)} songs, {sum(size[f] for f in songs)/1e9:.1f} GB", flush=True)
    if a.dry_run: return

    a.dest.mkdir(parents=True, exist_ok=True)
    (a.dest / "_playlists").mkdir(exist_ok=True)
    for m in (a.dump / "lists").glob("*.m3u"): shutil.copy2(m, a.dest / "_playlists" / m.name)
    with (a.dest / "_manifest.tsv").open("w", encoding="utf-8") as mf:
        for f in songs: mf.write(f"{size[f]}\t{f}\n")

    done = skipped = failed = 0; t0 = time.time(); got = 0
    for i, f in enumerate(songs, 1):
        out = a.dest / rel(f)
        if out.exists() and out.stat().st_size == size[f]:
            skipped += 1; continue
        out.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([ADB, "-s", a.serial, "pull", f, str(out)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode or not out.exists() or out.stat().st_size != size[f]:
            failed += 1; print(f"FAIL {f}: {r.stderr.strip()[:200]}", flush=True)
        else:
            done += 1; got += size[f]
        if i % 250 == 0:
            el = time.time() - t0
            print(f"{i}/{len(songs)} pulled={done} skipped={skipped} failed={failed} "
                  f"{got/1e6/max(el,1):.1f} MB/s", flush=True)
    print(f"DONE pulled={done} skipped={skipped} failed={failed} in {(time.time()-t0)/60:.0f} min", flush=True)


if __name__ == "__main__":
    main()
