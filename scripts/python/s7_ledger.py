#!/usr/bin/env python3
"""Collect and validate a reproducible S7 observed-finding ledger.

S7 records what the three Blueprint tools actually said.  It deliberately does
not decide whether a message is useful: that is an auditable human judgement in
``adjudications.jsonl``.  A non-zero exit without a Blueprint headline, and
environment stderr, are retained in the execution record instead of being
silently counted as findings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import shutil
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA = 1
HEADLINE = re.compile(r"^  ([⚠✗]) (.+)$", re.M)
# Some tools intentionally use a non-glyph diagnostic for command-level errors
# (notably invalid Base chains).  It is still a tool outcome when the argv has
# already been proven to invoke a Blueprint tool, so it must not disappear into
# environment stderr merely because it lacks ⚠/✗.
TOOL_ERROR = re.compile(r"^(ERROR:|usage:|error:|timed out:?)\s*(.+)$", re.M | re.I)
TOOLS = {
    "validate": "validate_blueprint.py",
    "apply": "apply_blueprint.py",
    "scaffold": "validate-scaffold.sh",
}

# Check IDs describe a semantic checker, rather than merely a rendered line.
# Patterns are intentionally narrow.  A new headline is data, not something a
# collector may guess about: it stays ``unmapped`` until the catalog is updated.
CATALOG: dict[str, list[tuple[str, str]]] = {
    "validate": [
        ("header.file-count", r"header's file counts do not match"),
        ("tasks.coverage", r"task\(s\) from tasks\.md missing"),
        ("tasks.structure", r"no task sections found"),
        ("requirements.citations", r"no \*\*Requirements\*\* citations"),
        ("guide.body", r"guide blueprint has .*body|body logic"),
        ("base.chain", r"Base .*?(missing|cycle|empty|chain)|invalid Base chain"),
        ("source.stamp", r"Sources|source stamp|stamp"),
        ("before-after", r"Before block|After"),
    ],
    "apply": [
        ("build.exit", r"exit code \d+"),
        ("verification.command", r"\$ .* — exit|did not finish"),
        ("apply.anchor", r"FAILED|cannot tell|block left unplaced|already applied"),
        ("base.chain", r"Base .*?(missing|cycle|empty|chain)"),
    ],
    "scaffold": [
        ("blueprint.shape", r"No NEW file paths detected"),
        ("done.marker", r"not-implemented marker|still carry a .*marker"),
        ("done.declaration", r"declared .*missing|declared file"),
        ("marker.ownership", r"not this feature|marker"),
    ],
}


def die(message: str) -> None:
    raise SystemExit(f"s7-ledger: {message}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value))


def safe_relative(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    p = Path(value)
    return not p.is_absolute() and ".." not in p.parts


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def parsed_tool_events(stdout: str, stderr: str) -> list[dict[str, str | int]]:
    events: list[dict[str, str | int]] = []
    for stream, raw in (("stdout", stdout), ("stderr", stderr)):
        for line_no, raw_line in enumerate(raw.splitlines(), 1):
            line = strip_ansi(raw_line)
            m = re.fullmatch(r"  ([⚠✗]) (.+)", line)
            if m:
                events.append({"kind": "headline", "mark": m.group(1), "headline": m.group(2).strip(), "stream": stream, "line": line_no})
                continue
            m = re.fullmatch(r"(ERROR:|usage:|error:|timed out:?)\s*(.+)", line, re.I)
            if m:
                events.append({"kind": "tool-error", "mark": "!", "headline": f"{m.group(1)} {m.group(2).strip()}", "stream": stream, "line": line_no})
    return events


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def reserve_run(out: Path, run_id: str) -> None:
    """Reserve before any raw/output write; O_EXCL makes duplicate writers lose."""
    directory = out / "reservations"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(directory / f"{run_id}.reserve"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        die(f"duplicate run_id {run_id}: already reserved or recorded")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(run_id + "\n")


def acquire_collect_lock(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    lock = out / ".collect.lock"
    if any(out.iterdir()):
        die(f"refusing non-empty output directory {out}; start a new campaign output")
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        die(f"another collect owns {out}")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()) + "\n")
    return lock


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            die(f"{path}:{no}: invalid JSON: {exc.msg}")
        if not isinstance(value, dict):
            die(f"{path}:{no}: row must be an object")
        rows.append(value)
    return rows


def classify(tool: str, headline: str) -> str:
    for check_id, pattern in CATALOG[tool]:
        if re.search(pattern, headline, re.I):
            return f"{tool}.{check_id}"
    return "unmapped"


def command_is_tool(tool: str, argv: list[str], cwd: str) -> bool:
    expected = TOOLS[tool]
    if not argv:
        return False
    if Path(argv[0]).name == expected:
        script = argv[0]
    elif tool in ("validate", "apply") and Path(argv[0]).name in ("python", "python3") and len(argv) >= 2:
        script = argv[1]
    elif tool == "scaffold" and Path(argv[0]).name in ("bash", "sh") and len(argv) >= 2:
        script = argv[1]
    else:
        return False
    path = Path(script)
    if not path.is_absolute(): path = Path(cwd) / path
    return path.name == expected and path.is_file()


def fingerprint(tool: str, check_id: str, headline: str) -> str:
    normalized = re.sub(r"\b\d+\b", "#", headline)
    normalized = re.sub(r"/[\w./-]+", "<path>", normalized)
    value = f"{tool}\0{check_id}\0{normalized}".encode()
    return hashlib.sha256(value).hexdigest()[:16]


def tool_revision(argv: list[str], cwd: str) -> str:
    candidates = [Path(argv[0])]
    if len(argv) >= 2: candidates.append(Path(argv[1]))
    for candidate in candidates:
        if not candidate.is_absolute(): candidate = Path(cwd) / candidate
        if candidate.name in TOOLS.values() and candidate.is_file(): return sha256(candidate)
    die("declared tool script was not a readable file")


def source_files(argv: list[str], cwd: str) -> dict[str, Path]:
    script = next((Path(x) for x in argv if Path(x).name in TOOLS.values()), None)
    if script is None: die("cannot locate tool script")
    if not script.is_absolute(): script = Path(cwd) / script
    root = script.parents[2]  # extension root from scripts/python|bash/tool
    files = ("scripts/python/validate_blueprint.py", "scripts/python/apply_blueprint.py",
             "scripts/python/_blueprint_parse.py", "scripts/bash/validate-scaffold.sh")
    result: dict[str, Path] = {}
    for rel in files:
        candidate = root / rel
        if candidate.is_file(): result[rel] = candidate
    if len(result) != 4: die("vendored extension lacks one of the four S7 source files")
    return result


def source_manifest(argv: list[str], cwd: str) -> dict[str, str]:
    return {rel: sha256(path) for rel, path in source_files(argv, cwd).items()}


def snapshot_sources(out: Path, argv: list[str], cwd: str) -> dict[str, str]:
    files = source_files(argv, cwd); manifest = {rel: sha256(path) for rel, path in files.items()}
    store = out / "source"
    store.mkdir(parents=True, exist_ok=True)
    for path in files.values():
        digest = sha256(path); target = store / digest
        if target.exists():
            if sha256(target) != digest: die(f"content-addressed source collision at {target}")
        else:
            shutil.copyfile(path, target)
    return manifest


def record(args: argparse.Namespace) -> int:
    argv = args.command
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        die("record needs a command after --")
    if not safe_id(args.run_id): die("run_id must be a safe identifier")
    if not command_is_tool(args.tool, argv, args.cwd):
        die(f"argv is not the declared Blueprint {args.tool} tool ({TOOLS[args.tool]})")
    out = Path(args.out).resolve()
    reserve_run(out, args.run_id)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(argv, cwd=args.cwd, text=True, capture_output=True, timeout=args.timeout)
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        code, timed_out = None, True
    except OSError as exc:
        stdout, stderr, code = "", f"spawn error: {exc}", 127
        timed_out = False
    if isinstance(stdout, bytes): stdout = stdout.decode(errors="replace")
    if isinstance(stderr, bytes): stderr = stderr.decode(errors="replace")
    stdout_path, stderr_path = raw / f"{args.run_id}.stdout", raw / f"{args.run_id}.stderr"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    lines = parsed_tool_events(stdout, stderr)
    run = {
        "schema": SCHEMA, "run_id": args.run_id, "campaign_id": args.campaign,
        "scenario_id": args.scenario, "correlation_id": args.correlation,
        "state": args.state, "tool": args.tool, "argv": argv, "cwd": str(Path(args.cwd).resolve()),
        "exit": code, "timed_out": timed_out, "duration_ms": round((time.time() - started) * 1000),
        "stdout": str(stdout_path.relative_to(out)), "stdout_sha256": sha256(stdout_path),
        "stderr": str(stderr_path.relative_to(out)), "stderr_sha256": sha256(stderr_path),
        "tool_sha256": tool_revision(argv, args.cwd), "source_manifest": snapshot_sources(out, argv, args.cwd), "headline_count": len(lines),
        "nonheadline_failure": bool(timed_out or code != 0 and not lines),
    }
    append_jsonl(out / "executions.jsonl", run)
    for seq, event in enumerate(lines, 1):
        text = str(event["headline"]); check_id = classify(args.tool, text)
        append_jsonl(out / "emissions.jsonl", {
            "schema": SCHEMA, "emission_id": f"{args.run_id}:{seq:02d}", "run_id": args.run_id,
            "seq": seq, "tool": args.tool, "check_id": check_id, "kind": event["kind"], "mark": event["mark"],
            "headline": text, "stream": event["stream"], "line": event["line"], "fingerprint": fingerprint(args.tool, check_id, text),
        })
    print(f"{args.run_id}: exit={code if code is not None else 'timeout'} headlines={len(lines)}")
    return 124 if timed_out else int(code)


def validate(args: argparse.Namespace) -> int:
    out = Path(args.out)
    runs, emissions, adjudications = (read_jsonl(out / name) for name in
        ("executions.jsonl", "emissions.jsonl", "adjudications.jsonl"))
    errors: list[str] = []
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8")) if args.manifest else None
    if not runs and not (manifest and manifest.get("allow_empty") is True):
        errors.append("no executions: completed campaigns require observed runs")
    if manifest:
        expected = manifest.get("runs")
        if not isinstance(expected, list) or not expected:
            errors.append("manifest has no explicit runs")
        else:
            expected_ids = [x.get("run_id") for x in expected]
            if len(expected_ids) != len(set(expected_ids)) or any(not safe_id(str(x)) for x in expected_ids):
                errors.append("manifest run_id must be present, safe, and unique")
            wanted = {x.get("run_id") for x in expected}
            got = {x.get("run_id") for x in runs}
            if wanted != got: errors.append(f"manifest/run mismatch: missing={sorted(wanted-got)} extra={sorted(got-wanted)}")
            expected_by_id = {x.get("run_id"): x for x in expected}
            for row in runs:
                wanted_row = expected_by_id.get(row.get("run_id"), {})
                if wanted_row and row.get("campaign_id") != manifest.get("campaign_id"):
                    errors.append(f"{row.get('run_id')} differs from manifest campaign_id")
                for key in ("scenario_id", "correlation_id", "state", "tool"):
                    if wanted_row and row.get(key) != wanted_row.get(key): errors.append(f"{row.get('run_id')} differs from manifest {key}")
                if wanted_row:
                    expected_argv = [str(value).replace("{project_root}", str(row.get("cwd"))) for value in wanted_row.get("argv", [])]
                    if row.get("argv") != expected_argv: errors.append(f"{row.get('run_id')} argv differs from manifest")
    run_ids = [r.get("run_id") for r in runs]
    for row in runs + emissions + adjudications:
        if row.get("schema") != SCHEMA: errors.append("row schema does not match collector schema")
    if len(run_ids) != len(set(run_ids)) or any(not x for x in run_ids): errors.append("run_id must be present and unique")
    emission_ids = [r.get("emission_id") for r in emissions]
    if len(emission_ids) != len(set(emission_ids)) or any(not x for x in emission_ids): errors.append("emission_id must be present and unique")
    by_run: dict[str, list[dict[str, Any]]] = {str(x): [] for x in run_ids if x}
    for e in emissions:
        if e.get("run_id") not in by_run: errors.append(f"emission {e.get('emission_id')} has unknown run_id")
        else:
            by_run[e["run_id"]].append(e)
            owner = next((r for r in runs if r.get("run_id") == e.get("run_id")), {})
            if e.get("tool") != owner.get("tool"): errors.append(f"emission {e.get('emission_id')} tool differs from execution")
        if e.get("check_id") == "unmapped": errors.append(f"unmapped headline {e.get('emission_id')}")
        if e.get("tool") not in TOOLS: errors.append(f"invalid tool for {e.get('emission_id')}")
        if not isinstance(e.get("seq"), int) or e.get("seq", 0) < 1: errors.append(f"invalid seq for {e.get('emission_id')}")
        if e.get("check_id") != "unmapped" and e.get("check_id") not in {f"{tool}.{cid}" for tool, rows in CATALOG.items() for cid, _ in rows}:
            errors.append(f"unknown check_id for {e.get('emission_id')}")
        if e.get("tool") in TOOLS:
            expected_check = classify(e["tool"], str(e.get("headline", "")))
            if e.get("check_id") != expected_check: errors.append(f"{e.get('emission_id')} check_id disagrees with raw headline")
            if e.get("fingerprint") != fingerprint(e["tool"], expected_check, str(e.get("headline", ""))): errors.append(f"{e.get('emission_id')} fingerprint disagrees with raw headline")
    for run in runs:
        for key in ("campaign_id", "scenario_id", "correlation_id"):
            if not safe_id(str(run.get(key, ""))): errors.append(f"{run.get('run_id')} invalid {key}")
        if run.get("tool") not in TOOLS: errors.append(f"{run.get('run_id')} invalid tool")
        if run.get("state") not in ("baseline", "probe", "mutation"): errors.append(f"{run.get('run_id')} invalid state")
        if not isinstance(run.get("argv"), list) or not run["argv"]: errors.append(f"{run.get('run_id')} missing argv")
        if not isinstance(run.get("tool_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", run["tool_sha256"]): errors.append(f"{run.get('run_id')} invalid tool_sha256")
        manifest_hashes = run.get("source_manifest")
        if not isinstance(manifest_hashes, dict) or set(manifest_hashes) != {"scripts/python/validate_blueprint.py", "scripts/python/apply_blueprint.py", "scripts/python/_blueprint_parse.py", "scripts/bash/validate-scaffold.sh"} or not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in manifest_hashes.values()):
            errors.append(f"{run.get('run_id')} invalid four-file source_manifest")
        elif any(not (out / "source" / digest).is_file() or sha256(out / "source" / digest) != digest for digest in manifest_hashes.values()):
            errors.append(f"{run.get('run_id')} source_manifest does not match content-addressed snapshot")
        elif run.get("tool_sha256") != manifest_hashes.get(f"scripts/python/{TOOLS[run.get('tool')]}" if run.get("tool") in ("validate", "apply") else "scripts/bash/validate-scaffold.sh"):
            errors.append(f"{run.get('run_id')} tool_sha256 disagrees with source_manifest")
        for key in ("stdout", "stderr"):
            if not safe_relative(run.get(key)):
                errors.append(f"{run.get('run_id')} unsafe {key} path")
                continue
            p = out / str(run.get(key, ""))
            digest_key = f"{key}_sha256"
            if not p.is_file(): errors.append(f"{run.get('run_id')} missing {key} raw log")
            elif sha256(p) != run.get(digest_key): errors.append(f"{run.get('run_id')} {key} hash mismatch")
        actual = len(by_run.get(run.get("run_id"), []))
        if run.get("headline_count") != actual: errors.append(f"{run.get('run_id')} headline_count={run.get('headline_count')} but {actual} emission rows")
        if not safe_relative(run.get("stdout")) or not safe_relative(run.get("stderr")):
            continue
        stdout_path, stderr_path = out / str(run.get("stdout", "")), out / str(run.get("stderr", ""))
        if not stdout_path.is_file() or not stderr_path.is_file():
            continue
        stdout = stdout_path.read_text(encoding="utf-8")
        stderr = stderr_path.read_text(encoding="utf-8")
        parsed = parsed_tool_events(stdout, stderr)
        observed = sorted((x.get("seq"), x.get("kind"), x.get("mark"), x.get("headline"), x.get("stream"), x.get("line")) for x in by_run[run["run_id"]])
        expected = [(n, x["kind"], x["mark"], x["headline"], x["stream"], x["line"]) for n, x in enumerate(parsed, 1)]
        if observed != expected: errors.append(f"{run.get('run_id')} emission rows do not match raw logs")
    valid_classes = {"actionable", "informational", "noise", "unknown"}
    seen_adjudications: set[str] = set()
    for a in adjudications:
        eid = a.get("emission_id")
        if eid not in set(emission_ids): errors.append(f"adjudication refers to unknown emission {eid}")
        if eid in seen_adjudications: errors.append(f"duplicate adjudication for {eid}")
        seen_adjudications.add(eid)
        if a.get("classification") not in valid_classes: errors.append(f"invalid classification for {eid}")
        if not a.get("reason"): errors.append(f"missing adjudication reason for {eid}")
        if not a.get("adjudicator"): errors.append(f"missing adjudicator for {eid}")
        evidence = a.get("evidence")
        if not safe_relative(evidence) or not (out / str(evidence)).is_file(): errors.append(f"missing adjudication evidence for {eid}")
    pending = set(emission_ids) - seen_adjudications
    if pending: errors.append(f"pending adjudication: {', '.join(sorted(pending))}")
    if errors:
        print("S7 ledger INVALID:")
        for err in errors: print(f"  - {err}")
        return 1
    print(f"S7 ledger valid: {len(runs)} executions, {len(emissions)} headlines, {len(adjudications)} adjudications.")
    return 0


def summarize(args: argparse.Namespace) -> int:
    if validate(args):
        return 1
    out = Path(args.out); runs = read_jsonl(out / "executions.jsonl"); emissions = read_jsonl(out / "emissions.jsonl")
    adjudications = {x.get("emission_id"): x for x in read_jsonl(out / "adjudications.jsonl")}
    print("tool\truns\tzero-headline-runs\theadline-runs\theadlines\tunmapped\tpending\tunique-correlations")
    for tool in TOOLS:
        rr = [r for r in runs if r.get("tool") == tool]; ee = [e for e in emissions if e.get("tool") == tool]
        with_head = {e.get("run_id") for e in ee}
        print(f"{tool}\t{len(rr)}\t{sum(not r.get('headline_count') for r in rr)}\t{len(with_head)}\t{len(ee)}\t{sum(e.get('check_id') == 'unmapped' for e in ee)}\t{sum(e.get('emission_id') not in adjudications for e in ee)}\t{len({r.get('correlation_id') for r in rr})}")
    print("\ncheck_id\theadline-runs\theadlines\tunique-scenarios\tunique-correlations\tactionable\tinformational\tnoise\tunknown")
    for check in sorted({e.get("check_id") for e in emissions}):
        ee = [e for e in emissions if e.get("check_id") == check]
        rr = {e.get("run_id") for e in ee}; source = [r for r in runs if r.get("run_id") in rr]
        labels = [adjudications.get(e.get("emission_id"), {}).get("classification") for e in ee]
        print(f"{check}\t{len(rr)}\t{len(ee)}\t{len({r.get('scenario_id') for r in source})}\t{len({r.get('correlation_id') for r in source})}\t" + "\t".join(str(labels.count(x)) for x in ("actionable", "informational", "noise", "unknown")))
    print("\nPer-check eligible runs are not inferred: an absent headline is only a zero-headline run, not a pass for every check.")
    return 0


def adjudicate(args: argparse.Namespace) -> int:
    out = Path(args.out)
    known = {row.get("emission_id") for row in read_jsonl(out / "emissions.jsonl")}
    if args.emission_id not in known:
        die(f"unknown emission_id {args.emission_id}")
    if any(row.get("emission_id") == args.emission_id for row in read_jsonl(out / "adjudications.jsonl")):
        die(f"duplicate adjudication for {args.emission_id}")
    append_jsonl(out / "adjudications.jsonl", {"schema": SCHEMA, "emission_id": args.emission_id,
                 "classification": args.classification, "reason": args.reason,
                 "adjudicator": args.adjudicator, "evidence": args.evidence})
    print(f"{args.emission_id}: {args.classification}")
    return 0


def collect(args: argparse.Namespace) -> int:
    """Run a portable explicit manifest.  It never discovers commands heuristically."""
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    runs = manifest.get("runs")
    if not isinstance(runs, list) or not runs:
        die("manifest needs a non-empty explicit runs list")
    out = Path(args.out).resolve()
    lock = acquire_collect_lock(out)
    roots: dict[str, str] = {}
    for item in args.project_root:
        if "=" not in item: die("--project-root must be PROJECT=/absolute/clone/path")
        key, value = item.split("=", 1); roots[key] = str(Path(value).resolve())
    extension = Path(args.extension_root).resolve() if args.extension_root else None
    if extension:
        try:
            source_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=extension, text=True).strip()
            source_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=extension, text=True).strip())
        except (OSError, subprocess.CalledProcessError):
            die("--extension-root must be a Git worktree so source revision is provenance")
        provenance = {"schema": SCHEMA, "source_revision": source_head, "source_dirty_snapshot": source_dirty,
                      "collector_sha256": sha256(Path(__file__).resolve()), "catalog_sha256": hashlib.sha256(repr(CATALOG).encode()).hexdigest(),
                      "project_capsule": manifest.get("source_projects")}
        prior = Path(args.out) / "provenance.json"
        if prior.exists() and json.loads(prior.read_text(encoding="utf-8")) != provenance:
            die("existing output has different collector/source provenance")
        Path(args.out).mkdir(parents=True, exist_ok=True); prior.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = 0
    prepared: set[str] = set()
    try:
        for run in runs:
            project = run.get("project")
            if project not in roots: die(f"no --project-root for project {project!r}")
            root = Path(roots[project])
            if extension and project not in prepared:
                dest = root / ".specify/extensions/blueprint"
                if dest.exists() and not args.replace_extension:
                    die("--extension-root needs --replace-extension (only use a disposable full-history clone)")
                if dest.exists(): shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True); shutil.copytree(extension, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
                prepared.add(project)
            command = [str(x).replace("{project_root}", str(root)) for x in run.get("argv", [])]
            ns = argparse.Namespace(out=args.out, run_id=run.get("run_id"), campaign=manifest.get("campaign_id"),
                scenario=run.get("scenario_id"), correlation=run.get("correlation_id"), state=run.get("state"),
                tool=run.get("tool"), cwd=str(root), timeout=run.get("timeout", 300), command=command)
            if not all((ns.run_id, ns.campaign, ns.scenario, ns.correlation, ns.state, ns.tool)):
                die(f"manifest run missing required field: {run}")
            code = record(ns); status = status or code
        return status
    finally:
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("record"); p.set_defaults(fn=record)
    p.add_argument("--out", required=True); p.add_argument("--run-id", required=True); p.add_argument("--campaign", required=True)
    p.add_argument("--scenario", required=True); p.add_argument("--correlation", required=True); p.add_argument("--state", choices=("baseline", "probe", "mutation"), required=True)
    p.add_argument("--tool", choices=sorted(TOOLS), required=True); p.add_argument("--cwd", required=True); p.add_argument("--timeout", type=int, default=300); p.add_argument("command", nargs=argparse.REMAINDER)
    for name, fn in (("validate", validate), ("summarize", summarize)):
        p = sub.add_parser(name); p.set_defaults(fn=fn); p.add_argument("--out", required=True); p.add_argument("--manifest")
    p = sub.add_parser("adjudicate"); p.set_defaults(fn=adjudicate); p.add_argument("--out", required=True)
    p.add_argument("--emission-id", required=True); p.add_argument("--classification", choices=("actionable", "informational", "noise", "unknown"), required=True)
    p.add_argument("--reason", required=True); p.add_argument("--adjudicator", required=True); p.add_argument("--evidence", required=True)
    p = sub.add_parser("collect"); p.set_defaults(fn=collect); p.add_argument("--out", required=True); p.add_argument("--manifest", required=True)
    p.add_argument("--project-root", action="append", default=[]); p.add_argument("--extension-root")
    p.add_argument("--replace-extension", action="store_true")
    args = parser.parse_args()
    return args.fn(args)

if __name__ == "__main__":
    sys.exit(main())
