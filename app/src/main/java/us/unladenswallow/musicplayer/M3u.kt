/*
 * Purpose: Read and edit .m3u/.m3u8 playlist files in place (the "system playlists").
 * Version: v4 (2026-10-11)
 * Scope: PRODUCTION - Music Player app on the music phone.
 * Architecture: pure-JVM data layer (no Android imports, unit-tested in src/test).
 *   PlaybackService calls entries() to build the shuffle and removeEntry() for
 *   "remove the playing song". Only the playlist text is edited - never the MP3.
 *   A song's identity (Entry.key) is the file it resolves to, so a song listed twice
 *   in different path styles is one song, and removing it drops every line for it.
 *   Removal works on the raw bytes: untouched lines come back byte-for-byte whatever
 *   the encoding (UTF-8, UTF-16 + BOM, cp1252); the write is atomic (temp + rename)
 *   with a one-time backup and a removal log.
 *   v2: tolerant resolution via LibraryIndex (real phone playlists mix path styles).
 * Invocation: imported by PlaybackService.kt and MainActivity.kt.
 */
package us.unladenswallow.musicplayer

import java.io.File
import java.net.URI
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** One song line in a playlist. [file] is null when the line points at nothing on this phone. */
data class Entry(val line: String, val title: String?, val file: File?) {
    /** Stable identity used by the shuffle stack and for removal. */
    // Lowercased: phone storage (and Windows) ignores case, so "the beatles/..." and
    // "The Beatles/..." are the same file and must be the same song.
    val key: String get() = file?.path?.lowercase(Locale.ROOT) ?: "missing:$line"

    /** "Artist - Title" from #EXTINF when present, else derived from the path. */
    // A file loose in a Music folder is usually named "Artist - Title.mp3";
    // otherwise the layout is Music/<Artist>/<Album>/<song>.
    val artist: String?
        get() = when {
            title != null && title.contains(" - ") -> title.substringBefore(" - ")
            looseInMusic() -> if (title == null && baseName().contains(" - ")) baseName().substringBefore(" - ") else null
            else -> pathParts().let { if (it.size >= 3) it[it.size - 3] else null }
        }
    val songTitle: String
        get() = title?.let { if (it.contains(" - ")) it.substringAfter(" - ") else it }
            ?: if (looseInMusic() && baseName().contains(" - ")) baseName().substringAfter(" - ")
            else baseName().replace(Regex("^\\d+\\s*[-_.]?\\s*"), "")

    private fun baseName(): String = pathParts().last().substringBeforeLast('.')
    private fun looseInMusic(): Boolean =
        pathParts().let { it.size >= 2 && it[it.size - 2].equals("music", ignoreCase = true) }

    private fun pathParts(): List<String> =
        (file?.path ?: M3u.unquote(line)).replace('\\', '/').split('/').filter { it.isNotEmpty() }
}

object M3u {
    private val UTF16LE_BOM = byteArrayOf(0xFF.toByte(), 0xFE.toByte())
    private val UTF16BE_BOM = byteArrayOf(0xFE.toByte(), 0xFF.toByte())
    private val UTF8_BOM = byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte())

    /** How a file was stored. */
    data class Text(val lines: List<String>, val charset: Charset, val bom: ByteArray, val bytes: ByteArray)

    fun isPlaylist(f: File): Boolean =
        f.isFile && f.extension.lowercase(Locale.ROOT).let { it == "m3u" || it == "m3u8" }

    fun read(file: File): Text {
        val bytes = file.readBytes()
        val (charset, bom) = when {
            bytes.startsWith(UTF16LE_BOM) -> Charsets.UTF_16LE to UTF16LE_BOM
            bytes.startsWith(UTF16BE_BOM) -> Charsets.UTF_16BE to UTF16BE_BOM
            bytes.startsWith(UTF8_BOM) -> Charsets.UTF_8 to UTF8_BOM
            else -> (if (isStrictUtf8(bytes)) Charsets.UTF_8 else Charset.forName("windows-1252")) to ByteArray(0)
        }
        // Split on '\n' only, exactly as splitBytes() does, so line i == byte segment i.
        val lines = splitBytes(bytes, bom.size, unitSize(charset), bigEndian = charset == Charsets.UTF_16BE)
            .map { (s, e) -> String(bytes, s, e - s, charset).trimEnd('\n', '\u0000').removeSuffix("\r") }
        return Text(lines, charset, bom, bytes)
    }

    /** Song entries, resolved with [resolve] (default: plain path resolution only). */
    fun entries(file: File, resolve: (File, String) -> File? = ::resolveStrict): List<Entry> {
        val out = ArrayList<Entry>()
        var pendingTitle: String? = null
        for (raw in read(file).lines) {
            val line = raw.trim()
            when {
                line.isEmpty() -> {}
                line.startsWith("#EXTINF", ignoreCase = true) ->
                    pendingTitle = line.substringAfter(',', "").trim().ifEmpty { null }
                line.startsWith("#") -> {}
                else -> {
                    out.add(Entry(line, pendingTitle, resolve(file, line)))
                    pendingTitle = null
                }
            }
        }
        return out
    }

    fun unquote(line: String): String =
        if (line.length >= 2 && line.startsWith('"') && line.endsWith('"')) line.substring(1, line.length - 1) else line

    /** The literal meaning of a path line (relative to the playlist's folder). Existence not checked. */
    fun literalPath(playlist: File, line: String): File {
        val pathLine = unquote(line)
        if (pathLine.startsWith("file:", ignoreCase = true)) {
            return runCatching { File(URI(pathLine)) }.getOrElse { File(pathLine) }
        }
        // A Windows drive path (F:\Music\...) from a PC copy - cannot exist on the phone.
        if (Regex("^[A-Za-z]:[\\\\/]").containsMatchIn(pathLine)) return File(pathLine)
        val p = pathLine.replace('\\', '/')
        val full = if (p.startsWith("/")) p
            else playlist.absoluteFile.parentFile!!.path.replace('\\', '/') + "/" + p
        return File(normalize(full))
    }

    /** Plain resolution: the literal path if that file exists, else null. */
    fun resolveStrict(playlist: File, line: String): File? =
        literalPath(playlist, line).takeIf { it.isFile }

    /**
     * Remove every line that resolves to the song [key] (plus the #EXTINF line directly
     * above each) from [playlist]. Returns how many song lines were removed (0 = not found,
     * file untouched). Before the first edit of a playlist a copy is kept in [backupDir];
     * every removal is appended to backupDir/removed.log so it can be put back by hand.
     */
    fun removeEntry(
        playlist: File,
        key: String,
        backupDir: File?,
        resolve: (File, String) -> File? = ::resolveStrict,
        knownKeys: Map<String, String> = emptyMap(),  // trimmed line -> key, from entries()
    ): Int {
        val t = read(playlist)
        val drop = HashSet<Int>()
        for ((i, raw) in t.lines.withIndex()) {
            val s = raw.trim()
            if (s.isEmpty() || s.startsWith("#")) continue
            // Lines matched when the playlist was opened skip the (slow, SD card) lookup.
            val k = knownKeys[s] ?: Entry(s, null, resolve(playlist, s)).key
            if (k == key) {
                drop.add(i)
                if (i > 0 && t.lines[i - 1].trim().startsWith("#EXTINF", ignoreCase = true)) drop.add(i - 1)
            }
        }
        val removed = drop.count { !t.lines[it].trim().startsWith("#") }
        if (removed == 0) return 0

        if (backupDir != null) {
            backupDir.mkdirs()
            val orig = File(backupDir, playlist.name + ".original")
            if (!orig.exists()) playlist.copyTo(orig)
            val stamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())
            File(backupDir, "removed.log").appendText(
                "$stamp\t${playlist.absolutePath}\n" + drop.sorted().joinToString("") { "\t${t.lines[it]}\n" }
            )
        }

        // Rebuild from the original bytes, leaving out the dropped line segments.
        val segs = splitBytes(t.bytes, t.bom.size, unitSize(t.charset), bigEndian = t.charset == Charsets.UTF_16BE)
        val out = java.io.ByteArrayOutputStream(t.bytes.size)
        out.write(t.bytes, 0, t.bom.size)
        for ((i, se) in segs.withIndex()) if (i !in drop) out.write(t.bytes, se.first, se.second - se.first)
        val bytes = out.toByteArray()

        val tmp = File(playlist.absoluteFile.parentFile, ".${playlist.name}.tmp")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(playlist)) {
            playlist.writeBytes(bytes)
            tmp.delete()
        }
        return removed
    }

    private fun unitSize(cs: Charset) = if (cs == Charsets.UTF_16LE || cs == Charsets.UTF_16BE) 2 else 1

    /** Byte ranges [start, end) of each line, each including its '\n' (the last may lack one). */
    private fun splitBytes(b: ByteArray, from: Int, unit: Int, bigEndian: Boolean): List<Pair<Int, Int>> {
        val out = ArrayList<Pair<Int, Int>>()
        var start = from
        var i = from
        while (i + unit <= b.size) {
            val nl = if (unit == 1) b[i] == '\n'.code.toByte()
                else if (bigEndian) b[i] == 0.toByte() && b[i + 1] == '\n'.code.toByte()
                else b[i] == '\n'.code.toByte() && b[i + 1] == 0.toByte()
            i += unit
            if (nl) { out.add(start to i); start = i }
        }
        if (start < b.size) out.add(start to b.size)
        return out
    }

    /** Collapse "." and ".." segments as plain text (never throws on odd characters). */
    fun normalize(path: String): String {
        val prefix = Regex("^([A-Za-z]:)?/").find(path)?.value ?: ""
        val out = ArrayList<String>()
        for (seg in path.substring(prefix.length).split('/')) {
            when (seg) {
                "", "." -> {}
                ".." -> if (out.isNotEmpty()) out.removeAt(out.size - 1)
                else -> out.add(seg)
            }
        }
        return prefix + out.joinToString("/")
    }

    private fun ByteArray.startsWith(prefix: ByteArray): Boolean =
        size >= prefix.size && prefix.indices.all { this[it] == prefix[it] }

    private fun isStrictUtf8(bytes: ByteArray): Boolean = try {
        Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes))
        true
    } catch (e: CharacterCodingException) {
        false
    }
}
