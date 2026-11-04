"""
Purpose: Make a phone's SD-card Music folder hold exactly a chosen set of songs (the songs of
    the playlists Lee keeps on his own phone), copied from the library on E:; everything else
    in Music/ - and any extra stale paths named - is moved to a holding folder on the card.
    Nothing is deleted.
Version: v1 (2026-10-13)
Scope: STANDALONE UTILITY - Music Player library tooling; safe to re-run (a second run finds
    nothing to do) or delete.
Architecture: Card in a USB reader (e.g. G:). keep.txt = `size|Artist/Album/Title` per song
    (relative to the library root). A card file counts as present when its path matches
    case-insensitively AND its size equals the library's; a size mismatch (an older version)
    is moved to holding and replaced. Copies go via a .part file, md5-verified against the
    library, then renamed. Image files (jpg/png) in folders that still hold a kept song stay.
    Moves use os.replace (same volume = instant); <holding>/_undo.tsv lists holding ->
    original. Empty folders left behind are removed. Sibling of mirror_library.py.
Invocation: python tools/fill_card_from_library.py <library-root> <card-music> <holding> <keep.txt>
    [--also <card-path> ...] [--dry-run]
    e.g. ... E:\\Media\\Music G:\\Music G:\\_holding_2026-10-13 keep.txt --also G:\\.android_secure
    Old playlists in Music/ are moved too; the new ones are written separately (m3u_for_library.py output into <card-music>\\Playlists).
"""
import argparse, hashlib, os, time

IMAGES = (".jpg", ".jpeg", ".png")


def walk(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = os.path.getsize(p)
    return out


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library"); ap.add_argument("card"); ap.add_argument("holding"); ap.add_argument("keep")
    ap.add_argument("--also", nargs="*", default=[]); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    keep = {}
    for l in open(a.keep, encoding="utf-8"):
        s, p = l.rstrip("\r\n").split("|", 1); keep[p.lower()] = (p, int(s))
    card = walk(a.card)
    cl = {p.lower(): p for p in card}
    copy = [p for k, (p, s) in keep.items() if k not in cl or card[cl[k]] != s]
    kept_dirs = {os.path.dirname(k) for k in keep}
    move = [p for p in card
            if not (p.lower() in keep and card[p] == keep[p.lower()][1])
            and not (p.lower().endswith(IMAGES) and os.path.dirname(p.lower()) in kept_dirs)]
    gb = lambda n: n / 1e9
    print(f"keep {len(keep)} | card files {len(card)} | copy {len(copy)} "
          f"({gb(sum(keep[p.lower()][1] for p in copy)):.1f} GB) | move to holding {len(move)} "
          f"({gb(sum(card[p] for p in move)):.1f} GB) | also {a.also}", flush=True)
    if a.dry_run: return

    os.makedirs(a.holding, exist_ok=True)
    with open(os.path.join(a.holding, "_undo.tsv"), "a", encoding="utf-8") as undo:
        for p in move:
            s, d = os.path.join(a.card, p), os.path.join(a.holding, "Music", p)
            os.makedirs(os.path.dirname(d), exist_ok=True); os.replace(s, d); undo.write(f"{d}\t{s}\n")
        for x in a.also:
            if os.path.exists(x):
                d = os.path.join(a.holding, os.path.basename(x.rstrip("\\/")))
                os.replace(x, d); undo.write(f"{d}\t{x}\n")
    print(f"moved {len(move)} files + {len(a.also)} extra paths to {a.holding}", flush=True)

    t0 = time.time(); got = bad = 0
    for i, p in enumerate(copy, 1):
        s, d = os.path.join(a.library, p), os.path.join(a.card, p)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        part = d + ".part"; h = hashlib.md5()
        with open(s, "rb") as fi, open(part, "wb") as fo:
            for b in iter(lambda: fi.read(1 << 20), b""): h.update(b); fo.write(b)
        if md5(part) != h.hexdigest():
            os.remove(part); bad += 1; print("VERIFY FAIL", p, flush=True); continue
        os.replace(part, d); got += os.path.getsize(d)
        if i % 500 == 0: print(f"copy {i}/{len(copy)} {got/1e6/(time.time()-t0):.0f} MB/s", flush=True)
    print(f"copied {len(copy)-bad}, failed {bad}, {gb(got):.1f} GB in {(time.time()-t0)/60:.0f} min", flush=True)

    removed = 0
    for d, _, _ in os.walk(a.card, topdown=False):
        if d != a.card and not os.listdir(d): os.rmdir(d); removed += 1
    print(f"removed {removed} empty folders", flush=True)


if __name__ == "__main__":
    main()
