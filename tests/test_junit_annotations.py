import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPT = Path(__file__).resolve().parents[1] / "ci" / "junit_annotations.py"

XML = """<testsuite name="s">
  <testcase classname="com.x.MeshScenarioTest" name="relay_works" time="1.5"/>
  <testcase classname="com.x.MeshScenarioTest" name="slow_one" time="0.0"><skipped/></testcase>
  <testcase classname="com.x.MeshScenarioTest" name="odd: name, really" time="2.0">
    <failure message="A should cut the attacker out">java.lang.AssertionError
at org.junit.Assert.fail</failure>
  </testcase>
  <system-out>sinkhole scenario: attack phase delivered 3/5</system-out>
</testsuite>"""


class JunitAnnotationsTest(unittest.TestCase):
    def run_on(self, xml):
        with TemporaryDirectory() as d:
            (Path(d) / "r.xml").write_text(xml)
            return subprocess.run([sys.executable, str(SCRIPT), str(Path(d) / "*.xml")],
                                  capture_output=True, text=True)

    def test_counts_skips_separately_and_escapes_titles(self):
        res = self.run_on(XML)
        self.assertEqual(res.returncode, 1)
        lines = res.stdout.splitlines()
        self.assertIn("::notice title=Virtual mesh tests%3A 1 passed%2C 1 failed%2C 1 skipped::"
                      "MeshScenarioTest.relay_works (1.5s)", lines)
        self.assertTrue(any(line.startswith("::warning title=1 skipped::MeshScenarioTest.slow_one")
                            for line in lines))
        error = next(line for line in lines if line.startswith("::error"))
        # The ':' and ',' in the test name must not end the title property early.
        self.assertTrue(error.startswith("::error title=FAILED MeshScenarioTest.odd%3A name%2C really (2.0s)::"))
        self.assertIn("A should cut the attacker out%0Ajava.lang.AssertionError", error)
        self.assertIn("::notice title=Scenario output::sinkhole scenario: attack phase delivered 3/5", lines)

    def test_all_green_exits_zero(self):
        res = self.run_on('<testsuite><testcase classname="a.B" name="t" time="0.1"/></testsuite>')
        self.assertEqual(res.returncode, 0)
        self.assertNotIn("skipped", res.stdout)


if __name__ == "__main__":
    unittest.main()
