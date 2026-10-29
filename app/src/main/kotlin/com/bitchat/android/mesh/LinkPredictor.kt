package com.bitchat.android.mesh

import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

/**
 * Link-survival prediction on the phone, the same model as simulation/link_predictor.py:
 * will this neighbour still be heard at every second of the next [horizonMs]?
 *
 * Features from the RSSI of the neighbour's adverts, sampled once per second:
 *   [1, (smoothed RSSI + 70) / 10, least-squares RSSI slope over 5 samples (dB/s) / 2, min(link age, 30 s) / 30]
 * Logistic regression trained online by SGD, test-then-train: each prediction is scored when its
 * label resolves and only then used to update the weights, so no prediction sees its own future.
 * The phone logs every scored prediction, so a field test measures the predictor on real radios.
 */
class LinkPredictor(private val horizonMs: Long = 3_000, private val warmupMs: Long = 60_000) {

    private class Link {
        val hist = ArrayDeque<Pair<Long, Double>>()
        var since = 0L
        var present = false
        val losses = ArrayDeque<Long>()
    }

    private class Pending(val peer: String, val t0: Long, val x: DoubleArray, val p: Double)

    var w = doubleArrayOf(2.0, 0.5, 0.0, 0.0)
        private set
    private val links = HashMap<String, Link>()
    private val pending = ArrayList<Pending>()
    private var started = -1L

    /** Scored predictions (after warm-up): p and outcome (1 = survived). */
    val scored = ArrayList<Pair<Double, Int>>()

    private fun sigmoid(z: Double) = if (z >= 0) 1.0 / (1.0 + exp(-z)) else exp(z).let { it / (1.0 + it) }

    private fun slope(h: ArrayDeque<Pair<Long, Double>>): Double {
        if (h.size < 2) return 0.0
        val ts = h.map { it.first / 1000.0 }
        val rs = h.map { it.second }
        val mt = ts.average()
        val mr = rs.average()
        val den = ts.sumOf { (it - mt) * (it - mt) }
        return if (den < 1e-9) 0.0 else ts.indices.sumOf { (ts[it] - mt) * (rs[it] - mr) } / den
    }

    fun features(peer: String, t: Long): DoubleArray? {
        val ln = links[peer] ?: return null
        if (!ln.present || ln.hist.isEmpty()) return null
        val rs = ln.hist.map { it.second }
        val rssi = 0.6 * rs.last() + 0.4 * rs.average()
        val s = max(-10.0, min(10.0, slope(ln.hist)))
        val age = min((t - ln.since) / 1000.0, 30.0)
        return doubleArrayOf(1.0, (rssi + 70.0) / 10.0, s / 2.0, age / 30.0)
    }

    private fun p(x: DoubleArray) = sigmoid(w.indices.sumOf { w[it] * x[it] })

    /** Chance the link to [peer] lasts the next [horizonMs]; 1.0 with no history yet. */
    fun predict(peer: String, t: Long): Double = features(peer, t)?.let { p(it) } ?: 1.0

    /** RSSI slope in dB/s: negative = getting weaker (walking away). */
    fun trend(peer: String): Double = links[peer]?.let { slope(it.hist) } ?: 0.0

    /** Once per second: who is in range right now, with their RSSI. Returns predictions scored this call. */
    fun observe(t: Long, heard: Map<String, Double>): List<Pair<Double, Int>> {
        if (started < 0) started = t
        for ((peer, rssi) in heard) {
            val ln = links.getOrPut(peer) { Link() }
            if (!ln.present) { ln.present = true; ln.since = t; ln.hist.clear() }
            ln.hist.addLast(t to rssi)
            while (ln.hist.size > 5) ln.hist.removeFirst()
        }
        for ((peer, ln) in links) if (ln.present && peer !in heard) {
            ln.present = false
            ln.losses.addLast(t)
            while (ln.losses.size > 16) ln.losses.removeFirst()
        }
        val done = ArrayList<Pair<Double, Int>>()
        val iter = pending.iterator()
        while (iter.hasNext()) {
            val pd = iter.next()
            val ln = links[pd.peer] ?: continue
            val broke = ln.losses.any { it > pd.t0 && it <= pd.t0 + horizonMs }
            if (!broke && t < pd.t0 + horizonMs) continue
            iter.remove()
            val y = if (broke) 0 else 1
            if (pd.t0 - started >= warmupMs) { scored.add(pd.p to y); done.add(pd.p to y) }
            val err = p(pd.x) - y
            w = DoubleArray(w.size) { i -> w[i] - 0.05 * (err * pd.x[i] + 1e-4 * w[i]) }
        }
        for (peer in heard.keys) {
            val x = features(peer, t) ?: continue
            if ((links[peer]?.hist?.size ?: 0) >= 2) pending.add(Pending(peer, t, x, p(x)))
        }
        if (scored.size > 5000) scored.subList(0, scored.size - 5000).clear()
        return done
    }

    data class Score(val n: Int, val breaks: Int, val brier: Double, val caught: Int)

    /** Brier score, and how many real breaks were flagged (p < 0.5) in advance. */
    fun score(): Score {
        if (scored.isEmpty()) return Score(0, 0, 0.0, 0)
        val brier = scored.sumOf { (p, y) -> (p - y) * (p - y) } / scored.size
        val breaks = scored.count { it.second == 0 }
        return Score(scored.size, breaks, brier, scored.count { it.second == 0 && it.first < 0.5 })
    }
}
