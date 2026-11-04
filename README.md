<!--
Purpose: Start-here doc for the Music Player Android app - what it does, build, install, gotchas.
Version: v2 (2026-10-11)
Scope: PRODUCTION - Music Player app on the music phone (the Pulsar phone -> Fusion stereo).
Architecture: repo root doc; code in app/src/main/java/us/unladenswallow/musicplayer/.
Invocation: n/a (reference doc)
-->
# Music Player

A shuffle player for the boat's music phone (the recycled Samsung that runs Pulsar
and streams to the Fusion stereo over Bluetooth).

1. **Choose a playlist.** It plays the phone's existing `.m3u` / `.m3u8` files. The app
   finds them on internal storage and SD cards and skips `Android/`.
2. **True shuffle, no repeats.** Each playlist gets a Fisher-Yates shuffle (SecureRandom)
   that the app saves: the "stack". It plays song 1..n of that order. A song only
   comes back after the whole list has played; then a new round is shuffled. The
   round survives restarts and reboots, and each playlist has its own.
3. **Remove the playing song** from the playlist, with a confirm. This edits the
   playlist file in place (encoding, BOM, line endings and `#EXTINF` lines are kept).
   **The MP3 is never touched.**

Bluetooth and notification Play/Pause/Next work. Next pops the stack.

**Auto-play on the Fusion.** When the Fusion stereo connects over Bluetooth (pairs as
`YOUR_STEREO`, address `XX:XX:XX:XX:XX:XX`), the app starts playing the last playlist's
round. No other Bluetooth device triggers it. A replacement stereo needs its address
added in `BluetoothAutoPlay.kt`. This replaced Pulsar's own auto-play, so retire Pulsar
or turn its auto-play off, or the two will fight over the speaker.

## Files

| File | Role |
|---|---|
| `M3u.kt` | read / resolve / edit playlists (pure JVM, unit-tested) |
| `ShuffleStack.kt` | shuffle order + position, save/load, reconcile with an edited list |
| `PlaybackService.kt` | Media3 ExoPlayer + MediaSession; owns stack + edits |
| `MainActivity.kt` | Compose screen; talks to the service via MediaController |
| `LibraryIndex.kt` | finds the MP3 for a line in any path style (per-folder, cached) |
| `BluetoothAutoPlay.kt` | Fusion connects -> service ACTION_AUTOPLAY |

Where data lives on the phone:
- Each round's stack is in app-private storage (`files/stacks/`).
- The first time a playlist is edited, a copy of it is kept, and every removal is
  logged. Both are in `Internal storage/Documents/MusicPlayer/`
  (`<name>.original`, `removed.log`). Put a song back by copying its lines from the log.

If the playlist changes outside the app (Pulsar, PC copy), the next load reconciles:
songs that are gone drop out, and new songs are slotted at random into the unplayed
part of the current round.

## Build (Windows laptop)

Toolchain installed 2026-10-11: Microsoft OpenJDK 17 (`JAVA_HOME`) and the Android
SDK at `%LOCALAPPDATA%\Android\Sdk` (`ANDROID_HOME`; platform 35, build-tools 35,
platform-tools/adb). `local.properties` (git-ignored) points at the SDK.

```
gradlew.bat testDebugUnitTest assembleDebug
```
APK: `app/build/outputs/apk/debug/app-debug.apk`. It is signed with this laptop's
debug key (`%USERPROFILE%\.android\debug.keystore`). An update must be signed with the
same key, or the old app has to be uninstalled first.

## Install on the phone

- **USB:** turn on Developer options and USB debugging on the phone, plug it in, then
  run `gradlew.bat installDebug` (or `adb install -r app-debug.apk`).
- **Or by hand:** copy the APK to the phone and open it (allow "install unknown apps").

First launch: tap **Grant file access** and turn on "Allow access to manage all
files". The app needs it to read MP3s on the SD card and rewrite playlists.

## Gotchas

- Paths in a playlist are resolved relative to the playlist's own folder. The phone
  copies use `../../../4A21-0000/Music/Music/...`, which is the SD card.
- Some exporters put quotes around a path that contains a comma (14 of these in
  CCMb.m3u). They are handled.
- The PC copy `CCM.m3u8` uses `F:\Music\...` paths. Those don't exist on the phone,
  so they show as "missing files skipped".
- Pulsar keeps its own playlist database. Whether it re-reads an edited `.m3u` is
  Pulsar's behaviour and has not been checked.
