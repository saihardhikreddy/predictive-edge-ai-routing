// Census accuracy check: kotlinc -cp android.jar app/src/main/kotlin/com/bitchat/android/mesh/Census.kt tools/CensusAccuracy.kt -d out && kotlin -cp out:android.jar CensusAccuracyKt
import com.bitchat.android.mesh.Census
import kotlin.random.Random
fun main() {  // CensusAccuracyKt
    val rnd = Random(7)
    println("n  mean_est  p10  p90  worst_abs_err  (200 random meshes each)")
    for (n in listOf(3, 5, 10, 20, 30, 48, 75, 100, 150, 200)) {
        val ests = (1..200).map {
            val c = Census()
            repeat(n) { c.add(Census.PEOPLE, String.format("%08X", rnd.nextInt()), 1000L) }
            c.counts(1000L).phones
        }.sorted()
        println("%-4d %6.1f  %4d %4d  %4d".format(n, ests.average(), ests[20], ests[180], ests.maxOf { kotlin.math.abs(it - n) }))
    }
    // gossip: 30 phones in a line, each only merges with neighbours, repeated contacts must not inflate
    val phones = List(30) { Census() }
    phones.forEachIndexed { i, c -> c.add(Census.PEOPLE, "P$i", 0) }
    val wire = { c: Census -> c::class.java.getDeclaredField("windows").let { f -> f.isAccessible = true; @Suppress("UNCHECKED_CAST") (f.get(c) as HashMap<Long, Array<LongArray>>) } }
    var rounds = 0
    while (phones.any { it.counts(0).phones < 25 } && rounds < 100) {
        rounds++
        for (i in 0 until 29) { val a = phones[i]; val b = phones[i + 1]; a.merge(wire(b), 0); b.merge(wire(a), 0) }
    }
    repeat(50) { for (i in 0 until 29) { phones[i].merge(wire(phones[i + 1]), 0); phones[i + 1].merge(wire(phones[i]), 0) } }
    println("chain of 30: estimates after 50 more rounds of repeated contacts = " + phones.map { it.counts(0).phones }.distinct())
    // windows: a phone that stopped re-adding itself is gone after two windows
    val c = Census(); c.add(Census.PEOPLE, "A", 0); c.add(Census.PEOPLE, "B", 0)
    c.add(Census.PEOPLE, "A", 11 * 60_000L)
    println("after 1 window: ${c.counts(11 * 60_000L).phones} (A and B), after 2: " + run { c.add(Census.PEOPLE, "A", 21 * 60_000L); c.counts(21 * 60_000L).phones } + " (only A)")
    // SOS
    val s = Census(); repeat(4) { s.add(Census.SOS, "sos$it", 0) }; repeat(3) { s.add(Census.ANSWERED, "sos$it", 0) }
    println("SOS: " + s.counts(0))
}
