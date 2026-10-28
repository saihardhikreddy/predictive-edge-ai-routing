package com.bitchat.android.mesh

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

/**
 * Delivery forecast: before a message is sent, predict how long until its delivery is confirmed
 * and how likely that is, and afterwards check the prediction against what really happened.
 *
 * Three situations, each predicted from what this phone has measured itself:
 *  - DIRECT: the destination is in range. Round trip ≈ 2 hops of measured hop time.
 *  - ROUTED: a fresh name announcement says the destination is h hops away through a neighbour
 *    in range. Round trip ≈ 2h hops; chance ≈ measured hop success ^ 2h.
 *  - CARRY: no path right now. For every friend the phone remembers how long they stayed out of
 *    reach before a path came back ("outages"). Treating the wait as memoryless, the expected wait
 *    is the mean outage, and the chance of a path within H is 1 − e^(−H / mean outage).
 *
 * Every confirmed delivery feeds back: the ratio of actual to predicted time updates a
 * per-situation correction factor, so the forecast calibrates itself to the phones in use.
 */
class Forecast {

    companion object {
        const val DIRECT = 0
        const val ROUTED = 1
        const val CARRY = 2
        const val NONE = 3
        /** The horizon the probability refers to when no path exists. */
        const val CARRY_HORIZON_MS = 10 * 60_000L
        /** The horizon for direct and routed messages. */
        const val PATH_HORIZON_MS = 30_000L
        val KIND_NAMES = arrayOf("direct", "routed", "carry", "none")
    }

    /** Measured time for one hop (frame written and acknowledged by the radio), ms. */
    var hopMs = 900.0
        private set
    /** Measured share of hop attempts that got through. */
    var hopOk = 0.9
        private set
    private var hopSamples = 0

    /** Learned correction: actual / predicted, per situation, averaged in log space. */
    private val logCal = DoubleArray(3)
    private val calN = IntArray(3)

    private class Outage {
        var downSince: Long? = null
        /** The path came back at this time; the outage only ends once it has stayed back for a while. */
        var upSince: Long? = null
        val recent = ArrayDeque<Double>()
        val meanMs get() = if (recent.isEmpty()) 0.0 else recent.average()
        val n get() = recent.size
        var lastHops = 2
    }

    /** A path must stay up this long to end an outage, and shorter outages are flicker, not absences. */
    private val settleMs = 3_000L
    private val minOutageMs = 5_000L
    private val outages = HashMap<String, Outage>()

    data class Prediction(
        val kind: Int,
        /** Expected time until the delivery is confirmed, ms; -1 = unknown. */
        val etaMs: Long,
        /** Chance it is confirmed within [horizonMs]; -1 = unknown. */
        val p: Double,
        val horizonMs: Long,
        val hops: Int,
        /** CARRY only: the learned mean outage for this destination, ms. */
        val meanOutageMs: Long = 0,
    )

    // ---------------------------------------------------------- learning

    fun onHop(ms: Long, ok: Boolean) {
        hopSamples++
        val a = if (hopSamples < 10) 1.0 / hopSamples else 0.1
        hopOk = (1 - a) * hopOk + a * (if (ok) 1.0 else 0.0)
        if (ok) hopMs = (1 - a) * hopMs + a * ms.toDouble()
    }

    /** Called every tick for every known phone: is there a usable path to it right now? */
    fun observe(id: String, reachable: Boolean, hops: Int, t: Long) {
        val o = outages.getOrPut(id) { Outage() }
        if (reachable) {
            o.lastHops = max(1, hops)
            val down = o.downSince ?: return
            val up = o.upSince ?: t.also { o.upSince = it }
            if (t - up < settleMs) return
            val d = (up - down).toDouble()
            if (d >= minOutageMs) {
                o.recent.addLast(d)
                while (o.recent.size > 8) o.recent.removeFirst()
            }
            o.downSince = null
            o.upSince = null
        } else {
            o.upSince = null // a brief return does not end the outage
            if (o.downSince == null) o.downSince = t
        }
    }

    private fun cal(kind: Int) = exp(logCal[kind])

    data class Outcome(val kind: Int, val predictedMs: Long, val actualMs: Long) {
        /** "Good" = within ±50 % of the prediction, or within 1 s for very short trips. */
        val good get() = abs(actualMs - predictedMs) <= max(1_000L, predictedMs / 2)
    }

    val outcomes = ArrayList<Outcome>()

    fun onResult(kind: Int, predictedMs: Long, actualMs: Long) {
        if (kind !in 0..2 || predictedMs <= 0 || actualMs <= 0) return
        outcomes.add(Outcome(kind, predictedMs, actualMs))
        if (outcomes.size > 500) outcomes.removeAt(0)
        // the prediction already included the correction; update it with the remaining error
        val r = ln((actualMs.toDouble() / predictedMs).coerceIn(0.2, 5.0))
        calN[kind]++
        val a = if (calN[kind] < 5) 1.0 / (calN[kind] + 1) else 0.2
        logCal[kind] += a * r
        logCal[kind] = logCal[kind].coerceIn(ln(0.2), ln(8.0))
    }

    // ---------------------------------------------------------- predicting

    private fun rtt(hops: Int, kind: Int) = (2 * hops * hopMs * cal(kind)).toLong()

    fun predict(id: String, directLinkP: Double?, routeHops: Int?, t: Long): Prediction {
        if (directLinkP != null) {
            val p = min(0.99, 1 - (1 - hopOk * directLinkP).pow(3)) // up to 3 tries in 30 s
            return Prediction(DIRECT, rtt(1, DIRECT), p, PATH_HORIZON_MS, 1)
        }
        if (routeHops != null && routeHops >= 1) {
            val p = min(0.99, hopOk.pow(2 * routeHops) + 0.05)
            return Prediction(ROUTED, rtt(routeHops, ROUTED), p, PATH_HORIZON_MS, routeHops)
        }
        val o = outages[id]
        if (o == null || o.n == 0) return Prediction(NONE, -1, -1.0, CARRY_HORIZON_MS, 0)
        // memoryless: the expected wait for the next path does not shrink with time already waited
        val wait = o.meanMs * cal(CARRY)
        val eta = (wait + rtt(o.lastHops, ROUTED)).toLong()
        val p = 1 - exp(-CARRY_HORIZON_MS / max(1.0, wait))
        return Prediction(CARRY, eta, p, CARRY_HORIZON_MS, o.lastHops, o.meanMs.toLong())
    }

    // ---------------------------------------------------------- reporting

    data class Accuracy(val n: Int, val good: Int, val medianErrPct: Int)

    fun accuracy(): Accuracy {
        if (outcomes.isEmpty()) return Accuracy(0, 0, 0)
        val errs = outcomes.map { abs(it.actualMs - it.predictedMs) * 100.0 / it.predictedMs }.sorted()
        return Accuracy(outcomes.size, outcomes.count { it.good }, errs[errs.size / 2].toInt())
    }
}
