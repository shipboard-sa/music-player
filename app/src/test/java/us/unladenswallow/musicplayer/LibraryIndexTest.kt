/*
 * Purpose: JVM unit tests for LibraryIndex - the path styles seen in the phone's real
 *   playlists (2026-10-11) resolve to the SD card's Music folder; removal by song.
 * Version: v1 (2026-10-11)
 * Scope: PRODUCTION - test suite for the Music Player app.
 * Architecture: plain JUnit4 with a fake /storage tree in a temp folder.
 * Invocation: gradlew.bat testDebugUnitTest (from code/music-player).
 */
package us.unladenswallow.musicplayer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class LibraryIndexTest {
    @get:Rule val tmp = TemporaryFolder()
    private lateinit var storage: File
    private lateinit var internal: File
    private lateinit var playlist: File
    private lateinit var idx: LibraryIndex

    private fun song(rel: String) = File(storage, "4A21-0000/Music/$rel").apply { parentFile!!.mkdirs(); writeText("x") }

    @Before fun setUp() {
        storage = tmp.newFolder("storage")
        internal = File(storage, "emulated/0").apply { File(this, "Music").mkdirs() }
        song("The Beatles/1/Hey Jude.mp3")
        song("Olivia Newton\u2010John/Physical/Physical.mp3")
        song("kids/'N Sync/home for Christmas/01_'N Sync - Home For Christmas.mp3")
        song("@eaDir/junk.mp3")
        playlist = File(internal, "Music/sailing.m3u")
        idx = LibraryIndex.build(LibraryIndex.musicDirs(listOf(internal, File(storage, "4A21-0000"))))
    }

    @Test fun nasJunkFoldersAreIgnored() = assertNull(idx.resolve(playlist, "@eaDir/junk.mp3"))

    @Test fun allPathStylesFromThePhoneResolve() {
        val want = File(storage, "4A21-0000/Music/The Beatles/1/Hey Jude.mp3").path
        for (line in listOf(
            "The Beatles/1/Hey Jude.mp3",                              // sailing.m3u: relative to internal Music
            "../../../4A21-0000/The Beatles/1/Hey Jude.mp3",           // sailing_2.m3u: SD root, no Music/
            "../../../4A21-0000/Music/Music/the beatles/1/hey jude.mp3", // CCMa: Music/Music, other case
            "\"../../../4A21-0000/The Beatles/1/Hey Jude.mp3\"",      // quoted
        )) assertEquals(line, want.lowercase(), idx.resolve(playlist, line)?.path?.lowercase())
    }

    @Test fun questionMarkMatchesACharacterTheExporterLost() {
        assertEquals("Physical.mp3", idx.resolve(playlist, "Olivia Newton?John/Physical/Physical.mp3")?.name)
    }

    @Test fun oldSdCardIdAndLowercaseMusicMusic() {
        val line = "/storage/6236-3939/music/music/kids/'N Sync/home for Christmas/01_'N Sync - Home For Christmas.mp3"
        assertEquals("01_'N Sync - Home For Christmas.mp3", idx.resolve(playlist, line)?.name)
    }

    @Test fun genuinelyMissingStaysMissing() {
        assertNull(idx.resolve(playlist, "Doors/The Best Of The Doors/When the The Beatles/1/Hey Jude.mp3"))
    }

    @Test fun removeDropsEveryLineForTheSameSong() {
        playlist.writeText("#EXTM3U\nThe Beatles/1/Hey Jude.mp3\n../../../4A21-0000/The Beatles/1/Hey Jude.mp3\nOlivia Newton?John/Physical/Physical.mp3\n")
        val entries = M3u.entries(playlist, idx::resolve)
        assertEquals(2, entries.map { it.key }.distinct().size)
        assertEquals(2, M3u.removeEntry(playlist, entries[0].key, null, idx::resolve))
        assertEquals("#EXTM3U\nOlivia Newton?John/Physical/Physical.mp3\n", playlist.readText())
    }
}
