import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import analyze_field_logs as afl  # noqa: E402

HEADER = "ts_ms,node,event,mode,msg,src,dst,peer,rssi,hops,bytes,value,battery\n"


class AnalyzeFieldLogsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, name, body):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(HEADER + body)
        return path

    def test_load_dedupes_rows_exported_twice(self):
        row = "1000,A,SEND,MARL,m1,A,B,,,,,,90\n"
        self._write("a.csv", row)
        self._write("a_copy.csv", row)
        rows = afl.load([self.tmp.name])
        self.assertEqual(len(rows), 1)

    def test_load_skips_bad_timestamps_and_sorts(self):
        p = self._write("b.csv", "2000,B,RECV,MARL,m1,A,B,,,,,,80\nnot-a-number,B,X,,,,,,,,,,\n1000,A,SEND,MARL,m1,A,B,,,,,,90\n")
        rows = afl.load([p])
        self.assertEqual([r["ts"] for r in rows], [1000, 2000])

    def test_missing_columns_become_empty_strings(self):
        p = self._write("c.csv", "1000,A,SEND,,,,,,,,,,\n")
        r = afl.load([p])[0]
        self.assertEqual(r["peer"], "")
        self.assertEqual(r["battery"], "")

    def test_parse_time(self):
        self.assertIsNone(afl.parse_time(None))
        self.assertIsNone(afl.parse_time(""))
        self.assertIsInstance(afl.parse_time("2026-10-10T14:00"), int)

    def test_fmt(self):
        self.assertEqual(afl.fmt([]), "–")
        self.assertEqual(afl.fmt([None, None]), "–")
        self.assertEqual(afl.fmt([2.0, 4.0], " ms"), "3.0 ms")
        self.assertEqual(afl.fmt([1.0, 2.0, 9.0]), "4.0 (median 2.0)")


if __name__ == "__main__":
    unittest.main()
