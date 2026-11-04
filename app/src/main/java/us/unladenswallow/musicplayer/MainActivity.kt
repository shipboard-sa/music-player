/*
 * Purpose: The app's one screen - grant file access, pick a playlist, see/drive what's
 *   playing, and remove the playing song from the playlist (with a confirm).
 * Version: v3 (2026-10-11)
 * Scope: PRODUCTION - Music Player app on the music phone.
 * Architecture: Jetpack Compose UI. Finds .m3u/.m3u8 files on internal storage and SD
 *   cards, then drives PlaybackService through a Media3 MediaController (standard
 *   play/pause/next + custom LOAD / REMOVE / STATUS commands). Holds no playback state.
 * Invocation: launcher icon "Music Player"; declared in AndroidManifest.xml.
 */
package us.unladenswallow.musicplayer

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import androidx.media3.session.SessionToken
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.guava.await
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class MainActivity : ComponentActivity() {

    private data class PlaylistInfo(val file: File, val songs: Int)

    private var controller: MediaController? = null

    private var hasAccess by mutableStateOf(false)
    private var playlists by mutableStateOf<List<PlaylistInfo>?>(null)  // null = still scanning
    private var current by mutableStateOf<String?>(null)
    private var nowTitle by mutableStateOf<String?>(null)
    private var nowArtist by mutableStateOf<String?>(null)
    private var isPlaying by mutableStateOf(false)
    private var pos by mutableStateOf(0)
    private var total by mutableStateOf(0)
    private var missing by mutableStateOf(0)
    private var confirmRemove by mutableStateOf(false)
    private var loadingPath by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // Notifications (player controls) and Bluetooth (auto-play when the Fusion connects).
        val wanted = buildList {
            if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
            if (Build.VERSION.SDK_INT >= 31) add(Manifest.permission.BLUETOOTH_CONNECT)
        }.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
        if (wanted.isNotEmpty()) requestPermissions(wanted.toTypedArray(), 2)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface(Modifier.fillMaxSize()) { Screen() }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        val token = SessionToken(this, ComponentName(this, PlaybackService::class.java))
        lifecycleScope.launch {
            val c = MediaController.Builder(this@MainActivity, token).buildAsync().await()
            controller = c
            c.addListener(object : Player.Listener {
                override fun onEvents(player: Player, events: Player.Events) = refresh()
            })
            refresh()
        }
    }

    override fun onResume() {
        super.onResume()
        val had = hasAccess
        hasAccess = checkAccess()
        if (hasAccess && (!had || playlists == null)) scan()
    }

    override fun onStop() {
        controller?.release()
        controller = null
        super.onStop()
    }

    private fun checkAccess(): Boolean =
        if (Build.VERSION.SDK_INT >= 30) Environment.isExternalStorageManager()
        else ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED

    private fun askAccess() {
        if (Build.VERSION.SDK_INT >= 30) {
            val i = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName"))
            runCatching { startActivity(i) }
                .onFailure { startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)) }
        } else {
            requestPermissions(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE), 1)
        }
    }

    @Deprecated("Activity Result API not needed for one legacy (API < 30) prompt")
    @Suppress("DEPRECATION")
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1) { hasAccess = checkAccess(); if (hasAccess) scan() }
    }

    /** Find playlists on internal storage and every SD card (skipping Android/ app data). */
    private fun scan() {
        playlists = null
        lifecycleScope.launch {
            playlists = withContext(Dispatchers.IO) {
                // Apps can't list /storage itself; each volume's root comes from its app-files dir.
                val roots = getExternalFilesDirs(null).filterNotNull()
                    .map { File(it.path.substringBefore("/Android/")) }.distinctBy { it.path }
                val found = ArrayList<File>()
                for (r in roots) walk(r, 0, found)
                found.distinctBy { it.absolutePath }
                    .map { PlaylistInfo(it, runCatching { M3u.entries(it).size }.getOrDefault(0)) }
                    .sortedBy { it.file.name.lowercase() }
            }
        }
    }

    private fun walk(dir: File, depth: Int, out: MutableList<File>) {
        if (depth > 2) return  // playlists live near the top (Music/*.m3u); don't crawl 31K songs
        val kids = dir.listFiles() ?: return
        for (k in kids) {
            if (k.isDirectory) {
                // Inside a Music folder only "*playlist*" subfolders are searched - the rest
                // are thousands of artist folders (a minute+ to list over the SD card).
                val inMusic = dir.name.equals("music", ignoreCase = true)
                if (!k.name.startsWith(".") && !(depth == 0 && k.name == "Android") &&
                    (!inMusic || k.name.contains("playlist", ignoreCase = true))
                ) walk(k, depth + 1, out)
            } else if (M3u.isPlaylist(k)) out.add(k)
        }
    }

    private fun refresh() {
        val c = controller ?: return
        val md = c.mediaMetadata
        nowTitle = md.title?.toString()
        nowArtist = md.artist?.toString()
        isPlaying = c.isPlaying
        command(PlaybackService.CMD_STATUS)
    }

    private fun command(action: String, args: Bundle = Bundle.EMPTY, toastResult: Boolean = false) {
        val c = controller ?: return
        lifecycleScope.launch {
            val r = c.sendCustomCommand(SessionCommand(action, Bundle.EMPTY), args).await()
            val x = r.extras
            current = x.getString(PlaybackService.K_PLAYLIST)
            pos = x.getInt(PlaybackService.K_POS)
            total = x.getInt(PlaybackService.K_TOTAL)
            missing = x.getInt(PlaybackService.K_MISSING)
            loadingPath = x.getString(PlaybackService.K_LOADING)
            val msg = x.getString(PlaybackService.K_MESSAGE)
            if (msg != null && (toastResult || r.resultCode != SessionResult.RESULT_SUCCESS)) {
                Toast.makeText(this@MainActivity, msg, Toast.LENGTH_LONG).show()
            }
        }
    }

    @Composable
    private fun Screen() {
        // While the service is opening a playlist, poll its status so the card updates.
        LaunchedEffect(loadingPath) {
            while (loadingPath != null) { delay(1000); command(PlaybackService.CMD_STATUS) }
        }
        Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp)) {
            if (!hasAccess) {
                Text("Music Player needs access to all files to play your MP3s and edit playlists.")
                Spacer(Modifier.height(12.dp))
                Button(onClick = ::askAccess) { Text("Grant file access") }
                return@Column
            }
            NowPlaying()
            Spacer(Modifier.height(16.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Playlists", fontWeight = FontWeight.Bold, fontSize = 18.sp)
                TextButton(onClick = ::scan) { Text("Rescan") }
            }
            val list = playlists
            when {
                list == null -> Text("Looking for playlists…")
                list.isEmpty() -> Text("No .m3u / .m3u8 playlists found on this phone.")
                else -> LazyColumn {
                    items(list, key = { it.file.absolutePath }) { p ->
                        val selected = p.file.absolutePath == current
                        Column(
                            Modifier.fillMaxWidth()
                                .clickable {
                                    loadingPath = p.file.absolutePath
                                    command(PlaybackService.CMD_LOAD, Bundle().apply { putString(PlaybackService.ARG_PATH, p.file.absolutePath) })
                                }
                                .padding(vertical = 10.dp)
                        ) {
                            Text(
                                (if (selected) "▶ " else "") + p.file.nameWithoutExtension,
                                fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                                fontSize = 17.sp,
                            )
                            Text("${p.songs} songs · ${p.file.parent}", fontSize = 12.sp,
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        HorizontalDivider()
                    }
                }
            }
        }

        if (confirmRemove) {
            AlertDialog(
                onDismissRequest = { confirmRemove = false },
                title = { Text("Remove from playlist?") },
                text = {
                    Text("\"${nowTitle ?: "this song"}\" will be taken out of ${current?.let { File(it).name } ?: "the playlist"}. " +
                        "The MP3 stays on the card.")
                },
                confirmButton = {
                    TextButton(onClick = {
                        confirmRemove = false
                        command(PlaybackService.CMD_REMOVE, toastResult = true)
                    }) { Text("Remove") }
                },
                dismissButton = { TextButton(onClick = { confirmRemove = false }) { Text("Cancel") } },
            )
        }
    }

    @Composable
    private fun NowPlaying() {
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                val opening = loadingPath
                if (opening != null) {
                    Text("Opening ${File(opening).nameWithoutExtension}…", fontSize = 13.sp, fontWeight = FontWeight.Bold)
                } else {
                    Text(current?.let { File(it).nameWithoutExtension } ?: "No playlist chosen", fontSize = 13.sp)
                }
                Spacer(Modifier.height(6.dp))
                Text(nowTitle ?: "—", fontSize = 22.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(nowArtist ?: "", fontSize = 16.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (total > 0) {
                    Spacer(Modifier.height(6.dp))
                    Text("Song $pos of $total this round" + if (missing > 0) " · $missing playlist lines match no file" else "", fontSize = 12.sp)
                }
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { controller?.let { if (it.isPlaying) it.pause() else it.play() } }) {
                        Text(if (isPlaying) "Pause" else "Play")
                    }
                    OutlinedButton(onClick = { controller?.seekToNextMediaItem() }) { Text("Next") }
                    Button(
                        onClick = { confirmRemove = true },
                        enabled = nowTitle != null && current != null && loadingPath == null,
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                    ) { Text("Remove") }
                }
            }
        }
    }
}
