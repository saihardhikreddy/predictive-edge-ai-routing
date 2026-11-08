#!/usr/bin/env python3
"""Turn JUnit XML results into GitHub annotations (readable through the public API)."""
import glob
import sys
import xml.etree.ElementTree as ET


def esc(s: str) -> str:
    """Escape an annotation message."""
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def esc_prop(s: str) -> str:
    """Escape a property such as title=: ':' and ',' would otherwise end it early."""
    return esc(s).replace(":", "%3A").replace(",", "%2C")


passed, failed, skipped = [], [], []
for f in glob.glob(sys.argv[1] if len(sys.argv) > 1 else "app/build/test-results/**/*.xml", recursive=True):
    root = ET.parse(f).getroot()
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '').split('.')[-1]}.{case.get('name')} ({float(case.get('time', 0)):.1f}s)"
        bad = case.find("failure") if case.find("failure") is not None else case.find("error")
        if bad is not None:
            text = (bad.get("message") or "") + "\n" + "\n".join((bad.text or "").splitlines()[:12])
            failed.append((name, text))
        elif case.find("skipped") is not None:  # @Ignore'd or assumption failed: it didn't pass
            skipped.append(name)
        else:
            passed.append(name)
    out = root.find("system-out")
    for line in (out.text or "").splitlines() if out is not None else []:
        if "scenario" in line:
            print(f"::notice title=Scenario output::{esc(line.strip())}")

summary = f"Virtual mesh tests: {len(passed)} passed, {len(failed)} failed"
if skipped:
    summary += f", {len(skipped)} skipped"
print(f"::notice title={esc_prop(summary)}::{esc(chr(10).join(passed))}")
if skipped:
    print(f"::warning title={esc_prop(f'{len(skipped)} skipped')}::{esc(chr(10).join(skipped))}")
for name, text in failed[:20]:
    print(f"::error title={esc_prop('FAILED ' + name)}::{esc(text)}")
sys.exit(1 if failed else 0)
