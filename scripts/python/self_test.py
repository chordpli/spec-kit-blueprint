#!/usr/bin/env python3
"""self_test.py — run the fixture corpus in tests/fixtures and check what the tools say.

Every fixture is a tiny repository with one blueprint and an `expected.txt` holding the
exact findings the tools must produce for it. Any difference fails.

This exists because a comment is not a mechanism. The release that diagnosed "a check
that counts a quotation as authorship" and fixed it in one place shipped the same bug in
two new checks in the same file, ten lines apart — and three reviewers found it. The rule
now has fixtures behind it: `quoted-not-authored` fails the moment a check starts reading
a **Before** as this document's writing, or stops reading what an **After** adds.

    python3 scripts/python/self_test.py              run them all
    python3 scripts/python/self_test.py --coverage   which findings the corpus pins, and
                                                     which it has never once produced
    python3 scripts/python/self_test.py --update     show the diff; refuses to write
    python3 scripts/python/self_test.py --update --i-read-the-diff   write it

Exit 0 all fixtures match, 1 some do not, 2 --update was asked for without reading.

WHAT THIS CORPUS IS FOR, measured rather than asserted. A reviewer planted 46 regressions
into a copy of this extension and asked the corpus about each one. The first version
caught 14. The two things that were wrong with it:

  * It ran each tool ONCE, with no flags. Twelve flags change behaviour and the corpus
    executed none of them, so `--done`, `--markers`, `--fresh`, `--strict-guide` and the
    unknown-option guard could all be deleted outright and the corpus said `3 of 3 ok`.
  * Every fixture was a CLEAN document. A check that never fires cannot be observed to
    have been switched off or downgraded, which is why lowering five checks from fail to
    warn was caught zero times. Pinning more *detail* about a silent check does not help;
    the reviewer tried that and the number did not move. What helps is a document that
    makes the check speak.

So: the flags are run, and `dirty-guide` and `quoted-only` exist to be red.
"""
from __future__ import annotations

import difflib
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
        vp = os.path.join(HERE, "validate_blueprint.py")
        ap = os.path.join(HERE, "apply_blueprint.py")
        sp = os.path.join(ROOT, "scripts", "bash", "validate-scaffold.sh")
        py = sys.executable
        rows = []
        # A flag is a behaviour, and an unexercised behaviour is an unguarded one. The
        # two typo entries are here because the unknown-option guard is a gate whose
        # whole job is to fail, and deleting it left every fixture green.
        for name, cmd, verbatim in (
            ("validate", [py, vp, rel], False),
            ("validate --strict-guide", [py, vp, rel, "--strict-guide"], False),
            ("validate --typo", [py, vp, rel, "--strict-guied"], True),
            ("apply", [py, ap, rel], False),
            ("apply --verify", [py, ap, rel, "--verify"], False),
            ("apply --typo", [py, ap, rel, "--verfy"], True),
            ("scaffold", ["bash", sp, rel], False),
            ("scaffold --fresh", ["bash", sp, rel, "--fresh"], False),
            ("scaffold --done", ["bash", sp, rel, "--done"], False),
            ("scaffold --strict", ["bash", sp, rel, "--strict"], False),
            ("scaffold --markers", ["bash", sp, rel, "--markers"], True),
            ("scaffold --done --all", ["bash", sp, "--done", "--all"], False),
            ("scaffold --typo", ["bash", sp, rel, "--frsh"], True),
        ):
            proc = subprocess.run(cmd, cwd=dest, capture_output=True, text=True,
                                  env=env, timeout=300)
            out = proc.stdout + proc.stderr
            # Absolute paths differ on every machine and every run. Without this every
            # case reads as a difference and the corpus is noise — the reviewer who
            # prototyped the flag runs made exactly this mistake first.
            out = out.replace(ROOT, "<EXT>").replace(dest, "<TREE>").replace(tmp, "<TMP>")
            out = re.sub(r"/[^\s'\"]*blueprint-(?:apply|verify)-\w+", "<COPY>", out)
            if verbatim:
                # A listing IS the output; there are no `⚠` headlines to summarise.
                rows += [f"{name}: {l.rstrip()}" for l in out.split("\n") if l.strip()]
            else:
                rows += [f"{name}: {f}" for f in findings(out)]
            rows.append(f"{name}: exit {proc.returncode}")
        return rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- Coverage ---------------------------------------------------------------------
#
# The corpus used to have no idea what it covered, and "add a fixture when you add a
# check" was a rule nobody could check. These two functions make the gap a number: every
# finding the three scripts can literally print, against every finding the fixtures have
# actually produced. It is a static read of string literals, so it is approximate in one
# direction only — a message built at runtime is invisible here and is reported as such.
FINDING_LITERAL = re.compile(
    r"""record\(\s*["'](?:fail|warn)["']\s*,\s*(?:f?["'])(.{6,120}?)["']""", re.S)
BASH_LITERAL = re.compile(r"""^\s*(?:fail|warn)\s+"([^"$][^"]{5,120})"$""", re.M)


def declared_findings() -> list[str]:
    out = []
    for rel in ("scripts/python/validate_blueprint.py", "scripts/python/apply_blueprint.py"):
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        out += [m.group(1) for m in FINDING_LITERAL.finditer(text)]
    text = open(os.path.join(ROOT, "scripts/bash/validate-scaffold.sh"), encoding="utf-8").read()
    out += [m.group(1) for m in BASH_LITERAL.finditer(text)]
    return sorted(set(out))


def stable_fragment(msg: str) -> str:
    """The longest run of a finding that is the same however its counts come out.

    Most findings are f-strings — `{len(bare_ids)} identifier(s) inside code blocks…` —
    so the literal in the source is never the text on screen. The longest placeholder-free
    run is, and it is what decides whether a fixture has ever produced this finding.
    """
    parts = re.split(r"\{[^}]*\}|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*", msg)
    return max((p.strip() for p in parts), key=len, default="")


def report_coverage(pinned: set[str]) -> int:
    declared = declared_findings()
    hit, miss = [], []
    for d in declared:
        frag = stable_fragment(d)[:60]
        (hit if len(frag) >= 12 and any(frag in p for p in pinned) else miss).append(d)
    print(f"\nthe corpus pins {len(pinned)} distinct finding(s) across the fixtures.")
    print(f"of {len(declared)} finding(s) written as a literal in the three scripts,"
          f" {len(hit)} have been produced by a fixture and {len(miss)} never have.")
    print("\nnever produced by any fixture — each of these can be deleted, downgraded or")
    print("broken without this corpus noticing:\n")
    for d in miss:
        print(f"  - {d}")
    print("\nA finding built at runtime rather than written as a literal is not counted"
          "\nhere at all, so the real denominator is larger than the one above.")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    update = "--update" in argv
    acked = "--i-read-the-diff" in argv
    coverage = "--coverage" in argv
    if not os.path.isdir(FIXTURES):
        print(f"no fixture directory at {FIXTURES}")
        return 1
    names = sorted(d for d in os.listdir(FIXTURES)
                   if os.path.isdir(os.path.join(FIXTURES, d, "specs")))
    if not names:
        print(f"no fixtures under {FIXTURES}")
        return 1
    bad = 0
    pinned: set[str] = set()
    pending: list[tuple[str, list[str]]] = []
    for name in names:
        path = os.path.join(FIXTURES, name)
        got = run_fixture(path)
        exp_path = os.path.join(path, "expected.txt")
        want = []
        if os.path.isfile(exp_path):
            want = [l for l in open(exp_path, encoding="utf-8").read().split("\n") if l.strip()]
        pinned |= {l.split(": ", 1)[1] for l in (got if update else want) if ": " in l}
        if update:
            # --update used to rewrite expected.txt in silence. Plant a regression, run
            # it, and the corpus adopted the regression as the new truth — the escape
            # hatch was wide open and its docstring said "read the diff first", which is
            # a request, not a mechanism. Now the diff is printed whether you want it or
            # not, and writing takes a second flag that says you read it.
            diff = list(difflib.unified_diff(want, got, fromfile=f"{name}/expected.txt",
                                             tofile=f"{name}/now", lineterm=""))
            if diff:
                print(f"\n--- {name} ---")
                for line in diff:
                    print(line)
            else:
                print(f"\n--- {name} --- (no change)")
            pending.append((exp_path, got))
            continue
        if not want:
            print(f"  {name}: no expected.txt — run with --update and read the diff")
            bad += 1
            continue
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
        if not acked:
            print("\nNothing was written. Every line above is a change to what this extension")
            print("says. Read it: if it is the point of your change, run again with")
            print("  --update --i-read-the-diff")
            print("and commit the fixture update alongside the change that caused it. If any")
            print("of it surprises you, that is the regression this corpus exists to catch.")
            return 2
        for exp_path, got in pending:
            with open(exp_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(got) + "\n")
        print(f"\nwrote {len(pending)} expected.txt file(s).")
        if coverage:
            report_coverage(pinned)
        return 0
    print(f"\n{len(names) - bad} of {len(names)} fixture(s) match.")
    if bad:
        print("A difference here is a check that changed what it says. Either the change is")
        print("the point — then update expected.txt in the same commit — or it is the bug this")
        print("corpus exists to catch. See tests/fixtures/README.md.")
    if coverage:
        report_coverage(pinned)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
