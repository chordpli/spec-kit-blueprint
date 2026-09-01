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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _blueprint_parse import (  # noqa: E402  (path set above)
    file_kinds,
    file_paths,
    repo_root,
    resolve_feature_dir,
    split_tasks,
    strip_quoted,
)

GREEN, YELLOW, RED, CYAN, NC = "\033[0;32m", "\033[0;33m", "\033[0;31m", "\033[0;36m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = YELLOW = RED = CYAN = NC = ""

SCRIPT_VERSION = "1.2.0"

results: list[tuple[str, str, str]] = []  # (status, name, evidence)


def record(status: str, name: str, evidence: str = "") -> None:
    results.append((status, name, evidence))
    mark = {"pass": f"{GREEN}✓{NC}", "warn": f"{YELLOW}⚠{NC}", "fail": f"{RED}✗{NC}"}[status]
    print(f"  {mark} {name}")
    if evidence:
        for line in evidence.split("\n"):
            print(f"      {line}")


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
    sections = dict(split_tasks(bp))
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
    out_of_range, identical, ambiguous = [], [], []
    for tid, sec in sections.items():
        # Check against the longest file the task declares: a Before block belongs to one
        # of them, and citing only the first path silently skipped multi-file tasks.
        # Per file, not per task. Taking the longest of a task's files as the bound lets a
        # 60-line citation against a 37-line file hide behind a 74-line sibling.
        lengths = {}
        for rel in file_paths(sec):
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                lengths[rel] = len(open(path, encoding="utf-8", errors="replace").read().splitlines())
        if lengths:
            shortest = min(lengths.values())
            for bm in re.finditer(r"\*\*Before\*\*[^\n]*?\blines?[^\d]{0,4}(\d+)", sec):
                n = int(bm.group(1))
                # A Before block does not say which of the task's files it quotes, so a
                # citation is out of range only when it exceeds every candidate.
                if n > max(lengths.values()):
                    out_of_range.append(
                        f"{tid}: line {n} > {max(lengths.values())} lines, the longest file it declares"
                    )
                elif n > shortest and len(lengths) > 1:
                    over = [f"{f} ({ln})" for f, ln in sorted(lengths.items()) if n > ln]
                    ambiguous.append(f"{tid}: line {n} is past the end of {', '.join(over)}")
        for before, after in re.findall(
            r"\*\*Before\*\*[^\n]*\n+```\w*\n(.*?)```.*?\*\*After\*\*[^\n]*\n+```\w*\n(.*?)```", sec, re.S
        ):
            if before.strip() == after.strip():
                identical.append(tid)
    if out_of_range:
        record("fail", "Before block cites a line past the end of its file", "\n".join(out_of_range[:6]))
    else:
        record("pass", "Before line references are within their files")
    if ambiguous:
        record(
            "warn",
            "a Before citation is out of range for some of its task's files",
            "\n".join(ambiguous[:6]) + "\nname the file the block quotes so the reference can be checked",
        )
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

    # A modify task's code has to say where it goes. Prose like "append this at the end of
    # the file" reads fine and is not a position, so the applier cannot place it — better to
    # hear that here than after a build fails.
    unanchored = []
    for tid, sec in sections.items():
        kinds = re.findall(r"`[^`]+`\s*\((new|modify|delete)[^)]*\)", sec)
        if "modify" not in kinds:
            continue
        if re.search(r"\*\*Replace entire file\*\*", sec):
            continue
        blocks = len(re.findall(r"^```[a-zA-Z]", sec, re.M))
        anchored = len(re.findall(r"\*\*Before\*\*[^\n]*\n+```", sec)) * 2
        # A task may create new files and edit an existing one in the same breath. A block
        # introduced by its own path label is that whole new file, and has nothing to anchor to.
        labelled_new = len(re.findall(r"\*\*`[^`]+`\*\*[^\n]*:\s*\n+```", sec))
        if blocks - labelled_new > anchored:
            unanchored.append(f"{tid}: {blocks - labelled_new - anchored} block(s) with no Before/After or Replace marker")
    if unanchored:
        record(
            "warn",
            "modify task has code that is not anchored to a position",
            "\n".join(unanchored[:6]) + "\nthe applier cannot place these; quote the surrounding lines in a Before block",
        )
    else:
        record("pass", "every modify task anchors its code")

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

    # 6. Staleness — the header records what the blueprint was built from, so drift is a
    #    fact to check rather than something everyone assumes away.
    print(f"\n{CYAN}[6] Freshness{NC}")
    src_line = next((ln for ln in bp.split("\n") if ln.lower().startswith("**sources**")), "")
    if not src_line:
        record("warn", "no **Sources** stamp — staleness cannot be checked (regenerate to add one)")
    else:
        import hashlib

        stale, unknown = [], []
        for name, want in re.findall(r"([\w.\-/]+\.\w+)@([0-9a-f]{6,64})", src_line):
            path = os.path.join(feature_dir, os.path.basename(name))
            if not os.path.isfile(path):
                path = os.path.join(root, name)
            if not os.path.isfile(path):
                unknown.append(name)
                continue
            got = hashlib.sha256(open(path, "rb").read()).hexdigest()[: len(want)]
            if got != want:
                stale.append(f"{name}: stamped {want}, now {got}")
        if stale:
            record(
                "fail",
                f"{len(stale)} source artifact(s) changed since this blueprint was generated",
                "\n".join(stale) + "\nregenerate, or say in the document why the difference is fine",
            )
        elif unknown:
            record("warn", "stamped sources not found on disk", ", ".join(unknown))
        else:
            record("pass", "every stamped source artifact still matches")

    # 7. Cited requirements are reproduced, not just named. A task header pointing at
    #    "FR-002" is useless to a reader working from this document alone if FR-002's text
    #    lives only in spec.md — the rule exists, but nothing enforced it until here.
    print(f"\n{CYAN}[7] Cited requirements reproduced{NC}")
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
        print(f"\n{CYAN}[8] Open questions{NC}")
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
