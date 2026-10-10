package com.bitchat.android.mesh

import android.content.Context
import android.os.Looper
import android.os.SystemClock
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.time.Duration

/**
 * End-to-end scenarios: several virtual phones, each running the real [MeshEngine],
 * talking over [VirtualAir]. Positions are in metres; radio range is 12 m.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class MeshScenarioTest {

    private lateinit var ctx: Context
    private lateinit var air: VirtualAir
    private val phones = LinkedHashMap<String, MeshEngine>()

    @Before
    fun setUp() {
        ctx = ApplicationProvider.getApplicationContext()
        air = VirtualAir()
        air.startBeacons()
        phones.clear()
    }

    // ------------------------------------------------------------ helpers

    private fun phone(name: String, x: Double, y: Double = 0.0, mode: String = Protocol.MODE_MARL): MeshEngine {
        val e = MeshEngine(ctx, Looper.getMainLooper(), { SystemClock.uptimeMillis() }, { 80 }, air.factory(name), "mesh_$name")
        air.radio(name).apply { this.x = x; this.y = y }
        e.setNick(name)
        e.setMode(mode)
        e.start()
        phones[name] = e
        return e
    }

    private fun run(seconds: Double) = shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis((seconds * 1000).toLong()))
    private fun id(name: String) = phones.getValue(name).myId
    private fun st(name: String) = phones.getValue(name).state.value
    private fun sent(from: String, to: String) = st(from).messages.filter { it.outgoing && it.peer == id(to) }
    private fun lastSent(from: String, to: String) = sent(from, to).last()
    private fun move(name: String, x: Double, y: Double = 0.0) = air.radio(name).apply { this.x = x; this.y = y }

    private fun sendAndWait(from: String, to: String, text: String = "Meet me at the main gate", wait: Double = 20.0): ChatMsg {
        phones.getValue(from).send(id(to), text)
        run(wait)
        return lastSent(from, to)
    }

    private fun describe(m: ChatMsg) = "status=${m.status} hops=${m.hops} rtt=${m.rttMs}ms"

    // ------------------------------------------------------- same room

    @Test
    fun sameRoom_learnedRouting_deliversInOneHop() {
        phone("A", 0.0); phone("B", 2.0); phone("C", 1.0, 2.0)
        run(10.0)
        val m = sendAndWait("A", "C")
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(describe(m), 1, m.hops)
    }

    @Test
    fun sameRoom_flooding_deliversInOneHop() {
        phone("A", 0.0, mode = Protocol.MODE_FLOOD); phone("B", 2.0, mode = Protocol.MODE_FLOOD); phone("C", 1.0, 2.0, Protocol.MODE_FLOOD)
        run(10.0)
        repeat(5) { i ->
            val m = sendAndWait("A", "C", "flood test $i", 10.0)
            assertEquals("message $i: ${describe(m)}", "delivered", m.status)
            assertEquals("message $i: ${describe(m)}", 1, m.hops)
        }
    }

    @Test
    fun sameRoom_sos_deliversInOneHop() {
        phone("A", 0.0); phone("B", 2.0); phone("C", 1.0, 2.0)
        run(10.0)
        val m = sendAndWait("A", "C", "SOS fire on the second floor, we are trapped!")
        assertEquals(Triage.SOS, m.intent)
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(describe(m), 1, m.hops)
    }

    @Test
    fun sameRoom_advertGaps_stillOneHop() {
        phone("A", 0.0); phone("B", 2.0); phone("C", 1.0, 2.0)
        run(10.0)
        // C's advertiser goes quiet for 9 s, as real phones do
        air.radio("C").advertGapUntil = SystemClock.uptimeMillis() + 9_000
        run(7.0)
        val m = sendAndWait("A", "C")
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(describe(m), 1, m.hops)
    }

    @Test
    fun sameRoom_manyMessages_allDirect() {
        phone("A", 0.0); phone("B", 2.0); phone("C", 1.0, 2.0)
        run(10.0)
        repeat(10) { i -> phones.getValue("A").send(id("C"), "message $i"); run(3.0) }
        run(15.0)
        val ms = sent("A", "C")
        assertEquals(10, ms.size)
        assertTrue(ms.joinToString { describe(it) }, ms.all { it.status == "delivered" && it.hops == 1 })
    }

    // ------------------------------------------------------- forcing multi-hop

    @Test
    fun block_forcesRelay() {
        phone("A", 0.0); phone("B", 2.0); phone("C", 1.0, 2.0)
        run(10.0)
        phones.getValue("A").toggleBlock(id("C"))
        run(2.0)
        val m = sendAndWait("A", "C")
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(describe(m), 2, m.hops)
    }

    @Test
    fun rangeLimit_forcesRelay() {
        // A–B 4 m (about -68 dBm), A–C 8 m (about -82 dBm)
        phone("A", 0.0); phone("B", 4.0); phone("C", 8.0)
        run(10.0)
        phones.getValue("A").setRange(-75)
        run(2.0)
        val m = sendAndWait("A", "C")
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(describe(m), 2, m.hops)
    }

    // ------------------------------------------------------- out of range

    @Test
    fun chain_farPhoneAppearsByNameWithHopCount() {
        phone("A", 0.0); phone("B", 10.0); phone("Cara", 20.0)
        run(40.0)
        val k = st("A").known.firstOrNull { it.id == id("Cara") }
        assertTrue("A should know Cara: ${st("A").known}", k != null)
        assertEquals("Cara", k!!.name)
        assertFalse(k.present)
        assertEquals(2, k.hops)
    }

    @Test
    fun chain_learnedRouting_deliversInTwoHops() {
        phone("A", 0.0); phone("B", 10.0); phone("C", 20.0)
        run(40.0)
        val m = sendAndWait("A", "C", wait = 30.0)
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(describe(m), 2, m.hops)
    }

    @Test
    fun chain_flooding_deliversInTwoHops() {
        phone("A", 0.0, mode = Protocol.MODE_FLOOD); phone("B", 10.0, mode = Protocol.MODE_FLOOD); phone("C", 20.0, mode = Protocol.MODE_FLOOD)
        run(40.0)
        val m = sendAndWait("A", "C", wait = 30.0)
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(describe(m), 2, m.hops)
    }

    @Test
    fun chainOfFour_deliversInThreeHops() {
        phone("A", 0.0); phone("B", 10.0); phone("C", 20.0); phone("D", 30.0)
        run(60.0)
        assertEquals(3, st("A").known.first { it.id == id("D") }.hops)
        val m = sendAndWait("A", "D", wait = 40.0)
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(describe(m), 3, m.hops)
    }

    @Test
    fun storeCarryForward_deliversWhenRelayReturns() {
        phone("A", 0.0); phone("B", 10.0); phone("C", 20.0)
        run(40.0)
        move("B", 100.0) // relay walks away: A and C are cut off from each other
        run(15.0)
        phones.getValue("A").send(id("C"), "Are you okay?")
        run(20.0)
        assertEquals("not deliverable while cut off", "sent", lastSent("A", "C").status)
        move("B", 10.0) // relay comes back
        run(40.0)
        val m = lastSent("A", "C")
        assertEquals(describe(m), "delivered", m.status)
    }

    // ------------------------------------------------------- names

    @Test
    fun name_isRememberedAfterRestart() {
        val first = MeshEngine(ctx, Looper.getMainLooper(), { SystemClock.uptimeMillis() }, { 80 }, air.factory("P"), "mesh_restart")
        assertFalse("a fresh install must ask for a name", first.state.value.nickSet)
        first.setNick("Hardhik")
        run(1.0)
        // the app is closed and opened again: a new engine on the same storage
        val second = MeshEngine(ctx, Looper.getMainLooper(), { SystemClock.uptimeMillis() }, { 80 }, air.factory("P2"), "mesh_restart")
        assertTrue("the very first state after restart must already know the name", second.state.value.nickSet)
        assertEquals("Hardhik", second.state.value.nick)
    }

    @Test
    fun name_changeReachesFarPhones() {
        phone("A", 0.0); phone("B", 10.0); phone("C", 20.0)
        run(40.0)
        phones.getValue("C").setNick("Priya")
        run(10.0)
        assertEquals("Priya", st("A").known.first { it.id == id("C") }.name)
    }

    @Test
    fun receivedMessage_showsSenderName() {
        phone("A", 0.0); phone("B", 10.0); phone("Charan", 20.0)
        run(40.0)
        sendAndWait("Charan", "A", "hello from the far side", 30.0)
        val inbox = st("A").messages.filter { !it.outgoing }
        assertEquals(1, inbox.size)
        assertEquals("Charan", inbox[0].peerName)
    }

    // ------------------------------------------------------- attack

    @Test
    fun sinkhole_isQuarantinedAndTrafficReroutes() {
        // two disjoint relays between A and C: B (attacker) and D (honest)
        phone("A", 0.0); phone("B", 10.0, 4.0); phone("D", 10.0, -4.0); phone("C", 20.0)
        run(40.0)
        phones.getValue("B").setSinkhole(true)
        run(2.0)
        repeat(16) { i -> phones.getValue("A").send(id("C"), "message $i"); run(4.0) }
        run(90.0)
        val ms = sent("A", "C")
        val delivered = ms.count { it.status == "delivered" }
        val bQuarantined = st("A").neighbors.first { it.id == id("B") }.quarantined
        println("sinkhole scenario: delivered $delivered/${ms.size}, B quarantined by A = $bQuarantined")
        assertTrue("A should cut the attacker out (delivered $delivered/16)", bQuarantined)
        // once B is cut out, later messages go through D
        assertTrue("the last messages should get through D: ${ms.takeLast(4).joinToString { describe(it) }}",
            ms.takeLast(4).all { it.status == "delivered" })
    }

    @Test
    fun honestRelays_areNotQuarantined() {
        phone("A", 0.0); phone("B", 10.0); phone("C", 20.0)
        run(40.0)
        repeat(12) { i -> phones.getValue("A").send(id("C"), "message $i"); run(4.0) }
        run(60.0)
        assertFalse(st("A").neighbors.first { it.id == id("B") }.quarantined)
        assertTrue(sent("A", "C").all { it.status == "delivered" })
    }
}
