#!/usr/bin/env python3
"""validate_blueprint.py — check the blueprint document itself.

`validate-scaffold.sh` checks what a blueprint put on disk. This checks the
document: whether every task from tasks.md survived into it, whether each task
carries its rationale, and whether its claims about the working tree hold.

These are format-level checks, so they apply to any language or project.

Usage: python3 validate_blueprint.py [feature-dir]
  feature-dir: specs/{feature}/ (default: auto-detect from the current branch)
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _blueprint_parse import (  # noqa: E402  (path set above)
    BEFORE_AFTER_RE,
    base_chain,
    before_labels,
    body_replaced_by_marker,
    changed_since,
    dependent_slices,
    code_blocks,
    count_path_labels,
    file_kinds,
    file_paths,
    looks_like_path,
    outside_fences,
    parse_mode,
    repo_root,
    resolve_feature_dir,
    section_events,
    split_tasks,
    stamped_head,
    strip_quoted,
)

SKIP_DIRS = {"node_modules", "venv", ".venv", "target", "build", "dist", "out", "__pycache__", "specs"}

GREEN, YELLOW, RED, CYAN, NC = "\033[0;32m", "\033[0;33m", "\033[0;31m", "\033[0;36m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = YELLOW = RED = CYAN = NC = ""

SCRIPT_VERSION = "1.2.0"

results: list[tuple[str, str, str]] = []  # (status, name, evidence)


# A run prints twenty-odd green ticks and hides its warnings among them. Measured over one
# repository: 92% of the lines this script produced were passes, and a reader looking for
# the one warning in section [3] read eighteen of them first. A pass that carries evidence
# still prints — it is saying something the reader needs. A pass that carries none is
# counted. `--verbose` restores the old listing.
VERBOSE = False
_pending_pass = 0
_cur_title = ""
_printed_any = False
_cur_lines: list[str] = []


def flush_passes() -> None:
    """Print the section just finished: its findings, or one line saying it had none."""
    global _pending_pass, _cur_title, _cur_lines, _printed_any
    if not _cur_title and not _cur_lines and not _pending_pass:
        return
    lead = "" if not _printed_any else "\n"
    _printed_any = True
    if _cur_lines:
        print(f"{lead}{CYAN}{_cur_title}{NC}")
        for ln in _cur_lines:
            print(ln)
        if _pending_pass:
            print(f"  {GREEN}✓{NC} {_pending_pass} other check(s) passed")
    elif _cur_title:
        print(f"{lead}{CYAN}{_cur_title}{NC} {GREEN}— {_pending_pass} check(s) passed{NC}")
    _pending_pass = 0
    _cur_lines = []
    _cur_title = ""


def section(title: str, *, first: bool = False) -> None:
    global _cur_title
    flush_passes()
    _cur_title = title


def record(status: str, name: str, evidence: str = "") -> None:
    global _pending_pass
    results.append((status, name, evidence))
    if status == "pass" and not evidence and not VERBOSE:
        _pending_pass += 1
        return
    mark = {"pass": f"{GREEN}✓{NC}", "warn": f"{YELLOW}⚠{NC}", "fail": f"{RED}✗{NC}"}[status]
    _cur_lines.append(f"  {mark} {name}")
    if evidence:
        for line in evidence.split("\n"):
            _cur_lines.append(f"      {line}")


def listing(rows, limit: int = 6, sep: str = "\n") -> str:
    """The first `limit` rows, and — when there are more — how many were left out.

    A truncated list that does not say it is truncated is a count the reader gets wrong.
    Twenty-nine misnumbered Before headers were reported as six, and the other twenty-three
    went unmentioned; the applier had already learned to say `(+N more)` and the checker
    that fires on every run had not.
    """
    rows = list(rows)
    out = sep.join(rows[:limit])
    if len(rows) > limit:
        out += f"{sep}(+{len(rows) - limit} more)"
    return out



def after_additions(sec: str) -> list[str]:
    """What each After block ADDS, as a block of lines.

    A modify hunk's After repeats the lines around the change; those are quotations of
    existing code, and scanning them reported an untouched `if` in the context as body
    logic. Only what the After adds was authored here.
    """
    out = []
    for before, after in BEFORE_AFTER_RE.findall(sec):
        kept = {ln.strip() for ln in before.split(chr(10)) if ln.strip()}
        added = [ln for ln in after.split(chr(10)) if ln.strip() and ln.strip() not in kept]
        if added:
            out.append(chr(10).join(added))
    return out


def code_lines(block: str) -> list[str]:
    """Lines of a code block that are code — comments and doc comments dropped.

    Prose describes control flow constantly ("if the balance is insufficient…"),
    and a guide skeleton's whole job is to carry that prose in its marker and its
    doc comment. Reading those as body logic flags the healthiest skeletons.
    """
    out, in_doc = [], False
    for ln in block.split(chr(10)):
        t = ln.strip()
        if in_doc:
            if '"""' in t or "'''" in t or t.endswith("*/"):
                in_doc = False
            continue
        if t.startswith(("#", "//")):
            continue
        if t.startswith(("/*", "*")):
            # A `/* ... */` that does not close on its own line runs on; a `*`
            # continuation line is already inside one.
            if t.startswith("/*") and not t.endswith("*/"):
                in_doc = True
            continue
        if t.startswith(('"""', "'''")):
            quote = t[:3]
            # A one-line docstring opens and closes on the same line. Toggling on it
            # left the flag stuck for the rest of the block, so every line after the
            # commonest Python docstring form went unread and guide mode's one
            # mechanically enforced promise never fired.
            if not (len(t) > 3 and t.endswith(quote)):
                in_doc = True
            continue
        out.append(ln)
    return out


def main() -> int:
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        print("Usage: validate_blueprint.py [specs/NNN-feature-name] [--strict-guide] [--verbose]")
        print("\nChecks blueprint.md against tasks.md and the working tree.")
        print("  --strict-guide  make the guide-mode body findings failures rather than warnings")
        print("  --verbose       print a line for every check that passed, not just the count")
        print("Exit 0 pass, 1 failures found, 2 feature directory not resolved.")
        return 0
    global VERBOSE
    strict_guide = "--strict-guide" in argv
    VERBOSE = "--verbose" in argv
    argv = [a for a in argv if a not in ("--strict-guide", "--verbose")]
    unknown = [a for a in argv if a.startswith("-")]
    if unknown:
        # Silently ignoring these meant a typo in a flag looked like a clean run.
        print(f"{RED}ERROR: unknown option(s): {' '.join(unknown)}{NC}")
        print("Usage: validate_blueprint.py [specs/NNN-feature-name]")
        return 2
    args = argv
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
    ordered_sections = split_tasks(bp)
    # A blueprint that emits `### T001` twice is exactly what check [1] exists to
    # catch, and dict() kept only the last — so the first went unchecked by every
    # check below and the section count printed one too few. Merge instead.
    sections: dict[str, str] = {}
    duplicate_ids: list[str] = []
    for _tid, _sec in ordered_sections:
        if _tid in sections:
            duplicate_ids.append(_tid)
            sections[_tid] += chr(10) + _sec
        else:
            sections[_tid] = _sec
    mode = parse_mode(bp)
    print(f"Mode: {mode} | {len(bp.splitlines())} lines | {len(sections)} task sections\n")
    if mode == "unknown":
        record(
            "warn",
            "the header's **Mode**: line is missing or unreadable",
            "the guide-mode checks and the placeholder rules depend on it, and a run with no mode skips them without saying so",
        )

    # The slices this blueprint continues, if the header names one. Read once: coverage
    # and forward references both span the chain, and reading it twice would let them
    # disagree about what exists.
    chain = base_chain(bp, feature_dir, root)
    # And the slices that name this one as their base. The link is declared once, by the
    # later slice, and both ends need it: this one refers forward to work its successor
    # delivers, and the successor refers back to work this one does.
    later = dependent_slices(feature_dir, root)
    chain_ids: set[str] = set()
    for _cpath, ctext in chain + later:
        chain_ids |= {t for t, _sec in split_tasks(ctext)}
        chain_ids |= {m.group(1) for m in re.finditer(r"^\|\s*\**\s*(T\d+)\b", ctext, re.M)}
    if chain or later:
        section("[0] Sibling slices", first=True)
        record(
            "pass",
            f"this feature is split across {len(chain) + len(later) + 1} blueprint(s)",
            "base: " + (", ".join(os.path.relpath(cp, root) for cp, _t in chain) or "none")
            + " | continued in: " + (", ".join(os.path.relpath(cp, root) for cp, _t in later) or "none")
            + f" — {len(chain_ids)} task(s) live in them",
        )

    # 1. Coverage — every task id in tasks.md reaches the blueprint
    section("[1] Task coverage", first=True)
    if os.path.isfile(tasks_path):
        tasks_text = open(tasks_path, encoding="utf-8", errors="replace").read()
        declared = set(re.findall(r"^\s*-\s*\[[ xX]\]\s*(T\d+)\b", tasks_text, re.M))
        # A checklist row and a "Dependencies: T017" mention are not content. Counting
        # every T-id anywhere made this check unfailable — the template requires a
        # checklist listing all of them.
        precompleted = set()
        for m in re.finditer(r"^\|[^\n|]*\b(T\d+)\b[^\n]*\|", bp, re.M):
            line = m.group(0)
            if re.search(r"already complete|pre-?completed|사전 완료|이미 완료", line, re.I):
                precompleted.add(m.group(1))
        # A slice covers what it has plus what its base slices deliver; tasks.md is the
        # feature's, not the slice's, so without this every split fails here.
        # What this slice's family delivers. tasks.md belongs to the feature, not the
        # slice, so a split had no passing configuration: a per-slice tasks.md left the
        # references across the seam dangling, and a whole-feature tasks.md failed here
        # instead. A slice that exists has delivered its tasks; one that does not exist
        # yet is still a real omission and still fails.
        family_ids: set[str] = set()
        for _cpath, ctext in chain + later:
            family_ids |= {t for t, _sec in split_tasks(ctext)}
        present = set(sections) | precompleted | family_ids
        missing = sorted(declared - present)
        if not declared:
            record("warn", "no task ids found in tasks.md (check its format)")
        elif missing:
            record("fail", f"{len(missing)} task(s) from tasks.md missing", listing(missing, 12, ", "))
        else:
            record("pass", f"all {len(declared)} tasks from tasks.md appear")
    else:
        record("warn", "tasks.md not found — coverage not checked")

    # The header states counts nobody ever checked. A file some task declares `(new)` is
    # new however many later tasks modify it — that is the documented pattern — so the
    # strongest kind wins, and what is left is a real disagreement between the header and
    # the document under it.
    fm = re.search(r"^\*\*Total Tasks\*\*.*?\*\*Files\*\*:\s*([^\n]+)", bp, re.M)
    if fm:
        claimed = {k: int(n) for n, k in re.findall(r"(\d+)\s+(new|modified|deleted)", fm.group(1))}
        if claimed:
            rank = {"new": 3, "deleted": 2, "modified": 1}
            strongest: dict = {}
            for _t, sec in sections.items():
                for path, kind in file_kinds(sec):
                    k = {"new": "new", "modify": "modified", "modified": "modified",
                         "delete": "deleted", "deleted": "deleted"}.get(kind)
                    if k and rank[k] > rank.get(strongest.get(path, ""), 0):
                        strongest[path] = k
            actual = {"new": 0, "modified": 0, "deleted": 0}
            for k in strongest.values():
                actual[k] += 1
            off = [f"{k}: header says {claimed[k]}, the tasks declare {actual[k]}"
                   for k in ("new", "modified", "deleted")
                   if k in claimed and claimed[k] != actual[k]]
            if off:
                record("warn", "the header's file counts do not match the tasks",
                       "\n".join(off) + "\na file declared new by one task and modified by later ones counts once, as new")
            else:
                record("pass", "the header's file counts match the tasks")

    if duplicate_ids:
        record(
            "fail",
            "the same task id has more than one section",
            ", ".join(sorted(set(duplicate_ids)))
            + "\none task = one id: give each its own heading, or merge them into one",
        )

    # 2. Rationale — every task states why it looks the way it does
    section("[2] Rationale (Why)")
    no_why = sorted(tid for tid, sec in sections.items() if "**Why**" not in sec)
    if not sections:
        record("warn", "no task sections found (check blueprint format)")
    elif no_why:
        record("fail", f"{len(no_why)} task(s) without a Why", listing(no_why, 12, ", "))
    else:
        record("pass", f"all {len(sections)} task sections carry a Why")

    section("[3] Working-tree claims")
    if mode.startswith("guide"):
        build_line = next((ln for ln in bp.split("\n") if ln.lower().startswith("**build**")), "")
        # A test RUNNER, not the word "test": `compileall -q moneylog tests` names a
        # directory, and it is the command the spec tells a Python project to stamp.
        RUNS_TESTS = re.compile(
            r"\bpytest\b|\bunittest\b|\bgo\s+test\b|\bcargo\s+test\b|\bctest\b|\brspec\b|\bjest\b"
            r"|\b(?:gradlew?|mvn|npm|yarn|pnpm|make|rake|dotnet|swift|sbt)\s+\S*test"
            r"|\btools?/test[\w.\-]*|\btest\.sh\b",
            re.I,
        )
        if RUNS_TESTS.search(build_line):
            record(
                "warn",
                "the **Build** command looks like it runs tests, in a guide-mode blueprint",
                build_line.strip()[:90] + "\nguide skeletons throw by design; stamp a compile or syntax check, or the applier's build fails on the mode itself",
            )

    # 3-pre. The files a task declares exist where it says, and where it says is in the tree.
    #        A (modify) path that is not on disk passed sixteen checks green, because every
    #        check that reads the file skipped it quietly; the applier was the first to say so.
    missing_modify, escapes = [], []
    created_earlier: set[str] = set()
    for tid, sec in sections.items():
        for relp, kind in file_kinds(sec):
            norm = os.path.normpath(relp)
            if os.path.isabs(relp) or norm.startswith("..") or norm.split(os.sep)[0] == "..":
                escapes.append(f"{tid}: {relp}")
                continue
            # A file an earlier task creates is (modify) to every task after it, and is not
            # on disk until the first is typed — the "one new file, several tasks" form.
            # "unknown" too: a declaration written without its `(kind)` was not counted,
            # so a path typo in one passed every document check and failed in the applier.
            if kind in ("modify", "unknown") and relp not in created_earlier and not os.path.isfile(os.path.join(root, relp)):
                missing_modify.append(f"{tid}: {relp}" + ("  (no kind declared)" if kind == "unknown" else ""))
            if kind == "new":
                created_earlier.add(relp)
    if escapes:
        record("fail", "a declared path resolves outside the repository", listing(escapes))
    # A hunk edits a file that exists, so its task has to declare one as (modify).
    hunk_without_modify = []
    for tid, sec in sections.items():
        if not BEFORE_AFTER_RE.search(sec):
            continue
        kinds_here = {k for _p, k in file_kinds(sec)}
        if kinds_here and "modify" not in kinds_here and "unknown" not in kinds_here:
            hunk_without_modify.append(f"{tid}: has a Before/After hunk and declares only {', '.join(sorted(kinds_here))} file(s)")
    if hunk_without_modify:
        record(
            "fail",
            "a task has a Before/After hunk but declares no file to modify",
            listing(hunk_without_modify) + "\nif the file it edits already exists, declare it (modify), not (new)",
        )

    if missing_modify:
        record(
            "fail",
            "a task declares a (modify) file that is not in the tree",
            listing(missing_modify) + "\nthe path is wrong, or the file is new and mislabelled",
        )
    else:
        record("pass", "every declared (modify) file is in the tree")

    # 3. Before blocks quote something that is actually there
    out_of_range, moved_first, identical, ambiguous, misnumbered = [], [], [], [], []
    unjudged: set[str] = set()
    not_quoted: list[str] = []
    ambiguous_anchor: list[str] = []
    # Quoting only makes a claim about the tree the blueprint was generated against. On a
    # tree that has moved on, a Before that no longer matches is the implementation having
    # happened — the applier learned this first; the two now ask git the same question.
    head = stamped_head(bp)
    moved: dict[str, bool] = {}

    answers: dict = {}

    def moved_answer(rel_path: str):
        """True changed, False unchanged, None git could not say."""
        if rel_path not in answers:
            answers[rel_path] = changed_since(root, head, rel_path)
        return answers[rel_path]

    def has_moved(rel_path: str) -> bool:
        if rel_path not in moved:
            answer = moved_answer(rel_path)
            # `None` is git declining to answer — a shallow clone, a stamp from another
            # machine. Reading it as "unchanged" ran every position check against a tree
            # nothing could vouch for, and a correct blueprint came back red under
            # `actions/checkout`, whose default is depth 1. The applier learned this; the
            # document validator had the same line and never got the fix.
            moved[rel_path] = True if answer is None else answer
        return moved[rel_path]
    # Files this run declined to judge because the tree moved past the stamp. Named on the
    # `unjudged` pass line, so "not checked" is still said out loud.
    drifted_files: set = set()
    # Which task first declares each file. A later task that cites a line past the end of
    # the file on disk may be citing the file as an EARLIER task leaves it — the wiring
    # T006 adds is what T008 edits — and disk cannot confirm or deny that. The applier
    # can: it applies in order and matches the Before text itself. So that case is a
    # warning that says who moved the file, not a failure that a correct blueprint can
    # only pass by citing a number it knows is wrong.
    first_touch: dict[str, str] = {}
    for tid, sec in sections.items():
        for rel in file_paths(sec):
            first_touch.setdefault(rel, tid)
    for tid, sec in sections.items():
        declared_kinds = dict(file_kinds(sec))
        declared = list(declared_kinds)
        lengths = {}
        for rel in declared:
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                lengths[rel] = len(open(path, encoding="utf-8", errors="replace").read().splitlines())
        if not lengths:
            continue
        # A hunk can only edit a file that exists before the task — the same rule the
        # applier uses to place it. So a Before with no path of its own is measured against
        # the task's (modify) files, never its (new) ones: a fifteen-line new exception
        # class was being offered as the file a sixty-line service hunk might be quoting.
        editable = {f: n for f, n in lengths.items() if declared_kinds.get(f) != "new"} or lengths
        # Each citation is attributed to a file when the document says which: a path
        # named on the Before line itself, else the nearest `**`path`**` label above it.
        # Without that, every declared file was a candidate, and the check told an author
        # who had labelled the block to "name the file" they had already named.
        # Only a label for a file a hunk CAN edit attributes the hunks below it. A `(new)`
        # file's label above the hunks made the validator measure them against the new
        # file — an eighteen-line exception class — and fail a correct blueprint.
        labels_at = [
            (m.start(), m.group(1))
            for m in re.finditer(r"^\*\*`([^`]+)`\*\*", sec, re.M)
            if m.group(1) in editable
        ]
        for bm in re.finditer(
            r"\*\*Before\*\*([^\n]*?)\blines?[^\d]{0,4}(\d+)(?:\s*[-\u2013]\s*(\d+))?", sec
        ):
            cites = [int(bm.group(2))] + ([int(bm.group(3))] if bm.group(3) else [])
            named = next((f for f in lengths if f"`{f}`" in bm.group(1)), None)
            if named is None:
                named = next((f for at, f in reversed(labels_at) if at < bm.start()), None)
            if named is None and len(editable) == 1:
                named = next(iter(editable))
            candidates = {named: lengths[named]} if named else editable
            # Where the quoted text actually is. In range is not the same as right: a
            # Before that says (lines 2-4) over text that sits at 5-7 passed every tool,
            # because the applier matches text and the range check only had a bound.
            quoted = None
            pair_m = re.compile(
                r"\*\*Before\*\*[^\n]*\n+```\w*\n(.*?)```", re.S
            ).match(sec, bm.start())
            if pair_m and named:
                quoted = pair_m.group(1)
                try:
                    text = open(os.path.join(root, named), encoding="utf-8", errors="replace").read()
                except OSError:
                    text = ""
                needle = quoted if quoted in text else quoted.rstrip("\n")
                # Not there at all, in a file no earlier task rewrites: the quotation is
                # wrong, and until now only the applier said so. "17 checks passed" did
                # not mean the document matched the tree.
                if (needle and text and text.count(needle) == 0
                        and first_touch.get(named) in (None, tid) and not has_moved(named)):
                    # Not `head`: that name holds the stamped commit every position check
                    # asks git about, and rebinding it here left every later call running
                    # `git diff` against a line of Java. git answered nothing, the tools
                    # read "cannot say", and the rest of the document went unchecked from
                    # the first finding onward.
                    starts = needle.strip().split("\n")[0][:50]
                    not_quoted.append(f"{tid}: {named} does not contain the Before block (starts {starts!r})")
                # Not gated on whether the tree moved: a Before that appears twice is
                # ambiguous for the applier wherever the tree stands, and this is the one
                # position finding that needs no stamp to be true.
                if needle and text.count(needle) > 1:
                    ambiguous_anchor.append(f"{tid}: the Before block appears {text.count(needle)} times in {named}")
                if needle and text.count(needle) == 1:
                    actual = text[: text.index(needle)].count("\n") + 1
                    mine = first_touch.get(named) in (None, tid)
                    if actual != cites[0]:
                        if mine and has_moved(named):
                            # The file has changed since the stamp, so the number was right
                            # about the tree the blueprint describes and the reader is
                            # looking at a different one. Measured over one corpus: this
                            # warning fired on all five implemented features and on none of
                            # the freshly generated ones, and not one of the five was a
                            # defect in a document. An alarm that only rings after the work
                            # is done is not reporting the work.
                            drifted_files.add(named)
                        elif mine:
                            misnumbered.append(f"{tid}: Before says line {cites[0]}, the quoted text is at line {actual} of {named}")
                        else:
                            # An earlier task rewrites this file, so where the text sits on
                            # disk says nothing about where it will sit when the hunk runs.
                            unjudged.add(named)
                    elif len(cites) > 1 and mine:
                        # Only the first number was ever compared, so `(lines 48-50)` over a
                        # four-line block passed, and a delivered blueprint carried that
                        # error through every check. The reader counting down from 48 stops
                        # one line short of what the hunk actually replaces.
                        span = len(needle.rstrip("\n").split("\n"))
                        end = actual + span - 1
                        if cites[-1] != end:
                            if has_moved(named):
                                drifted_files.add(named)
                            else:
                                misnumbered.append(
                                    f"{tid}: Before says lines {cites[0]}-{cites[-1]}, the quoted block is"
                                    f" {span} line(s) and ends at {end} of {named}"
                                )
            for n in cites:
                bound = max(candidates.values())
                if n > bound:
                    over = [f for f, ln in candidates.items() if n > ln]
                    earlier = [
                        first_touch[f] for f in over if first_touch.get(f) not in (None, tid)
                    ]
                    if earlier:
                        moved_first.append(
                            f"{tid}: line {n} > {bound} lines on disk, but {sorted(set(earlier))[0]}"
                            f" changes {', '.join(over)} first"
                        )
                    else:
                        which = named or f"{bound}-line longest file it declares"
                        out_of_range.append(f"{tid}: line {n} > {bound} lines ({which})")
                elif n > min(candidates.values()) and len(candidates) > 1:
                    over = [f"{f} ({ln})" for f, ln in sorted(candidates.items()) if n > ln]
                    ambiguous.append(f"{tid}: line {n} is past the end of {', '.join(over)}")
        for before, after in BEFORE_AFTER_RE.findall(sec):
            if before.strip() == after.strip():
                identical.append(tid)
    if out_of_range:
        record("fail", "Before block cites a line past the end of its file", listing(out_of_range))
    else:
        record("pass", "Before line references are within their files")
    # A `path:line` written in prose is a claim about the tree like any other, and one
    # that names a line the file does not have is simply false. A reviewer planted
    # `SettlementService.java:900` in a 300-line file and no check moved.
    bad_cite = []
    basename_index: dict = {}
    for m in re.finditer(r"`([\w./-]+\.\w{1,5}):(\d{1,5})`", outside_fences(bp)):
        rel_p, n = m.group(1), int(m.group(2))
        full = os.path.join(root, rel_p)
        if not os.path.isfile(full):
            # `Money.java:900` is the shape people write in prose. Skipping it left the
            # commonest form of this claim unchecked.
            if os.sep in rel_p:
                continue
            if not basename_index:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
                    for fn in filenames:
                        basename_index.setdefault(fn, []).append(os.path.join(dirpath, fn))
            hits = basename_index.get(rel_p, [])
            if len(hits) != 1:
                continue
            full = hits[0]
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                have = sum(1 for _ in f)
        except OSError:
            continue
        if n > have:
            bad_cite.append(f"{rel_p}:{n} — the file has {have} line(s)")
    if bad_cite:
        record("fail", f"{len(bad_cite)} citation(s) point past the end of the file they name",
               listing(sorted(set(bad_cite)))
               + "\na line number in prose is a claim about the tree; this one cannot be true")

    if not_quoted:
        record(
            "fail",
            "a Before block is not in the file it quotes",
            listing(not_quoted)
            + "\nthe applier matches this text exactly; quote the file as it is now."
              "\nIf the work is already done — a regeneration re-stamps HEAD to a commit that includes it —"
              "\nthe task belongs in the Pre-completed Tasks table, and its row must carry the Why and the"
              "\nKey Decision the section held. Deleting the section makes this quiet and loses the record.",
        )
    else:
        record("pass", "every checkable Before block is in the file it quotes")
    if ambiguous_anchor:
        record(
            "warn",
            "a Before block appears more than once in its file — the anchor is ambiguous",
            listing(ambiguous_anchor) + "\nthe applier refuses these; quote more of the surrounding lines",
        )
    if unjudged:
        # Without this line the run names one task and looks like the others were checked.
        record(
            "pass",
            f"line positions not checked in {len(unjudged)} file(s) an earlier task rewrites",
            listing(sorted(unjudged), 6, ", ") + " — the applier checks these, since it applies in order",
        )
    if drifted_files:
        record(
            "pass",
            f"line positions not checked in {len(drifted_files)} file(s) this run cannot vouch for",
            listing(sorted(drifted_files), 6, ", ")
            + "\n— changed since the stamp, or the stamp is not in this clone; either way the numbers"
              "\ndescribe the tree the blueprint was written against and not this one",
        )
    if misnumbered:
        record(
            "warn",
            "a Before cites a line number that is not where its text is",
            listing(misnumbered) + "\nthe applier will still place it; the reader following the number will not",
        )
    if moved_first:
        record(
            "warn",
            "a Before cites a line past the end of the file on disk, in a file an earlier task changes",
            listing(moved_first)
            + "\ndisk cannot check this one; apply_blueprint.py can, since it applies in order and matches the text",
        )
    if ambiguous:
        record(
            "warn",
            "a Before citation is out of range for some of its task's files",
            listing(ambiguous) + "\nname the file the block quotes so the reference can be checked",
        )
    # Labels outside the code blocks, since a blueprint that documents this format quotes
    # `**Before**` inside one. Counting those made a task that explains the notation look
    # like a task with a dangling hunk.
    dangling = [
        tid
        for tid, sec in sections.items()
        if before_labels(sec) > len(BEFORE_AFTER_RE.findall(sec))
    ]
    if dangling:
        record(
            "fail",
            "a **Before** block has no **After** after it",
            ", ".join(sorted(dangling)) + "\ngive every Before its After — a pair is how a change is stated here",
        )
    else:
        record("pass", "every Before block is followed by its After")

    if identical:
        record(
            "fail",
            "Before and After are identical — the change is not a diff",
            ", ".join(sorted(set(identical))),
        )
    else:
        record("pass", "every After differs from its Before")

    # A Before block quotes real lines so the reader can find the spot, and applying the
    # pair replaces that whole region — so a structural line the Before quotes and the
    # After does not return is deleted from the file, usually a brace or a doc-comment
    # delimiter the task never meant to touch, and the build breaks somewhere else.
    #
    # Counted, not positioned. Two earlier versions compared head and tail windows and
    # both were wrong in both directions at once: a two-line Before put its closing brace
    # in the opening window and failed a correct diff, while a dropped `/**` four lines
    # in fell between the windows and passed. Where a line sits does not matter; whether
    # it survives does.
    #
    # Closers only — an opener is followed by the body that identifies it, but a bare
    # closer carries no context and is what a lossy transcription drops.
    STRUCTURAL = re.compile(
        r"^(?:[)}\]]+[;,]?"          # C family: } ) ] and runs of them
        r"|/\*\*|\*/"                # block-comment delimiters
        r"|\)\s*[;{]?"               # ); ) {
        r"|end|fi|esac|done"         # Ruby, shell
        r"|</[A-Za-z][-A-Za-z0-9]*>"  # closing tag
        r")$"
    )

    lossy = []
    for tid, sec in sections.items():
        for before, after in BEFORE_AFTER_RE.findall(sec):
            b_lines = [ln.strip() for ln in before.split("\n") if ln.strip()]
            a_lines = [ln.strip() for ln in after.split("\n") if ln.strip()]
            for tok in sorted({ln for ln in b_lines if STRUCTURAL.match(ln)}):
                dropped = b_lines.count(tok) - a_lines.count(tok)
                if dropped > 0:
                    lossy.append(
                        f"{tid}: Before quotes {tok!r} {b_lines.count(tok)}x, "
                        f"After returns it {a_lines.count(tok)}x"
                    )
    if lossy:
        record(
            "warn",
            "a Before quotes a structural line the After does not return — applying it deletes that line",
            listing(lossy)
            + "\nintended if the task removes that block; otherwise the hunk is lossy and the build breaks elsewhere",
        )
    else:
        record("pass", "no Before/After pair drops a structural line")

    # A task that declares a new file has to supply it. The applier removes declared-new
    # files from its copy before applying, so a missing block is a missing file at build
    # time — but the document can say so first, with the task id instead of a javac trace.
    empty_new = []
    for tid, sec in sections.items():
        new_paths = [p for p, k in file_kinds(sec) if k == "new"]
        if not new_paths:
            continue
        blocks = code_blocks(sec, content_only=True)
        if not blocks:
            empty_new.append(f"{tid}: declares {', '.join(new_paths)} (new) and carries no code block")
        elif len(new_paths) > 1:
            # Per file, not per task: a task declaring two new files with one block
            # between them passed, and the missing file surfaced as a compiler error.
            for relp in new_paths:
                if not re.search(r"^\*\*`" + re.escape(relp) + r"`\*\*", sec, re.M):
                    empty_new.append(f"{tid}: declares {relp} (new) and no code block is labelled with it")
    if empty_new:
        record("fail", "a task declares a new file and gives it no content", listing(empty_new))
    else:
        record("pass", "every declared-new file has a code block")

    # A modify task's code has to say where it goes. Prose like "append this at the end of
    # the file" reads fine and is not a position, so the applier cannot place it — better to
    # hear that here than after a build fails.
    unanchored = []
    for tid, sec in sections.items():
        kinds = [k for _, k in file_kinds(sec)]
        if "modify" not in kinds:
            continue
        if re.search(r"\*\*Replace entire file\*\*", sec):
            continue
        blocks = len([b for b in code_blocks(sec, content_only=True) if b[0]])
        anchored = len(re.findall(r"\*\*Before\*\*[^\n]*\n+```", sec)) * 2
        # A task may create new files and edit an existing one in the same breath. A block
        # introduced by its own path label is that whole new file, and has nothing to anchor to.
        labelled_new = count_path_labels(sec)
        if blocks - labelled_new > anchored:
            unanchored.append(f"{tid}: {blocks - labelled_new - anchored} block(s) with no Before/After or Replace marker")
    if unanchored:
        record(
            "warn",
            "modify task has code that is not anchored to a position",
            listing(unanchored) + "\nthe applier cannot place these; quote the surrounding lines in a Before block",
        )
    else:
        record("pass", "every modify task anchors its code")

    # 3-post. A skeleton on disk that still carries its marker is, by the mode's promise,
    #         the blueprint's block verbatim. Nothing checked that: a method added to the
    #         file on disk, or a skeleton written differently from the block, passed all
    #         three tools, since the applier tests the block and the scaffold validator
    #         only counts markers.
    drifted = []
    # A file that later tasks grow is not its creating task's block once they have run —
    # the "one new file, several tasks" form in 3a-G, and what --scaffold writes. Only a
    # file no other task touches can be compared to a single block; comparing the rest
    # reported a scaffold nobody had opened as edited since scaffolding.
    grown_later = {
        p for tid, sec in sections.items()
        for p, k in file_kinds(sec) if k != "new"
    }
    for tid, sec in sections.items():
        blocks = code_blocks(strip_quoted(sec), content_only=True)
        for relp, kind in file_kinds(sec):
            if kind != "new" or relp in grown_later:
                continue
            path = os.path.join(root, relp)
            if not os.path.isfile(path):
                continue
            block = next((c for _i, c in blocks if len(blocks) == 1), None)
            if block is None:
                # multi-file task: the block under this path's label
                lab = re.search(r"^\*\*`" + re.escape(relp) + r"`\*\*[^\n]*\n+```[^\n]*\n(.*?)```", sec, re.S | re.M)
                block = lab.group(1) if lab else None
            if block is None:
                continue
            try:
                disk = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if re.search(r"\bT\d{3,}:", disk) and disk.strip() != block.strip():
                drifted.append(f"{tid}: {relp} still carries its marker but is not the blueprint's block")
    if drifted:
        record(
            "warn",
            "a skeleton on disk differs from the block the blueprint declares for it",
            listing(drifted) + "\nedited since scaffolding, or scaffolded from a different version — the applier tests the block, not the file",
        )

    # 3-post-b. A block label names a file the task declares. A label with a typo in it is
    #           ignored by every tool — the applier falls back to the sole modified file
    #           and says the block "had no path label" — so the document keeps pointing a
    #           reader at a file that does not exist.
    stray_labels = []
    for tid, sec in sections.items():
        declared_here = {p for p, _k in file_kinds(sec)}
        for m in re.finditer(r"^\*\*`([^`]+)`\*\*", sec, re.M):
            label = m.group(1)
            if looks_like_path(label) and label not in declared_here:
                stray_labels.append(f"{tid}: labels a block `{label}`, which the task does not declare")
    if stray_labels:
        record(
            "fail",
            "a code block is labelled with a path the task does not declare",
            listing(stray_labels) + "\nthe tools ignore the label and a reader follows it to a file that is not there",
        )
    else:
        record("pass", "every block label names a file its task declares")

    # 4. Multi-file tasks map each block to a path
    section("[4] Multi-file task labels")
    unlabeled = []
    for tid, sec in sections.items():
        paths = file_paths(sec)
        authored = strip_quoted(sec)
        blocks = len([b for b in code_blocks(authored, content_only=True) if b[0]])
        if len(paths) > 1 and blocks > 1:
            # A label may be followed by anything — ":", " (new):", " — **Replace entire
            # file**". Requiring a colon counted four labelled blocks as one.
            labels = count_path_labels(authored)
            if labels < blocks:
                unlabeled.append(f"{tid}: {len(paths)} files, {blocks} blocks, {labels} labeled")
    # And the hunks. `strip_quoted` above drops every Before/After pair — rightly, they
    # quote existing code — so a task made ONLY of hunks collapsed to a single authored
    # block and `blocks > 1` was false for it whatever the document said. The two largest
    # multi-file tasks in the corpus that prompted this (nine files and three, thirty-seven
    # and fourteen blocks) never reached the check at all, while the applier failed both
    # for the very defect it exists to catch. This half asks the applier's own question:
    # when a hunk follows no usable label and the task declares more than one file to
    # modify, nothing can say which file it edits.
    unattributed = []
    for tid, sec in sections.items():
        kinds: dict[str, str] = {}
        for _p, _k in file_kinds(sec):
            kinds.setdefault(_p, _k)
        mods = [p for p, k in kinds.items() if k == "modify"]
        if len(mods) < 2:
            # One modifiable file is never ambiguous — the applier infers it, and so can
            # a reader. No file to modify at all is a different check's finding.
            continue
        current: str | None = list(kinds)[0] if len(kinds) == 1 else None
        bad = 0
        for ev_kind, payload in section_events(sec):
            if ev_kind == "label" and payload in kinds:
                current = payload
            elif ev_kind == "directive" and payload == "before":
                if not (current and kinds.get(current) in ("modify", "unknown")):
                    bad += 1
        if bad:
            unattributed.append(
                f"{tid}: {bad} Before/After hunk(s) follow no **`path`** label, and the task"
                f" declares {len(mods)} files to modify"
            )
    if unlabeled or unattributed:
        rows = unlabeled + unattributed
        record(
            "fail",
            "multi-file task does not label every code block with its path",
            listing(rows, 8)
            + "\nthe applier fails these too; label the block or the hunk with the file it edits",
        )
    else:
        record("pass", "multi-file tasks label each code block")

    # 4b. An identifier that is unique inside this document and not outside it. `plan D5`
    #     and `OQ-1` collide across a repository, and text inside a code block is text that
    #     ends up in the tree: one `cli.py` came to hold two `(plan D9)` comments meaning
    #     different decisions of different features, both typed straight from a blueprint
    #     that wrote the id 34 times and never once with its feature number. The rule was
    #     added to the generate spec a round earlier and nothing checked it.
    #
    #     One finding per document, not one per site. There were 34 sites in that one.
    LOCAL_ID = re.compile(r"\b(plan\s+D\d+|OQ-\d+)\b")
    bare_ids: list[str] = []
    for tid, sec in sections.items():
        for _i, blk in code_blocks(strip_quoted(sec), content_only=True):
            for ln in blk.split("\n"):
                for m in LOCAL_ID.finditer(ln):
                    if re.search(r"\d{3}\s$", ln[max(0, m.start() - 4):m.start()]):
                        continue
                    bare_ids.append(f"{tid}: {m.group(1)} — {ln.strip()[:60]}")
    if bare_ids:
        record(
            "warn",
            f"{len(bare_ids)} identifier(s) inside code blocks carry no feature number",
            listing(bare_ids, 4)
            + "\nthis text becomes a comment in the tree, where `plan D5` and `OQ-1` belong to"
              f"\nwhatever feature wrote them; write `{os.path.basename(feature_dir)[:3]} plan D5`",
        )

    # 5. Placeholders — full-code modes forbid them; guide mode expects markers in bodies only
    section("[5] Placeholder content")
    ellipsis = []
    for tid, sec in sections.items():
        for blk in [c for _i, c in code_blocks(strip_quoted(sec))]:
            for ln in blk.split("\n"):
                if re.search(r"(//|#|/\*)\s*\.\.\.", ln):
                    ellipsis.append(f"{tid}: {ln.strip()[:60]}")
    if ellipsis:
        record("fail", "ellipsis placeholder in a code block", listing(ellipsis))
    else:
        record("pass", "no ellipsis placeholders")

    # A doc comment that narrates the blueprint — "moved verbatim", "pre-existing" — is
    # written for this document's reader, not the code's, and cleanup never touches doc
    # comments. A warning: the phrases are a heuristic, the judgment is the author's.
    HISTORY = re.compile(
        r"\b(moved verbatim|pre-existing|previously|as before|unchanged from|from the original|"
        r"was (?:moved|copied|extracted)|the old |formerly|used to)\b", re.I
    )
    history = []
    for tid, sec in sections.items():
        # After blocks are authored content too — only the Before is a quotation — and the
        # javadoc that prompted this check sat in one.
        authored_blocks = [c for _i, c in code_blocks(strip_quoted(sec), content_only=True)]
        authored_blocks += after_additions(sec)
        for blk in authored_blocks:
            for ln in blk.split("\n"):
                t = ln.strip()
                if t.startswith(("/**", "*", "///", "#", "//", chr(34) * 3, chr(39) * 3)) and HISTORY.search(t):
                    history.append(f"{tid}: {t[:70]}")
                    break
    if history:
        record(
            "warn",
            "a comment narrates the blueprint's history rather than the code",
            listing(history) + "\nsay it in the task's prose; cleanup leaves doc comments alone, so this one stays for ever",
        )

    # A Before is a quotation, and `// ... rest of file` inside one is the abbreviation the
    # generate rules forbid by name. The check above strips Before/After first — rightly,
    # they quote existing code — so the abbreviation reached the applier before anyone
    # said so, and only as "not found verbatim".
    abbreviated = []
    for tid, sec in sections.items():
        for before, _after in BEFORE_AFTER_RE.findall(sec):
            for ln in before.split("\n"):
                if re.search(r"(//|#|/\*|--)\s*\.\.\.|\.\.\.\s*(rest|stub|omitted|unchanged|other)", ln, re.I):
                    abbreviated.append(f"{tid}: {ln.strip()[:60]}")
                    break
    if abbreviated:
        record(
            "fail",
            "a Before block is abbreviated — it has to quote the file verbatim",
            listing(abbreviated) + "\nthe applier matches the Before text exactly; an abbreviation never matches",
        )
    else:
        record("pass", "no Before block is abbreviated")

    if mode in ("doc-only", "scaffold"):
        stubs = []
        for tid, sec in sections.items():
            for blk in [c for _i, c in code_blocks(strip_quoted(sec))]:
                if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", blk):
                    stubs.append(tid)
        if stubs:
            record(
                "fail",
                f"{mode} blueprint contains stub markers in code blocks",
                listing(sorted(set(stubs)), 10, ", "),
            )
        else:
            record("pass", f"{mode} blueprint has no stub markers")

    # 5a. Guide mode's one promise: the bodies are the developer's work. "No body logic"
    #     lived only in the prompt, so a skeleton that quietly carried a branch or a query
    #     read as compliant. Control flow inside an authored block is the tell — a
    #     signature and a not-implemented marker need none of it.
    if mode.startswith("guide"):
        # Guide modes only — in a full-code mode the numbering skips from [5] to [7].
        section("[6] Guide-mode bodies")
        # A module guard is not a body: 3a-G asks test skeletons to match the project's
        # existing tests, and in Python those end with exactly this line.
        NOT_BODY = re.compile(
            r'^\s*if\s+__name__\s*==|^\s*if\s+TYPE_CHECKING\s*:|^\s*if\s+not\s+TYPE_CHECKING\s*:'
        )
        CONTROL = re.compile(
            r"^\s*(if|for|while|switch|when|elif|else\s+if|do|try|catch|except|match)\b[\s({:]"
        )
        # Not in declaration position: a JS file that declares the error type it throws
        # — `export class NotImplementedError extends Error {}` — was counted as carrying
        # a marker, so the file that declared nothing and threw an undefined name passed
        # and the correct one did not.
        MARKER = re.compile(
            r"TODO\(|(?<!class )(?<!extends )(?:NotImplementedError|UnsupportedOperationException)\b"
            r"|fatalError\(|todo!\(|unimplemented!\(|panic\("
            r"|throw\s+new\s+Error\s*\(\s*[\"'`]\s*T\d{2,}\s*:"
        )
        # Body logic that carries no control-flow keyword at the head of a line. In Java,
        # Kotlin and JS half of a body is a stream chain or a lambda, and the check saw
        # none of it: `store.values().stream().filter(m -> …).findFirst()` passed.
        EXPRESSION_BODY = re.compile(
            r"\.stream\(\)|\.filter\(|\.map\(|\.flatMap\(|\.collect\(|\.reduce\(|\.forEach\("
            r"|\.groupingBy\(|\.orElseThrow\(|\.findFirst\(|\bawait\b|\?\s*[^:\n]{1,40}\s*:"
        )
        # And the marker's own message. A message that hands over the exact expression is
        # the same transfer of the body, moved inside a string where no code check looks:
        # 3a-G asks for a self-contained instruction and forbids dictating the code, and a
        # generator satisfying the first breaks the second.
        # Precision over recall, and measured: the first version of this caught `&&` and
        # `==` and nothing else, while a sweep of every blueprint written against this
        # tool showed its other rules firing only on honest prose — a `->` between two
        # states, an API named mid-sentence, a semicolon between list items. A check that
        # fires on prose and misses expressions trains the author backwards.
        #
        # What survives is what a reader could paste: boolean operators, a comparison
        # with a call on one side, a ternary with code arms, a `return` carrying an
        # operator, and a `return` of a method call that ends the message.
        CODE_IN_PROSE = re.compile(
            r"&&|\|\|"
            r"|[\w)\]]\s*(?:==|!=|<=|>=)\s*[\w.]*\w\s*[.(]"
            r"|[\w.]*\w\s*[.(][^\n]{0,30}?(?:==|!=|<=|>=)"
            r"|\?[^:\n]{1,60}:\s*\w+[.(]"
            r"|\breturn\b[^.\n]{0,60}?[\w)]\s*(?:\?|&&|\|\||[!<>]=|==)"
            r"|\breturn\s+\w[\w.]*\.\w+\s*\([^()]*\)\s*;?\s*$"
            # A call whose result is called again. Measured over every marker message in
            # the corpus: 36 of 1495, and each one hands the reader an expression to
            # paste — `amount.amount().toPlainString()`, `findById(id).orElseThrow(...)`.
            r"|\w\s*\([^()\n]*\)\s*\.\s*\w+\s*\("
            # Everything above was written against Java and Kotlin, where a body is a
            # chain of calls. A Python body is arithmetic and keyword arguments, and the
            # check saw none of it: six of the seven expressions in one reviewer's
            # `pace.py` marker — four formulas and two constructor calls with eight
            # keyword arguments — passed. The five rules below were each measured over
            # every marker message, TODO comment and implementation note in the corpus
            # (2,400 texts): twelve new hits, all of them pasteable code, and none on the
            # prose shapes that trip a careless rule — a path (`moneylog/storage.py`), an
            # id (`FR-002`), `and/or`, a `*` used for emphasis.
            #
            # Two or more keyword arguments: `CategoryPace(category=category, budget=…)`.
            r"|\b\w+\s*=\s*[^=\s][^\n,]{0,40},\s*\w{3,}\s*=\s*[^=\s]"
            # A call subscripted: `calendar.monthrange(year, month)[1]`.
            r"|\w\s*\([^()\n]{0,60}\)\s*\["
            # An identifier compared against a number: `elapsed_days > 0`.
            r"|\b[a-z_][A-Za-z0-9_]{2,}\s*[<>]\s*-?\d"
            # Arithmetic between identifiers, where one side is unmistakably an
            # identifier (it carries a `_` or a digit) rather than an English word.
            r"|(?<![*\w])[a-z_][A-Za-z0-9_]*[_0-9][A-Za-z0-9_]*\s*\*\s*[a-z_][A-Za-z0-9_]{2,}(?![*\w])"
            r"|(?<![*\w])[a-z_][A-Za-z0-9_]{2,}\s*\*\s*[a-z_][A-Za-z0-9_]*[_0-9][A-Za-z0-9_]*(?![*\w])"
            r"|(?<![/\w.])[a-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\s*/\s*[a-z_][A-Za-z0-9_]{2,}(?![/.\w])"
            r"|(?<![/\w.])[a-z_][A-Za-z0-9_]{2,}\s*/\s*[a-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*(?![/.\w])"
            r"|\)\s*/\s*[a-z_][A-Za-z0-9_]{2,}(?![/.\w])"
        )
        # Where a body can be dictated. The check used to read the string inside a marker
        # CALL and nothing else, and 3a-G's own recommended shape for a change inside an
        # existing body is a `// TODO(blueprint):` COMMENT — so the form the spec teaches
        # was the one form nothing looked at. Implementation notes are the third: a
        # reviewer's notes 2, 3 and 4 for one task were whole Java statements, and the
        # string "Implementation notes" did not appear anywhere in these scripts.
        MSG_CALL = re.compile(
            r"""(?:TODO|NotImplementedError|UnsupportedOperationException|panic|todo!|fatalError)"""
            r"""\s*\(\s*["'`](.+?)["'`]\s*\)""",
            re.S,
        )
        MSG_COMMENT = re.compile(r"""(?://|#|--)\s*TODO\(blueprint\)\s*:?\s*([^\n]+)""")
        NOTES = re.compile(r"^\*\*Implementation [Nn]otes?\*\*:?(.*?)(?=^\*\*|\Z)", re.M | re.S)

        # `"…findById(id)" + ".orElseThrow()…"` is one sentence at runtime and two string
        # literals in the source, and every pattern below reads one line. A reviewer wrote
        # the same expression three ways and only the single-literal one was seen. The seams
        # are removed before scanning, so what the check reads is the message the developer
        # reads.
        SEAM = re.compile(r"""["'`]\s*\+?\s*\n?\s*["'`]""")

        def dictation_sources(sec: str, blocks: list):
            """(what kind of text, the text) for everything that can spell out a body."""
            for blk in blocks:
                for m in MSG_CALL.finditer(blk):
                    yield "a marker message", SEAM.sub("", m.group(1))
                for m in MSG_COMMENT.finditer(blk):
                    yield "a TODO(blueprint) comment", m.group(1)
            for m in NOTES.finditer(outside_fences(sec)):
                for para in m.group(1).split("\n"):
                    if para.strip():
                        yield "an implementation note", para.strip()
        # The same basename reading the scaffold validator uses: a file with one of these
        # in its name holds behavior, and a guide skeleton for it has to carry a marker.
        #
        # WORDS, not substrings. `FeeScheduleRepository.java` contains the letters of
        # "scheduler" across the seam between `Schedule` and `Repository`, so a port — a
        # Java interface with no bodies at all — was told to carry a not-implemented
        # marker it has nowhere to put. A check nothing can satisfy is worse than no check.
        BEHAVIORAL_WORDS = {
            "service", "handler", "usecase", "use", "case", "interactor",
            "controller", "scheduler", "test", "spec",
        }

        def is_behavioral(basename: str) -> bool:
            words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", basename)
            words = re.split(r"[^A-Za-z]+", words.lower())
            if "use" in words and "case" in words:
                return True
            return any(w in BEHAVIORAL_WORDS - {"use", "case"} for w in words)

        # A block that declares no method BODY cannot hold a marker. Java and Kotlin
        # interfaces, TypeScript `interface`/`type`, Python `Protocol` — the whole point of
        # the file is that the bodies live elsewhere, and adding a `default` method to
        # satisfy a checker stops it being a port.
        def has_body(block: str) -> bool:
            lines = code_lines(block)
            for i, ln in enumerate(lines):
                t = ln.strip()
                if not t:
                    continue
                # A type declaration's own brace opens the type, not a body.
                if re.match(r"^(export\s+|public\s+|private\s+|protected\s+|final\s+|abstract\s+|sealed\s+)*"
                            r"(class|interface|struct|enum|object|record|trait|type)\b", t):
                    continue
                if t.endswith("{") or t.endswith(":") and re.match(r"^\s*def\s", ln):
                    return True
            return False
        smuggled, unmarked, dictated = [], [], []
        for tid, sec in sections.items():
            kinds = dict(file_kinds(sec))
            new_behavioral = [f for f, k in kinds.items() if k == "new" and is_behavioral(os.path.basename(f))]
            # An After is authored content — only the Before is a quotation — and in a
            # guide blueprint the behaviour changes usually live in modify hunks, so
            # skipping them checked the promise everywhere except where it mattered.
            blocks = [c for _i, c in code_blocks(strip_quoted(sec), content_only=True)]
            blocks += after_additions(sec)
            if (new_behavioral and blocks and not any(MARKER.search(b) for b in blocks)
                    and any(has_body(b) for b in blocks)):
                # A complete implementation with one `if` in it carried no control flow
                # worth counting, and passed. The marker is the skeleton's signature; a
                # behavioral file's block without one is a body, however short.
                unmarked.append(f"{tid}: {', '.join(new_behavioral)} — no not-implemented marker in its block")
            for blk in blocks:
                hits = [ln.strip() for ln in code_lines(blk) if CONTROL.match(ln) and not NOT_BODY.match(ln)]
                exprs = [
                    ln.strip() for ln in code_lines(blk)
                    if EXPRESSION_BODY.search(ln) and not MARKER.search(ln) and not NOT_BODY.match(ln)
                ]
                if MARKER.search(blk):
                    # A block that still carries its marker is a skeleton; a branch beside
                    # the marker is the author starting a body. One is enough — a method
                    # written complete beside five that kept their markers is one `if`.
                    if hits:
                        smuggled.append(f"{tid}: {len(hits)} control-flow line(s) beside a not-implemented marker — {hits[0][:50]!r}")
                    elif exprs:
                        smuggled.append(f"{tid}: an expression body beside a not-implemented marker — {exprs[0][:50]!r}")
                elif hits:
                    smuggled.append(f"{tid}: {len(hits)} control-flow line(s) in a block with no marker — {hits[0][:50]!r}")
                elif exprs:
                    smuggled.append(f"{tid}: an expression body in a block with no marker — {exprs[0][:50]!r}")
            # Marker messages, TODO(blueprint) comments and implementation notes — the
            # three places a body can be handed over in prose.
            for what, text in dictation_sources(sec, blocks):
                hit = CODE_IN_PROSE.search(text)
                if hit:
                    # The fragment, not the opening of the message: a reviewer had to
                    # bisect one marker twelve times to find what had fired.
                    frag = hit.group(0).strip()
                    at = text.find(frag)
                    around = text[max(0, at - 20): at + len(frag) + 20].strip()
                    dictated.append(f"{tid}: {what} spells out the body — {frag!r} in …{around}…")
                    break
        # 4b asks every marker message to begin with its task id, and --markers and
        # cleanup both trace markers to tasks by it. Nothing checked it.
        unlabelled_markers = []
        for tid, sec in sections.items():
            blocks = [c for _i, c in code_blocks(strip_quoted(sec), content_only=True)]
            blocks += after_additions(sec)
            for blk in blocks:
                # A message, not a mention: the executable forms are matched only as a
                # call carrying a string. Without the call, `class NotImplementedError
                # extends Error {}` read as a marker whose message was "extends Error {}",
                # and declaring the type correctly was reported as the defect.
                for m in re.finditer(
                    r"""TODO\(blueprint\)\s*:\s*([^\n]{0,40})"""
                    r"""|(?:TODO|NotImplementedError|UnsupportedOperationException|panic|todo!|fatalError)"""
                    r"""\s*\(\s*["'`]([^"'`\n]{0,40})""",
                    blk,
                ):
                    head = (m.group(1) or m.group(2) or "").strip()
                    # Go's documented form is `panic("TODO: T0NN: …")`; the `TODO:` in
                    # front is the example this document gives, not a missing task id.
                    if head and not re.match(r"(?:TODO\s*:\s*)?T\d+\s*:", head):
                        unlabelled_markers.append(f"{tid}: a marker message does not begin with a task id — {head[:45]!r}")
                        break
        if unlabelled_markers:
            record(
                "fail" if strict_guide else "warn",
                "a not-implemented marker's message does not begin with its task id",
                listing(unlabelled_markers)
                + "\n--markers and cleanup trace a marker to its task by that id; without it the marker is orphaned",
            )

        # One message written once and pasted is not a work instruction. A reviewer found
        # twelve of eighteen markers carrying the same sentence, all passing.
        from collections import Counter
        msgs = []
        for tid, sec in sections.items():
            for m in re.finditer(
                r"""(?:TODO\(blueprint\)\s*:|NotImplementedError|UnsupportedOperationException"""
                r"""|panic|todo!|fatalError|throw\s+new\s+Error)\s*[(:]?\s*["'`]?\s*T\d+\s*:\s*([^"'`\n]{10,})""",
                sec,
            ):
                msgs.append(m.group(1).strip())
        repeated = [(t, n) for t, n in Counter(msgs).items() if n >= 3]
        if repeated:
            repeated.sort(key=lambda x: -x[1])
            record(
                "warn",
                f"{len(repeated)} marker message(s) are repeated across three or more tasks",
                "\n".join(f"{n}x: {t[:70]!r}" for t, n in repeated[:4])
                + "\na message that fits three tasks is describing none of them; say what THIS body must achieve",
            )

        # A type the language does not have and the block never declares.
        JS_INFO = {"js", "jsx", "javascript", "ts", "tsx", "typescript"}
        BUILTIN = {"Error", "TypeError", "RangeError", "SyntaxError", "EvalError", "ReferenceError", "URIError"}
        invented = []
        for tid, sec in sections.items():
            # Quoted blocks are the file as it already is — a `(modify)` hunk whose Before
            # shows a correct `throw new DomainError(...)` was reported as inventing the
            # type it was quoting. And the import that declares it lives in another hunk
            # of the same task, so the whole task is the scope, not one block.
            declared_here = strip_quoted(sec)
            for info, blk in code_blocks(strip_quoted(sec)):
                if (info or "").lower() not in JS_INFO:
                    continue
                for m in re.finditer(r"throw\s+new\s+(\w+)\s*\(", blk):
                    name = m.group(1)
                    if name in BUILTIN:
                        continue
                    if re.search(r"\b(?:class|import|const|let|var|function)\b[^\n]*\b" + re.escape(name) + r"\b", declared_here):
                        continue
                    invented.append(f"{tid}: throws `{name}`, which this block never declares or imports")
        if invented:
            record(
                "fail" if strict_guide else "warn",
                "a not-implemented marker throws a type the block does not have",
                listing(sorted(set(invented)))
                + "\nJavaScript and TypeScript have no not-implemented type — 3a-G's form is `throw new Error(\"T0NN: ...\")`;"
                  "\nan undeclared one parses, passes a syntax-only build, and dies with a ReferenceError",
            )

        # The Build line the header stamps decides what "it compiles" is worth. In guide
        # mode a parser accepts a skeleton that names something which does not exist, and
        # the document says so two paragraphs after telling you to stamp one.
        PARSER_ONLY = re.compile(
            r"\bcompileall\b|\bpy_compile\b|node\s+--check|\bruby\s+-c\b|\bphp\s+-l\b|\bbash\s+-n\b|\bsh\s+-n\b"
        )
        build_line = next((ln for ln in bp.split("\n") if ln.lower().startswith("**build**")), "")
        if build_line and PARSER_ONLY.search(build_line):
            record(
                "warn",
                "the stamped build parses the skeleton and cannot resolve names",
                build_line.strip()[:100]
                + "\na marker that calls something the file never imports passes this and fails at runtime;"
                  "\nprefer a checker that resolves names, or a command that loads the files",
            )

        demolished = []
        for tid, sec in sections.items():
            for first, n in body_replaced_by_marker(sec):
                demolished.append(f"{tid}: replaces {n} line(s) of working code with a marker — first is {first[:46]!r}")
        if demolished:
            # Not gated on --strict-guide. There is no judgment in this one: the Before
            # holds working lines and the After holds a marker where they were. A weak
            # generator treats FAIL 0 as the target and stops, so a warning here is a
            # gate that passes a document which breaks a shipped feature when typed.
            record(
                "fail",
                "a guide-mode hunk replaces existing code with a not-implemented marker",
                listing(demolished)
                + "\nthe applier's build compiles the skeleton and goes green; the behavior deleted here"
                  "\nshows up in the project's own tests, which that build never runs",
            )

        if dictated:
            record(
                "fail" if strict_guide else "warn",
                "prose in this task spells out the code it is standing in for",
                listing(dictated)
                + "\nsay what to achieve and what to avoid; an exact expression makes typing transcription, which is what guide mode exists to avoid",
            )
        if unmarked:
            record(
                "fail" if strict_guide else "warn",
                "a guide-mode skeleton for a file with behavior carries no marker",
                listing(unmarked) + "\na structural file (types, config, wiring) is complete on purpose; a service or a test is not",
            )
        if smuggled:
            record(
                "fail" if strict_guide else "warn",
                "a guide-mode block looks like it contains body logic",
                listing(smuggled) + "\nguide skeletons carry signatures and markers; the branches are the developer's to write",
            )
        else:
            record("pass", "no guide-mode block carries body logic")

    # 5b. Regeneration discipline. The generate spec says a regeneration keeps unchanged
    #     tasks verbatim, so the diff stays reviewable — and until now that was a sentence
    #     in a prompt with nothing behind it. If the previous blueprint is in git, the
    #     claim is checkable: sources that did not move cannot justify rewritten tasks.
    section("[7] Regeneration")
    prev = ""
    try:
        prev = subprocess.run(
            ["git", "show", f"HEAD:{os.path.relpath(bp_path, root)}"],
            capture_output=True, text=True, cwd=root, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    if not prev:
        record("pass", "no committed version to compare against")
    else:
        prev_sections: dict[str, str] = {}
        for _tid, _sec in split_tasks(prev):
            prev_sections[_tid] = prev_sections.get(_tid, '') + _sec
        def stamp(text: str) -> str:
            # Only the artifact hashes. The line ends with "| HEAD {sha}", which moves on
            # any unrelated commit and would excuse a full rewrite.
            ln = next((l for l in text.split("\n") if l.lower().startswith("**sources**")), "")
            return " ".join(sorted(re.findall(r"[\w.\-/]+@[0-9a-f]{6,64}", ln)))

        # A section that vanished is invisible to a comparison of shared ids, and a
        # regeneration that quietly drops one reads as `2 of 11 rewritten` without saying
        # the denominator moved from 12.
        dropped = sorted(set(prev_sections) - set(sections))
        if dropped:
            record(
                "warn",
                f"{len(dropped)} task section(s) present in the committed version are gone",
                listing(dropped, 12, ", ")
                + "\nif they were folded into a pre-completed row that is fine; if they were lost, the"
                  "\nfeature is short that work and nothing else here will notice",
            )
        rewritten = sorted(
            tid for tid, sec in sections.items()
            if tid in prev_sections and sec.strip() != prev_sections[tid].strip()
        )
        if not rewritten:
            record("pass", "no task text changed since the committed version")
        elif stamp(bp) and stamp(bp) == stamp(prev):
            record(
                "fail",
                f"{len(rewritten)} task(s) rewritten while every source stayed the same",
                listing(rewritten, 12, ", ")
                + "\nunchanged inputs cannot justify new text — keep those tasks verbatim",
            )
        else:
            record(
                "pass",
                f"{len(rewritten)} of {len(sections)} task(s) rewritten, {len(sections) - len(rewritten)} kept verbatim",
                listing(rewritten, 12, ", ") if len(rewritten) <= 12 else "",
            )

    # 8. Staleness — the header records what the blueprint was built from, so drift is a
    #    fact to check rather than something everyone assumes away.
    section("[8] Freshness")
    src_line = next((ln for ln in bp.split("\n") if ln.lower().startswith("**sources**")), "")
    if not src_line:
        record("warn", "no **Sources** stamp — staleness cannot be checked (regenerate to add one)")
    else:
        import hashlib

        stale, unknown, own_work = [], [], []
        for name, want in re.findall(r"([\w.\-/]+\.\w+)@([0-9a-f]{6,64})", src_line):
            # The stamp records a repo-relative path; resolve it as one. Matching the
            # basename inside feature_dir first let an unrelated same-named file shadow
            # the real source and report a byte-identical artifact as changed.
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                path = os.path.join(feature_dir, name)
            if not os.path.isfile(path):
                path = os.path.join(feature_dir, os.path.basename(name))
            if not os.path.isfile(path):
                unknown.append(name)
                continue
            got = hashlib.sha256(open(path, "rb").read()).hexdigest()[: len(want)]
            if got != want:
                # A stamp on a file one of this blueprint's own tasks edits goes stale the
                # moment that task is typed, and stays stale for every run afterwards. The
                # generate spec already says not to stamp such a file; when one is stamped
                # anyway the drift is the work, not something to regenerate over. The
                # document said so in prose and there was no path in the code to say it.
                # The family, not this document: a split feature's stamp is edited by
                # whichever slice owns that task, and looking only here left the first
                # slice failing forever over work its sibling does.
                owner = next((tid for tid, sec in sections.items()
                              if name in {q for q, _k in file_kinds(sec)}), "")
                if not owner:
                    owner = next((f"{tid} (in {os.path.relpath(cpath, root)})"
                                  for cpath, ctext in chain + later
                                  for tid, sec in split_tasks(ctext)
                                  if name in {q for q, _k in file_kinds(sec)}), "")
                (own_work if owner else stale).append(
                    f"{name}: stamped {want}, now {got}" + (f" — {owner} edits this file" if owner else "")
                )
        if own_work:
            # A pass, not a warning. The evidence line already said "expected once that
            # task is typed" — a finding that explains why it is not a finding is one the
            # reader has to read to learn they can ignore it, on every run, for ever.
            record(
                "pass",
                f"{len(own_work)} stamped source(s) are edited by this blueprint's own tasks — expected once those tasks are typed",
                listing(own_work)
                + "\ncite such a file in the Why that needs it rather than stamping it",
            )
        if stale:
            record(
                "fail",
                f"{len(stale)} source artifact(s) changed since this blueprint was generated",
                "\n".join(stale) + "\nregenerate, or move the citation into the Why of the task that depends on it",
            )
        elif unknown:
            record("warn", "stamped sources not found on disk", ", ".join(unknown))
        else:
            record("pass", "every stamped source artifact still matches")

    # 9. Cited requirements are reproduced, not just named. A task header pointing at
    #    "FR-002" is useless to a reader working from this document alone if FR-002's text
    #    lives only in spec.md — the rule exists, but nothing enforced it until here.
    section("[9] Cited requirements reproduced")
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
            listing(missing, 12, ", ") + " — a reader working from this file alone cannot look them up",
        )
    else:
        record("pass", f"all {len(cited)} cited requirement ids are stated in the document")

    # 9b. A forward reference resolves. "the retry policy is defined in T019" is worse
    #     than an open question when T019 is not in the document: the reader stops looking.
    #     The Step 3d rule said so and nothing checked it — the one rule in that list with
    #     no machine behind it.
    section("[10] Forward references")
    known_ids = set(sections)
    # Pre-completed rows are real tasks too: a table row `| T004 | … |` delivers its work.
    known_ids |= {m.group(1) for m in re.finditer(r"^\|\s*\**\s*(T\d+)\b", bp, re.M)}
    # A slice's predecessors deliver their own tasks. Without this a split feature fails
    # here on every reference across the seam, which is most of them.
    known_ids |= chain_ids
    # Every id tasks.md declares is a task of this feature, wherever its section ends up.
    # Without this the first slice of a split cannot pass until the second exists, which
    # inverts the only order anyone would work in.
    # Which ids belong to some other feature in this repo. A Why that says "feature 002's
    # T021" was a hard failure, which is the wrong verdict for a correct cross-reference.
    other_feature: dict = {}
    for other in sorted(glob.glob(os.path.join(root, "specs", "*", "tasks.md"))):
        if os.path.realpath(other) == os.path.realpath(tasks_path):
            continue
        try:
            otext = open(other, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for oid in re.findall(r"^\s*-\s*\[[ xX]\]\s*(T\d+)\b", otext, re.M):
            other_feature.setdefault(oid, os.path.basename(os.path.dirname(other)))
    feature_ids: set[str] = set()
    if os.path.isfile(tasks_path):
        feature_ids = set(re.findall(r"^\s*-\s*\[[ xX]\]\s*(T\d+)\b",
                          open(tasks_path, encoding="utf-8", errors="replace").read(), re.M))
    # "defined in T019", "see T019", "delivered by T019", "T019 creates it" — a reference
    # is a task id named in prose, not a task's own heading and not a dependency list.
    # **Dependencies**: lines name earlier tasks by design; check them too, since a
    # dependency on a task that does not exist is the same defect.
    dangling: list[str] = []
    elsewhere: list[str] = []
    for tid, sec in sections.items():
        for line in sec.split("\n"):
            t = line.strip()
            if t.startswith("###") or t.startswith("|"):
                continue
            for m in re.finditer(r"\bT(\d{2,})\b", t):
                ref = "T" + m.group(1)
                if ref == tid or ref in known_ids:
                    continue
                if ref in feature_ids:
                    elsewhere.append(f"{tid}: points at {ref}, a task of this feature that this blueprint does not carry")
                    continue
                if ref in other_feature:
                    elsewhere.append(f"{tid}: points at {ref}, which belongs to {other_feature[ref]}")
                    continue
                dangling.append(f"{tid}: points at {ref}, which no section here or in a **Base** blueprint delivers — {t[:60]}")
    if dangling:
        # Deduplicate on (task, target): one missing task cited three times is one problem.
        seen, unique = set(), []
        for d in dangling:
            key = d.split(" — ")[0]
            if key not in seen:
                seen.add(key)
                unique.append(d)
        record(
            "fail",
            f"{len(unique)} forward reference(s) point at a task the document does not have",
            listing(unique, 8) + "\na promise pointing at a task that never delivers is worse than an open question",
        )
    if elsewhere:
        # Not `elif`: a document with one dangling reference and nine that resolve
        # elsewhere reported only the first, so the nine looked like they had passed.
        # A pass, not a warning: every one of these resolves — to a sibling slice, to
        # another feature, or to a task of this feature that lives in another document —
        # and the line that reported them ended by saying so itself.
        uniq2 = list(dict.fromkeys(elsewhere))
        record(
            "pass",
            f"{len(uniq2)} reference(s) resolve outside this blueprint — expected across slices and features",
            listing(uniq2),
        )
    if not dangling and not elsewhere:
        record("pass", "every task id referenced in prose has a section")

    # 11. Open questions — not pass/fail, but a blocked task is the thing a reader
    #    most needs to see before they start typing.
    # Close at a heading of the same depth or shallower; `^##\s` let a `### Open
    # Questions` swallow every following `###` section to the end of the document.
    oq = re.search(
        r"^(?P<h>#{2,})\s*Open Questions\b(?P<body>.*?)(?=^#{1,%d}\s|\Z)" % 6, bp, re.M | re.S
    )
    if oq:
        depth = len(oq.group("h"))
        oq = re.search(
            r"^#{%d}\s*Open Questions\b(.*?)(?=^#{1,%d}\s|\Z)" % (depth, depth), bp, re.M | re.S
        )
    if not oq:
        section("[11] Open questions")
        record(
            "warn",
            "no Open Questions section",
            "the section's absence and \"the generator had none\" look identical from here;"
            "\nsay which by keeping the section and writing None in it",
        )
    if oq:
        body = oq.group(1)
        # Two shapes in the wild: a table of rows, or a heading per question.
        rows = [ln for ln in body.split("\n") if ln.strip().startswith("|")]
        rows = [r for r in rows if not re.match(r"^\s*\|[\s|:-]+\|\s*$", r)]
        if rows:
            rows = rows[1:]  # drop the header row
            blocking = [r for r in rows if re.search(r"\|\s*[*_`]*\s*(?:yes|y|예|blocking)\b", r, re.I)]
        else:
            rows = re.findall(r"^#+\s*(OQ-\d+[^\n]*)", body, re.M)
            blocking = [r for r in rows if re.search(r"blocking|blocks|차단", r, re.I)
                        and not re.search(r"non-?blocking|미차단", r, re.I)]
        section("[11] Open questions")
        record(
            "warn" if blocking else "pass",
            f"{len(rows)} open question(s), {len(blocking)} blocking",
            "blocking items must be answered before the tasks they block can be typed" if blocking else "",
        )

    flush_passes()
    print(f"\n{CYAN}=== Summary ==={NC}")
    counts = {k: sum(1 for r in results if r[0] == k) for k in ("pass", "warn", "fail")}
    print(f"  {GREEN}PASS{NC}: {counts['pass']}  {YELLOW}WARN{NC}: {counts['warn']}  {RED}FAIL{NC}: {counts['fail']}")
    if counts["fail"]:
        print(f"\n{RED}Validation FAILED — {counts['fail']} issue(s) found{NC}")
        return 1
    if counts["warn"]:
        print(f"\n{GREEN}No failures{NC} — {counts['warn']} warning(s) above; read them before you rely on this document")
    else:
        print(f"\n{GREEN}All checks passed{NC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
