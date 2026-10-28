package com.bitchat.android.mesh

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class CensusForecastTest {

    @Test
    fun census_repeatedMergesNeverDoubleCount() {
        val a = Census(); val b = Census()
        repeat(6) { a.add(Census.PEOPLE, "A$it", 0) }
        repeat(6) { b.add(Census.PEOPLE, "A$it", 0) } // the same six phones, heard another way
        b.add(Census.PEOPLE, "B", 0)
        repeat(20) { a.merge(b.decode(b.encode(0)), 0); b.merge(a.decode(a.encode(0)), 0) }
        assertEquals(7, a.counts(0).phones)
        assertEquals(7, b.counts(0).phones)
    }

    @Test
    fun census_wireRoundTripKeepsEveryBit() {
        val a = Census()
        repeat(40) { a.add(Census.PEOPLE, "P$it", 0) }
        a.add(Census.SOS, "s1", 0)
        val b = Census()
        b.merge(a.decode(a.encode(0)), 0)
        assertEquals(a.counts(0), b.counts(0))
        assertTrue(a.encode(0).toString().length < 400)
    }

    @Test
    fun forecast_learnsOutagesAndCalibrates() {
        val f = Forecast()
        repeat(20) { f.onHop(300, true) }
        val d = f.predict("x", 0.95, null, 0)
        assertEquals(Forecast.DIRECT, d.kind)
        assertTrue("direct ≈ 2 × 300 ms, got ${d.etaMs}", d.etaMs in 500..700)
        // after a few deliveries that took twice as long, the direct forecast moves towards reality
        repeat(6) { f.onResult(Forecast.DIRECT, f.predict("x", 0.95, null, 0).etaMs, 1_200) }
        assertTrue(f.predict("x", 0.95, null, 0).etaMs in 1_000..1_400)
        // outages: away 60 s, back, away 60 s ... -> carry forecast of about a minute
        var t = 0L
        repeat(5) {
            f.observe("y", true, 2, t); t += 3_000; f.observe("y", true, 2, t); t += 1_000
            f.observe("y", false, 0, t); t += 30_000
            f.observe("y", true, 2, t); t += 1_000; f.observe("y", false, 0, t) // a 1 s flicker: same outage
            t += 29_000
        }
        f.observe("y", true, 2, t); t += 3_000; f.observe("y", true, 2, t); t += 1_000; f.observe("y", false, 0, t)
        val c = f.predict("y", null, null, t)
        assertEquals(Forecast.CARRY, c.kind)
        assertTrue("mean outage ≈ 60 s, got ${c.meanOutageMs}", c.meanOutageMs in 55_000..65_000)
        assertTrue(c.p > 0.99) // 10 minutes is ten mean outages
        assertEquals(Forecast.NONE, f.predict("never-seen", null, null, t).kind)
    }
}
