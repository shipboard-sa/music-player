/*
 * Purpose: Background playback - plays the chosen playlist's shuffle stack in order,
 *   starts a new round when it runs out, and removes the playing song on request.
 * Version: v8 (2026-10-12)
 * Scope: PRODUCTION - Music Player app on the music phone.
 * Architecture: Media3 MediaSessionService + ExoPlayer. Owns the ShuffleStack and the
 *   M3u edits. The ExoPlayer queue is the not-yet-played part of the stack (order[pos..]),
 *   so Bluetooth / notification Next simply pops the stack. MainActivity talks to it
 *   through a MediaController plus the custom commands below (load / remove / status).
 * Invocation: started by the system when MainActivity (or Bluetooth media buttons)
 *   connect; declared in AndroidManifest.xml. Needs all-files access to read MP3s and
 *   rewrite playlists. State: one stack file per playlist in filesDir/stacks, prefs "player"; backups + removal
 *   log in <internal storage>/Documents/MusicPlayer/.
 *   v2: songs resolved through LibraryIndex (built per playlist load).
 *   v3: a new load cancels one in progress; status reports K_LOADING; no remove mid-load.
 *   v4: Remove skips the song first, then edits the file using the keys from load.
 *   v5: ACTION_AUTOPLAY (from BluetoothAutoPlay when the Fusion connects).
 *   v8: playlist edits serialised (Mutex).
 *   v7: per-playlist cache of where each line was found (first open slow, then fast).
 *   v6: onPlaybackResumption + autoplay reopen the last playlist when nothing is queued; logging (tag MusicPlayer).
 */
package us.unladenswallow.musicplayer

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.guava.future
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

class PlaybackService : MediaSessionService() {

    companion object {
        private const val TAG = "MusicPlayer"
        const val ACTION_AUTOPLAY = "us.unladenswallow.musicplayer.AUTOPLAY"  // Fusion connected
        private const val NOTIFICATION_ID = 1001  // same id Media3 uses, so its player notification replaces ours
        const val CMD_LOAD = "us.unladenswallow.musicplayer.LOAD"      // arg: path
        const val CMD_REMOVE = "us.unladenswallow.musicplayer.REMOVE"  // removes the playing song
        const val CMD_STATUS = "us.unladenswallow.musicplayer.STATUS"
        const val ARG_PATH = "path"
        // Status / result keys
        const val K_PLAYLIST = "playlist"
        const val K_POS = "pos"
        const val K_TOTAL = "total"
        const val K_MISSING = "missing"
        const val K_MESSAGE = "message"
        const val K_REMOVED = "removed"
        const val K_LOADING = "loading"   // path of a playlist still being opened
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var player: ExoPlayer
    private lateinit var session: MediaSession

    private var playlist: File? = null
    private var stack: ShuffleStack? = null
    private var entries: Map<String, Entry> = emptyMap()
    private var index: LibraryIndex? = null
    private var lineKeys: Map<String, String> = emptyMap()  // playlist line -> song key
    private var loadJob: Job? = null
    private var loading: String? = null
    private var autoPlayPending = false
    // One playlist edit at a time: two Removes in flight could each rewrite the file from
    // their own earlier read and undo the other (seen 10-11: one Remove ran twice).
    private val editLock = Mutex()
    private var missing = 0
    private var errorsInARow = 0
    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    private val ioSerial = Dispatchers.IO.limitedParallelism(1)  // stack saves in order

    private val backupDir: File
        get() = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS), "MusicPlayer")

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "service onCreate")
        player = ExoPlayer.Builder(this)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(C.USAGE_MEDIA)
                    .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                    .build(),
                /* handleAudioFocus = */ true,
            )
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_LOCAL)
            .build()
        player.addListener(object : Player.Listener {
            override fun onMediaItemTransition(item: MediaItem?, reason: Int) {
                val s = stack ?: return
                item?.mediaId?.let { s.markPlaying(it); saveStack() }
            }

            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_READY) errorsInARow = 0
                // Ran off the end of the round (an empty queue means nothing playable - stop).
                if (state == Player.STATE_ENDED && player.mediaItemCount > 0) startNewRound(play = true)
            }

            override fun onPlayerError(error: PlaybackException) {
                // An unreadable file: skip it rather than stop the music - but give up after
                // a run of failures (e.g. file access revoked) instead of spinning forever.
                if (++errorsInARow >= 5) return
                if (player.hasNextMediaItem()) {
                    player.seekToNextMediaItem()
                    player.prepare()
                    player.play()
                } else startNewRound(play = true)
            }
        })
        session = MediaSession.Builder(this, player).setCallback(Callback()).build()

        prefs().getString("playlist", null)?.let { startLoad(it, play = false) }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession = session

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.i(TAG, "onStartCommand ${intent?.action} items=${player.mediaItemCount} loading=$loading playlist=$playlist")
        if (intent?.action != ACTION_AUTOPLAY) return super.onStartCommand(intent, flags, startId)
        // Started by BluetoothAutoPlay via startForegroundService: go foreground at once
        // (Android's deadline is seconds; opening the playlist can take ~25 s).
        startForegroundNow()
        when {
            player.isPlaying -> {}
            loading != null -> autoPlayPending = true          // play when the open finishes
            player.mediaItemCount > 0 -> { player.prepare(); player.play() }
            else -> {
                // Nothing queued (e.g. a service restarted without its queue): reopen the
                // last playlist and play when it's ready.
                val last = prefs().getString("playlist", null)
                if (last == null) stopForegroundNow() else { autoPlayPending = true; startLoad(last, play = false) }
            }
        }
        return START_NOT_STICKY
    }

    private fun startForegroundNow() {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel("autoplay") == null) {
            nm.createNotificationChannel(NotificationChannel("autoplay", "Starting music", NotificationManager.IMPORTANCE_LOW))
        }
        val n = NotificationCompat.Builder(this, "autoplay")
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("Music Player")
            .setContentText("Fusion connected - starting the music…")
            .build()
        ServiceCompat.startForeground(
            this, NOTIFICATION_ID, n,
            if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK else 0,
        )
    }

    private fun stopForegroundNow() = ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)

    override fun onDestroy() {
        Log.i(TAG, "service onDestroy")
        session.release()
        player.release()
        scope.cancel()
        super.onDestroy()
    }

    private inner class Callback : MediaSession.Callback {
        // Bluetooth Play (or Android's "resume music") with nothing queued: open the last
        // playlist and hand back its round so playback resumes where it left off.
        override fun onPlaybackResumption(
            s: MediaSession,
            controller: MediaSession.ControllerInfo,
        ): ListenableFuture<MediaSession.MediaItemsWithStartPosition> = scope.future {
            Log.i(TAG, "onPlaybackResumption items=${player.mediaItemCount} loading=$loading")
            if (player.mediaItemCount == 0) {
                if (loading == null) prefs().getString("playlist", null)?.let { startLoad(it, play = false) }
                loadJob?.join()
            }
            val items = (0 until player.mediaItemCount).map { player.getMediaItemAt(it) }
            MediaSession.MediaItemsWithStartPosition(items, 0, 0L)
        }

        override fun onConnect(s: MediaSession, controller: MediaSession.ControllerInfo): MediaSession.ConnectionResult {
            val cmds = MediaSession.ConnectionResult.DEFAULT_SESSION_COMMANDS.buildUpon()
                .add(SessionCommand(CMD_LOAD, Bundle.EMPTY))
                .add(SessionCommand(CMD_REMOVE, Bundle.EMPTY))
                .add(SessionCommand(CMD_STATUS, Bundle.EMPTY))
                .build()
            return MediaSession.ConnectionResult.AcceptedResultBuilder(s)
                .setAvailableSessionCommands(cmds)
                .build()
        }

        override fun onCustomCommand(
            s: MediaSession,
            controller: MediaSession.ControllerInfo,
            command: SessionCommand,
            args: Bundle,
        ): ListenableFuture<SessionResult> = scope.future {
            when (command.customAction) {
                CMD_LOAD -> {
                    val path = args.getString(ARG_PATH)
                    if (path == null) result(SessionResult.RESULT_ERROR_BAD_VALUE, "no playlist path")
                    else { startLoad(path, play = true); result(SessionResult.RESULT_SUCCESS, null) }
                }
                CMD_REMOVE -> removeCurrent()
                CMD_STATUS -> result(SessionResult.RESULT_SUCCESS, null)
                else -> SessionResult(SessionResult.RESULT_ERROR_NOT_SUPPORTED)
            }
        }
    }

    /** Status bundle travels with every result so the screen can refresh from any reply. */
    private fun result(code: Int, message: String?, extra: Bundle.() -> Unit = {}): SessionResult {
        val b = Bundle().apply {
            putString(K_PLAYLIST, playlist?.absolutePath)
            putInt(K_POS, (stack?.pos ?: 0) + 1)
            putInt(K_TOTAL, stack?.size ?: 0)
            putInt(K_MISSING, missing)
            loading?.let { putString(K_LOADING, it) }
            message?.let { putString(K_MESSAGE, it) }
            extra()
        }
        return SessionResult(code, b)
    }

    /** A newer choice cancels a load still in progress (taps must never queue up). */
    private fun startLoad(path: String, play: Boolean) {
        loadJob?.cancel()
        loading = path
        loadJob = scope.launch {
            try { load(File(path), play) }
            catch (e: kotlinx.coroutines.CancellationException) { Log.i(TAG, "load cancelled: $path"); throw e }
            catch (e: Throwable) { Log.e(TAG, "load failed: $path", e) }
            finally {
                if (loading == path) {
                    loading = null
                    // An auto-play that found nothing to play must not leave a stale notification.
                    if (autoPlayPending) { autoPlayPending = false; stopForegroundNow() }
                }
            }
        }
    }

    /** Open [file]: read it, restore (or start) its shuffle round, queue the rest. */
    private suspend fun load(file: File, play: Boolean) {
        Log.i(TAG, "load ${file.path} play=$play")
        val t0 = System.currentTimeMillis()
        val loaded = withContext(Dispatchers.IO) {
            if (!file.isFile) { Log.w(TAG, "load: not a readable file: ${file.path}"); return@withContext null }
            val idx = LibraryIndex.build(LibraryIndex.musicDirs(storageVolumes()))
            // Where each line was found last time: the first open of a big list checks every
            // line against the SD card (~45 s for sailing_2); later opens take a second.
            val cache = loadResolveCache(file)
            val l = M3u.entries(file) { pl, line -> ensureActive(); cache[line]?.let(::File) ?: idx.resolve(pl, line) }
            saveResolveCache(file, l)
            idx to l
        } ?: return
        val (idx, list) = loaded
        Log.i(TAG, "load: ${list.size} lines in ${System.currentTimeMillis() - t0} ms")
        index = idx
        playlist = file
        // Only songs that resolve to a file take part; a song listed twice (two path
        // styles) is one song. Unresolvable lines are counted, never "played".
        entries = list.filter { it.file != null }.associateBy { it.key }
        lineKeys = list.associate { it.line to it.key }
        missing = list.filter { it.file == null }.map { it.line }.distinct().size
        val exists = entries.keys
        prefs().edit().putString("playlist", file.absolutePath).apply()

        val keys = list.map { it.key }
        val saved = withContext(Dispatchers.IO) { ShuffleStack.load(stackFile(file)) }
        val s = saved?.also { it.reconcile(keys) } ?: ShuffleStack.fresh(keys)
        stack = if (s.remaining.isEmpty()) ShuffleStack.fresh(keys) else s
        saveStack()
        queueRemaining(exists, play)
    }

    private fun queueRemaining(playable: Set<String>?, play: Boolean) {
        val s = stack ?: return
        val items = s.remaining
            .filter { playable == null || it in playable }
            .mapNotNull { k -> entries[k]?.let { mediaItem(it) } }
        player.setMediaItems(items)
        player.prepare()
        player.playWhenReady = play || autoPlayPending
        autoPlayPending = false
    }

    private fun startNewRound(play: Boolean) {
        val s = stack ?: return
        val last = s.order.getOrNull(s.pos)
        stack = ShuffleStack.fresh(entries.keys, avoidFirst = last)
        saveStack()
        scope.launch {
            val playable = withContext(Dispatchers.IO) { entries.values.filter { it.file?.isFile == true }.map { it.key }.toHashSet() }
            queueRemaining(playable, play)
        }
    }

    private suspend fun removeCurrent(): SessionResult {
        loading?.let { return result(SessionResult.RESULT_ERROR_INVALID_STATE, "Still opening ${File(it).name} - try again in a moment") }
        val file = playlist ?: return result(SessionResult.RESULT_ERROR_INVALID_STATE, "no playlist loaded")
        val key = player.currentMediaItem?.mediaId
            ?: return result(SessionResult.RESULT_ERROR_INVALID_STATE, "nothing playing")
        val title = entries[key]?.songTitle ?: key
        // The song goes away the moment it's confirmed; the file edit follows.
        val idx = (0 until player.mediaItemCount).firstOrNull { player.getMediaItemAt(it).mediaId == key }
        if (idx != null) player.removeMediaItem(idx)
        if (player.mediaItemCount == 0) startNewRound(play = true)
        stack?.remove(key)
        saveStack()
        entries = entries - key

        val n = try {
            val resolve = index?.let { it::resolve } ?: M3u::resolveStrict
            val known = lineKeys
            editLock.withLock { withContext(Dispatchers.IO) { M3u.removeEntry(file, key, backupDir, resolve, known) } }
        } catch (e: Exception) {
            return result(SessionResult.RESULT_ERROR_IO, "Skipped, but could not edit ${file.name}: ${e.message}")
        }
        if (n == 0) return result(SessionResult.RESULT_ERROR_UNKNOWN, "Skipped, but \"$title\" was not found in ${file.name}")
        return result(SessionResult.RESULT_SUCCESS, "Removed \"$title\" from ${file.name}") {
            putInt(K_REMOVED, n)
        }
    }

    private fun mediaItem(e: Entry): MediaItem? =
        if (e.file == null) null else MediaItem.Builder()
            .setMediaId(e.key)
            .setUri(Uri.fromFile(e.file))
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(e.songTitle)
                    .setArtist(e.artist)
                    .setAlbumTitle(e.file.parentFile?.name)
                    .build()
            )
            .build()

    private fun saveStack() {
        val f = playlist ?: return
        val s = stack ?: return
        val snapshot = ShuffleStack(s.order.toMutableList(), s.pos)
        scope.launch(ioSerial) { snapshot.save(stackFile(f)) }
    }

    private fun cacheFile(playlist: File) = File(filesDir, "resolved/${pathHash(playlist)}.tsv")

    private fun loadResolveCache(playlist: File): Map<String, String> = runCatching {
        cacheFile(playlist).readLines().mapNotNull { l ->
            val tab = l.indexOf('\t'); if (tab > 0) l.substring(0, tab) to l.substring(tab + 1) else null
        }.toMap()
    }.getOrDefault(emptyMap())

    private fun saveResolveCache(playlist: File, list: List<Entry>) {
        val f = cacheFile(playlist)
        f.parentFile?.mkdirs()
        f.writeText(buildString {
            for (e in list) if (e.file != null && '\t' !in e.line) append(e.line).append('\t').append(e.file.path).append('\n')
        })
    }

    private fun pathHash(f: File): String =
        MessageDigest.getInstance("SHA-1").digest(f.absolutePath.toByteArray()).joinToString("") { "%02x".format(it) }

    private fun stackFile(playlist: File): File {
        val h = MessageDigest.getInstance("SHA-1").digest(playlist.absolutePath.toByteArray())
            .joinToString("") { "%02x".format(it) }
        return File(filesDir, "stacks/$h.txt")
    }

    /** Root of every mounted volume: /storage/emulated/0, /storage/<SD id>, ... */
    private fun storageVolumes(): List<File> =
        getExternalFilesDirs(null).filterNotNull().map { File(it.path.substringBefore("/Android/")) }

    private fun prefs() = getSharedPreferences("player", MODE_PRIVATE)
}
