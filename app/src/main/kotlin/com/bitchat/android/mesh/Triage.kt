package com.bitchat.android.mesh

/** Kotlin port of simulation/triage.py: emergency classifier + semantic SOS encoding. */
object Triage {
    const val ROUTINE = "ROUTINE"
    const val URGENT = "URGENT"
    const val SOS = "EMERGENCY_SOS"

    private val lexicon: List<Triple<String, List<String>, Double>> = listOf(
        Triple("SOS", listOf("sos", "mayday"), 3.0),
        Triple("HELP", listOf("help", "rescue", "save us"), 1.5),
        Triple("TRAPPED", listOf("trapped", "stuck", "pinned", "buried"), 2.0),
        Triple("INJURED", listOf("injur", "hurt", "wound", "broken leg", "broken arm"), 2.0),
        Triple("BLEEDING", listOf("bleed", "blood"), 2.0),
        Triple("UNCONSCIOUS", listOf("unconscious", "not breathing", "fainted"), 2.5),
        Triple("FIRE", listOf("fire", "smoke", "burning"), 2.0),
        Triple("COLLAPSE", listOf("collapse", "caved in"), 2.0),
        Triple("FLOOD", listOf("flood", "water rising", "drowning"), 2.0),
        Triple("QUAKE", listOf("earthquake", "tremor"), 1.5),
        Triple("MEDICAL", listOf("ambulance", "doctor", "medic", "insulin", "heart attack", "asthma"), 1.5),
        Triple("VIOLENCE", listOf("attack", "gun", "knife", "stampede"), 2.0),
        Triple("URGENT", listOf("urgent", "emergency", "asap", "immediately"), 1.0),
    )

    data class Result(val intent: String, val urgency: Double, val wireText: String, val rawBytes: Int, val wireBytes: Int)

    fun process(text: String, enabled: Boolean = true): Result {
        val raw = text.toByteArray(Charsets.UTF_8).size
        if (!enabled) return Result(ROUTINE, 1.0, text, raw, raw)
        val t = text.lowercase()
        var score = 0.0
        val tokens = ArrayList<String>()
        for ((name, stems, w) in lexicon) {
            if (stems.any { t.contains(it) }) {
                score += w
                tokens += name
            }
        }
        if (text.count { it == '!' } >= 2) score += 0.5
        val intent = when {
            score >= 3.0 -> SOS
            score >= 1.0 -> URGENT
            else -> ROUTINE
        }
        if (intent != SOS) {
            return Result(intent, if (intent == URGENT) 2.5 else 1.0, text, raw, raw)
        }
        val people = Regex("""\b(\d{1,3})\s+(people|persons|students|of us|injured|stranded)""").find(t)?.groupValues?.get(1)
        val core = tokens.filter { it != "URGENT" && it != "HELP" }.take(4)
        val wire = "SOS[" + core.joinToString(",") + "]" + (people?.let { "p$it" } ?: "")
        return Result(SOS, 5.0, wire, raw, wire.toByteArray().size)
    }

    val ROUTINE_CORPUS = listOf(
        "Hey, where are you right now? Meet me near the main gate in 10 minutes.",
        "Reached the hostel safely. Network is down here, message me when you can.",
        "Are you okay? We are at the library block, everyone is fine.",
        "Battery is low, I will switch off for a while. See you at the canteen.",
        "No signal here at all. Is the mess open for dinner tonight?",
        "Can you bring the charger when you come to block C? Thanks!",
    )

    val EMERGENCY_CORPUS = listOf(
        "Help! The building near block B collapsed and 3 people are trapped inside, one is bleeding.",
        "SOS fire on the second floor of the hostel, smoke everywhere, we are stuck in room 214.",
        "Urgent: my friend is unconscious near the canteen, need a doctor now!",
        "Flood water rising fast near the south gate, 5 people stranded, please send rescue.",
    )
}
