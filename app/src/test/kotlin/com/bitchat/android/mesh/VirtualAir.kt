package com.bitchat.android.mesh

import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import kotlin.math.hypot
import kotlin.math.log10
import kotlin.math.max

/**
 * A simulated Bluetooth medium for several [MeshEngine]s in one test process.
 *
 * Phones sit at (x, y) in metres. Signal follows a log-distance model calibrated so that
 * 1 m ≈ -40 dBm, a few metres ≈ -60 dBm and the 12 m range edge ≈ -90 dBm. Every phone
 * advertises once per second to everyone in range (unless its adverts are paused, to mimic
 * the gaps real phones show), and a frame sent to a phone in range arrives after a GATT-like
 * 300 ms delay. Everything runs on the main looper, so Robolectric's virtual clock drives it.
 */
class VirtualAir(var rangeM: Double = 12.0, var codedRangeM: Double = 24.0) {
    val handler = Handler(Looper.getMainLooper())
    private val radios = mutableListOf<VirtualRadio>()

    inner class VirtualRadio(
        val label: String,
        private val engineHandler: Handler,
        private val onAdvert: (Protocol.Advert, Any, Int) -> Unit,
        private val onFrame: (ByteArray) -> Unit,
    ) : Radio {
        var x = 0.0
        var y = 0.0
        var running = false
        var advert: ByteArray = ByteArray(0)
        /** Adverts are silent until this virtual time (ms), like a phone pausing its advertiser. */
        var advertGapUntil = 0L
        var framesSent = 0
        /** Supports Bluetooth 5 Long Range (LE Coded PHY): about 2x the range, slower frames. */
        var coded = false
        var longRangeOn = true
        var codedFramesSent = 0
        val longRange get() = coded && longRangeOn
        override val longRangeSupported get() = coded
        override fun setLongRange(on: Boolean) { longRangeOn = on }

        override val isEnabled = true
        override var queueSize = 0
        override fun start(advert: ByteArray) { this.advert = advert; running = true }
        override fun stop() { running = false }
        override fun startAdvertising(advert: ByteArray) { this.advert = advert }

        override fun send(peer: Any, bytes: ByteArray, cb: (Boolean) -> Unit) = send(peer, bytes, false, cb)

        override fun send(peer: Any, bytes: ByteArray, longRange: Boolean, cb: (Boolean) -> Unit) {
            val to = peer as VirtualRadio
            val lr = longRange && this.longRange && to.longRange
            framesSent++
            if (lr) codedFramesSent++
            queueSize++
            handler.postDelayed({
                queueSize--
                val ok = running && to.running && (if (lr) inCodedRange(this, to) else inRange(this, to))
                if (ok) to.engineHandler.post { to.onFrame(bytes.copyOf()) }
                engineHandler.post { cb(ok) }
            }, if (lr) 900L else 300L) // 125 kbit/s Coded PHY: slower frames
        }

        fun deliverAdvertFrom(from: VirtualRadio, longRange: Boolean = false) {
            val adv = Protocol.parseAdvert(from.advert)?.copy(longRange = longRange) ?: return
            engineHandler.post { onAdvert(adv, from, rssi(from, this)) }
        }
    }

    fun factory(label: String): RadioFactory = { h, onAdvert, onFrame, _ ->
        VirtualRadio(label, h, onAdvert, onFrame).also { radios += it }
    }

    fun radio(label: String) = radios.first { it.label == label }

    fun distance(a: VirtualRadio, b: VirtualRadio) = hypot(a.x - b.x, a.y - b.y)
    fun inRange(a: VirtualRadio, b: VirtualRadio) = distance(a, b) <= rangeM
    fun inCodedRange(a: VirtualRadio, b: VirtualRadio) = a.longRange && b.longRange && distance(a, b) <= codedRangeM
    fun rssi(a: VirtualRadio, b: VirtualRadio): Int = (-40 - 46 * log10(max(distance(a, b), 1.0))).toInt()

    private val beacon = object : Runnable {
        override fun run() {
            val now = SystemClock.uptimeMillis()
            for (s in radios) {
                if (!s.running || now < s.advertGapUntil) continue
                for (r in radios) {
                    if (r === s || !r.running) continue
                    if (inRange(s, r)) r.deliverAdvertFrom(s)
                    if (inCodedRange(s, r)) r.deliverAdvertFrom(s, longRange = true) // the extended Coded PHY advert
                }
            }
            handler.postDelayed(this, 1000)
        }
    }

    fun startBeacons() = handler.post(beacon)
}
