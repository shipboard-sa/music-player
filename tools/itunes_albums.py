"""
Purpose: Second-source album lookup via Apple's public iTunes Search API, for songs
    MusicBrainz could not place (or only placed on a single).
Version: v1 (2026-10-12)
Scope: STANDALONE UTILITY - Music Player library tooling.
Architecture: reads find_albums.py's proposals CSV; for rows NOT FOUND or kind Single it
    searches iTunes (entity=song), keeps hits by the same artist with the same title,
    drops various-artists compilations and Christmas albums, and picks: the earliest
    album released by chart year + 1; else the artist's own album / greatest hits
    (earliest). Writes an updated CSV with a source column. No tags are written here.
    The API is free, keyless and rate-limited (~20 requests/min), so it sleeps 3 s per call.
Invocation: python tools/itunes_albums.py <proposals.csv> <out.csv>
"""
import csv, os, re, sys, time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import norm, artist_ok          # noqa: E402

UA = {"User-Agent": "SailboatMusicCatalog/1.0 (personal library tool)"}
XMAS = re.compile(r"christmas|xmas|noel|holiday", re.I)
SINGLE = re.compile(r"\s-\s(single|ep)$", re.I)


def chart_years():
    out = {}
    for r in csv.DictReader(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "yearend_hot100.csv"), encoding="utf-8")):
        out.setdefault(norm(r["title"]), []).append((r["artist"], int(r["year"])))
    return out


def search(artist, title):
    main_artist = re.split(r"\s+(?:&|and|with|feat\.?|featuring)\s+|\s*\(|,", artist)[0].strip()
    clean_title = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", title).strip()
    for term in (f"{artist} {title}", f"{main_artist} {clean_title}"):
        for attempt in range(3):
            r = requests.get("https://itunes.apple.com/search", headers=UA, timeout=30,
                             params={"term": term, "entity": "song", "limit": 50, "country": "US"})
            time.sleep(3)
            if r.status_code in (403, 429): time.sleep(20); continue
            r.raise_for_status(); break
        hits = [h for h in r.json().get("results", [])
                if artist_ok(h.get("artistName", ""), main_artist)
                and (norm(h.get("trackName", "")).startswith(norm(clean_title)) or norm(clean_title).startswith(norm(h.get("trackName", ""))))]
        if hits: return hits
    return []


def pick(hits, max_year):
    def ok(h):
        name = h.get("collectionName", "")
        return name and not XMAS.search(name) and h.get("collectionArtistName", h.get("artistName")) != "Various Artists"
    albums = [h for h in hits if ok(h) and not SINGLE.search(h["collectionName"])]
    dated = lambda h: h.get("releaseDate", "9999")[:10]
    early = [h for h in albums if max_year and dated(h)[:4].isdigit() and int(dated(h)[:4]) <= max_year]
    for pool, why in ((early, "original album"), (albums, "artist album/hits")):
        if pool:
            h = min(pool, key=dated)
            return h["collectionName"], dated(h)[:4], why
    return None


def main(src, out):
    cy = chart_years()
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    for r in rows:
        r["source"] = "MusicBrainz" if r["album"] else ""
        if r["album"] and r["kind"] != "Single": continue
        yrs = [y for a, y in cy.get(norm(r["title"]), []) if artist_ok(a, r["artist"])]
        p = pick(search(r["artist"], r["title"]), max(yrs) + 1 if yrs else None)
        if p:
            r["album"], r["year"], r["kind"], r["source"] = p[0], p[1], p[2], "iTunes"
        print(f'{r["artist"][:28]:28} {r["title"][:34]:34} => {r["album"][:45]} ({r["year"]} {r["kind"]} {r["source"]})', flush=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f'{sum(1 for r in rows if r["album"])} of {len(rows)} now have an album -> {out}')


if __name__ == "__main__":
    if len(sys.argv) != 3: sys.exit(__doc__)
    main(*sys.argv[1:])
