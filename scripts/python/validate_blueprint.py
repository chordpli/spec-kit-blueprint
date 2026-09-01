#!/usr/bin/env python3
"""validate_blueprint.py — check the blueprint document itself.

`validate-scaffold.sh` checks what a blueprint put on disk. This checks the
document: whether every task from tasks.md survived into it, whether each task
carries its rationale, and whether its claims about the working tree hold.

These are format-level checks, so they apply to any language or project.

Usage: python3 validate_blueprint.py [feature-dir] [--quiet]
  feature-dir: specs/{feature}/ (default: auto-detect from the current branch)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

GREEN, YELLOW, RED, CYAN, NC = "\033[0;32m", "\033[0;33m", "\033[0;31m", "\033[0;36m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = YELLOW = RED = CYAN = NC = ""

results: list[tuple[str, str, str]] = []  # (status, name, evidence)


def record(status: str, name: str, evidence: str = "") -> None:
    results.append((status, name, evidence))
    mark = {"pass": f"{GREEN}✓{NC}", "warn": f"{YELLOW}⚠{NC}", "fail": f"{RED}✗{NC}"}[status]
    print(f"  {mark} {name}")
    if evidence:
        for line in evidence.split("\n"):
            print(f"      {line}")


def repo_root() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return os.getcwd()


def resolve_feature_dir(root: str, arg: str | None) -> str:
    if arg:
        return arg if os.path.isabs(arg) else os.path.join(root, arg)
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        branch = ""
    m = re.match(r"^(\d{3}|\d{8})-", branch)
    specs = os.path.join(root, "specs")
    if m and os.path.isdir(specs):
        for name in sorted(os.listdir(specs)):
            if name.startswith(m.group(1)):
                return os.path.join(specs, name)
    return ""


def split_tasks(text: str) -> dict[str, str]:
    """Task id -> its section, from `### T001 ...` up to the next task heading."""
    return {
        m.group(1): m.group(0)
        for m in re.finditer(r"^### (T\d+)\b.*?(?=^### T\d+|\Z)", text, re.M | re.S)
    }


def strip_quoted(section: str) -> str:
    """Drop Before/After blocks — they quote existing code, not authored content."""
    return re.sub(r"\*\*(?:Before|After)\*\*[^\n]*\n+```\w*\n.*?```", "", section, flags=re.S)



FILE_DECL = re.compile(r"\*\*File\*\*:(.*?)(?:\n\s*\n|\n(?=\*\*))", re.S)


def file_paths(section: str) -> list[str]:
    """Every path in a task's **File**: declaration, which may wrap onto later lines."""
    m = FILE_DECL.search(section)
    if not m:
        return []
    return [
        p for p in re.findall(r"`([^`]+)`", m.group(1))
        if re.search(r"\.[A-Za-z0-9]{1,6}$", p)
    ]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = repo_root()
    feature_dir = resolve_feature_dir(root, args[0] if args else None)

    if not feature_dir or not os.path.isdir(feature_dir):
        print(f"{RED}ERROR: feature directory not found.{NC}")
        print("Usage: validate_blueprint.py [specs/NNN-feature-name]")
        return 2

    bp_path = os.path.join(feature_dir, "blueprint.md")
    tasks_path = os.path.join(feature_dir, "tasks.md")

    print(f"{CYAN}=== Blueprint Document Validator ==={NC}")
    print(f"Feature: {os.path.relpath(feature_dir, root)}")

    if not os.path.isfile(bp_path):
        print(f"\n{RED}blueprint.md not found — run /speckit.blueprint.generate first.{NC}")
        return 1

    bp = open(bp_path, encoding="utf-8", errors="replace").read()
    sections = split_tasks(bp)
    mode_line = next((ln for ln in bp.split("\n") if ln.lower().startswith("**mode**:")), "")
    mode = (mode_line.split(":", 1)[1].strip().split()[0].lower() if ":" in mode_line else "unknown")
    print(f"Mode: {mode} | {len(bp.splitlines())} lines | {len(sections)} task sections\n")

    # 1. Coverage — every task id in tasks.md reaches the blueprint
    print(f"{CYAN}[1] Task coverage{NC}")
    if os.path.isfile(tasks_path):
        tasks_text = open(tasks_path, encoding="utf-8", errors="replace").read()
        declared = set(re.findall(r"^\s*-\s*\[[ xX]\]\s*(T\d+)\b", tasks_text, re.M))
        present = set(sections) | set(re.findall(r"\b(T\d+)\b", bp))
        missing = sorted(declared - present)
        if not declared:
            record("warn", "no task ids found in tasks.md (check its format)")
        elif missing:
            record("fail", f"{len(missing)} task(s) from tasks.md missing", ", ".join(missing[:12]))
        else:
            record("pass", f"all {len(declared)} tasks from tasks.md appear")
    else:
        record("warn", "tasks.md not found — coverage not checked")

    # 2. Rationale — every task states why it looks the way it does
    print(f"\n{CYAN}[2] Rationale (Why){NC}")
    no_why = sorted(tid for tid, sec in sections.items() if "**Why**" not in sec)
    if not sections:
        record("warn", "no task sections found (check blueprint format)")
    elif no_why:
        record("fail", f"{len(no_why)} task(s) without a Why", ", ".join(no_why[:12]))
    else:
        record("pass", f"all {len(sections)} task sections carry a Why")

    # 3. Before blocks quote something that is actually there
    print(f"\n{CYAN}[3] Working-tree claims{NC}")
    out_of_range, identical = [], []
    for tid, sec in sections.items():
        # Check against the longest file the task declares: a Before block belongs to one
        # of them, and citing only the first path silently skipped multi-file tasks.
        totals = []
        for rel in file_paths(sec):
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                totals.append(len(open(path, encoding="utf-8", errors="replace").read().splitlines()))
        if totals:
            total = max(totals)
            for bm in re.finditer(r"\*\*Before\*\*[^\n]*?\blines?[^\d]{0,4}(\d+)", sec):
                if int(bm.group(1)) > total:
                    out_of_range.append(f"{tid}: line {bm.group(1)} > {total} lines in file")
        for before, after in re.findall(
            r"\*\*Before\*\*[^\n]*\n+```\w*\n(.*?)```.*?\*\*After\*\*[^\n]*\n+```\w*\n(.*?)```", sec, re.S
        ):
            if before.strip() == after.strip():
                identical.append(tid)
    if out_of_range:
        record("fail", "Before block cites a line past the end of its file", "\n".join(out_of_range[:6]))
    else:
        record("pass", "Before line references are within their files")
    if identical:
        record(
            "fail",
            "Before and After are identical — the change is not a diff",
            ", ".join(sorted(set(identical))),
        )
    else:
        record("pass", "every After differs from its Before")

    # A Before block quotes real lines so the reader can find the spot. Applying the pair
    # replaces all of them, so any quoted line the After does not carry is deleted from the
    # file — usually an anchor the task never meant to touch, and the build breaks somewhere
    # else entirely. Blank lines and comment-fence noise are not evidence, so ignore them.
    lossy = []
    for tid, sec in sections.items():
        for before, after in re.findall(
            r"\*\*Before\*\*[^\n]*\n+```\w*\n(.*?)```.*?\*\*After\*\*[^\n]*\n+```\w*\n(.*?)```", sec, re.S
        ):
            after_lines = {ln.strip() for ln in after.split("\n") if ln.strip()}
            # Reformatting is not loss: a one-line doc comment respread over three lines
            # keeps its text. Compare on content alone before calling a line dropped.
            after_sig = re.sub(r"[^0-9A-Za-z]", "", after)
            for ln in before.split("\n"):
                t = ln.strip()
                if len(t) < 3 or t in after_lines:
                    continue
                sig = re.sub(r"[^0-9A-Za-z]", "", t)
                if len(sig) >= 12 and sig in after_sig:
                    continue
                # A structural line that vanished: closing braces and doc openers are the
                # ones that actually break compilation when swallowed.
                if t in ("}", "};", "*/", "/**", ")", "],", "}," ) or t.startswith(("/**", "* ", "}")):
                    lossy.append(f"{tid}: Before quotes {t!r}, After drops it")
                    break
    if lossy:
        record(
            "fail",
            "Before quotes a structural line the After does not return — applying it deletes that line",
            "\n".join(lossy[:6]),
        )
    else:
        record("pass", "no Before/After pair silently drops a quoted structural line")

    # 4. Multi-file tasks map each block to a path
    print(f"\n{CYAN}[4] Multi-file task labels{NC}")
    unlabeled = []
    for tid, sec in sections.items():
        paths = file_paths(sec)
        authored = strip_quoted(sec)
        blocks = len(re.findall(r"^```[a-zA-Z]", authored, re.M))
        if len(paths) > 1 and blocks > 1:
            labels = len(re.findall(r"\*\*`[^`]+\.[A-Za-z0-9]{1,6}`\*\*:", authored))
            if labels < blocks:
                unlabeled.append(f"{tid}: {len(paths)} files, {blocks} blocks, {labels} labeled")
    if unlabeled:
        record(
            "fail",
            "multi-file task does not label every code block with its path",
            "\n".join(unlabeled[:8]),
        )
    else:
        record("pass", "multi-file tasks label each code block")

    # 5. Placeholders — full-code modes forbid them; guide mode expects markers in bodies only
    print(f"\n{CYAN}[5] Placeholder content{NC}")
    ellipsis = []
    for tid, sec in sections.items():
        for blk in re.findall(r"```\w*\n(.*?)```", strip_quoted(sec), re.S):
            for ln in blk.split("\n"):
                if re.search(r"(//|#|/\*)\s*\.\.\.", ln):
                    ellipsis.append(f"{tid}: {ln.strip()[:60]}")
    if ellipsis:
        record("fail", "ellipsis placeholder in a code block", "\n".join(ellipsis[:6]))
    else:
        record("pass", "no ellipsis placeholders")

    if mode in ("doc-only", "scaffold"):
        stubs = []
        for tid, sec in sections.items():
            for blk in re.findall(r"```\w*\n(.*?)```", strip_quoted(sec), re.S):
                if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", blk):
                    stubs.append(tid)
        if stubs:
            record(
                "fail",
                f"{mode} blueprint contains stub markers in code blocks",
                ", ".join(sorted(set(stubs))[:10]),
            )
        else:
            record("pass", f"{mode} blueprint has no stub markers")

    print(f"\n{CYAN}=== Summary ==={NC}")
    counts = {k: sum(1 for r in results if r[0] == k) for k in ("pass", "warn", "fail")}
    print(f"  {GREEN}PASS{NC}: {counts['pass']}  {YELLOW}WARN{NC}: {counts['warn']}  {RED}FAIL{NC}: {counts['fail']}")
    if counts["fail"]:
        print(f"\n{RED}Validation FAILED — {counts['fail']} issue(s) found{NC}")
        return 1
    print(f"\n{GREEN}All checks passed{NC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
