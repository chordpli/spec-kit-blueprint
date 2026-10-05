#!/usr/bin/env python3
"""Replay the frozen guru before/half/complete verification boundary corpus.

Run from any directory with `python3 tests/guru_verification_e2e.py`. The project
bundle keeps full commit history; only the pinned generated artifact inputs are
copied into fresh temporary clones. Candidate runtime tools are the scripts beside
this test. `--evidence-dir DIR` preserves each exact command and combined output.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/corpus/verification_scope"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text())
BUNDLE = ROOT / MANIFEST["bundle"]
PYTHON = ROOT / "scripts/python"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(root: pathlib.Path, name: str, argv: list[str], evidence: pathlib.Path | None,
             expected: int, required_output: str | None = None) -> dict:
    result = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=900)
    matched = required_output is None or required_output in result.stdout + result.stderr
    row = {"case": name, "command": argv, "exit": result.returncode,
           "expected": expected, "required_output": required_output,
           "output_matched": matched,
           "passed": result.returncode == expected and matched}
    if evidence:
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / f"{name}.log").write_text(
            f"PROJECT_ROOT={root}\n$ {' '.join(argv)}\nSTDOUT\n{result.stdout}"
            f"\nSTDERR\n{result.stderr}\nEXIT={result.returncode}\n")
    if not row["passed"]:
        row["stdout"] = result.stdout[-4000:]
        row["stderr"] = result.stderr[-2000:]
    return row


def prepare(state: str, root: pathlib.Path) -> str:
    state_spec = CORPUS / state
    commit = MANIFEST["states"][state]["commit"]
    subprocess.run(["git", "clone", "-q", str(BUNDLE), str(root)], check=True)
    subprocess.run(["git", "checkout", "-q", "--detach", commit], cwd=root, check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if actual != commit:
        raise AssertionError(f"{state}: checked out {actual}, expected {commit}")
    for relative in ("specs/001-idempotent-transfer/blueprint.md",
                     "specs/002-transfer-history/blueprint.md",
                     "docs/r16-verification-boundary.md"):
        source = state_spec / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        expected_hash = MANIFEST["states"][state]["sha256"][relative]
        if sha256(destination) != expected_hash:
            raise AssertionError(f"{state}: corpus hash mismatch for {relative}")
    return commit


def run_all(evidence: pathlib.Path | None) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory(prefix="guru-verification-e2e-") as tmp:
        tmp = pathlib.Path(tmp)
        for state, config in MANIFEST["states"].items():
            project = tmp / state
            prepare(state, project)
            expected = config["expected"]
            for feature, key in (("001-idempotent-transfer", "a_document"),
                                 ("002-transfer-history", "b_document")):
                results.append(run_case(
                    project, f"{state}-{key}",
                    [sys.executable, str(PYTHON / "validate_blueprint.py"),
                     f"specs/{feature}", "--strict-guide"], evidence, expected[key]))
            for feature, key in (("001-idempotent-transfer", "a_focused"),
                                 ("002-transfer-history", "b_focused")):
                results.append(run_case(
                    project, f"{state}-{key}",
                    [sys.executable, str(PYTHON / "apply_blueprint.py"),
                     f"specs/{feature}", "--verify", "--verify-scope", "feature"],
                    evidence, expected[key]))
            results.append(run_case(project, f"{state}-repository",
                                    ["npm", "test"], evidence, expected["repository"]))
        # Three independent behavior mutants run only on disposable complete-app copies.
        base = tmp / "complete"
        mutants = [
            ("mutant-cli-empty", "src/cli.js", "io.log(JSON.stringify(items));", "io.log(\"\");",
             "SyntaxError: Unexpected end of JSON input"),
            ("mutant-history-save", "src/cli.js", "io.log(JSON.stringify(items));",
             'await saveLedger(values["--file"], ledger);\n      io.log(JSON.stringify(items));',
             "read-only CLI must not rewrite identical bytes"),
            ("mutant-domain-empty", "src/ledger.js",
             ".filter((item) => account === undefined || item.from === account || item.to === account)",
             ".filter(() => false)", "CLI must emit the exact filtered JSON result"),
            ("mutant-cli-stderr", "src/cli.js", "io.log(JSON.stringify(items));",
             "io.error('unexpected history diagnostic');\n      io.log(JSON.stringify(items));",
             "valid CLI must have empty stderr"),
        ]
        for name, relative, old, new, required in mutants:
            mutant = tmp / name
            shutil.copytree(base, mutant, ignore=shutil.ignore_patterns(".git"))
            path = mutant / relative
            body = path.read_text()
            if body.count(old) != 1:
                raise AssertionError(f"{name}: expected one mutation anchor, found {body.count(old)}")
            path.write_text(body.replace(old, new, 1))
            syntax = subprocess.run(["node", "--check", str(path)], cwd=mutant,
                                    capture_output=True, text=True, timeout=30)
            if syntax.returncode:
                raise AssertionError(f"{name}: mutant is not valid JavaScript: {syntax.stderr}")
            syntax_row = {"case": f"{name}-syntax", "command": ["node", "--check", str(path)],
                          "exit": syntax.returncode, "expected": 0, "passed": True}
            results.append(syntax_row)
            if evidence:
                evidence.mkdir(parents=True, exist_ok=True)
                (evidence / f"{name}-syntax.log").write_text(
                    f"PROJECT_ROOT={mutant}\n$ node --check {path}\n"
                    f"STDOUT\n{syntax.stdout}\nSTDERR\n{syntax.stderr}\nEXIT={syntax.returncode}\n")
            results.append(run_case(
                mutant, name,
                [sys.executable, str(PYTHON / "apply_blueprint.py"),
                 "specs/002-transfer-history", "--verify", "--verify-scope", "feature"],
                evidence, 1, required_output=required))
        results.extend(run_runner_attacks(tmp, evidence))
    return results


def run_runner_attacks(tmp: pathlib.Path, evidence: pathlib.Path | None) -> list[dict]:
    """Independent probes for heredoc fidelity, failure propagation, and quoted blocks."""
    module_path = PYTHON / "apply_blueprint.py"
    spec = importlib.util.spec_from_file_location("guru_e2e_applier", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate applier: {module_path}")
    applier = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = applier
    spec.loader.exec_module(applier)
    root = tmp / "runner-attacks"
    root.mkdir()
    (root / "fail.py").write_text("raise SystemExit(9)\n")
    (root / "pass.py").write_text("print('later command ran')\n")
    probes = [
        ("runner-heredoc-assertion",
         "**Verification**:\n```bash\npython3 - <<'PYCODE'\nassert False, 'independent assertion executed'\nPYCODE\n```",
         "independent assertion executed"),
        ("runner-first-command-fail",
         "**Verification**:\n```bash\npython3 fail.py\npython3 pass.py\n```",
         "exit 9"),
    ]
    rows = []
    for name, section, required in probes:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = applier.run_verifications(
                str(root), [("specs/002-transfer-history/T999", section)], section, False)
        text = output.getvalue()
        passed = code == 1 and required in text
        row = {"case": name, "exit": code, "expected": 1,
               "required_output": required, "output_matched": required in text,
               "passed": passed}
        rows.append(row)
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / f"{name}.log").write_text(
                f"PROJECT_ROOT={root}\nSECTION\n{section}\nSTDOUT\n{text}\nEXIT={code}\n")
    quoted = "> **Verification**:\n> ```bash\n> python3 -c \"raise SystemExit(9)\"\n> ```"
    parsed = applier.verification_commands(quoted)
    rows.append({"case": "runner-quoted-verification", "parsed": parsed,
                 "expected": [], "passed": parsed == []})
    if evidence:
        (evidence / "runner-quoted-verification.log").write_text(
            f"SECTION\n{quoted}\nPARSED={parsed!r}\nEXIT=0\n")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=pathlib.Path)
    args = parser.parse_args()
    results = run_all(args.evidence_dir)
    if args.evidence_dir:
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        (args.evidence_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    return 0 if all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
