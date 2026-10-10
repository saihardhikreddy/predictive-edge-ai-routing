package com.bitchat.android.mesh

import android.annotation.SuppressLint
import android.content.Context
import android.os.BatteryManager
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import com.bitchat.android.marl.MarlRouter
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.Locale
import kotlin.random.Random

/**
 * The testbed's brain. Runs on its own thread; the UI only reads [state] and
 * calls the public methods (which post onto the engine thread).
 *
 * Protocol summary (see Protocol.kt for frames):
 *  - Encounter (neighbour appears after >5 s absence): lower id sends HELLO with its
 *    PRoPHET vector (+ model weights at most every 30 s); the other replies; both
 *    update predictability and, if weights were exchanged, FedAvg them.
 *  - FLOOD mode: first copy received is re-sent to every in-range neighbour not on
 *    the path, TTL 7 (BitChat-style).
 *  - MARL mode: the holder asks MarlRouter for forward-or-carry every second; the
 *    receiver answers with HOPACK(V) for the TD update; after relaying it sends a
 *    FWDACK to whoever handed it the copy (2-hop ACK); missing FWDACKs feed CUSUM.
 *  - Destination sends DELIVERY ACK back along the route; the source logs the RTT.
 */
@SuppressLint("MissingPermission")
class MeshEngine(
    private val context: Context,
    /** Thread the engine runs on; null = its own background thread. Tests pass the main looper. */
    looper: Looper? = null,
    /** Wall clock in ms. Tests pass a virtual clock so simulated minutes run in milliseconds. */
    private val clock: () -> Long = System::currentTimeMillis,
    /** Battery %, null = read the phone's battery. */
    private val batteryLevel: (() -> Int)? = null,
    /** Radio to use; null = real Bluetooth LE. */
    radioFactory: RadioFactory? = null,
    /** SharedPreferences file holding this phone's id and name (one per virtual phone in tests). */
    prefsName: String = "mesh",
) {

    // ------------------------------------------------------------ identity

    companion object {
        /** How long a relay has to prove it passed a message on before it counts against it. */
        const val WATCH_MS = 15_000L
    }

    private val handler = Handler(looper ?: HandlerThread("mesh-engine").apply { start() }.looper)
    private val prefs = context.getSharedPreferences(prefsName, Context.MODE_PRIVATE)

    val myId: String = prefs.getString("id", null) ?: String.format(Locale.US, "%08X", Random.nextInt()).also {
        prefs.edit().putString("id", it).apply()
    }
    private var nick: String = prefs.getString("nick", null) ?: "Phone-${myId.take(4)}"
    private var nickSet: Boolean = prefs.contains("nick")

    private val log = EventLog(context, myId)
    private val fxEvents = ArrayDeque<FxEvent>()
    private var fxSeq = 0L
    private val router = MarlRouter(myId, cusumH = 6.0)
    private val transport: Radio = radioFactory?.invoke(handler, ::onAdvert, ::onFrame, ::onError)
        ?: BleTransport(context, handler, ::onAdvert, ::onFrame, ::onError)

    // ------------------------------------------------------------ settings

    private var running = false
    private var mode = Protocol.MODE_MARL
    private var sinkhole = false
    private var triageOn = true
    private var rangeDbm = -100
    private val blocked = HashSet<String>()

    // --------------------------------------------------------------- state

    private class Neighbor(val id: String) {
        var device: Any? = null // radio handle (BluetoothDevice on a phone)
        var rssi = -100.0
        var lastSeen = 0L
        var battery = 100
        var buffer = 0
        var nick = ""
        var p: Map<String, Double> = emptyMap()
        var wasInRange = false
        var lastLeft = 0L
    }

    private class Stored(
        val data: Frame.Data,
        val receivedFrom: String?,
        val storedAt: Long,
    ) {
        var nextDecision = 0L
        var carryFeatures: DoubleArray? = null
        var inFlight = false
        var loggedCarry = false
        val avoid = HashSet<String>()
    }

    private class Ctrl(val to: String, val frame: Frame, var tries: Int = 0, var nextTry: Long = 0, var inFlight: Boolean = false)

    private val neighbors = HashMap<String, Neighbor>()
    /** id -> profile name ("" until the name has reached us). */
    private val known = LinkedHashMap<String, String>()

    /** Best route learned from name announcements: [hops] away, first hop [via]. */
    private class Route(var hops: Int, var via: String, var heardAt: Long)
    private val routes = HashMap<String, Route>()

    /** neighbour -> (destination -> hops from that neighbour, when heard). Feeds the router as a P(dest) prior. */
    private val annHops = HashMap<String, HashMap<String, Pair<Int, Long>>>()
    private var annSeq = 0
    private var lastAnnounce = 0L
    private val store = ArrayList<Stored>()
    private val pendingTd = HashMap<String, Pair<DoubleArray, Int>>()
    private val watches = HashMap<String, Pair<String, Long>>()
    private val seen = HashSet<String>()
    private val deliveredHere = HashSet<String>()
    private val ctrlOut = ArrayList<Ctrl>()
    private val messages = ArrayList<ChatMsg>()
    private var counter = 0
    private var lastFl = 0L
    private var flRounds = 0
    private var lastAdvert = 0L
    private var lastAdvertBytes: ByteArray? = null

    private val stats = HashMap<String, ModeStats>().apply {
        put(Protocol.MODE_MARL, ModeStats())
        put(Protocol.MODE_FLOOD, ModeStats())
    }
    private var txFrames = 0
    private var txFails = 0
    private var txBytes = 0L
    private var status = "Stopped"

    // experiment runner
    private var expRemaining = 0
    private var expTotal = 0
    private var expInterval = 3000L
    private var expSos = 0.2
    private var expNext = 0L

    init {
        log.listener = { ev, md, msg, peer, value ->
            synchronized(fxEvents) {
                fxEvents.addLast(FxEvent(++fxSeq, ev, md, msg, peer, value))
                while (fxEvents.size > 80) fxEvents.removeFirst()
            }
        }
    }

    private val _state = MutableStateFlow(UiState(myId = myId, nick = nick, nickSet = nickSet))
    val state: StateFlow<UiState> = _state

    // ------------------------------------------------------- public controls

    fun start() = handler.post {
        if (running) return@post
        if (!transport.isEnabled) {
            status = "Bluetooth is off"
            publish(); return@post
        }
        running = true
        status = "Running"
        lastAdvertBytes = Protocol.advertPayload(myId, battery(), bufferPct())
        transport.start(lastAdvertBytes!!)
        lastAdvert = now()
        lastAnnounce = now() - 27_000 // first announcement ~3 s after start, once neighbours are found
        log.write("START", mode = mode, value = "nick=$nick")
        handler.post(tick)
        publish()
    }

    fun stop() = handler.post {
        if (!running) return@post
        running = false
        handler.removeCallbacks(tick)
        transport.stop()
        status = "Stopped"
        log.write("STOP", mode = mode)
        publish()
    }

    fun setMode(m: String) = handler.post { mode = m; log.write("MODE", mode = m); publish() }
    fun setSinkhole(on: Boolean) = handler.post { sinkhole = on; log.write("SINKHOLE_MODE", value = on.toString()); publish() }
    fun setTriage(on: Boolean) = handler.post { triageOn = on; publish() }
    fun setRange(dbm: Int) = handler.post { rangeDbm = dbm; log.write("RANGE", value = dbm.toString()); publish() }
    fun setNick(n: String) = handler.post {
        val clean = n.trim().take(24)
        if (clean.isEmpty()) return@post
        nick = clean
        nickSet = true
        prefs.edit().putString("nick", nick).apply()
        log.write("NICK", value = nick)
        lastAnnounce = 0L // tell the mesh the new name on the next tick
        publish()
    }

    fun toggleBlock(id: String) = handler.post {
        if (!blocked.add(id)) blocked.remove(id)
        log.write("BLOCK", peer = id, value = (id in blocked).toString())
        publish()
    }

    fun clearTrust() = handler.post {
        router.clearTrust()
        watches.clear()
        log.write("TRUST_RESET")
        publish()
    }

    fun send(dst: String, text: String) = handler.post { originate(dst, text) }

    fun startExperiment(count: Int, intervalMs: Long, sosFraction: Double) = handler.post {
        expTotal = count
        expRemaining = count
        expInterval = intervalMs
        expSos = sosFraction
        expNext = now()
        log.write("EXPERIMENT_START", mode = mode, value = "n=$count interval=$intervalMs sos=$sosFraction")
        publish()
    }

    fun stopExperiment() = handler.post { expRemaining = 0; publish() }

    fun resetStats() = handler.post {
        stats.values.forEach { it.reset() }
        txFrames = 0; txFails = 0; txBytes = 0
        messages.clear()
        log.write("STATS_RESET")
        publish()
    }

    fun exportLog(): String = log.exportToDownloads()
    fun csvText(): String = log.readAll()

    // ----------------------------------------------------------------- tick

    private val tick = object : Runnable {
        override fun run() {
            if (!running) return
            val t = now()
            updatePresence(t)
            router.age(0.5)
            router.decayTrust(0.5)
            processStore(t)
            processCtrl(t)
            processWatches(t)
            processExperiment(t)
            if (t - lastAdvert > 10_000) refreshAdvert(t)
            if (t - lastAnnounce > 30_000) announce(t)
            publish()
            handler.postDelayed(this, 500)
        }
    }

    private fun refreshAdvert(t: Long) {
        lastAdvert = t
        val bytes = Protocol.advertPayload(myId, battery(), bufferPct())
        if (!bytes.contentEquals(lastAdvertBytes)) {
            lastAdvertBytes = bytes
            transport.startAdvertising(bytes)
        }
    }

    // ------------------------------------------------------------ neighbours

    /** Phones pause BLE adverts for several seconds at a time, so allow 12 s of silence. */
    private fun inRange(n: Neighbor, t: Long = now()) =
        t - n.lastSeen < 12_000 && n.rssi >= rangeDbm && n.id !in blocked && n.device != null

    /** A frame written to our inbox proves its sender is still in direct range. */
    private fun heardFrom(id: String?) {
        val n = neighbors[id ?: return] ?: return
        n.lastSeen = maxOf(n.lastSeen, now())
    }

    private fun onAdvert(adv: Protocol.Advert, device: Any, rssi: Int) {
        if (!running || adv.nodeId == myId) return
        val t = now()
        val n = neighbors.getOrPut(adv.nodeId) { Neighbor(adv.nodeId) }
        n.device = device
        n.rssi = if (n.lastSeen == 0L || t - n.lastSeen > 6_000) rssi.toDouble() else 0.7 * n.rssi + 0.3 * rssi
        n.lastSeen = t
        n.battery = adv.battery
        n.buffer = adv.buffer
        known.putIfAbsent(adv.nodeId, n.nick)
        val r = inRange(n, t)
        if (r && !n.wasInRange) {
            n.wasInRange = true
            if (t - n.lastLeft > 5_000) onEncounter(n)
        }
    }

    private fun updatePresence(t: Long) {
        for (n in neighbors.values) {
            val r = inRange(n, t)
            if (n.wasInRange && !r) {
                n.wasInRange = false
                n.lastLeft = t
                log.write("NEIGHBOR_LOST", peer = n.id)
            } else if (!n.wasInRange && r) {
                n.wasInRange = true
                if (t - n.lastLeft > 5_000) onEncounter(n)
            }
        }
    }

    private fun onEncounter(n: Neighbor) {
        log.write("ENCOUNTER", peer = n.id, rssi = n.rssi.toInt())
        if (myId < n.id) {
            val withModel = now() - lastFl > 30_000 && !router.quarantined.contains(n.id)
            sendHello(n.id, reply = false, includeModel = withModel)
        }
    }

    private fun sendHello(to: String, reply: Boolean, includeModel: Boolean) {
        val vec: Map<String, Double> = if (sinkhole) known.keys.filter { it != to }.associateWith { 1.0 } else router.advertisedVector(8)
        val (w, k) = router.modelUpdate()
        sendFrame(to, Frame.Hello(myId, nick, vec, if (includeModel) w else null, k, reply)) {}
    }

    private fun neighborInfos(exclude: Set<String>): List<MarlRouter.NeighborInfo> =
        neighbors.values.filter { inRange(it) && it.id !in exclude && it.id !in router.quarantined }.map {
            MarlRouter.NeighborInfo(it.id, it.rssi.toInt(), it.battery.toDouble(), it.buffer.toDouble(), effectiveP(it))
        }

    /**
     * Neighbour's delivery predictability per destination: its PRoPHET vector (from HELLO),
     * raised by fresh announcements ("this neighbour is h hops from d" -> 0.85^h). This is what
     * lets the router head towards a phone nobody has met directly yet.
     */
    private fun effectiveP(n: Neighbor): Map<String, Double> {
        val ann = annHops[n.id] ?: return n.p
        val t = now()
        val out = HashMap(n.p)
        for ((d, hv) in ann) {
            if (t - hv.second > 120_000) continue
            val est = Math.pow(0.85, hv.first.toDouble())
            if (est > (out[d] ?: 0.0)) out[d] = est
        }
        return out
    }

    // ------------------------------------------------------------ names

    fun nameOf(id: String): String = known[id]?.takeIf { it.isNotBlank() } ?: "Unknown phone ${id.take(4)}"

    /** Flood "I exist, my name is …" (TTL 7). */
    private fun announce(t: Long) {
        lastAnnounce = t
        annSeq++
        seen.add("N:$myId:$annSeq")
        val f = Frame.Announce(myId, nick, annSeq, 0, Protocol.FLOOD_TTL, myId)
        neighbors.values.filter { inRange(it, t) }.forEach { sendFrame(it.id, f) {} }
    }

    private fun onAnnounce(a: Frame.Announce) {
        if (a.src == myId || !seen.add("N:${a.src}:${a.seq}")) return
        val t = now()
        if (a.nick.isNotBlank() && known[a.src] != a.nick) {
            known[a.src] = a.nick
            log.write("NAME", peer = a.src, value = a.nick)
        } else known.putIfAbsent(a.src, "")
        val h = a.hops + 1
        val r = routes[a.src]
        if (r == null || h <= r.hops || t - r.heardAt > 60_000) routes[a.src] = Route(h, a.from, t)
        else if (r.via == a.from) r.heardAt = t
        annHops.getOrPut(a.from) { HashMap() }[a.src] = a.hops to t
        if (a.ttl > 1 && !sinkhole) {
            val fwd = a.copy(hops = h, ttl = a.ttl - 1, from = myId)
            neighbors.values.filter { inRange(it, t) && it.id != a.from && it.id != a.src }.forEach { sendFrame(it.id, fwd) {} }
        }
    }

    // ---------------------------------------------------------------- sending

    private fun sendFrame(to: String, frame: Frame, cb: (Boolean) -> Unit) {
        val n = neighbors[to]
        if (n == null || !inRange(n)) { cb(false); return }
        val dev = n.device ?: run { cb(false); return }
        val bytes = frame.encode()
        val type = frame.javaClass.simpleName
        val msg = when (frame) {
            is Frame.Data -> frame.msgId
            is Frame.HopAck -> frame.msgId
            is Frame.FwdAck -> frame.msgId
            is Frame.DeliveryAck -> frame.msgId
            is Frame.Announce -> ""
            else -> ""
        }
        transport.send(dev, bytes) { ok ->
            txFrames++
            txBytes += bytes.size
            if (!ok) txFails++
            log.write(if (ok) "TX_OK" else "TX_FAIL", mode = (frame as? Frame.Data)?.mode ?: "",
                msg = msg, peer = to, rssi = n.rssi.toInt(), bytes = bytes.size, value = type)
            cb(ok)
        }
    }

    private fun originate(dst: String, text: String) {
        val tri = Triage.process(text, triageOn)
        counter++
        val msgId = "${myId.take(4)}-${counter.toString(36)}-${Random.nextInt(1000)}"
        val t = now()
        val sos = tri.intent == Triage.SOS
        val copies = if (mode == Protocol.MODE_MARL && sos) 2 else 1
        stats[mode]!!.originated++
        if (sos) stats[mode]!!.sosOriginated++
        messages.add(ChatMsg(msgId, dst, nameOf(dst), text, true, tri.intent, "sent", t, mode = mode,
            note = if (tri.wireBytes < tri.rawBytes) "${tri.rawBytes}→${tri.wireBytes} B" else ""))
        log.write("ORIG", mode = mode, msg = msgId, dst = dst, bytes = tri.wireBytes, value = "${tri.intent};raw=${tri.rawBytes}")
        val base = Frame.Data(msgId, 0, myId, dst, t, emptyList(), tri.urgency, tri.intent, tri.wireText, mode, Protocol.FLOOD_TTL, nick)
        if (mode == Protocol.MODE_FLOOD) {
            seen.add(msgId)
            floodForward(base, null)
        } else {
            for (c in 0 until copies) {
                val d = base.copy(copy = c)
                seen.add(d.key)
                store.add(Stored(d, null, t).apply { nextDecision = t })
            }
            processStore(t)
        }
        publish()
    }

    private fun floodForward(d: Frame.Data, from: String?) {
        if (d.ttl <= 0) return
        val out = d.copy(path = d.path + myId, ttl = d.ttl - 1)
        val targets = neighbors.values.filter { inRange(it) && it.id !in d.path && it.id != from }
            .sortedBy { if (it.id == d.dst) 0 else 1 } // the destination hears it first, directly
        if (targets.isEmpty()) log.write("FLOOD_NO_NEIGHBOR", mode = d.mode, msg = d.msgId)
        targets.forEach { sendFrame(it.id, out) {} }
    }

    // ------------------------------------------------------------- MARL store

    private fun bufferPct() = (store.size * 10).coerceAtMost(100)

    private fun processStore(t: Long) {
        for (s in store.toList()) {
            if (s.inFlight || t < s.nextDecision) continue
            val d = s.data
            val ttl = if (d.urgency >= 5.0) 240_000 else 120_000
            if (t - s.storedAt > ttl) {
                store.remove(s)
                log.write("TTL_DROP", mode = d.mode, msg = d.msgId, src = d.src, dst = d.dst, hops = d.path.size)
                continue
            }
            decide(s, t)
        }
    }

    private fun decide(s: Stored, t: Long) {
        val d = s.data
        // a sibling SOS copy was already handed straight to the destination: this one is redundant
        if (d.dst in s.avoid) {
            store.remove(s)
            log.write("COPY_SKIPPED", mode = d.mode, msg = d.msgId, value = "sibling went direct")
            return
        }
        val exclude = HashSet<String>(d.path).apply { add(myId); addAll(s.avoid) }
        val all = neighborInfos(exclude)
        // Destination in direct range over a usable link: hand it over directly (1 hop).
        // The learned router only chooses among relays when the destination is not reachable.
        val direct = all.firstOrNull { it.peerId == d.dst && MarlRouter.packetSuccessProb(it.rssi) >= 0.5 }
        val infos = if (direct != null) listOf(direct) else all
        val dec = router.decide(d.dst, infos, emergency = direct != null || d.urgency >= 5.0)
        val best = dec.qValues.values.maxOrNull() ?: 0.0
        s.carryFeatures?.let { if (!sinkhole) router.onCarryResolved(it, best) }
        s.carryFeatures = null
        val y = dec.nextHop
        if (y == null) {
            s.carryFeatures = dec.features
            s.nextDecision = t + 1_000
            if (!s.loggedCarry) {
                s.loggedCarry = true
                log.write("CARRY", mode = d.mode, msg = d.msgId, dst = d.dst, value = "neighbors=${infos.size}")
            }
            return
        }
        val out = d.copy(path = d.path + myId)
        val bytes = out.encode().size
        val features = dec.features
        s.inFlight = true
        sendFrame(y, out) { ok ->
            s.inFlight = false
            if (ok) {
                store.remove(s)
                pendingTd[d.key] = features to bytes
                // 2-hop ACK deadline: an honest relay in range forwards within a few seconds
                if (y != d.dst) watches[d.key] = y to now() + WATCH_MS
                s.receivedFrom?.let { prev -> sendFrame(prev, Frame.FwdAck(d.msgId, d.copy, myId)) {} }
                store.filter { it.data.msgId == d.msgId }.forEach { it.avoid.add(y) }
            } else {
                s.nextDecision = now() + 1_000
            }
        }
    }

    // ------------------------------------------------------------- receiving

    private fun onFrame(bytes: ByteArray) {
        if (!running) return
        val f = Frame.decode(bytes)
        heardFrom(when (f) {
            is Frame.Hello -> f.src
            is Frame.Announce -> f.from
            is Frame.Data -> f.path.lastOrNull()
            is Frame.HopAck -> f.src
            is Frame.FwdAck -> f.src
            else -> null
        })
        when (f) {
            is Frame.Hello -> onHello(f)
            is Frame.Announce -> onAnnounce(f)
            is Frame.Data -> onData(f, bytes.size)
            is Frame.HopAck -> onHopAck(f)
            is Frame.FwdAck -> onFwdAck(f)
            is Frame.DeliveryAck -> onDeliveryAck(f)
            null -> log.write("RX_GARBAGE", bytes = bytes.size)
        }
        publish()
    }

    private fun onHello(h: Frame.Hello) {
        if (h.nick.isNotBlank()) known[h.src] = h.nick else known.putIfAbsent(h.src, "")
        neighbors[h.src]?.let { it.nick = h.nick; it.p = h.p }
        router.onEncounter(h.src, h.p)
        log.write("HELLO_RX", peer = h.src, value = "reply=${h.reply};model=${h.w != null}")
        if (!h.reply) sendHello(h.src, reply = true, includeModel = h.w != null)
        val w = h.w
        if (w != null && w.size == MarlRouter.N_FEAT && h.src !in router.quarantined && !sinkhole) {
            router.mergeModel(w, h.samples)
            lastFl = now()
            flRounds++
            log.write("FL_MERGE", peer = h.src, value = router.w.joinToString(";") { String.format(Locale.US, "%.3f", it) })
        }
    }

    private fun onData(d: Frame.Data, size: Int) {
        val sender = d.path.lastOrNull() ?: d.src
        if (d.srcName.isNotBlank()) known[d.src] = d.srcName else known.putIfAbsent(d.src, "")
        if (d.mode == Protocol.MODE_FLOOD) {
            if (!seen.add(d.msgId)) { log.write("DUP", mode = d.mode, msg = d.msgId, peer = sender); return }
            log.write("RX", mode = d.mode, msg = d.msgId, src = d.src, dst = d.dst, peer = sender, hops = d.path.size, bytes = size)
            if (sinkhole) { log.write("SINK_DROP", mode = d.mode, msg = d.msgId); return }
            if (d.dst == myId) deliver(d) else floodForward(d, sender)
            return
        }
        if (!seen.add(d.key)) { log.write("DUP", mode = d.mode, msg = d.msgId, peer = sender); return }
        log.write("RX", mode = d.mode, msg = d.msgId, src = d.src, dst = d.dst, peer = sender, hops = d.path.size, bytes = size)
        if (sinkhole) {
            sendFrame(sender, Frame.HopAck(d.msgId, d.copy, myId, 9.9)) {}
            log.write("SINK_DROP", mode = d.mode, msg = d.msgId)
            return
        }
        if (d.dst == myId) {
            sendFrame(sender, Frame.HopAck(d.msgId, d.copy, myId, null)) {}
            deliver(d)
            return
        }
        val v = router.bestValue(d.dst, neighborInfos(HashSet(d.path) + myId))
        sendFrame(sender, Frame.HopAck(d.msgId, d.copy, myId, v)) {}
        val t = now()
        store.add(Stored(d, sender, t).apply { nextDecision = t })
        processStore(t)
    }

    private fun deliver(d: Frame.Data) {
        log.write("DELIVER", mode = d.mode, msg = d.msgId, src = d.src, dst = myId, hops = d.path.size,
            value = "copy=${d.copy};intent=${d.intent}")
        if (!deliveredHere.add(d.msgId)) return
        messages.add(ChatMsg(d.msgId, d.src, nameOf(d.src), d.text, false, d.intent, "received", now(),
            hops = d.path.size, mode = d.mode))
        val route = d.path + myId
        queueBack(Frame.DeliveryAck(d.msgId, myId, d.src, d.createdAt, route, d.path.size))
    }

    private fun queueBack(k: Frame.DeliveryAck) {
        val idx = k.path.lastIndexOf(myId)
        if (idx <= 0) return
        ctrlOut.add(Ctrl(k.path[idx - 1], k))
    }

    private fun onDeliveryAck(k: Frame.DeliveryAck) {
        if (k.dst != myId) { queueBack(k); return }
        val m = messages.firstOrNull { it.id == k.msgId && it.outgoing } ?: return
        if (m.status == "delivered") return
        val rtt = now() - k.createdAt
        m.status = "delivered"
        m.rttMs = rtt
        m.hops = k.hops
        stats[m.mode]?.let {
            it.confirmed++
            it.rttSum += rtt
            it.hopSum += k.hops
            if (m.intent == Triage.SOS) it.sosConfirmed++
        }
        log.write("DELACK_RX", mode = m.mode, msg = k.msgId, src = myId, dst = k.src, hops = k.hops, value = rtt.toString())
    }

    private fun onHopAck(a: Frame.HopAck) {
        val key = "${a.msgId}:${a.copy}"
        val (features, bytes) = pendingTd.remove(key) ?: return
        if (!sinkhole) router.onHopAcked(features, bytes, a.value)
        log.write("HOPACK_RX", msg = a.msgId, peer = a.src, value = a.value?.let { String.format(Locale.US, "%.2f", it) } ?: "dest")
    }

    private fun onFwdAck(f: Frame.FwdAck) {
        val key = "${f.msgId}:${f.copy}"
        val w = watches[key] ?: return
        if (w.first != f.src) return
        watches.remove(key)
        report(f.src, true)
    }

    private fun processWatches(t: Long) {
        val expired = watches.filter { it.value.second < t }
        for ((key, w) in expired) {
            watches.remove(key)
            report(w.first, false)
        }
    }

    private fun report(peer: String, ok: Boolean) {
        val others = neighbors.keys.filter { it != peer && it !in router.quarantined }.map { router.reputation(it) }
        val p0 = if (others.isEmpty()) 0.85 else others.average()
        val flagged = router.reportOutcome(peer, ok, p0)
        log.write("TRUST", peer = peer, value = "ok=$ok;anomaly=${String.format(Locale.US, "%.2f", router.anomalyScore(peer))}")
        if (flagged) {
            log.write("QUARANTINE", peer = peer, value = "reputation=${String.format(Locale.US, "%.2f", router.reputation(peer))}")
            status = "Quarantined ${nameOf(peer)}"
        }
    }

    private fun processCtrl(t: Long) {
        for (c in ctrlOut.toList()) {
            if (c.inFlight || t < c.nextTry) continue
            if (c.tries >= 20) { ctrlOut.remove(c); log.write("CTRL_DROP", peer = c.to); continue }
            c.tries++
            c.nextTry = t + 2_000
            val n = neighbors[c.to]
            if (n == null || !inRange(n, t)) continue
            c.inFlight = true
            sendFrame(c.to, c.frame) { ok -> c.inFlight = false; if (ok) ctrlOut.remove(c) }
        }
    }

    private fun processExperiment(t: Long) {
        if (expRemaining <= 0 || t < expNext) return
        val targets = known.keys.filter { it != myId }
        if (targets.isEmpty()) { status = "Experiment waiting: no known phones yet"; expNext = t + 2_000; return }
        val dst = targets.random()
        val sos = Random.nextDouble() < expSos
        val text = (if (sos) Triage.EMERGENCY_CORPUS else Triage.ROUTINE_CORPUS).random()
        originate(dst, text)
        expRemaining--
        expNext = t + expInterval
        if (expRemaining == 0) log.write("EXPERIMENT_DONE", mode = mode)
    }

    private fun onError(msg: String) {
        status = msg
        log.write("ERROR", value = msg)
        publish()
    }

    // ---------------------------------------------------------------- helpers

    private fun now() = clock()

    private fun battery(): Int = batteryLevel?.invoke() ?: try {
        context.getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
    } catch (_: Exception) { 100 }

    private fun publish() {
        val t = now()
        _state.value = UiState(
            myId = myId,
            nick = nick,
            running = running,
            status = status,
            mode = mode,
            sinkhole = sinkhole,
            triageOn = triageOn,
            rangeDbm = rangeDbm,
            battery = battery(),
            neighbors = neighbors.values.sortedByDescending { it.rssi }.map {
                UiNeighbor(
                    id = it.id, nick = nameOf(it.id), rssi = it.rssi.toInt(), battery = it.battery,
                    present = inRange(it, t), seenAgoS = ((t - it.lastSeen) / 1000).toInt(),
                    linkQ = MarlRouter.packetSuccessProb(it.rssi.toInt()),
                    reputation = router.reputation(it.id), anomaly = router.anomalyScore(it.id),
                    quarantined = it.id in router.quarantined, blocked = it.id in blocked,
                )
            },
            nickSet = nickSet,
            known = (known.keys + routes.keys).filter { it != myId }.distinct().map { id ->
                val nb = neighbors[id]
                val present = nb != null && inRange(nb, t)
                val r = routes[id]
                val heard = maxOf(nb?.lastSeen ?: 0L, r?.heardAt ?: 0L)
                KnownPhone(
                    id = id, name = nameOf(id), present = present,
                    hops = if (present) 1 else r?.hops ?: 0,
                    heardAgoS = if (heard > 0) ((t - heard) / 1000).toInt() else -1,
                )
            }.sortedWith(compareBy({ !it.present }, { if (it.hops == 0) 99 else it.hops }, { it.name.lowercase() })),
            messages = messages.takeLast(100).map { it.copy() },
            stats = stats.mapValues { it.value.copy() },
            txFrames = txFrames, txFails = txFails, txBytes = txBytes,
            stored = store.size, queue = transport.queueSize,
            weights = router.w.toList(), samples = router.nSamples, flRounds = flRounds,
            predictability = router.advertisedVector(6).toList().map { (k, v) -> nameOf(k) to v },
            expRemaining = expRemaining, expTotal = expTotal,
            logTail = log.tail(150),
            events = synchronized(fxEvents) { fxEvents.toList() },
        )
    }
}

data class ModeStats(
    var originated: Int = 0,
    var confirmed: Int = 0,
    var rttSum: Long = 0,
    var hopSum: Int = 0,
    var sosOriginated: Int = 0,
    var sosConfirmed: Int = 0,
) {
    fun reset() { originated = 0; confirmed = 0; rttSum = 0; hopSum = 0; sosOriginated = 0; sosConfirmed = 0 }
}

data class ChatMsg(
    val id: String,
    val peer: String,
    val peerName: String,
    val text: String,
    val outgoing: Boolean,
    val intent: String,
    var status: String,
    val time: Long,
    var rttMs: Long = 0,
    var hops: Int = 0,
    val mode: String = "",
    val note: String = "",
)

/** A phone you can message: in direct range, or known through name announcements. */
data class KnownPhone(val id: String, val name: String, val present: Boolean, val hops: Int, val heardAgoS: Int)

data class UiNeighbor(
    val id: String,
    val nick: String,
    val rssi: Int,
    val battery: Int,
    val present: Boolean,
    val seenAgoS: Int,
    val linkQ: Double,
    val reputation: Double,
    val anomaly: Double,
    val quarantined: Boolean,
    val blocked: Boolean,
)

data class UiState(
    val myId: String = "",
    val nick: String = "",
    val running: Boolean = false,
    val status: String = "Stopped",
    val mode: String = Protocol.MODE_MARL,
    val sinkhole: Boolean = false,
    val triageOn: Boolean = true,
    val rangeDbm: Int = -100,
    val battery: Int = 100,
    val neighbors: List<UiNeighbor> = emptyList(),
    val nickSet: Boolean = false,
    val known: List<KnownPhone> = emptyList(),
    val messages: List<ChatMsg> = emptyList(),
    val stats: Map<String, ModeStats> = emptyMap(),
    val txFrames: Int = 0,
    val txFails: Int = 0,
    val txBytes: Long = 0,
    val stored: Int = 0,
    val queue: Int = 0,
    val weights: List<Double> = emptyList(),
    val samples: Int = 0,
    val flRounds: Int = 0,
    val predictability: List<Pair<String, Double>> = emptyList(),
    val expRemaining: Int = 0,
    val expTotal: Int = 0,
    val logTail: List<String> = emptyList(),
    val events: List<FxEvent> = emptyList(),
)

data class FxEvent(val seq: Long, val ev: String, val mode: String, val msg: String, val peer: String, val value: String)
