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

    /** True when this phone can use Bluetooth 5 Long Range (LE Coded PHY). */
    val longRangeSupported: Boolean get() = false

    /** Turn Long Range advertising and scanning on or off (no-op without support). */
    fun setLongRange(on: Boolean) {}

    /** Send over Long Range when [longRange] is true and supported; otherwise the normal 1M PHY. */
    fun send(peer: Any, bytes: ByteArray, longRange: Boolean, cb: (Boolean) -> Unit) = send(peer, bytes, cb)
}

/** Builds a radio bound to the engine's thread and callbacks. */
typealias RadioFactory = (
    handler: Handler,
    onAdvert: (Protocol.Advert, Any, Int) -> Unit,
    onFrame: (ByteArray) -> Unit,
    onError: (String) -> Unit,
) -> Radio
