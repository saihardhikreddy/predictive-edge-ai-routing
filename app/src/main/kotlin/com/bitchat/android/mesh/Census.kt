package com.bitchat.android.mesh

import java.util.Base64
import kotlin.math.ln
import kotlin.math.roundToInt

/**
 * Survivor census: every phone estimates how many phones are in the whole mesh, how many SOS
 * calls were raised and how many of those reached someone, with no server and no list of ids.
 *
 * Each count is a fixed 256-bit sketch (32 bytes). A phone sets one bit for every id it counts,
 * chosen by hashing the id; two sketches merge with a bitwise OR whenever phones talk. The count
 * comes back from the share of bits still zero (linear counting): n ≈ -m · ln(zeros / m).
 * Because merging is an OR, hearing the same phone through ten different relays, or meeting it
 * again, never counts it twice, and a sketch stays 32 bytes whether the mesh has 3 phones or 200.
 *
 * Counts are kept per 10-minute window (keyed by wall-clock window number) and the last two
 * windows are reported, so a phone that leaves the mesh drops out of the count within 20 minutes.
 * Every phone re-adds itself, its own open SOS calls, and the SOS calls it received, each window.
 */
class Census(private val windowMs: Long = WINDOW_MS) {

    companion object {
        const val BITS = 256
        const val WINDOW_MS = 10 * 60_000L
        const val PEOPLE = 0
        const val SOS = 1
        const val ANSWERED = 2
        private const val KINDS = 3

        /** 64-bit FNV-1a, then a murmur finaliser: well spread, the same on every phone. */
        fun hash(s: String): Long {
            var h = -0x340d631b7bdddcdbL
            for (b in s.toByteArray(Charsets.UTF_8)) {
                h = h xor (b.toLong() and 0xFF)
                h *= 0x100000001b3L
            }
            h = h xor (h ushr 33); h *= -0xae502812aa7333L
            h = h xor (h ushr 33); h *= -0x3b314601e57a13adL
            h = h xor (h ushr 33)
            return h
        }

        fun bitOf(kind: Int, id: String): Int = Math.floorMod(hash("$kind:$id"), BITS.toLong()).toInt()

        /** Linear-counting estimate from the number of zero bits. */
        fun estimate(bits: LongArray): Double {
            val ones = bits.sumOf { java.lang.Long.bitCount(it) }
            val zeros = BITS - ones
            if (zeros == 0) return BITS * ln(BITS.toDouble()) // saturated: a lower bound (≈1400)
            return -BITS * ln(zeros.toDouble() / BITS)
        }
    }

    /** window number -> [kind][4 longs] */
    private val windows = HashMap<Long, Array<LongArray>>()

    /** Bumps whenever a merge or add changed something, so neighbours are only re-sent news. */
    var version = 0
        private set

    fun window(t: Long) = Math.floorDiv(t, windowMs)

    private fun sketches(w: Long) = windows.getOrPut(w) { Array(KINDS) { LongArray(BITS / 64) } }

    private fun prune(t: Long) {
        val cur = window(t)
        windows.keys.removeAll { it < cur - 1 || it > cur + 1 }
    }

    fun add(kind: Int, id: String, t: Long) {
        prune(t)
        val s = sketches(window(t))[kind]
        val b = bitOf(kind, id)
        val word = b / 64
        val mask = 1L shl (b % 64)
        if (s[word] and mask == 0L) { s[word] = s[word] or mask; version++ }
    }

    /** OR another phone's sketches into ours, window by window. Returns true if we learned something. */
    fun merge(other: Map<Long, Array<LongArray>>, t: Long): Boolean {
        prune(t)
        val cur = window(t)
        var changed = false
        for ((w, kinds) in other) {
            if (w < cur - 1 || w > cur + 1 || kinds.size != KINDS) continue
            val mine = sketches(w)
            for (k in 0 until KINDS) for (i in 0 until BITS / 64) {
                val v = mine[k][i] or kinds[k][i]
                if (v != mine[k][i]) { mine[k][i] = v; changed = true }
            }
        }
        if (changed) version++
        return changed
    }

    /** Union of the current and previous window for one kind. */
    private fun recent(kind: Int, t: Long): LongArray {
        val cur = window(t)
        val out = LongArray(BITS / 64)
        for (w in listOf(cur - 1, cur)) windows[w]?.let { s -> for (i in out.indices) out[i] = out[i] or s[kind][i] }
        return out
    }

    data class Counts(val phones: Int, val sos: Int, val answered: Int, val saturated: Boolean) {
        val unanswered get() = (sos - answered).coerceAtLeast(0)
    }

    fun counts(t: Long): Counts {
        val people = recent(PEOPLE, t)
        val p = estimate(people)
        val s = estimate(recent(SOS, t))
        val a = estimate(recent(ANSWERED, t)).coerceAtMost(s)
        val sat = people.all { it == -1L }
        return Counts(p.roundToInt(), s.roundToInt(), a.roundToInt(), sat)
    }

    // ------------------------------------------------------------- wire form

    /** {"w": window, "b": base64 of 3 × 32 bytes} for each of the last two windows. */
    fun encode(t: Long): org.json.JSONArray {
        prune(t)
        val cur = window(t)
        val arr = org.json.JSONArray()
        for (w in listOf(cur - 1, cur)) {
            val s = windows[w] ?: continue
            val bytes = java.nio.ByteBuffer.allocate(KINDS * BITS / 8)
            s.forEach { k -> k.forEach { bytes.putLong(it) } }
            arr.put(org.json.JSONObject().put("w", w).put("b", Base64.getEncoder().withoutPadding().encodeToString(bytes.array())))
        }
        return arr
    }

    fun decode(arr: org.json.JSONArray): Map<Long, Array<LongArray>> {
        val out = HashMap<Long, Array<LongArray>>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val raw = try { Base64.getDecoder().decode(o.optString("b")) } catch (_: Exception) { continue }
            if (raw.size != KINDS * BITS / 8) continue
            val buf = java.nio.ByteBuffer.wrap(raw)
            out[o.getLong("w")] = Array(KINDS) { LongArray(BITS / 64) { buf.long } }
        }
        return out
    }
}
