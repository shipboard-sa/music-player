/*
 * Purpose: Start the music when the Fusion stereo connects over Bluetooth (replaces
 *   Pulsar's auto-play-on-connect). Only the Fusion triggers it - headphones, speakers
 *   and the boat's other Bluetooth devices don't.
 * Version: v1 (2026-10-11)
 * Scope: PRODUCTION - Music Player app on the music phone.
 * Architecture: manifest-registered receiver for the A2DP connection-state broadcast.
 *   On "connected" from an address in AUTO_PLAY_DEVICES it starts PlaybackService with
 *   ACTION_AUTOPLAY; the service plays the next song of the last playlist's round.
 *   Android 12+ lets an app start a foreground service from a Bluetooth broadcast that
 *   needs BLUETOOTH_CONNECT (granted on first launch via MainActivity).
 * Invocation: declared in AndroidManifest.xml; Android delivers the broadcast.
 */
package us.unladenswallow.musicplayer

import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothProfile
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.content.ContextCompat

class BluetoothAutoPlay : BroadcastReceiver() {

    companion object {
        const val A2DP_STATE_CHANGED = "android.bluetooth.a2dp.profile.action.CONNECTION_STATE_CHANGED"

        /**
         * Bluetooth addresses that start the music on connect. The Fusion stereo pairs as
         * "MS-RA70" (alias "Fusion stereo" on the phone), read from the phone's paired
         * devices 2026-10-11. A replacement stereo has a new address - update it here.
         */
        val AUTO_PLAY_DEVICES = setOf("XX:XX:XX:XX:XX:XX")
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != A2DP_STATE_CHANGED) return
        if (intent.getIntExtra(BluetoothProfile.EXTRA_STATE, -1) != BluetoothProfile.STATE_CONNECTED) return
        val device: BluetoothDevice? =
            if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
            else @Suppress("DEPRECATION") intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
        val address = device?.address?.uppercase() ?: return
        android.util.Log.i("MusicPlayer", "A2DP connected: $address autoplay=${address in AUTO_PLAY_DEVICES}")
        if (address !in AUTO_PLAY_DEVICES) return

        ContextCompat.startForegroundService(
            context,
            Intent(context, PlaybackService::class.java).setAction(PlaybackService.ACTION_AUTOPLAY),
        )
    }
}
