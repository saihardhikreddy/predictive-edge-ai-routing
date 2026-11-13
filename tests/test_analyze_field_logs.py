import os
import sys
import tempfile
import unittest
import unittest.mock

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

    def test_log_resaved_by_excel_with_a_byte_order_mark_still_loads(self):
        path = os.path.join(self.tmp.name, "excel.csv")
        with open(path, "w", encoding="utf-8-sig") as fh:  # writes the BOM first
            fh.write(HEADER + "1000,A,SEND,MARL,m1,A,B,,,,,,90\n")
        rows = afl.load([path])
        self.assertEqual([r["ts"] for r in rows], [1000])

    def test_a_file_with_no_usable_rows_is_reported(self):
        path = os.path.join(self.tmp.name, "other.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("time,who\n1,A\n")
        with unittest.mock.patch("sys.stderr") as err:
            self.assertEqual(afl.load([path]), [])
        self.assertIn("no usable rows", "".join(c.args[0] for c in err.write.call_args_list))

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

    def test_quarantine_is_timed_from_the_attack_it_followed(self):
        p = self._write("d.csv", "".join([
            "1000,S,SINKHOLE_MODE,,,,,,,,,true,\n",
            "5000,S,SINKHOLE_MODE,,,,,,,,,false,\n",
            "9000,S,SINKHOLE_MODE,,,,,,,,,true,\n",
        ]))
        starts = afl.sinkhole_starts(afl.load([p]))
        self.assertEqual(starts, {"S": [1000, 9000]})
        self.assertEqual(afl.attack_age_s(starts, "S", 3000), 2.0)   # during the first attack
        self.assertEqual(afl.attack_age_s(starts, "S", 12000), 3.0)  # during the second
        self.assertIsNone(afl.attack_age_s(starts, "S", 500))        # before any attack
        self.assertIsNone(afl.attack_age_s(starts, "B", 12000))      # never attacked

    def test_summary_flags_a_quarantine_before_the_attack(self):
        import contextlib
        import io
        p = self._write("e.csv", "".join([
            "500,A,QUARANTINE,,,,,S,,,,,\n",
            "1000,S,SINKHOLE_MODE,,,,,,,,,true,\n",
            "4000,A,QUARANTINE,,,,,S,,,,,\n",
        ]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), unittest.mock.patch("sys.argv", ["x", p]):
            afl.main()
        lines = [ln for ln in out.getvalue().splitlines() if "quarantined" in ln]
        self.assertEqual(lines, ["- A quarantined S (FALSE POSITIVE)",
                                 "- A quarantined S (true positive, 3s after the attack started)"])


if __name__ == "__main__":
    unittest.main()
