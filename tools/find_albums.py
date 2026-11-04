"""
Purpose: Find the original album for MP3s whose album tag is empty, via the MusicBrainz
    database (dry run by default; --write fills the tags).
Version: v2 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player library tooling.
Architecture: for each MP3 with artist + title but no album, searches MusicBrainz
    recordings (artist + title, strict), keeps Official releases whose primary type is
    Album (else Single), skips compilations / live / soundtracks, and picks the EARLIEST
    release date. Writes a CSV of proposals (file, artist, title, album, year, kind,
    score). With --write it sets only the empty album tag (+ albumartist if empty); it
    never overwrites existing tags. MusicBrainz asks for <= 1 request/second and a
    descriptive User-Agent (generic - no personal email).
    v2: release must be no later than chart year + 1 (from tools/data/yearend_hot100.csv);
    never a Christmas album; looser retries (main artist, title without brackets).
Invocation: python tools/find_albums.py <mp3-folder> <proposals.csv> [--write]
"""
import csv, os, re, sys, time
import mutagen
import requests

UA = {"User-Agent": "SailboatMusicCatalog/1.0 (personal library tool)"}
API = "https://musicbrainz.org/ws/2/recording/"


def lucene(s):
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\/])', r"\\1", s)


XMAS = re.compile(r"christmas|xmas|noel|holiday", re.I)


def variants(artist, title):
    """Strict first, then looser: main artist only, title without (brackets)."""
    a1 = re.split(r"\s+(?:&|and|with|feat\.?|featuring|,)\s+|\s*\(", artist)[0].strip()
    t1 = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", title).strip()
    t1 = t1.replace("–", "-")
    seen = []
    for a, t in ((artist, title), (a1, title), (a1, t1), (artist, t1)):
        if (a, t) not in seen and a and t: seen.append((a, t))
    return seen


def lookup(artist, title, max_year=None):
    for a, t in variants(artist, title):
        b = _lookup(a, t, max_year)
        time.sleep(1.1)
        if b: return b
    return None


def _lookup(artist, title, max_year):
    q = f'recording:"{lucene(title)}" AND artist:"{lucene(artist)}"'
    for attempt in range(4):
        r = requests.get(API, headers=UA, timeout=30, params={"query": q, "fmt": "json", "limit": 25})
        if r.status_code == 503: time.sleep(3 * (attempt + 1)); continue
        r.raise_for_status(); break
    best = None
    for rec in r.json().get("recordings", []):
        if rec.get("score", 0) < 85: continue
        for rel in rec.get("releases", []):
            if rel.get("status") != "Official": continue
            rg = rel.get("release-group", {})
            kind = rg.get("primary-type")
            if kind not in ("Album", "Single") or rg.get("secondary-types"): continue
            if XMAS.search(rel.get("title", "")): continue      # never file a hit under a Christmas album
            date = rel.get("date") or "9999"
            # a hit's original album came out by the year after it charted - this drops
            # later reissues and compilations ("Poison" on a 2001 compilation)
            if max_year and (not date[:4].isdigit() or int(date[:4]) > max_year): continue
            key = (kind != "Album", date)        # albums first, then earliest
            if best is None or key < best[0]:
                best = (key, rel.get("title"), date[:4], kind, rec.get("score"))
    return best


def main(folder, out, write=False, charts_csv=None):
    import sys as _s; _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from catalog import norm, artist_ok
    chart_year = {}
    if charts_csv:
        for r in csv.DictReader(open(charts_csv, encoding="utf-8")):
            chart_year.setdefault(norm(r["title"]), []).append((r["artist"], int(r["year"])))
    rows = []
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(".mp3"): continue
        p = os.path.join(folder, f)
        t = mutagen.File(p, easy=True)
        g = lambda k: (t.get(k) or [""])[0]
        if g("album"): continue
        yrs = [y for a, y in chart_year.get(norm(g("title")), []) if artist_ok(a, g("artist"))]
        b = lookup(g("artist"), g("title"), max(yrs) + 1 if yrs else None)
        row = [f, g("artist"), g("title"), b[1] if b else "", b[2] if b else "", b[3] if b else "NOT FOUND", b[4] if b else ""]
        rows.append(row)
        print(" | ".join(str(x) for x in row), flush=True)
        if write and b:
            t["album"] = b[1]
            if not g("albumartist"): t["albumartist"] = g("artist")
            t.save()
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["file", "artist", "title", "album", "year", "kind", "score"]); w.writerows(rows)
    print(f"{len(rows)} without album; {sum(1 for r in rows if r[3])} found; -> {out}")


if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], "--write" in sys.argv[3:],
         os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "yearend_hot100.csv"))
