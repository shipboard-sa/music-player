/*
 * Purpose: The shuffled "stack" for one playlist - true random order, every song once
 *   per round, no repeats until the round is done; survives app restarts.
 * Version: v1 (2026-10-11)
 * Scope: PRODUCTION - Music Player app on the music phone.
 * Architecture: pure-JVM data layer (unit-tested in src/test). PlaybackService keeps
 *   one per playlist: order[] is a Fisher-Yates shuffle (SecureRandom) of the song
 *   keys, pos is the song now playing; everything before pos has been played this
 *   round. Saved as a small text file in the app's private storage per playlist.
 * Invocation: imported by PlaybackService.kt.
 */
package us.unladenswallow.musicplayer

import java.io.File
import java.security.SecureRandom
import java.util.Random

class ShuffleStack(val order: MutableList<String>, var pos: Int) {

    val remaining: List<String> get() = order.subList(pos.coerceAtMost(order.size), order.size)
    val size: Int get() = order.size

    /** The player moved on to [key]: everything before it is now played. */
    fun markPlaying(key: String) {
        val i = order.indexOf(key)
        if (i >= 0) pos = i
    }

    /** Drop [key] from the round (it was removed from the playlist). */
    fun remove(key: String) {
        val i = order.indexOf(key)
        if (i < 0) return
        order.removeAt(i)
        if (i < pos) pos--
    }

    /**
     * Bring the stack in line with the playlist as it is on disk now: songs gone from the
     * file drop out; songs new to the file go into a random spot among the not-yet-played
     * ones (so they still play this round, at a random time).
     */
    fun reconcile(present: Collection<String>, rnd: Random = SecureRandom()) {
        val presentSet = present.toHashSet()
        val known = order.toHashSet()
        var i = 0
        while (i < order.size) {
            if (order[i] !in presentSet) {
                order.removeAt(i)
                if (i < pos) pos--
            } else i++
        }
        pos = pos.coerceIn(0, order.size)
        for (k in present.distinct()) {
            if (k !in known) order.add(pos + rnd.nextInt(order.size - pos + 1), k)
        }
    }

    fun save(f: File) {
        f.parentFile?.mkdirs()
        val tmp = File(f.parentFile, f.name + ".tmp")
        tmp.writeText(buildString {
            append("v1\n").append("pos=").append(pos).append('\n')
            for (k in order) append(k).append('\n')
        })
        if (!tmp.renameTo(f)) { f.writeText(tmp.readText()); tmp.delete() }
    }

    companion object {
        /** A new round: Fisher-Yates over the distinct songs, SecureRandom-seeded. */
        fun fresh(keys: Collection<String>, avoidFirst: String? = null, rnd: Random = SecureRandom()): ShuffleStack {
            val a = keys.distinct().toMutableList()
            for (i in a.size - 1 downTo 1) {
                val j = rnd.nextInt(i + 1)
                val t = a[i]; a[i] = a[j]; a[j] = t
            }
            // Don't open the new round with the song that just closed the last one.
            if (a.size > 1 && a[0] == avoidFirst) {
                val j = 1 + rnd.nextInt(a.size - 1)
                val t = a[0]; a[0] = a[j]; a[j] = t
            }
            return ShuffleStack(a, 0)
        }

        fun load(f: File): ShuffleStack? {
            if (!f.isFile) return null
            val lines = f.readLines()
            if (lines.size < 2 || lines[0] != "v1" || !lines[1].startsWith("pos=")) return null
            val pos = lines[1].removePrefix("pos=").toIntOrNull() ?: return null
            val order = lines.drop(2).filter { it.isNotEmpty() }.toMutableList()
            return ShuffleStack(order, pos.coerceIn(0, order.size))
        }
    }
}
