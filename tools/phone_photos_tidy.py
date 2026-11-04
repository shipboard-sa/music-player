"""
Purpose: Gather the photos scattered over an Android phone into the standard layout on its
    SD card (DCIM/Camera, DCIM/Screenshots, Pictures/<source>); exact duplicates and the
    internal-storage originals go to holding folders. Nothing is deleted.
Version: v1 (2026-10-13)
Scope: STANDALONE UTILITY - phone housekeeping (lives with the music-player tools because it
    uses the same adb set-up); safe to re-run - a second run finds nothing to move.
Architecture: Input = `md5  path` lines from `md5sum` run on the phone over the candidate
    folders (see CHECKPOINT, "Lee's phone"). Each source folder maps to a card destination
    (MAP below); folders not in MAP stay put. A file whose md5 is already at its destination
    (or anywhere in the card's DCIM/Pictures) is a duplicate -> holding. Name clashes get
    " (2)". Card -> card = mv; internal -> card = cp, md5 check on the phone, then the
    original is mv'd to /sdcard/_holding_<date>/photos/. One adb shell per file.
Invocation: python tools/phone_photos_tidy.py <md5-list.txt> [--serial R5CYA23PDCL] [--dry-run]
    Then rescan media: adb shell content call --uri content://media --method scan_volume --arg 4a21-0000
"""
import argparse, os, posixpath, shutil, subprocess
from pathlib import Path

I, C = "/storage/emulated/0", "/storage/4A21-0000"
HOLD_I, HOLD_C = f"{I}/_holding_2026-10-13/photos", f"{C}/_holding_2026-10-13/photos"
MAP = {                                   # source folder -> card destination
    f"{I}/DCIM/Screenshots": f"{C}/DCIM/Screenshots",
    f"{I}/Pictures/Messages": f"{C}/Pictures/Messages",
    f"{I}/Download/Quick Share": f"{C}/Pictures/Quick Share",
    f"{I}/Pictures/Reolink/capture": f"{C}/Pictures/Reolink",
    f"{I}/Pictures": f"{C}/Pictures",
    f"{C}/Download/GS PICS/GS PICS": f"{C}/Pictures/GS PICS",
    f"{C}/Download": f"{C}/Pictures/Downloads",
    f"{C}/DCIM/Flickr": f"{C}/Pictures/Flickr",
    f"{C}/DCIM/Facebook": f"{C}/Pictures/Facebook",
    f"{C}/DCIM": f"{C}/DCIM/Camera",          # loose dated photo in the DCIM root
}
SDK_ADB = r"Android\Sdk\platform-tools\adb.exe"
ADB = shutil.which("adb") or next(
    (str(p) for p in [Path.home() / "AppData/Local" / SDK_ADB,
                      *(Path.home() / "AppData/Local/Packages").glob(f"Claude_*/LocalCache/Local/{SDK_ADB}")]
     if p.exists()), "adb")


def q(s):
    return "'" + s.replace("'", "'\\''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md5list"); ap.add_argument("--serial", default="R5CYA23PDCL")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sh = lambda cmd: subprocess.run([ADB, "-s", a.serial, "shell", cmd], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace")

    files = []
    for l in open(a.md5list, encoding="utf-8"):
        h, p = l.rstrip("\r\n").split("  ", 1); files.append((h, p))
    on_card = {h for h, p in files if posixpath.dirname(p) not in MAP and p.startswith(C)}
    taken = {p.lower() for h, p in files}
    moved = dup = 0
    for h, p in sorted(files, key=lambda x: x[1]):
        src_dir = posixpath.dirname(p)
        if src_dir not in MAP: continue
        internal = p.startswith(I)
        if h in on_card:
            hold = (HOLD_I if internal else HOLD_C) + p[len(I if internal else C):]
            print("DUP ", p); dup += 1
            if not a.dry_run:
                r = sh(f"mkdir -p {q(posixpath.dirname(hold))} && mv {q(p)} {q(hold)}")
                if r.returncode: print("  FAIL", r.stderr.strip())
            continue
        dest_dir, name = MAP[src_dir], posixpath.basename(p)
        dest = f"{dest_dir}/{name}"; n = 2
        while dest.lower() in taken:
            stem, ext = posixpath.splitext(name); dest = f"{dest_dir}/{stem} ({n}){ext}"; n += 1
        taken.add(dest.lower()); on_card.add(h); moved += 1
        print("MOVE", p, "->", dest)
        if a.dry_run: continue
        if internal:
            hold = HOLD_I + p[len(I):]
            r = sh(f"mkdir -p {q(dest_dir)} && cp {q(p)} {q(dest)} && "
                   f"[ \"$(md5sum {q(dest)} | cut -d' ' -f1)\" = {h} ] && "
                   f"mkdir -p {q(posixpath.dirname(hold))} && mv {q(p)} {q(hold)}")
        else:
            r = sh(f"mkdir -p {q(dest_dir)} && mv {q(p)} {q(dest)}")
        if r.returncode: print("  FAIL", r.stderr.strip())
    print(f"moved {moved}, duplicates held {dup}")


if __name__ == "__main__":
    main()
