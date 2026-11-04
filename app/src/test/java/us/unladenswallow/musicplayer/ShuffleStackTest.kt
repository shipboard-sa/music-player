/*
 * Purpose: JVM unit tests for ShuffleStack (no repeats in a round, uniformity,
 *   persistence, reconcile with an edited playlist, removal).
 * Version: v1 (2026-10-11)
 * Scope: PRODUCTION - test suite for the Music Player app.
 * Architecture: plain JUnit4, no Android runtime.
 * Invocation: gradlew.bat testDebugUnitTest (from code/music-player).
 */
package us.unladenswallow.musicplayer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.Random

class ShuffleStackTest {
    @get:Rule val tmp = TemporaryFolder()

    private val songs = (1..4000).map { "song$it.mp3" }

    @Test fun aRoundPlaysEverySongExactlyOnce() {
        val s = ShuffleStack.fresh(songs)
        assertEquals(4000, s.size)
        assertEquals(songs.toSet(), s.order.toSet())
        assertNotEquals(songs, s.order)  // 1 in 4000! chance of a false failure
    }

    @Test fun shuffleIsUniform() {
        // Each of 5 songs should land first ~1/5 of the time.
        val counts = IntArray(5)
        val rnd = Random(42)
        repeat(50_000) { counts[ShuffleStack.fresh(listOf("0", "1", "2", "3", "4"), rnd = rnd).order[0].toInt()]++ }
        counts.forEach { assertTrue("counts ${counts.toList()}", it in 9_500..10_500) }
    }

    @Test fun newRoundAvoidsRepeatingTheLastSong() {
        val rnd = Random(7)
        repeat(2000) {
            assertNotEquals("b", ShuffleStack.fresh(listOf("a", "b", "c"), avoidFirst = "b", rnd = rnd).order[0])
        }
    }

    @Test fun saveAndLoadKeepOrderAndPosition() {
        val s = ShuffleStack.fresh(songs)
        s.markPlaying(s.order[1234])
        val f = File(tmp.root, "stacks/x.txt")
        s.save(f)
        val l = ShuffleStack.load(f)!!
        assertEquals(s.order, l.order)
        assertEquals(1234, l.pos)
    }

    @Test fun reconcileDropsGoneSongsAndAddsNewOnesToTheUnplayedPart() {
        val s = ShuffleStack(mutableListOf("a", "b", "c", "d", "e"), 2)  // a, b played; c now
        s.reconcile(listOf("a", "c", "d", "e", "new1", "new2"), Random(1))
        assertEquals(1, s.pos)                       // b vanished from before pos
        assertEquals(listOf("a"), s.order.subList(0, s.pos))
        assertEquals(setOf("c", "d", "e", "new1", "new2"), s.remaining.toSet())
    }

    @Test fun removeBeforeAndAfterPosition() {
        val s = ShuffleStack(mutableListOf("a", "b", "c", "d"), 2)
        s.remove("a"); assertEquals(1, s.pos); assertEquals("c", s.order[s.pos])
        s.remove("c"); assertEquals(1, s.pos); assertEquals("d", s.order[s.pos])
    }
}
