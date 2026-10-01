#!/usr/bin/env python3
"""Meaningful contract tests for the S7 ledger collector."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "scripts/python/s7_ledger.py"


class S7LedgerTest(unittest.TestCase):
    def invoke(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(LEDGER), *args], text=True, capture_output=True, check=check)

    def validate_tool(self, root: Path, text: str) -> Path:
        scripts = root / "scripts"; (scripts / "python").mkdir(parents=True)
        tool = scripts / "python" / "validate_blueprint.py"; tool.write_text(text, encoding="utf-8")
        (scripts / "python" / "apply_blueprint.py").write_text("# companion\n", encoding="utf-8")
        (scripts / "python" / "_blueprint_parse.py").write_text("# companion\n", encoding="utf-8")
        (scripts / "bash").mkdir(); (scripts / "bash" / "validate-scaffold.sh").write_text("# companion\n", encoding="utf-8")
        return tool

    def test_record_zero_and_headline_are_distinct_and_raw_is_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / "out"; tool = self.validate_tool(root, "print(\"  ⚠ the header's file counts do not match the tasks\")\n")
            self.invoke("record", "--out", str(out), "--run-id", "r1", "--campaign", "c", "--scenario", "s", "--correlation", "g", "--state", "baseline", "--tool", "validate", "--cwd", str(root), "--", sys.executable, str(tool))
            runs = [json.loads(x) for x in (out / "executions.jsonl").read_text().splitlines()]
            emissions = [json.loads(x) for x in (out / "emissions.jsonl").read_text().splitlines()]
            self.assertEqual(1, runs[0]["headline_count"]); self.assertEqual("validate.header.file-count", emissions[0]["check_id"])
            self.assertTrue((out / runs[0]["stdout"]).is_file())
            (out / "adjudications.jsonl").write_text(json.dumps({"schema":1, "emission_id":"r1:01", "classification":"actionable", "reason":"fixture", "adjudicator":"test", "evidence":"raw/r1.stdout"}) + "\n")
            self.assertEqual(0, self.invoke("validate", "--out", str(out)).returncode)
            executions = out / "executions.jsonl"; row = json.loads(executions.read_text()); row["tool_sha256"] = "0" * 64; row["source_manifest"]["scripts/python/validate_blueprint.py"] = "0" * 64; executions.write_text(json.dumps(row) + "\n")
            self.assertNotEqual(0, self.invoke("validate", "--out", str(out), check=False).returncode)

    def test_validator_rejects_unmapped_duplicate_and_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / "out"; tool = self.validate_tool(root, "print('  ⚠ completely new diagnostic')\n")
            self.invoke("record", "--out", str(out), "--run-id", "r1", "--campaign", "c", "--scenario", "s", "--correlation", "g", "--state", "probe", "--tool", "validate", "--cwd", str(root), "--", sys.executable, str(tool))
            bad = self.invoke("validate", "--out", str(out), check=False)
            self.assertEqual(1, bad.returncode); self.assertIn("unmapped headline", bad.stdout); self.assertIn("pending adjudication", bad.stdout)
            duplicate = self.invoke("record", "--out", str(out), "--run-id", "r1", "--campaign", "c", "--scenario", "s2", "--correlation", "g", "--state", "probe", "--tool", "validate", "--cwd", str(root), "--", sys.executable, str(tool), check=False)
            self.assertNotEqual(0, duplicate.returncode); self.assertIn("duplicate run_id", duplicate.stderr)

    def test_rejects_non_blueprint_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.invoke("record", "--out", tmp, "--run-id", "r", "--campaign", "c", "--scenario", "s", "--correlation", "g", "--state", "baseline", "--tool", "apply", "--cwd", tmp, "--", sys.executable, "-c", "print('  ✗ fake')", check=False)
            self.assertNotEqual(0, result.returncode); self.assertIn("not the declared Blueprint apply", result.stderr)

    def test_non_glyph_base_error_is_a_tool_outcome_not_environment_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / "out"; tool = self.validate_tool(root, "print('ERROR: invalid Base chain: cycle')\n")
            self.invoke("record", "--out", str(out), "--run-id", "base", "--campaign", "c", "--scenario", "s", "--correlation", "g", "--state", "probe", "--tool", "validate", "--cwd", str(root), "--", sys.executable, str(tool))
            emission = json.loads((out / "emissions.jsonl").read_text())
            self.assertEqual("tool-error", emission["kind"])
            self.assertEqual("validate.base.chain", emission["check_id"])

    def test_adjudicate_rejects_unknown_and_completes_known_emission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / "out"; tool = self.validate_tool(root, "print('ERROR: invalid Base chain: cycle')\n")
            self.invoke("record", "--out", str(out), "--run-id", "base", "--campaign", "c", "--scenario", "s", "--correlation", "g", "--state", "probe", "--tool", "validate", "--cwd", str(root), "--", sys.executable, str(tool))
            bad = self.invoke("adjudicate", "--out", str(out), "--emission-id", "none:01", "--classification", "unknown", "--reason", "x", "--adjudicator", "a", "--evidence", "raw/x", check=False)
            self.assertNotEqual(0, bad.returncode)
            self.invoke("adjudicate", "--out", str(out), "--emission-id", "base:01", "--classification", "unknown", "--reason", "scope undecidable", "--adjudicator", "a", "--evidence", "raw/base.stdout")
            self.assertEqual(0, self.invoke("validate", "--out", str(out)).returncode)

    def test_empty_and_raw_disagreement_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / "out"
            self.assertNotEqual(0, self.invoke("validate", "--out", str(out), check=False).returncode)
            tool = self.validate_tool(root, "print(\"  ⚠ the header's file counts do not match the tasks\")\n")
            self.invoke("record", "--out", str(out), "--run-id", "r", "--campaign", "c", "--scenario", "s", "--correlation", "g", "--state", "baseline", "--tool", "validate", "--cwd", str(root), "--", sys.executable, str(tool))
            emissions = out / "emissions.jsonl"; row = json.loads(emissions.read_text()); row["headline"] = "forged"; emissions.write_text(json.dumps(row) + "\n")
            self.assertNotEqual(0, self.invoke("validate", "--out", str(out), check=False).returncode)

    def test_collect_refuses_nonempty_output_before_running_any_manifest_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"; out.mkdir(); (out / "existing").write_text("do not overwrite\n")
            manifest = ROOT / "tests/corpus/s7/r14-actual-campaign.json"
            result = self.invoke("collect", "--out", str(out), "--manifest", str(manifest), check=False)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("refusing non-empty output", result.stderr)
            self.assertEqual("do not overwrite\n", (out / "existing").read_text())

    def test_validator_rejects_schema_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / "out"; tool = self.validate_tool(root, "print('ERROR: invalid Base chain: cycle')\n")
            self.invoke("record", "--out", str(out), "--run-id", "schema", "--campaign", "c", "--scenario", "s", "--correlation", "g", "--state", "probe", "--tool", "validate", "--cwd", str(root), "--", sys.executable, str(tool))
            row = json.loads((out / "emissions.jsonl").read_text()); row["schema"] = 999; (out / "emissions.jsonl").write_text(json.dumps(row) + "\n")
            self.assertNotEqual(0, self.invoke("validate", "--out", str(out), check=False).returncode)

    def test_completed_ledger_rejects_integrity_mutations(self) -> None:
        # Each attack starts from a validated positive control, so rejection cannot
        # be explained by an unrelated pending adjudication.
        for attack in ("schema", "check-id", "argv", "metadata", "duplicate", "source-bytes"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); out = root / "out"
                tool = self.validate_tool(root, "print('ERROR: invalid Base chain: cycle')\n")
                self.invoke("record", "--out", str(out), "--run-id", "r", "--campaign", "c", "--scenario", "s", "--correlation", "g", "--state", "probe", "--tool", "validate", "--cwd", str(root), "--", sys.executable, str(tool))
                self.invoke("adjudicate", "--out", str(out), "--emission-id", "r:01", "--classification", "actionable", "--reason", "fixture", "--adjudicator", "test", "--evidence", "raw/r.stdout")
                execution = json.loads((out / "executions.jsonl").read_text())
                data = {"campaign_id": "c", "runs": [{key: execution[key] for key in ("run_id", "scenario_id", "correlation_id", "state", "tool", "argv")}]}
                manifest = root / "manifest.json"; manifest.write_text(json.dumps(data))
                self.invoke("validate", "--out", str(out), "--manifest", str(manifest))
                if attack == "schema":
                    execution["schema"] = 999
                    (out / "executions.jsonl").write_text(json.dumps(execution) + "\n")
                elif attack == "check-id":
                    emission = json.loads((out / "emissions.jsonl").read_text())
                    emission["check_id"] = "validate.source.stamp"
                    (out / "emissions.jsonl").write_text(json.dumps(emission) + "\n")
                elif attack == "source-bytes":
                    snapshot = out / "source" / execution["tool_sha256"]
                    snapshot.write_bytes(snapshot.read_bytes() + b"# altered\n")
                else:
                    if attack == "argv": data["runs"][0]["argv"] = ["forged-command"]
                    elif attack == "metadata": data["runs"][0]["scenario_id"] = "forged-scenario"
                    else: data["runs"].append(dict(data["runs"][0]))
                    manifest.write_text(json.dumps(data))
                self.assertEqual(1, self.invoke("validate", "--out", str(out), "--manifest", str(manifest), check=False).returncode)

    def test_collect_has_a_single_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / "out"
            self.validate_tool(root, "import time\ntime.sleep(1)\n")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"campaign_id": "c", "runs": [{"project": "p", "run_id": "r", "scenario_id": "s", "correlation_id": "g", "state": "baseline", "tool": "validate", "argv": [sys.executable, "{project_root}/scripts/python/validate_blueprint.py"], "timeout": 10}]}))
            argv = [sys.executable, str(LEDGER), "collect", "--out", str(out), "--manifest", str(manifest), "--project-root", f"p={root}"]
            first = subprocess.Popen(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not (out / ".collect.lock").exists() and first.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((out / ".collect.lock").exists())
                second = subprocess.run(argv, text=True, capture_output=True, timeout=10)
                self.assertNotEqual(0, second.returncode)
                self.assertTrue("another collect owns" in second.stderr or "refusing non-empty output" in second.stderr)
                stdout, stderr = first.communicate(timeout=10)
                self.assertEqual(0, first.returncode, stdout + stderr)
                self.assertEqual(1, len((out / "executions.jsonl").read_text().splitlines()))
            finally:
                if first.poll() is None:
                    first.kill(); first.communicate()


if __name__ == "__main__":
    unittest.main()
