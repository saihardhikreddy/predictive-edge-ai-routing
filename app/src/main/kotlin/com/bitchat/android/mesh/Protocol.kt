package com.bitchat.android.mesh

import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Wire format shared by every phone running the testbed. */
object Protocol {
    val SERVICE_UUID: UUID = UUID.fromString("6e8f0001-2b7c-4c1a-9a51-5e7a1d2c0b11")
    val INBOX_UUID: UUID = UUID.fromString("6e8f0002-2b7c-4c1a-9a51-5e7a1d2c0b11")

    const val MODE_MARL = "M"
    const val MODE_FLOOD = "F"
    const val FLOOD_TTL = 7

    /** Advertisement service data: 4-byte node id, battery %, buffer %. */
    fun advertPayload(nodeId: String, battery: Int, buffer: Int): ByteArray {
        val idBytes = nodeId.chunked(2).map { it.toInt(16).toByte() }
        return (idBytes + listOf(battery.coerceIn(0, 100).toByte(), buffer.coerceIn(0, 100).toByte())).toByteArray()
    }

    data class Advert(val nodeId: String, val battery: Int, val buffer: Int)

    fun parseAdvert(b: ByteArray): Advert? {
        if (b.size < 6) return null
        val id = b.take(4).joinToString("") { String.format(java.util.Locale.US, "%02X", it.toInt() and 0xFF) }
        return Advert(id, b[4].toInt() and 0xFF, b[5].toInt() and 0xFF)
    }
}

/** All frames are compact JSON objects; "t" is the type. */
sealed class Frame {
    abstract fun toJson(): JSONObject
    fun encode(): ByteArray = toJson().toString().toByteArray(Charsets.UTF_8)

    /** Encounter exchange: nickname, delivery-predictability vector, optional model for gossip FedAvg. */
    data class Hello(
        val src: String,
        val nick: String,
        val p: Map<String, Double>,
        val w: DoubleArray?,
        val samples: Int,
        val reply: Boolean,
    ) : Frame() {
        override fun toJson() = JSONObject().apply {
            put("t", "H"); put("s", src); put("n", nick); put("r", reply)
            put("p", JSONObject().apply { p.forEach { (k, v) -> put(k, Math.round(v * 1000.0) / 1000.0) } })
            if (w != null) {
                put("w", JSONArray().apply { w.forEach { put(Math.round(it * 10000.0) / 10000.0) } })
                put("k", samples)
            }
        }
    }

    /** A message copy travelling through the mesh. */
    data class Data(
        val msgId: String,
        val copy: Int,
        val src: String,
        val dst: String,
        val createdAt: Long,
        val path: List<String>,
        val urgency: Double,
        val intent: String,
        val text: String,
        val mode: String,
        val ttl: Int,
    ) : Frame() {
        val key get() = "$msgId:$copy"
        override fun toJson() = JSONObject().apply {
            put("t", "D"); put("m", msgId); put("c", copy); put("s", src); put("d", dst); put("o", createdAt)
            put("pa", JSONArray(path)); put("u", urgency); put("i", intent); put("x", text); put("md", mode); put("tl", ttl)
        }
    }

    /** Per-hop ACK carrying the receiver's value estimate V(d) (null when the receiver is the destination). */
    data class HopAck(val msgId: String, val copy: Int, val src: String, val value: Double?) : Frame() {
        override fun toJson() = JSONObject().apply {
            put("t", "A"); put("m", msgId); put("c", copy); put("s", src)
            if (value != null) put("v", value)
        }
    }

    /** 2-hop ACK: "I (src) forwarded the copy you gave me". */
    data class FwdAck(val msgId: String, val copy: Int, val src: String) : Frame() {
        override fun toJson() = JSONObject().apply { put("t", "F"); put("m", msgId); put("c", copy); put("s", src) }
    }

    /** End-to-end delivery confirmation, walked back along [path]. */
    data class DeliveryAck(val msgId: String, val src: String, val dst: String, val createdAt: Long, val path: List<String>, val hops: Int) : Frame() {
        override fun toJson() = JSONObject().apply {
            put("t", "K"); put("m", msgId); put("s", src); put("d", dst); put("o", createdAt); put("pa", JSONArray(path)); put("h", hops)
        }
    }

    companion object {
        fun decode(bytes: ByteArray): Frame? = try {
            val j = JSONObject(String(bytes, Charsets.UTF_8))
            when (j.getString("t")) {
                "H" -> {
                    val pj = j.optJSONObject("p") ?: JSONObject()
                    val p = HashMap<String, Double>()
                    pj.keys().forEach { p[it] = pj.getDouble(it) }
                    val wj = j.optJSONArray("w")
                    Hello(j.getString("s"), j.optString("n"), p, wj?.let { a -> DoubleArray(a.length()) { a.getDouble(it) } }, j.optInt("k"), j.optBoolean("r"))
                }
                "D" -> Data(
                    j.getString("m"), j.getInt("c"), j.getString("s"), j.getString("d"), j.getLong("o"),
                    j.getJSONArray("pa").let { a -> List(a.length()) { a.getString(it) } },
                    j.getDouble("u"), j.getString("i"), j.getString("x"), j.getString("md"), j.optInt("tl", Protocol.FLOOD_TTL),
                )
                "A" -> HopAck(j.getString("m"), j.getInt("c"), j.getString("s"), if (j.has("v")) j.getDouble("v") else null)
                "F" -> FwdAck(j.getString("m"), j.getInt("c"), j.getString("s"))
                "K" -> DeliveryAck(j.getString("m"), j.getString("s"), j.getString("d"), j.getLong("o"),
                    j.getJSONArray("pa").let { a -> List(a.length()) { a.getString(it) } }, j.optInt("h"))
                else -> null
            }
        } catch (e: Exception) {
            null
        }
    }
}
