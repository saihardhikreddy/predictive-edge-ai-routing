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

    private fun phone(name: String, x: Double, y: Double = 0.0, mode: String = Protocol.MODE_MARL, longRange: Boolean = false): MeshEngine {
        val e = MeshEngine(ctx, Looper.getMainLooper(), { SystemClock.uptimeMillis() }, { 80 }, air.factory(name), "mesh_$name")
        air.radio(name).apply { this.x = x; this.y = y; coded = longRange }
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
    fun friendsNames_areRememberedAfterRestart() {
        val a = MeshEngine(ctx, Looper.getMainLooper(), { SystemClock.uptimeMillis() }, { 80 }, air.factory("A"), "mesh_friends")
        air.radio("A").x = 0.0
        a.setNick("Hardhik"); a.start()
        phone("Priya", 3.0)
        run(40.0)
        val priya = id("Priya")
        assertEquals("Priya", a.state.value.known.first { it.id == priya }.name)
        a.stop()
        // reopen: Priya is not around yet, but her name is already known
        val again = MeshEngine(ctx, Looper.getMainLooper(), { SystemClock.uptimeMillis() }, { 80 }, air.factory("A2"), "mesh_friends")
        assertEquals("Priya", again.nameOf(priya))
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

    // ------------------------------------------------------- survivor census

    @Test
    fun census_countsTheWholeChain_eachPhoneHearsOnlyItsNeighbours() {
        phone("A", 0.0); phone("B", 10.0); phone("C", 20.0); phone("D", 30.0); phone("E", 40.0)
        run(90.0)
        val c = st("A").census
        println("census scenario: A hears ${c.direct} phone directly and estimates ${c.phones} phones in the mesh (truth: 5)")
        assertEquals(1, c.direct)
        assertEquals(5, c.phones)
        assertEquals(5, st("E").census.phones)
    }

    @Test
    fun census_talliesSosCallsAndWhichWereAnswered() {
        phone("A", 0.0); phone("B", 10.0); phone("C", 20.0)
        run(40.0)
        phones.getValue("C").send(id("A"), "SOS fire on the second floor, we are trapped!")
        phones.getValue("B").send("DEADBEEF", "SOS injured people need medical help") // nobody has this id: never answered
        run(60.0)
        val c = st("A").census
        println("census scenario: A counts ${c.sos} SOS calls, ${c.answered} answered, ${c.unanswered} waiting")
        assertEquals(2, c.sos)
        assertEquals(1, c.answered)
        assertEquals(1, st("C").census.unanswered)
    }

    // ------------------------------------------------------- delivery forecast

    private fun forecastReport(label: String, ms: List<ChatMsg>): Double {
        val done = ms.filter { it.status == "delivered" && it.fcMs > 0 }
        val good = done.count { kotlin.math.abs(it.rttMs - it.fcMs) <= maxOf(1_000L, it.fcMs / 2) }
        val errs = done.map { kotlin.math.abs(it.rttMs - it.fcMs) * 100.0 / it.fcMs }.sorted()
        println("forecast scenario ($label): ${done.size} delivered, $good within ±50 % (or 1 s) of the forecast, median error ${errs.getOrNull(errs.size / 2)?.toInt()} %, " +
            done.joinToString(prefix = "[", postfix = "]") { "${it.fcMs}->${it.rttMs}" })
        return if (done.isEmpty()) 0.0 else good.toDouble() / done.size
    }

    @Test
    fun forecast_direct_and_routed_matchMeasuredTimes() {
        phone("A", 0.0); phone("B", 2.0); phone("C", 1.0, 2.0)
        phone("X", 40.0); phone("Y", 50.0); phone("Z", 60.0) // a separate chain X–Y–Z
        run(45.0)
        repeat(8) { i -> phones.getValue("A").send(id("C"), "same room $i"); run(4.0) }
        repeat(8) { i -> phones.getValue("X").send(id("Z"), "two hops $i"); run(6.0) }
        run(15.0)
        val direct = sent("A", "C")
        val routed = sent("X", "Z")
        assertTrue(direct.all { it.fcKind == Forecast.DIRECT })
        assertTrue(routed.all { it.fcKind == Forecast.ROUTED })
        val d = forecastReport("direct", direct.drop(2))
        val r = forecastReport("2 hops", routed.drop(2))
        assertTrue("direct forecasts should mostly hold", d >= 0.6)
        assertTrue("routed forecasts should mostly hold", r >= 0.6)
    }

    @Test
    fun forecast_learnsHowLongAFriendIsOutOfReach() {
        // C is only reachable through B, who keeps walking away for ~40 s and back for ~20 s
        phone("A", 0.0); phone("B", 10.0); phone("C", 20.0)
        run(40.0)
        repeat(4) { move("B", 100.0); run(40.0); move("B", 10.0); run(20.0) }
        move("B", 100.0)
        run(16.0) // the route has expired: A has no path to C
        val k = st("A").known.first { it.id == id("C") }
        println("forecast scenario (carry): A predicts ${k.fcMs} ms, ${(k.fcP * 100).toInt()} % within 10 min, learned outage ${k.fcOutageMs} ms")
        assertEquals(Forecast.CARRY, k.fcKind)
        phones.getValue("A").send(id("C"), "are you okay?")
        run(24.0)
        move("B", 10.0)
        run(40.0)
        val m = lastSent("A", "C")
        println("forecast scenario (carry): predicted ${m.fcMs} ms, took ${m.rttMs} ms")
        assertEquals("delivered", m.status)
        assertTrue("outage learned (${k.fcOutageMs} ms)", k.fcOutageMs in 25_000..70_000)
        // the forecast treats the wait as memoryless, so on a strict walking timetable it can be off;
        // it must still be the right order of magnitude
        assertTrue("carry forecast within a factor of 3", m.rttMs in m.fcMs / 3..m.fcMs * 3)
    }

    // ------------------------------------------------------- Bluetooth 5 Long Range

    @Test
    fun longRange_reachesAPhoneBeyondNormalRange_inOneHop() {
        // 16 m apart: beyond normal BLE range here (12 m), inside Long Range
        phone("A", 0.0, longRange = true); phone("C", 16.0, longRange = true)
        run(20.0)
        val n = st("A").neighbors.firstOrNull { it.id == id("C") }
        assertTrue("A should hear C over Long Range: ${st("A").neighbors}", n != null && n.present && n.longRange)
        val m = sendAndWait("A", "C", wait = 20.0)
        println("long range scenario: 16 m apart, ${describe(m)}, link ${(n!!.linkQ * 100).toInt()} %")
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(1, m.hops)
    }

    @Test
    fun withoutLongRange_theSamePhonesCannotTalk() {
        phone("A", 0.0); phone("C", 16.0)
        run(20.0)
        phones.getValue("A").send(id("C"), "hello?")
        run(30.0)
        println("long range scenario (off): 16 m apart, A hears ${st("A").neighbors.count { it.present }} phones, message ${lastSent("A", "C").status}")
        assertTrue(st("A").neighbors.none { it.present })
        assertEquals("sent", lastSent("A", "C").status)
    }

    @Test
    fun longRange_joinsAMeshThatIsSplitWithoutIt() {
        // 16 m spacing: three islands with normal BLE, one mesh with Long Range
        phone("A", 0.0, longRange = true); phone("B", 16.0, longRange = true); phone("C", 32.0, longRange = true)
        run(60.0)
        val m = sendAndWait("A", "C", wait = 40.0)
        println("long range scenario: split mesh joined, ${describe(m)}")
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(2, m.hops)
    }

    @Test
    fun longRange_cutsHopsInAChain() {
        // 8 m spacing, 32 m end to end: 4 hops with normal BLE (see the next test)
        for ((i, n) in listOf("A", "B", "C", "D", "E").withIndex()) phone(n, i * 8.0, longRange = true)
        run(70.0)
        val m = sendAndWait("A", "E", wait = 40.0)
        println("long range scenario: 5-phone chain, 32 m, ${describe(m)} (normal BLE needs 4 hops)")
        assertEquals(describe(m), "delivered", m.status)
        assertTrue("Long Range should skip phones: ${describe(m)}", m.hops <= 3)
    }

    @Test
    fun withoutLongRange_theChainNeedsFourHops() {
        for ((i, n) in listOf("A", "B", "C", "D", "E").withIndex()) phone(n, i * 8.0)
        run(70.0)
        val m = sendAndWait("A", "E", wait = 40.0)
        println("long range scenario (off): 5-phone chain, 32 m, ${describe(m)}")
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(4, m.hops)
    }

    @Test
    fun longRange_oldPhonesStillWorkOnNormalBluetooth() {
        // A supports Long Range, B is an older phone that does not
        phone("A", 0.0, longRange = true); phone("B", 6.0)
        run(15.0)
        val m = sendAndWait("A", "B")
        assertEquals(describe(m), "delivered", m.status)
        assertEquals(1, m.hops)
        assertFalse(st("A").neighbors.first { it.id == id("B") }.longRange)
    }

    // ------------------------------------------------------- link prediction

    @Test
    fun linkPrediction_flagsTheNeighbourWhoIsWalkingAway() {
        // B stays put next to A; C keeps walking out of range and back at 1 m/s
        phone("A", 0.0); phone("B", 4.0); phone("C", 4.0)
        run(10.0)
        repeat(8) {
            // walk away to 25 m: out of range past 12 m, and dropped once 12 s pass without an advert
            for (d in 4..25) { move("C", d.toDouble()); run(1.0) }
            for (d in 25 downTo 4) { move("C", d.toDouble()); run(1.0) } // and back
        }
        for (d in 4..9) { move("C", d.toDouble()); run(1.0) }       // walking away again, still in range
        val last = st("A")
        val b = last.neighbors.first { it.id == id("B") }
        val c = last.neighbors.first { it.id == id("C") }
        println("link prediction scenario: B (standing) stays ${(b.stay * 100).toInt()} %, C (walking away, ${"%.1f".format(c.trendDbPerS)} dB/s) stays ${(c.stay * 100).toInt()} %; " +
            "checked ${last.linkScore.n} predictions, ${last.linkScore.caught}/${last.linkScore.breaks} breaks flagged, Brier ${"%.3f".format(last.linkScore.brier)}")
        assertTrue("C is getting weaker", c.trendDbPerS < -0.5)
        assertTrue("walking-away neighbour must look less likely to stay: B=${b.stay} C=${c.stay}", c.stay < b.stay)
        assertTrue(last.linkScore.breaks > 0)
    }

    // ------------------------------------------------------- attack

    @Test
    fun sinkhole_isQuarantinedAndTrafficReroutes() {
        // two disjoint relays between A and C: B (attacker) and D (honest)
        phone("A", 0.0); phone("B", 10.0, 4.0); phone("D", 10.0, -4.0); phone("C", 20.0)
        run(40.0)
        phones.getValue("B").setSinkhole(true)
        run(2.0)
        val t0 = SystemClock.uptimeMillis()
        // phase 1: the attack. B lies that it is next to everyone and swallows what it gets
        // keep the attack going until A cuts B out (or 30 messages); how many it takes depends on
        // how often the router happens to pick B, which is random exploration
        fun bQ() = st("A").neighbors.first { it.id == id("B") }.quarantined
        var i = 0
        while (i < 30 && !bQ()) { phones.getValue("A").send(id("C"), "attack phase $i"); run(4.0); i++ }
        run(30.0)
        val phase1 = sent("A", "C")
        val bQuarantined = bQ()
        val lost = phase1.count { it.status != "delivered" }
        println("sinkhole scenario: attack phase delivered ${phase1.size - lost}/${phase1.size}, B quarantined by A = $bQuarantined after <= ${(SystemClock.uptimeMillis() - t0) / 1000}s")
        assertTrue("A should cut the attacker out", bQuarantined)
        // phase 2: after the quarantine, everything goes through the honest relay D
        repeat(6) { i -> phones.getValue("A").send(id("C"), "after quarantine $i"); run(3.0) }
        run(25.0)
        val phase2 = sent("A", "C").drop(phase1.size)
        println("sinkhole scenario: after quarantine delivered ${phase2.count { it.status == "delivered" }}/${phase2.size}")
        assertTrue("after the quarantine messages should get through D: ${phase2.joinToString { describe(it) }}",
            phase2.all { it.status == "delivered" && it.hops == 2 })
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
