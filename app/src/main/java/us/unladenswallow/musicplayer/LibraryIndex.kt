/*
 * Purpose: Find the MP3 a playlist line means when the line is written in another path
 *   style (other SD card id, missing "Music/", wrong case, "?" for characters an exporter
 *   couldn't write).
 * Version: v3 (2026-10-11)
 * Scope: PRODUCTION - Music Player app on the music phone.
 * Architecture: pure-JVM data layer (unit-tested). PlaybackService makes one per playlist
 *   load and passes resolve() to M3u.entries / M3u.removeEntry. Lookup order: the literal
 *   path, then the line's tail walked folder by folder under each Music folder, matching
 *   each name exactly, then case-insensitively, then with any non-ASCII character as a
 *   one-character "?" wildcard. Folder listings are cached, so only folders a playlist
 *   actually touches are read.
 *   v3: lazy per-folder lookup - v2 walked all ~31K SD files per load (minutes via FUSE).
 * Invocation: imported by PlaybackService.kt.
 */
package us.unladenswallow.musicplayer

import java.io.File
import java.util.Locale

class LibraryIndex private constructor(private val musicDirs: List<File>) {

    private class Listing(val lower: Map<String, File>, val wild: Map<String, File>)
    private val listings = HashMap<String, Listing?>()

    fun resolve(playlist: File, line: String): File? {
        M3u.resolveStrict(playlist, line)?.let { return it }
        for (c in candidates(line)) {
            val segs = c.split('/').filter { it.isNotEmpty() }
            if (segs.isEmpty() || segs.any { it.startsWith(".") || it.startsWith("@") }) continue
            for (root in musicDirs) walk(root, segs)?.let { return it }
        }
        return null
    }

    private fun walk(root: File, segs: List<String>): File? {
        var cur = root
        for ((i, seg) in segs.withIndex()) {
            val direct = File(cur, seg)
            val last = i == segs.size - 1
            cur = if (if (last) direct.isFile else direct.isDirectory) direct
                else {
                    val l = listing(cur) ?: return null
                    val k = seg.lowercase(Locale.ROOT)
                    l.lower[k] ?: l.wild[wild(k)] ?: return null
                }
        }
        return cur.takeIf { it.isFile }
    }

    @Synchronized
    private fun listing(dir: File): Listing? = listings.getOrPut(dir.path) {
        val kids = dir.listFiles() ?: return@getOrPut null
        val lower = HashMap<String, File>(); val w = HashMap<String, File>()
        for (k in kids) {
            if (k.name.startsWith(".") || k.name.startsWith("@")) continue  // .thumbnails, NAS @eaDir
            val n = k.name.lowercase(Locale.ROOT)
            lower.putIfAbsent(n, k); w.putIfAbsent(wild(n), k)
        }
        Listing(lower, w)
    }

    companion object {
        fun build(musicDirs: List<File>): LibraryIndex = LibraryIndex(musicDirs)

        /**
         * The Music folders on the given storage volumes (internal storage + SD cards).
         * Apps may not list /storage itself, so the caller passes the volume roots
         * (PlaybackService derives them from Context.getExternalFilesDirs).
         */
        fun musicDirs(volumes: List<File>): List<File> =
            volumes.distinctBy { it.path }
                .flatMap { v -> v.listFiles()?.filter { it.isDirectory && it.name.equals("music", true) } ?: emptyList() }

        /**
         * The playlist line reduced to "Artist/Album/song.mp3"-style tails to look up:
         * quotes, "../", "/storage/<volume>/" and leading "Music/" folders stripped, each
         * stripping step offered as a candidate (longest first).
         */
        fun candidates(line: String): List<String> {
            var p = M3u.unquote(line.trim()).replace('\\', '/')
            p = p.replace(Regex("^[A-Za-z]:/"), "")                        // F:/Music/...
            while (p.startsWith("../") || p.startsWith("./")) p = p.substringAfter('/')
            p = p.removePrefix("/")
            p = p.replace(Regex("^(storage/|mnt/)?(emulated/\\d+/|sdcard\\d*/|self/primary/|[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}/)"), "")
            val out = ArrayList<String>()
            out.add(p)
            while (p.startsWith("music/", ignoreCase = true)) { p = p.substring(6); out.add(p) }
            return out
        }

        private fun wild(s: String): String =
            buildString(s.length) { for (ch in s) append(if (ch.code > 127) '?' else ch) }
    }
}
