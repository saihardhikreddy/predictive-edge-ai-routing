import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import benchmark  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ColumnOrderTest(unittest.TestCase):
    def test_keys_keep_first_seen_order(self):
        rows = [{"experiment": "scaling", "pdr": 0.9},
                {"experiment": "attack", "pdr": 0.5, "sinkhole_drops": 3, "ids_detection_s": 4.0},
                {"experiment": "coldstart", "window_pdr": 0.7}]
        self.assertEqual(benchmark.column_order(rows),
                         ["experiment", "pdr", "sinkhole_drops", "ids_detection_s", "window_pdr"])

    def test_order_does_not_depend_on_string_hashing(self):
        # The old code sorted a set; different PYTHONHASHSEEDs then gave different column orders.
        code = ("import benchmark; rows = [{'a': 1}] + [{k: 1} for k in 'zyxwvutsrqponmlkjihgfedcb']; "
                "print(','.join(benchmark.column_order(rows)))")
        outs = set()
        for seed in ("1", "2", "3"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outs.add(subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                    capture_output=True, text=True, check=True).stdout)
        self.assertEqual(len(outs), 1)
        self.assertTrue(outs.pop().startswith("a,z,y,x"))

    def test_workers_must_be_positive(self):
        import argparse
        self.assertEqual(benchmark.positive_int("4"), 4)
        for bad in ("0", "-2"):
            with self.assertRaises(argparse.ArgumentTypeError):
                benchmark.positive_int(bad)


if __name__ == "__main__":
    unittest.main()
