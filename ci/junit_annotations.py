#!/usr/bin/env python3
"""Turn JUnit XML results into GitHub annotations (readable through the public API)."""
import glob
import sys
import xml.etree.ElementTree as ET


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


passed, failed = [], []
for f in glob.glob(sys.argv[1] if len(sys.argv) > 1 else "app/build/test-results/**/*.xml", recursive=True):
    root = ET.parse(f).getroot()
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '').split('.')[-1]}.{case.get('name')} ({float(case.get('time', 0)):.1f}s)"
        bad = case.find("failure") if case.find("failure") is not None else case.find("error")
        if bad is not None:
            text = (bad.get("message") or "") + "\n" + "\n".join((bad.text or "").splitlines()[:12])
            failed.append((name, text))
        else:
            passed.append(name)
    out = root.find("system-out")
    for line in (out.text or "").splitlines() if out is not None else []:
        if "scenario" in line:
            print(f"::notice title=Scenario output::{esc(line.strip())}")

print(f"::notice title=Virtual mesh tests: {len(passed)} passed, {len(failed)} failed::{esc(chr(10).join(passed))}")
for name, text in failed[:20]:
    print(f"::error title=FAILED {name}::{esc(text)}")
sys.exit(1 if failed else 0)
