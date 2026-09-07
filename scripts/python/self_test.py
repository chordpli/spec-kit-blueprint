#!/usr/bin/env python3
"""self_test.py — run the fixture corpus in tests/fixtures and check what the tools say.

Every fixture is a tiny repository with one blueprint and an `expected.txt` holding the
exact findings the tools must produce for it. Any difference fails.

This exists because a comment is not a mechanism. The release that diagnosed "a check
that counts a quotation as authorship" and fixed it in one place shipped the same bug in
two new checks in the same file, ten lines apart — and three reviewers found it. The rule
now has a fixture behind it: `quoted-not-authored` fails the moment a check starts
reading a **Before** as this document's writing, or stops reading what an **After** adds.

    python3 scripts/python/self_test.py            run them all
    python3 scripts/python/self_test.py --update   rewrite expected.txt from what the
                                                   tools say now (read the diff first)

Exit 0 all fixtures match, 1 some do not.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

# The headline of a finding, with the leading mark. Evidence lines are indented further
# and are not part of the contract — they carry paths and counts that move with the tree.
FINDING = re.compile(r"^  ([⚠✗]) (.+)$")


def findings(out: str) -> list[str]:
    rows = []
    for line in out.split("\n"):
        m = FINDING.match(line)
        if m:
            rows.append(f"{m.group(1)} {m.group(2).strip()}")
    return rows


def run_fixture(path: str) -> list[str]:
    """Copy the fixture somewhere with no repository around it, then run the tools."""
    tmp = tempfile.mkdtemp(prefix="blueprint-selftest-")
    try:
        dest = os.path.join(tmp, "tree")
        shutil.copytree(path, dest)
        specs = os.path.join(dest, "specs")
        rel = "specs/" + sorted(os.listdir(specs))[0]
        env = dict(os.environ, NO_COLOR="1")
        rows = []
        for name, cmd in (
            ("validate", [sys.executable, os.path.join(HERE, "validate_blueprint.py"), rel]),
            ("apply", [sys.executable, os.path.join(HERE, "apply_blueprint.py"), rel]),
            ("scaffold", ["bash", os.path.join(ROOT, "scripts", "bash", "validate-scaffold.sh"), rel]),
        ):
            proc = subprocess.run(cmd, cwd=dest, capture_output=True, text=True, env=env, timeout=300)
            out = proc.stdout + proc.stderr
            rows += [f"{name}: {f}" for f in findings(out)]
            rows.append(f"{name}: exit {proc.returncode}")
        return rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    update = "--update" in sys.argv
    if not os.path.isdir(FIXTURES):
        print(f"no fixture directory at {FIXTURES}")
        return 1
    names = sorted(d for d in os.listdir(FIXTURES)
                   if os.path.isdir(os.path.join(FIXTURES, d, "specs")))
    if not names:
        print(f"no fixtures under {FIXTURES}")
        return 1
    bad = 0
    for name in names:
        path = os.path.join(FIXTURES, name)
        got = run_fixture(path)
        exp_path = os.path.join(path, "expected.txt")
        if update:
            with open(exp_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(got) + "\n")
            print(f"  updated  {name}  ({len(got)} line(s))")
            continue
        if not os.path.isfile(exp_path):
            print(f"  {name}: no expected.txt — run with --update and read the diff")
            bad += 1
            continue
        want = [l for l in open(exp_path, encoding="utf-8").read().split("\n") if l.strip()]
        if want == got:
            print(f"  ok       {name}")
            continue
        bad += 1
        print(f"  FAILED   {name}")
        for line in want:
            if line not in got:
                print(f"      missing: {line}")
        for line in got:
            if line not in want:
                print(f"      extra:   {line}")
    if update:
        return 0
    print(f"\n{len(names) - bad} of {len(names)} fixture(s) match.")
    if bad:
        print("A difference here is a check that changed what it says. Either the change is")
        print("the point — then update expected.txt in the same commit — or it is the bug this")
        print("corpus exists to catch. See tests/fixtures/README.md.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
