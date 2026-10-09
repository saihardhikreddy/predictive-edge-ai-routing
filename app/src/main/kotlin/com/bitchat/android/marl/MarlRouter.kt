package com.bitchat.android.marl

import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

/**
 * On-device predictive router for the BitChat BLE mesh.
 *
 * Pure Kotlin (no Android imports) so it can be unit-tested on the JVM and
 * called from BitChat's BluetoothMeshService. Mirrors simulation/mesh_engine.py:
 *
 *  - Linear Q-function  Q(d, a) = w . phi(a, d)  over actions {forward to y, CARRY}
 *  - Forward value = linkQ * Q + (1 - linkQ) * PENALTY_LINK   (expected-transmission aware)
 *  - TD(0) update from the next hop's advertised value V_y(d) (Q-routing)
 *  - PRoPHET delivery predictability P(d): encounter, aging, transitivity
 *  - Gossip FedAvg of w on encounters (only N_FEAT floats leave the device)
 *  - Trust: 2-hop-ACK outcomes per neighbour + one-sided CUSUM change detector
 */
class MarlRouter(
    val nodeId: String,
    var learningEnabled: Boolean = true,
    private val alpha: Double = 0.02,
    private val gamma: Double = 0.9,
    private val epsilon: Double = 0.05,
    private val random: java.util.Random = java.util.Random(),
    /** CUSUM alarm threshold; lower = faster detection, more false alarms. */
    var cusumH: Double = CUSUM_H,
) {
    companion object {
        const val N_FEAT = 7 // bias, P(dest), linkQ, battery, buffer, isDest, isCarry
        val PRIOR_W = doubleArrayOf(0.0, 7.0, 0.5, 1.0, -1.5, 10.0, -0.3)
        const val REWARD_DELIVER = 10.0
        const val PENALTY_LINK = -3.0
        const val CARRY_COST = 0.2
        const val W_CLIP = 50.0
        const val P_INIT = 0.75
        const val P_BETA = 0.25
        const val P_AGING_PER_S = 0.985
        const val PSR_MID_DBM = -85.0
        const val PSR_SCALE_DB = 2.5
        const val CUSUM_P1 = 0.2
        const val CUSUM_H = 12.0

        /** Probability a BLE frame gets through at this RSSI (logistic fit). */
        fun packetSuccessProb(rssi: Int): Double = 1.0 / (1.0 + exp(-(rssi - PSR_MID_DBM) / PSR_SCALE_DB))
    }

    /** What a neighbour advertises in its BLE announce (and on encounter). */
    data class NeighborInfo(
        val peerId: String,
        val rssi: Int,
        val batteryPercent: Double,
        val bufferPercent: Double,
        val predictability: Map<String, Double>,
    )

    /** Decision: null nextHop means CARRY (store-carry-forward, re-decide later). */
    data class Decision(val nextHop: String?, val qValues: Map<String, Double>, val features: DoubleArray)

    var w: DoubleArray = PRIOR_W.copyOf()
        private set
    var nSamples: Int = 0
        private set
    val predictability = HashMap<String, Double>()
    var batteryPercent: Double = 100.0
    var bufferPercent: Double = 10.0

    // ------------------------------------------------------------- features

    private fun phiForward(n: NeighborInfo, dest: String): DoubleArray = doubleArrayOf(
        1.0,
        if (n.peerId == dest) 1.0 else n.predictability[dest] ?: 0.0,
        packetSuccessProb(n.rssi),
        n.batteryPercent / 100.0,
        n.bufferPercent / 100.0,
        if (n.peerId == dest) 1.0 else 0.0,
        0.0,
    )

    private fun phiCarry(dest: String): DoubleArray = doubleArrayOf(
        1.0, predictability[dest] ?: 0.0, 0.0, batteryPercent / 100.0, bufferPercent / 100.0, 0.0, 1.0,
    )

    private fun dot(a: DoubleArray, b: DoubleArray): Double {
        var s = 0.0
        for (i in a.indices) s += a[i] * b[i]
        return s
    }

    private fun forwardValue(phi: DoubleArray): Double {
        val lq = phi[2]
        return lq * dot(w, phi) + (1.0 - lq) * PENALTY_LINK
    }

    // -------------------------------------------------------------- routing

    /**
     * Pick the next hop for a packet to [dest].
     * @param neighbors current radio neighbours (already filtered for quarantine/visited)
     * @param emergency SOS: no exploration, never wait while a reasonable relay exists
     */
    fun decide(dest: String, neighbors: List<NeighborInfo>, emergency: Boolean = false): Decision {
        val carryPhi = phiCarry(dest)
        val carryQ = dot(w, carryPhi)
        val fwd = neighbors.map { it.peerId to phiForward(it, dest) }
        val qs = LinkedHashMap<String, Double>()
        qs["CARRY"] = carryQ
        for ((id, phi) in fwd) qs[id] = forwardValue(phi)

        val allowCarry = !(emergency && fwd.any { forwardValue(it.second) > carryQ - 2.0 })
        val options = fwd.map { it.first to forwardValue(it.second) }.toMutableList()
        if (allowCarry || options.isEmpty()) options.add(0, "CARRY" to carryQ)

        val pick = if (!emergency && options.size > 1 && random.nextDouble() < epsilon) {
            options[random.nextInt(options.size)]
        } else {
            options.maxByOrNull { it.second }!!
        }
        return if (pick.first == "CARRY") {
            Decision(null, qs, carryPhi)
        } else {
            Decision(pick.first, qs, fwd.first { it.first == pick.first }.second)
        }
    }

    /** V(d) this node piggybacks on the link-layer ACK when it receives a packet. */
    fun bestValue(dest: String, neighbors: List<NeighborInfo>): Double {
        var best = dot(w, phiCarry(dest))
        for (n in neighbors) best = max(best, forwardValue(phiForward(n, dest)))
        return best
    }

    /** After a hop: [nextValue] is V_y(d) from the ACK, or null if y was the destination. */
    fun onHopAcked(features: DoubleArray, payloadBytes: Int, nextValue: Double?) {
        val hopCost = 0.4 + 0.6 * payloadBytes / 150.0
        val target = if (nextValue == null) REWARD_DELIVER - hopCost else -hopCost + gamma * nextValue
        tdUpdate(features, target)
    }

    /** Close a CARRY decision once the next decision for the same packet is made. */
    fun onCarryResolved(carryFeatures: DoubleArray, bestNow: Double) =
        tdUpdate(carryFeatures, -CARRY_COST + gamma * bestNow)

    private fun tdUpdate(phi: DoubleArray, target: Double) {
        if (!learningEnabled) return
        val err = target - dot(w, phi)
        for (i in w.indices) w[i] = min(W_CLIP, max(-W_CLIP, w[i] + alpha * err * phi[i]))
        nSamples++
    }

    // ------------------------------------------------- PRoPHET predictability

    fun onEncounter(peer: String, peerVector: Map<String, Double>) {
        val p = predictability[peer] ?: 0.0
        val pPeer = p + (1 - p) * P_INIT
        predictability[peer] = pPeer
        for ((c, pc) in peerVector) {
            if (c == nodeId) continue
            val old = predictability[c] ?: 0.0
            predictability[c] = old + (1 - old) * pPeer * pc * P_BETA
        }
    }

    fun age(elapsedSeconds: Double) {
        val k = P_AGING_PER_S.pow(elapsedSeconds)
        val it = predictability.entries.iterator()
        while (it.hasNext()) {
            val e = it.next()
            e.setValue(e.value * k)
            if (e.value < 1e-3) it.remove()
        }
    }

    /** Top entries to put in the BLE announce (3 bytes each on air). */
    fun advertisedVector(maxEntries: Int = 8): Map<String, Double> =
        predictability.entries.sortedByDescending { it.value }.take(maxEntries).associate { it.key to it.value }

    // ----------------------------------------------------- gossip federated

    /** Payload for an FL round: our weights + how much experience they encode. */
    fun modelUpdate(): Pair<DoubleArray, Int> = w.copyOf() to nSamples

    /** Sample-weighted FedAvg with a peer's model. */
    fun mergeModel(peerW: DoubleArray, peerSamples: Int) {
        require(peerW.size == N_FEAT)
        val na = nSamples + 1
        val nb = peerSamples + 1
        for (i in w.indices) w[i] = (na * w[i] + nb * peerW[i]) / (na + nb)
        nSamples = (na + nb) / 2
    }

    // ------------------------------------------------------------ trust IDS

    private val trust = HashMap<String, DoubleArray>() // peer -> [handed, credited] (decayed)
    private val cusum = HashMap<String, Double>()
    val quarantined = HashSet<String>()

    /**
     * Record a 2-hop-ACK outcome for [peer]: true if we saw it forward our packet
     * (or it was the destination), false if the 2ACK timer expired.
     * @param neighbourhoodRate expected forwarding rate of peer's ego graph (p0)
     * @return true if this observation pushed the peer into quarantine
     */
    fun reportOutcome(peer: String, forwarded: Boolean, neighbourhoodRate: Double = 0.85): Boolean {
        val rec = trust.getOrPut(peer) { doubleArrayOf(0.0, 0.0) }
        rec[0] += 1.0
        if (forwarded) rec[1] += 1.0
        val p0 = min(0.98, max(0.6, neighbourhoodRate))
        val llr = if (forwarded) ln(CUSUM_P1 / p0) else ln((1 - CUSUM_P1) / (1 - p0))
        val s = max(0.0, (cusum[peer] ?: 0.0) + llr)
        cusum[peer] = s
        if (s >= cusumH && quarantined.add(peer)) {
            predictability.remove(peer)
            return true
        }
        return false
    }

    fun reputation(peer: String): Double {
        val r = trust[peer] ?: return 0.5
        return (r[1] + 1.0) / (r[0] + 2.0)
    }

    fun anomalyScore(peer: String): Double = min(1.0, (cusum[peer] ?: 0.0) / cusumH)

    fun clearTrust() {
        trust.clear()
        cusum.clear()
        quarantined.clear()
    }

    fun decayTrust(elapsedSeconds: Double, perSecond: Double = 0.97) {
        val k = perSecond.pow(elapsedSeconds)
        for (r in trust.values) {
            r[0] *= k
            r[1] *= k
        }
    }
}
