"""
Purpose: Bring new MP3s up to the library's level without re-encoding: raise each quiet
    file's gain (MP3Gain, 1.5 dB steps) as far as it goes without clipping.
Version: v1 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player library tooling. MODIFIES the MP3s it is given
    (MP3Gain writes an undo record into each file's APE tag; mp3gain -u reverses it).
Architecture: matches Lee's earlier levelling (D:/music/sound_Level.py = pydub peak
    normalise, which re-encoded). Here: mp3gain -o -s s reads the peak amplitude and
    max global_gain; steps = floor(4*log2(32767/peak)), capped so global_gain <= 255;
    applied with mp3gain -g <steps> -c. Files already within 1.5 dB of full scale are
    left alone. ffmpeg volumedetect measures before/after. Writes a CSV log.
Invocation: python tools/level_new_music.py <folder> <log.csv>
    needs C:/Program Files (x86)/MP3Gain/mp3gain.exe (winget GlenSawyer.MP3Gain) and
    D:/music/ffmpeg.exe.
"""
import csv, glob, math, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

G = r"C:/Program Files (x86)/MP3Gain/mp3gain.exe"
FF = r"D:/music/ffmpeg.exe"
run = lambda a: subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace")


def level(f):
    """Level one file. mp3gain 1.2.5 cannot open non-ANSI paths ("The Bar‐Kays"), so such
    a file is processed as a plain-named temporary copy and copied back."""
    try:
        f.encode("cp1252")
        return _level(f)
    except UnicodeEncodeError:
        import shutil, tempfile
        tmp = os.path.join(tempfile.gettempdir(), "mp3gain_tmp.mp3")
        shutil.copy2(f, tmp)
        r = _level(tmp)
        if r[1] > 0: shutil.copy2(tmp, f)
        os.remove(tmp)
        return [f] + r[1:]


def _level(f):
    m = re.search(r"mean_volume: ([-\d.]+)", run([FF, "-hide_banner", "-nostats", "-i", f, "-af", "volumedetect", "-f", "null", "-"]).stderr)
    before = float(m.group(1)) if m else None
    rows = [l.split("\t") for l in run([G, "-o", "-s", "s", f]).stdout.splitlines() if "\t" in l]
    row = next((r for r in rows if r[0] not in ("File", '"Album"') and len(r) >= 5), None)   # the file's own row
    if row is None:   # mp3gain 1.2.5 cannot open some names (non-ANSI characters)
        return [f, -1, 0, before, before]
    amp, gmax = float(row[3]), int(row[4])
    n = max(0, min(int(math.floor(4 * math.log2(32767 / amp))), 255 - gmax)) if amp > 0 else 0   # <0 = already above full scale: leave
    after = before
    if n > 0:
        run([G, "-g", str(n), "-c", f])
        m = re.search(r"mean_volume: ([-\d.]+)", run([FF, "-hide_banner", "-nostats", "-i", f, "-af", "volumedetect", "-f", "null", "-"]).stderr)
        after = float(m.group(1)) if m else None
    return [f, n, n * 1.5, before, after]


def main(folder, log):
    # one separator style only: mp3gain 1.2.5 cannot open "D:/x\y" mixed paths
    files = sorted(p.replace("\\", "/") for p in glob.glob(os.path.join(folder, "**", "*.mp3"), recursive=True))
    rows = [level(f) for f in files]   # one at a time: parallel mp3gain runs garbled their output (10-12)
    with open(log, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["file", "steps", "dB added", "mean dB before", "mean dB after"]); w.writerows(rows)
    changed = [r for r in rows if r[1] > 0]
    failed = [r for r in rows if r[1] < 0]
    print(f"{len(files)} files; raised {len(changed)}; left alone {len(files) - len(changed) - len(failed)}; mp3gain could not open {len(failed)}")
    for r in failed: print("   could not open:", r[0], "mean dB", r[3])
    if changed:
        import statistics
        print("mean dB after (changed files): median %.1f, quietest %.1f" % (statistics.median(r[4] for r in changed), min(r[4] for r in changed)))


if __name__ == "__main__":
    if len(sys.argv) != 3: sys.exit(__doc__)
    main(*sys.argv[1:])
