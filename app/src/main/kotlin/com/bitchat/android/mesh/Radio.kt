package com.bitchat.android.mesh

import android.os.Handler

/**
 * What the mesh engine needs from a radio. [BleTransport] is the real Bluetooth LE one;
 * tests plug in a virtual radio so several engines can form a mesh inside one process.
 *
 * Peers are opaque handles (a BluetoothDevice for BLE); the engine only passes them back to [send].
 */
interface Radio {
    val isEnabled: Boolean
    val queueSize: Int
    fun start(advert: ByteArray)
    fun stop()
    fun startAdvertising(advert: ByteArray)
    fun send(peer: Any, bytes: ByteArray, cb: (Boolean) -> Unit)
}

/** Builds a radio bound to the engine's thread and callbacks. */
typealias RadioFactory = (
    handler: Handler,
    onAdvert: (Protocol.Advert, Any, Int) -> Unit,
    onFrame: (ByteArray) -> Unit,
    onError: (String) -> Unit,
) -> Radio
