"""
Purpose: Make a destination music folder match a source one (e.g. E:\\Media\\Music = the
    music phone's SD card in a reader): copy what is new, move what is extra into a holding
    folder on the destination drive. Nothing is deleted.
Version: v2 (2026-10-13) - dot-led album names ("...And Justice") are not hidden
Scope: STANDALONE UTILITY - Music Player library tooling; safe to re-run (a second run
    finds nothing to do) or delete.
Architecture: Walks both trees; identity = relative path, case-insensitive (both drives are
    Windows file systems). Source paths with a component starting with '.' (Android
    .thumbnails, hidden partial downloads) are never copied. Copies go to a .part file,
    are md5-verified against the source, then renamed into place. Extras are moved with
    os.replace (same volume = instant) and listed in <holding>/_undo.tsv (holding path,
    original path); undo = move each line back. Empty folders left behind are removed.
    Same-path files are assumed identical when the sizes match (10-13: 40 md5 samples ok).
Invocation: python tools/mirror_library.py <src> <dst> <holding> [--dry-run]
    e.g. python tools/mirror_library.py G:\\Music E:\\Media\\Music
         E:\\Media\\_music_holding_2026-10-13
    Prints a summary and progress; writes <holding>/_mirror_log.txt.
"""
import argparse, hashlib, os, sys, time


def walk(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = os.path.getsize(p)
    return out


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def hidden(rel):
    # ".thumbnails", ".nomedia", ".x.daio_peo.mp3" - but NOT album names like
    # "...And Justice for All" (v2 fix: v1 held back 7 such songs on 10-13)
    return any(c.startswith(".") and not c.startswith("..") for c in rel.split("/"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("holding")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src, dst = walk(a.src), walk(a.dst)
    dl = {p.lower(): p for p in dst}
    sl = {p.lower() for p in src}
    new = sorted(p for p in src if p.lower() not in dl and not hidden(p))
    differ = sorted(p for p in src if p.lower() in dl and src[p] != dst[dl[p.lower()]])
    extra = sorted(p for p in dst if p.lower() not in sl or hidden(p))
    gb = lambda L, d: sum(d[x] for x in L) / 1e9
    print(f"src {len(src)} dst {len(dst)} | new {len(new)} ({gb(new, src):.1f} GB) | "
          f"same path, different size {len(differ)} | extra on dst {len(extra)} ({gb(extra, dst):.1f} GB)",
          flush=True)
    if differ:
        print("Size differences - not handled, stopping:", *differ[:20], sep="\n  "); sys.exit(1)
    if a.dry_run: return

    os.makedirs(a.holding, exist_ok=True)
    log = open(os.path.join(a.holding, "_mirror_log.txt"), "a", encoding="utf-8")
    log.write(f"--- {time.ctime()} src={a.src} dst={a.dst}\n")

    t0 = time.time(); done = bad = 0; got = 0
    for i, p in enumerate(new, 1):
        s, d = os.path.join(a.src, p), os.path.join(a.dst, p)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        part = d + ".part"
        with open(s, "rb") as fi, open(part, "wb") as fo:
            h = hashlib.md5()
            for b in iter(lambda: fi.read(1 << 20), b""): h.update(b); fo.write(b)
        if md5(part) != h.hexdigest() or os.path.getsize(part) != src[p]:
            os.remove(part); bad += 1; print("VERIFY FAIL", p, flush=True); log.write(f"FAIL\t{p}\n"); continue
        os.replace(part, d); done += 1; got += src[p]; log.write(f"COPY\t{p}\n")
        if i % 500 == 0:
            print(f"copy {i}/{len(new)} {got/1e6/(time.time()-t0):.0f} MB/s", flush=True)
    print(f"copied {done}, failed {bad}, {got/1e9:.1f} GB in {(time.time()-t0)/60:.0f} min", flush=True)

    with open(os.path.join(a.holding, "_undo.tsv"), "a", encoding="utf-8") as undo:
        for p in extra:
            s, d = os.path.join(a.dst, p), os.path.join(a.holding, p)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            os.replace(s, d); undo.write(f"{d}\t{s}\n")
    print(f"moved {len(extra)} extras to {a.holding}", flush=True)

    removed = 0
    for d, dirs, files in os.walk(a.dst, topdown=False):
        if d != a.dst and not os.listdir(d):
            os.rmdir(d); removed += 1
    print(f"removed {removed} empty folders", flush=True)
    log.close()


if __name__ == "__main__":
    main()
