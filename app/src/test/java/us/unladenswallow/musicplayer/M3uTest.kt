/*
 * Purpose: JVM unit tests for M3u (parse, literal resolve, byte-exact in-place removal).
 * Version: v2 (2026-10-11)
 * Scope: PRODUCTION - test suite for the Music Player app.
 * Architecture: plain JUnit4, no Android runtime; also reads the real playlists in
 *   D:\Documents\sailboat (CCMa.m3u8.txt, CCMb.m3u) when present.
 * Invocation: gradlew.bat testDebugUnitTest (from code/music-player).
 */
package us.unladenswallow.musicplayer

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class M3uTest {
    @get:Rule val tmp = TemporaryFolder()

    private val bomLE = byteArrayOf(0xFF.toByte(), 0xFE.toByte())

    @Test fun parsesExtinfAndLiteralRelativePaths() {
        val dir = tmp.newFolder("emulated", "0", "Playlists")
        val f = File(dir, "a.m3u8")
        f.writeText("#EXTM3U\n#EXTINF:-1,Kutless - Beautiful\n../../../4A21-0000/Music/Music/Kutless/X/06 - Beautiful.mp3\nplain/07 - Other.mp3\n")
        val e = M3u.entries(f)
        assertEquals(2, e.size)
        assertEquals("Kutless", e[0].artist)
        assertEquals("Beautiful", e[0].songTitle)
        assertEquals(
            File(tmp.root, "4A21-0000/Music/Music/Kutless/X/06 - Beautiful.mp3").absolutePath,
            M3u.literalPath(f, e[0].line).absolutePath,
        )
        assertEquals("Other", e[1].songTitle)
    }

    @Test fun removeKeepsUtf16BomAndCrlf() {
        val f = tmp.newFile("b.m3u")
        val text = "#EXTM3U\r\na/one.mp3\r\nb/two.mp3\r\nc/thrée.mp3\r\n"
        f.writeBytes(bomLE + text.toByteArray(Charsets.UTF_16LE))
        val backups = tmp.newFolder("bk")

        assertEquals(1, M3u.removeEntry(f, "missing:b/two.mp3", backups))

        val expected = bomLE + "#EXTM3U\r\na/one.mp3\r\nc/thrée.mp3\r\n".toByteArray(Charsets.UTF_16LE)
        assertArrayEquals(expected, f.readBytes())
        assertTrue(File(backups, "b.m3u.original").exists())
        assertTrue(File(backups, "removed.log").readText().contains("b/two.mp3"))
    }

    @Test fun removeTakesTheExtinfLineAndAllDuplicates() {
        val f = tmp.newFile("c.m3u8")
        f.writeText("#EXTM3U\n#EXTINF:-1,A - One\nx/1.mp3\n#EXTINF:-1,B - Two\nx/2.mp3\n#EXTINF:-1,A - One\nx/1.mp3\n")
        assertEquals(2, M3u.removeEntry(f, "missing:x/1.mp3", null))
        assertEquals("#EXTM3U\n#EXTINF:-1,B - Two\nx/2.mp3\n", f.readText())
    }

    @Test fun removeMissingKeyLeavesFileUntouched() {
        val f = tmp.newFile("d.m3u8")
        f.writeText("#EXTM3U\nx/1.mp3\n")
        val before = f.readBytes()
        assertEquals(0, M3u.removeEntry(f, "missing:nope.mp3", null))
        assertArrayEquals(before, f.readBytes())
    }

    @Test fun windowsDrivePathIsLeftAsIs() {
        val f = tmp.newFile("e.m3u8")
        assertEquals("F:\\Music\\a.mp3", M3u.literalPath(f, "F:\\Music\\a.mp3").path)
    }

    @Test fun cp1252RemovalKeepsOtherBytesExactly() {
        val f = tmp.newFile("s.m3u")
        // 0x92 = cp1252 right quote, 0x81 = undefined in cp1252: both must survive untouched.
        val keep = "#EXTM3U\r\n".toByteArray() + "a/Don".toByteArray() + byteArrayOf(0x92.toByte()) +
            "t.mp3\r\nb/x".toByteArray() + byteArrayOf(0x81.toByte()) + ".mp3\r\n".toByteArray()
        f.writeBytes(keep + "c/gone.mp3\r\n".toByteArray())
        assertEquals(1, M3u.removeEntry(f, "missing:c/gone.mp3", null))
        assertArrayEquals(keep, f.readBytes())
        assertEquals("a/Don\u2019t.mp3", M3u.entries(f)[0].line)
    }

    @Test fun readsLeesRealPlaylists() {
        val root = File("../../..").canonicalFile  // app/ -> code/music-player -> code -> sailboat
        val b = File(root, "CCMb.m3u")
        val a = File(root, "CCMa.m3u8.txt")
        assumeTrue(a.exists() && b.exists())
        val eb = M3u.entries(b)
        val ea = M3u.entries(a)
        assertTrue("CCMb: ${eb.size}", eb.size > 400)
        assertTrue("CCMa: ${ea.size}", ea.size > 400)
        assertTrue(eb.all { it.line.trim('"').startsWith("../../../4A21-0000/Music/Music/") })
        val quoted = eb.first { it.line.startsWith("\"") }
        assertTrue(M3u.literalPath(b, quoted.line).path.replace('\\', '/')
            .endsWith("Come To The Well/03 - Jesus, Friend Of Sinners.mp3"))
        // Round-trip: removing from a copy changes exactly one entry and keeps the encoding.
        val copy = File(tmp.root, "CCMb.m3u").also { b.copyTo(it) }
        assertEquals(1, M3u.removeEntry(copy, eb[3].key, null))
        assertEquals(eb.size - 1, M3u.entries(copy).size)
        assertArrayEquals(b.readBytes().copyOf(2), copy.readBytes().copyOf(2))
    }
}
