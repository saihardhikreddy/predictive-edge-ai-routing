import unittest

from simulation import triage


class TriageEdgeCaseTests(unittest.TestCase):
    """Routine messages must survive encode/decode unchanged, whatever they contain."""

    CASES = [
        "",
        "hello",
        "नमस्ते, see you at 5 🙂",
        "x" * 500,
        "line one\nline two\ttabbed",
    ]

    def test_routine_roundtrip(self):
        for text in self.CASES:
            with self.subTest(text=text[:20]):
                r = triage.encode(text)
                self.assertNotEqual(r.intent, triage.INTENT_SOS)
                self.assertEqual(triage.decode(r.encoded), text)

    def test_roundtrip_with_slm_disabled(self):
        for text in self.CASES + list(triage.EMERGENCY_CORPUS[:3]):
            with self.subTest(text=text[:20]):
                r = triage.encode(text, slm_enabled=False)
                self.assertEqual(triage.decode(r.encoded), text)

    def test_repetitive_text_is_compressed(self):
        text = "meet at the library " * 20
        r = triage.encode(text)
        self.assertLess(len(r.encoded), len(text.encode("utf-8")))

    def test_people_count_is_capped_at_one_byte(self):
        self.assertEqual(triage._people_count("999 people stranded near gate"), 255)

    def test_empty_blob_decodes_to_empty_string(self):
        self.assertEqual(triage.decode(b""), "")


if __name__ == "__main__":
    unittest.main()
