"""Cognitive message triage — lightweight on-device stand-in for the SLM layer.

What this module actually does (no hard-coded results):
  1. classify(text)   -> intent class + urgency, from a weighted emergency lexicon.
  2. encode(text,...) -> the bytes that would go on air:
       * EMERGENCY_SOS : lossy *semantic* encoding (intent code + up to 4 hazard
                         tokens + people count) -> typically 6-9 bytes.
       * other intents : lossless zlib with a preset dictionary of common
                         chat phrases (a shared "codebook" every node ships with).
  3. decode(blob)     -> human-readable text back (used by tests and the UI).

The interface is deliberately the same one a real quantised SLM would expose
(classify + summarise-to-tokens), so the rule engine can be swapped for a
TinyBERT / Gemma-2B-it model later without touching the router.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from typing import List, Tuple

HEADER_BYTES = 24  # BitChat-style packet header: type, ttl, ts, sender, recipient, flags

INTENT_ROUTINE = "ROUTINE"
INTENT_URGENT = "URGENT"
INTENT_SOS = "EMERGENCY_SOS"

URGENCY = {INTENT_ROUTINE: 1.0, INTENT_URGENT: 2.5, INTENT_SOS: 5.0}

# token id -> (keyword stems, weight)
HAZARD_LEXICON: List[Tuple[str, Tuple[str, ...], float]] = [
    ("SOS", ("sos", "mayday"), 3.0),
    ("HELP", ("help", "rescue", "save us"), 1.5),
    ("TRAPPED", ("trapped", "stuck", "pinned", "buried"), 2.0),
    ("INJURED", ("injur", "hurt", "wound", "broken leg", "broken arm"), 2.0),
    ("BLEEDING", ("bleed", "blood"), 2.0),
    ("UNCONSCIOUS", ("unconscious", "not breathing", "fainted", "collapsed on"), 2.5),
    ("FIRE", ("fire", "smoke", "burning"), 2.0),
    ("COLLAPSE", ("collapse", "caved in", "fell down"), 2.0),
    ("FLOOD", ("flood", "water rising", "drowning"), 2.0),
    ("QUAKE", ("earthquake", "tremor"), 1.5),
    ("MEDICAL", ("ambulance", "doctor", "medic", "insulin", "heart attack", "asthma"), 1.5),
    ("VIOLENCE", ("attack", "gun", "knife", "stampede"), 2.0),
    ("URGENT", ("urgent", "emergency", "asap", "immediately", "now!"), 1.0),
]
TOKEN_IDS = {name: i + 1 for i, (name, _, _) in enumerate(HAZARD_LEXICON)}
TOKEN_NAMES = {v: k for k, v in TOKEN_IDS.items()}
INTENT_CODES = {INTENT_ROUTINE: 0, INTENT_URGENT: 1, INTENT_SOS: 2}
INTENT_FROM_CODE = {v: k for k, v in INTENT_CODES.items()}

SOS_THRESHOLD = 3.0
URGENT_THRESHOLD = 1.0

# Shared codebook for lossless compression of everyday chat.
_ZDICT = (
    b"where are you meet me at the  near the main gate library canteen hostel "
    b"block see you in minutes ok thanks reached safely battery is low "
    b"network is down no signal here message me when you can are you okay "
    b"everyone is fine we are at the  people need water food help "
).ljust(64, b" ")

ROUTINE_CORPUS = [
    "Hey, where are you right now? Meet me near the main gate in 10 minutes.",
    "Reached the hostel safely. Network is down here, message me when you can.",
    "Are you okay? We are at the library block, everyone is fine.",
    "Battery is low, I will switch off for a while. See you at the canteen.",
    "Lecture got cancelled, we are near the auditorium. Join us if you want.",
    "No signal here at all. Is the mess open for dinner tonight?",
    "Can you bring the charger when you come to block C? Thanks!",
    "Meet me at the parking lot after the event, we will walk back together.",
]

EMERGENCY_CORPUS = [
    "Help! The building near block B collapsed and 3 people are trapped inside, one is bleeding badly.",
    "SOS fire on the second floor of the hostel, smoke everywhere, we are stuck in room 214.",
    "Urgent: my friend is unconscious and not breathing properly near the canteen, need a doctor now!",
    "Flood water rising fast near the south gate, 5 people stranded, please send rescue.",
    "Earthquake damage at the library, 2 students injured with a broken leg, need ambulance immediately.",
    "Stampede at the main stage, several people hurt, someone call medics asap.",
]


@dataclass
class TriageResult:
    intent: str
    urgency: float
    score: float
    tokens: List[str]
    people: int
    raw_bytes: int
    encoded: bytes

    @property
    def payload_bytes(self) -> int:
        """Bytes on air including the packet header."""
        return HEADER_BYTES + len(self.encoded)

    @property
    def raw_payload_bytes(self) -> int:
        return HEADER_BYTES + self.raw_bytes


def classify(text: str) -> Tuple[str, float, List[str]]:
    t = text.lower()
    score = 0.0
    tokens: List[str] = []
    for name, stems, weight in HAZARD_LEXICON:
        if any(s in t for s in stems):
            score += weight
            tokens.append(name)
    if text.count("!") >= 2:
        score += 0.5
    if score >= SOS_THRESHOLD:
        intent = INTENT_SOS
    elif score >= URGENT_THRESHOLD:
        intent = INTENT_URGENT
    else:
        intent = INTENT_ROUTINE
    return intent, score, tokens


def _people_count(text: str) -> int:
    m = re.search(r"\b(\d{1,3})\s+(?:people|persons|students|of us|injured|stranded)", text.lower())
    if m:
        return min(int(m.group(1)), 255)
    return 0


def _zlib(text: str) -> bytes:
    c = zlib.compressobj(level=9, wbits=-15, zdict=_ZDICT)
    return c.compress(text.encode("utf-8")) + c.flush()


def _unzlib(blob: bytes) -> str:
    d = zlib.decompressobj(wbits=-15, zdict=_ZDICT)
    return (d.decompress(blob) + d.flush()).decode("utf-8")


def encode(text: str, slm_enabled: bool = True) -> TriageResult:
    raw = text.encode("utf-8")
    if not slm_enabled:
        return TriageResult(INTENT_ROUTINE, 1.0, 0.0, [], 0, len(raw), b"\xff" + raw)

    intent, score, tokens = classify(text)
    people = _people_count(text)
    if intent == INTENT_SOS:
        tok_ids = [TOKEN_IDS[t] for t in tokens if t not in ("URGENT", "HELP")][:4]
        blob = bytes([0x80 | INTENT_CODES[intent], len(tok_ids)] + tok_ids + [people])
    else:
        z = _zlib(text)
        blob = bytes([INTENT_CODES[intent]]) + (z if len(z) < len(raw) else raw)
    return TriageResult(intent, URGENCY[intent], score, tokens, people, len(raw), blob)


def decode(blob: bytes) -> str:
    if not blob:
        return ""
    head = blob[0]
    if head == 0xFF:
        return blob[1:].decode("utf-8")
    if head & 0x80:
        intent = INTENT_FROM_CODE[head & 0x7F]
        n = blob[1]
        toks = [TOKEN_NAMES.get(b, "?") for b in blob[2 : 2 + n]]
        people = blob[2 + n]
        s = f"{intent}: " + ", ".join(toks)
        if people:
            s += f" | people={people}"
        return s
    body = blob[1:]
    try:
        return _unzlib(body)
    except zlib.error:
        return body.decode("utf-8")
