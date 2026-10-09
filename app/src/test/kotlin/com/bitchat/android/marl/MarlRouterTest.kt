package com.bitchat.android.marl

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MarlRouterTest {
    private fun nb(id: String, rssi: Int, p: Double, dest: String = "D") =
        MarlRouter.NeighborInfo(id, rssi, 90.0, 10.0, mapOf(dest to p))

    @Test
    fun prefersNeighbourLikelyToMeetDestination() {
        val r = MarlRouter("A", random = java.util.Random(1))
        val d = r.decide("D", listOf(nb("B", -70, 0.1), nb("C", -70, 0.9)), emergency = true)
        assertEquals("C", d.nextHop)
    }

    @Test
    fun avoidsVeryWeakLinks() {
        val r = MarlRouter("A", random = java.util.Random(1))
        val d = r.decide("D", listOf(nb("B", -92, 0.95), nb("C", -70, 0.8)), emergency = true)
        assertEquals("C", d.nextHop)
    }

    @Test
    fun carriesWhenNoBetterRelay() {
        val r = MarlRouter("A", random = java.util.Random(1))
        r.onEncounter("D", emptyMap())
        val d = r.decide("D", listOf(nb("B", -70, 0.0)), emergency = false)
        assertNull(d.nextHop)
    }

    @Test
    fun tdUpdateMovesWeightsAndFedAvgMerges() {
        val a = MarlRouter("A", random = java.util.Random(1))
        val b = MarlRouter("B", random = java.util.Random(2))
        val dec = a.decide("D", listOf(nb("C", -70, 0.5)), emergency = true)
        val before = a.w.copyOf()
        a.onHopAcked(dec.features, 60, nextValue = null)
        assertFalse(before.contentEquals(a.w))
        val wa = a.w.copyOf()
        val na = a.nSamples + 1
        val (wb, nbSamples) = b.modelUpdate()
        a.mergeModel(wb, nbSamples)
        val nb = nbSamples + 1
        for (i in a.w.indices) assertEquals((na * wa[i] + nb * wb[i]) / (na + nb), a.w[i], 1e-9)
    }

    @Test
    fun cusumQuarantinesSinkholeNotHonestNode() {
        val r = MarlRouter("A")
        var flagged = false
        repeat(8) { flagged = flagged || r.reportOutcome("SINK", forwarded = false) }
        assertTrue(flagged)
        assertTrue("SINK" in r.quarantined)
        repeat(40) { i -> r.reportOutcome("HONEST", forwarded = i % 5 != 0) }
        assertFalse("HONEST" in r.quarantined)
    }

    @Test
    fun prophetAgingAndTransitivity() {
        val r = MarlRouter("A")
        r.onEncounter("B", mapOf("C" to 0.8))
        assertTrue((r.predictability["C"] ?: 0.0) > 0.0)
        val pb = r.predictability["B"]!!
        r.age(30.0)
        assertTrue(r.predictability["B"]!! < pb)
    }
}
