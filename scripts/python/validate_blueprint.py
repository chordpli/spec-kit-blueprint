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

SCRIPT_VERSION = "1.1.0"

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

    print(f"{CYAN}=== Blueprint Document Validator {SCRIPT_VERSION} ==={NC}")
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

    # A Before block quotes real lines so the reader can find the spot, and applying the
    # pair replaces that whole region — so an anchor at its edges that the After does not
    # reproduce is deleted from the file, usually a brace or a doc-comment opener the task
    # never meant to touch, and the build breaks somewhere else entirely.
    #
    # Only the edges are checked. Interior lines are what the task is there to change, and
    # comparing those reports every legitimate edit. Position matters too: an identical
    # token elsewhere in the After is not the one that was dropped.
    STRUCTURAL = re.compile(r"^(?:[)}\]]+[;,]?|/\*\*|\*/|\{|\)\s*[;{]?)$")

    def edge_anchors(block: str) -> tuple[list[str], list[str]]:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        return lines[:2], lines[-3:]

    lossy = []
    for tid, sec in sections.items():
        for before, after in re.findall(
            r"\*\*Before\*\*[^\n]*\n+```\w*\n(.*?)```.*?\*\*After\*\*[^\n]*\n+```\w*\n(.*?)```", sec, re.S
        ):
            b_head, b_tail = edge_anchors(before)
            a_lines = [ln.strip() for ln in after.split("\n") if ln.strip()]
            a_head, a_tail = a_lines[:5], a_lines[-5:]
            for anchors, region, where in ((b_head, a_head, "opening"), (b_tail, a_tail, "closing")):
                for t in anchors:
                    if not STRUCTURAL.match(t) or t in region:
                        continue
                    lossy.append(f"{tid}: Before's {where} anchor {t!r} is not in the After's {where} lines")
                    break
    if lossy:
        record(
            "fail",
            "Before quotes an edge anchor the After does not return — applying it deletes that line",
            "\n".join(lossy[:6]),
        )
    else:
        record("pass", "no Before/After pair silently drops an edge anchor")

    # 4. Multi-file tasks map each block to a path
    print(f"\n{CYAN}[4] Multi-file task labels{NC}")
    unlabeled = []
    for tid, sec in sections.items():
        paths = file_paths(sec)
        authored = strip_quoted(sec)
        blocks = len(re.findall(r"^```[a-zA-Z]", authored, re.M))
        if len(paths) > 1 and blocks > 1:
            # A label may be followed by anything — ":", " (new):", " — **Replace entire
            # file**". Requiring a colon counted four labelled blocks as one.
            labels = len(re.findall(r"\*\*`[^`]+\.[A-Za-z0-9]{1,6}`\*\*", authored))
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

    # 6. Cited requirements are reproduced, not just named. A task header pointing at
    #    "FR-002" is useless to a reader working from this document alone if FR-002's text
    #    lives only in spec.md — the rule exists, but nothing enforced it until here.
    print(f"\n{CYAN}[6] Cited requirements reproduced{NC}")
    ID_RE = r"\b((?:FR|NFR|SC|AC|US)[- ]?\d+(?:\.\d+)*)\b"
    cited: set[str] = set()
    for sec in sections.values():
        for line in sec.split("\n"):
            if line.strip().startswith("**Requirements**"):
                cited |= {m.group(1) for m in re.finditer(ID_RE, line)}
    # Where else does the id appear? A citation line does not count as reproduction.
    non_citation = "\n".join(
        ln for ln in bp.split("\n") if not ln.strip().startswith("**Requirements**")
    )
    missing = sorted(
        cid for cid in cited
        # The id may be wrapped in markdown emphasis or backticks before its delimiter:
        # "- **FR-001**: Transfers MUST ..." reproduces the requirement just as well.
        if not re.search(re.escape(cid) + r"[*`_\s]*[|:\-–—)]", non_citation)
    )
    if not cited:
        record("warn", "no **Requirements** citations found in task headers")
    elif missing:
        record(
            "fail",
            f"{len(missing)} cited requirement(s) never stated in the document",
            ", ".join(missing[:12]) + " — a reader working from this file alone cannot look them up",
        )
    else:
        record("pass", f"all {len(cited)} cited requirement ids are stated in the document")

    # 7. Open questions — not pass/fail, but a blocked task is the thing a reader
    #    most needs to see before they start typing.
    oq = re.search(r"^##+\s*Open Questions\b(.*?)(?=^##\s|\Z)", bp, re.M | re.S)
    if oq:
        body = oq.group(1)
        # Two shapes in the wild: a table of rows, or a heading per question.
        rows = [ln for ln in body.split("\n") if ln.strip().startswith("|")]
        rows = [r for r in rows if not re.match(r"^\s*\|[\s|:-]+\|\s*$", r)]
        if rows:
            rows = rows[1:]  # drop the header row
            blocking = [r for r in rows if re.search(r"\|\s*(yes|y|예|blocking)\s*\|", r, re.I)]
        else:
            rows = re.findall(r"^#+\s*(OQ-\d+[^\n]*)", body, re.M)
            blocking = [r for r in rows if re.search(r"blocking|blocks|차단", r, re.I)
                        and not re.search(r"non-?blocking|미차단", r, re.I)]
        print(f"\n{CYAN}[7] Open questions{NC}")
        record(
            "warn" if blocking else "pass",
            f"{len(rows)} open question(s), {len(blocking)} blocking",
            "blocking items must be answered before the tasks they block can be typed" if blocking else "",
        )

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
