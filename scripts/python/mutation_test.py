#!/usr/bin/env python3
"""Plant the seven named R12 regressions and require self_test.py to kill each one."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, shutil, subprocess, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]

def replace_one(path: pathlib.Path, old: str, new: str) -> None:
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError(f"expected exactly one patch target in {path}")
    path.write_text(text.replace(old, new, 1))

def digest(root: pathlib.Path) -> str:
    h = hashlib.sha256()
    paths = [root / rel for rel in (
        "scripts/python/_blueprint_parse.py", "scripts/python/validate_blueprint.py",
        "scripts/python/apply_blueprint.py", "scripts/bash/validate-scaffold.sh",
        "scripts/python/self_test.py", "scripts/python/mutation_test.py",
    )]
    paths += [p for p in (root / "tests" / "fixtures").rglob("*")
              if p.is_file() and p.name != "README.md" and p.suffix != ".pyc"]
    for path in sorted(paths):
        h.update(str(path.relative_to(root)).encode()); h.update(b"\0")
        h.update(path.read_bytes()); h.update(b"\0")
    return h.hexdigest()

MUTATIONS = {
 "REG3": ("scripts/python/apply_blueprint.py", "    for relp in claimed:\n        os.remove(os.path.join(tree, relp))\n", "    for relp, _ids in orphans:\n        os.remove(os.path.join(tree, relp))\n"),
 "REG4": ("scripts/python/apply_blueprint.py", """    tail = lines[-limit:]
    rx = pattern or ERROR_LINE
    first = next((i for i, ln in enumerate(lines) if rx.search(ln)), None)
    if first is None or first >= len(lines) - limit:
        return tail
    head_n = max(1, min(8, limit // 2))
    head = lines[first:first + head_n]
    return head + [f"      ... ({len(lines) - len(head) - (limit - head_n) - first} line(s) not shown)"] \\
        + lines[-(limit - head_n):]
""", "    return lines[-limit:]\n"),
 "RX1": ("scripts/python/_blueprint_parse.py", """MARKER_CALL = re.compile(
    r"TODO\\(blueprint\\)"
    r"|(?:TODO|NotImplementedError|UnsupportedOperationException|NotImplementedException"
    r"|fatalError|todo!|unimplemented!|panic)\\s*\\(\\s*[\\\"\\'`]"
    r"|throw\\s+new\\s+Error\\s*\\(\\s*[\\\"'`]\\s*T\\d{2,}\\s*:"
)
""", "MARKER_CALL = re.compile(r\"TODO\\(blueprint\\)\")\n"),
 "RX7": ("scripts/python/validate_blueprint.py", "            r\"|\\b[a-z_]\\w*\\s*\\(\\s*[a-z_]\\w*\\s*\\[[^\\]\\n]{1,12}\\]\\s*\\)\"\n", ""),
 "RX5": ("scripts/python/_blueprint_parse.py", "    return os.path.basename(token) in DOTLESS_FILES\n", "    return False\n"),
 "REG9": ("scripts/python/_blueprint_parse.py", "    def label_at_line(i: int) -> str:\n        if i in inside:\n            return \"\"\n        t = lines[i].strip()\n", "    def label_at_line(i: int) -> str:\n        t = lines[i].strip()\n"),
}
EXPECTED = {
    "REG3": "FAILED   REG3-foreign-untracked",
    "REG4": "FAILED   REG4-build-first-error",
    "RX1": "FAILED   RX1-marker-vocabulary",
    "RX3": "FAILED   authored-in-a-hunk",
    "RX7": "FAILED   prose-subscript-call",
    "RX5": "FAILED   RX5-dotless-path",
    "REG9": "FAILED   REG9-fenced-label",
}

def rx3(path: pathlib.Path) -> None:
    text=path.read_text(); start=text.index("        CODE_IN_PROSE = re.compile(\n")
    end=text.index("        )\n",start)+10
    path.write_text(text[:start]+'        CODE_IN_PROSE = re.compile(r"&&|\\|\\|")\n'+text[end:])

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output", type=pathlib.Path, required=True)
    ap.add_argument("--timeout", type=int, default=180); args=ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True); before=digest(ROOT); rows=[]
    for name in ("REG3","REG4","RX1","RX3","RX7","RX5","REG9"):
        print(f"[{name}] planting mutation", flush=True)
        tmp=pathlib.Path(tempfile.mkdtemp(prefix=f"blueprint-{name}-")); tree=tmp/"tree"
        try:
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".omc", "__pycache__"))
            try:
                if name == "RX3": rx3(tree/"scripts/python/validate_blueprint.py")
                else:
                    rel,old,new=MUTATIONS[name]; replace_one(tree/rel,old,new)
                patch="applied"
            except Exception as exc:
                patch=f"patch_error: {exc}"; rows.append({"mutation":name,"status":"patch_error","detail":str(exc)}); continue
            diff=subprocess.run(["git","diff","--no-index",str(ROOT/("scripts/python/validate_blueprint.py" if name in ("RX3","RX7") else MUTATIONS[name][0])),str(tree/("scripts/python/validate_blueprint.py" if name in ("RX3","RX7") else MUTATIONS[name][0]))],capture_output=True,text=True)
            (args.output/f"{name}.diff").write_text(diff.stdout)
            try:
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
                proc=subprocess.run(["python3","scripts/python/self_test.py"],cwd=tree,
                                    capture_output=True,text=True,timeout=args.timeout,env=env)
                expected = EXPECTED[name]
                if proc.returncode not in (0, 1):
                    status = "execution_error"
                else:
                    status="detected" if proc.returncode == 1 and expected in proc.stdout else "survived"
                (args.output/f"{name}.stdout").write_text(proc.stdout); (args.output/f"{name}.stderr").write_text(proc.stderr)
                rows.append({"mutation":name,"status":status,"exit":proc.returncode,
                             "expected_failure":expected,"expected_seen":expected in proc.stdout,
                             "patch":patch})
                print(f"[{name}] {status} (exit {proc.returncode})", flush=True)
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                (args.output/f"{name}.stdout").write_text(stdout)
                (args.output/f"{name}.stderr").write_text(stderr)
                rows.append({"mutation":name,"status":"timeout","timeout":args.timeout})
                print(f"[{name}] timeout after {args.timeout}s", flush=True)
        finally: shutil.rmtree(tmp,ignore_errors=True)
    after=digest(ROOT); result={"baseline_sha256_before":before,"baseline_sha256_after":after,"baseline_unchanged":before==after,"results":rows}
    (args.output/"results.json").write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result,indent=2))
    return 0 if before==after and len(rows)==7 and all(r["status"]=="detected" for r in rows) else 1

if __name__ == "__main__": raise SystemExit(main())
