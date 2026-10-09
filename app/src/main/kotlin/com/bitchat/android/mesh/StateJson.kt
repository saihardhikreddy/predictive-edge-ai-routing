package com.bitchat.android.mesh

import org.json.JSONArray
import org.json.JSONObject

/** UiState → the JSON shape web/js/main.js and world.js read (mirrors web/js/demo.js). */
fun UiState.toJson(): String {
    val o = JSONObject()
    o.put("myId", myId)
    o.put("nick", nick)
    o.put("running", running)
    o.put("status", status)
    o.put("mode", mode)
    o.put("sinkhole", sinkhole)
    o.put("triageOn", triageOn)
    o.put("rangeDbm", rangeDbm)
    o.put("battery", battery)
    o.put("neighbors", JSONArray().apply {
        neighbors.forEach { n ->
            put(JSONObject().apply {
                put("id", n.id); put("nick", n.nick); put("rssi", n.rssi); put("battery", n.battery)
                put("present", n.present); put("seenAgoS", n.seenAgoS); put("linkQ", n.linkQ)
                put("reputation", n.reputation); put("anomaly", n.anomaly)
                put("quarantined", n.quarantined); put("blocked", n.blocked)
            })
        }
    })
    o.put("known", JSONArray().apply { known.forEach { (id, name) -> put(JSONArray().put(id).put(name)) } })
    o.put("messages", JSONArray().apply {
        messages.forEach { m ->
            put(JSONObject().apply {
                put("id", m.id); put("peer", m.peer); put("peerName", m.peerName); put("text", m.text)
                put("outgoing", m.outgoing); put("intent", m.intent); put("status", m.status); put("time", m.time)
                put("rttMs", m.rttMs); put("hops", m.hops); put("mode", m.mode); put("note", m.note)
            })
        }
    })
    o.put("stats", JSONObject().apply {
        stats.forEach { (k, st) ->
            put(k, JSONObject().apply {
                put("originated", st.originated); put("confirmed", st.confirmed); put("rttSum", st.rttSum)
                put("hopSum", st.hopSum); put("sosOriginated", st.sosOriginated); put("sosConfirmed", st.sosConfirmed)
            })
        }
    })
    o.put("txFrames", txFrames)
    o.put("txFails", txFails)
    o.put("txBytes", txBytes)
    o.put("stored", stored)
    o.put("queue", queue)
    o.put("weights", JSONArray().apply { weights.forEach { put(it) } })
    o.put("samples", samples)
    o.put("flRounds", flRounds)
    o.put("predictability", JSONArray().apply { predictability.forEach { (k, v) -> put(JSONArray().put(k).put(v)) } })
    o.put("expRemaining", expRemaining)
    o.put("expTotal", expTotal)
    o.put("logTail", JSONArray(logTail))
    o.put("events", JSONArray().apply {
        events.forEach { e ->
            put(JSONObject().apply {
                put("seq", e.seq); put("ev", e.ev); put("mode", e.mode); put("msg", e.msg); put("peer", e.peer); put("value", e.value)
            })
        }
    })
    return o.toString()
}
