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

import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _blueprint_parse import (  # noqa: E402  (path set above)
    BEFORE_AFTER_RE,
    base_chain,
    body_replaced_by_marker,
    changed_since,
    dependent_slices,
    code_blocks,
    count_path_labels,
    file_kinds,
    file_paths,
    looks_like_path,
    parse_mode,
    repo_root,
    resolve_feature_dir,
    split_tasks,
    stamped_head,
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
        print("Usage: validate_blueprint.py [specs/NNN-feature-name] [--strict-guide]")
        print("\nChecks blueprint.md against tasks.md and the working tree.")
        print("  --strict-guide  make the guide-mode body findings failures rather than warnings")
        print("Exit 0 pass, 1 failures found, 2 feature directory not resolved.")
        return 0
    strict_guide = "--strict-guide" in argv
    argv = [a for a in argv if a != "--strict-guide"]
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
        print(f"{CYAN}[0] Sibling slices{NC}")
        record(
            "pass",
            f"this feature is split across {len(chain) + len(later) + 1} blueprint(s)",
            "base: " + (", ".join(os.path.relpath(cp, root) for cp, _t in chain) or "none")
            + " | continued in: " + (", ".join(os.path.relpath(cp, root) for cp, _t in later) or "none")
            + f" — {len(chain_ids)} task(s) live in them",
        )

    # 1. Coverage — every task id in tasks.md reaches the blueprint
    print(f"{CYAN}[1] Task coverage{NC}")
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
            record("fail", f"{len(missing)} task(s) from tasks.md missing", ", ".join(missing[:12]))
        else:
            record("pass", f"all {len(declared)} tasks from tasks.md appear")
    else:
        record("warn", "tasks.md not found — coverage not checked")

    if duplicate_ids:
        record(
            "fail",
            "the same task id has more than one section",
            ", ".join(sorted(set(duplicate_ids)))
            + "\none task = one id: give each its own heading, or merge them into one",
        )

    # 2. Rationale — every task states why it looks the way it does
    print(f"\n{CYAN}[2] Rationale (Why){NC}")
    no_why = sorted(tid for tid, sec in sections.items() if "**Why**" not in sec)
    if not sections:
        record("warn", "no task sections found (check blueprint format)")
    elif no_why:
        record("fail", f"{len(no_why)} task(s) without a Why", ", ".join(no_why[:12]))
    else:
        record("pass", f"all {len(sections)} task sections carry a Why")

    print(f"\n{CYAN}[3] Working-tree claims{NC}")
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
        record("fail", "a declared path resolves outside the repository", "\n".join(escapes[:6]))
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
            "\n".join(hunk_without_modify[:6]) + "\nif the file it edits already exists, declare it (modify), not (new)",
        )

    if missing_modify:
        record(
            "fail",
            "a task declares a (modify) file that is not in the tree",
            "\n".join(missing_modify[:6]) + "\nthe path is wrong, or the file is new and mislabelled",
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

    def has_moved(rel_path: str) -> bool:
        if rel_path not in moved:
            moved[rel_path] = bool(changed_since(root, head, rel_path))
        return moved[rel_path]
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
                    head = needle.strip().split("\n")[0][:50]
                    not_quoted.append(f"{tid}: {named} does not contain the Before block (starts {head!r})")
                if needle and text.count(needle) > 1 and not has_moved(named):
                    ambiguous_anchor.append(f"{tid}: the Before block appears {text.count(needle)} times in {named}")
                if needle and text.count(needle) == 1:
                    actual = text[: text.index(needle)].count("\n") + 1
                    if actual != cites[0]:
                        if first_touch.get(named) in (None, tid):
                            misnumbered.append(f"{tid}: Before says line {cites[0]}, the quoted text is at line {actual} of {named}")
                        else:
                            # An earlier task rewrites this file, so where the text sits on
                            # disk says nothing about where it will sit when the hunk runs.
                            unjudged.add(named)
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
        record("fail", "Before block cites a line past the end of its file", "\n".join(out_of_range[:6]))
    else:
        record("pass", "Before line references are within their files")
    if not_quoted:
        record(
            "fail",
            "a Before block is not in the file it quotes",
            "\n".join(not_quoted[:6]) + "\nthe applier matches this text exactly; quote the file as it is now",
        )
    else:
        record("pass", "every checkable Before block is in the file it quotes")
    if ambiguous_anchor:
        record(
            "warn",
            "a Before block appears more than once in its file — the anchor is ambiguous",
            "\n".join(ambiguous_anchor[:6]) + "\nthe applier refuses these; quote more of the surrounding lines",
        )
    if unjudged:
        # Without this line the run names one task and looks like the others were checked.
        record(
            "pass",
            f"line positions not checked in {len(unjudged)} file(s) an earlier task rewrites",
            ", ".join(sorted(unjudged)[:6]) + " — the applier checks these, since it applies in order",
        )
    if misnumbered:
        record(
            "warn",
            "a Before cites a line number that is not where its text is",
            "\n".join(misnumbered[:6]) + "\nthe applier will still place it; the reader following the number will not",
        )
    if moved_first:
        record(
            "warn",
            "a Before cites a line past the end of the file on disk, in a file an earlier task changes",
            "\n".join(moved_first[:6])
            + "\ndisk cannot check this one; apply_blueprint.py can, since it applies in order and matches the text",
        )
    if ambiguous:
        record(
            "warn",
            "a Before citation is out of range for some of its task's files",
            "\n".join(ambiguous[:6]) + "\nname the file the block quotes so the reference can be checked",
        )
    dangling = [
        tid
        for tid, sec in sections.items()
        if len(re.findall(r"^\*\*Before\*\*", sec, re.M)) > len(BEFORE_AFTER_RE.findall(sec))
    ]
    if dangling:
        record(
            "fail",
            "a **Before** block has no **After** after it",
            ", ".join(sorted(dangling)) + "\nthe applier refuses these; give every Before its After",
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
            "\n".join(lossy[:6])
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
        record("fail", "a task declares a new file and gives it no content", "\n".join(empty_new[:6]))
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
            "\n".join(unanchored[:6]) + "\nthe applier cannot place these; quote the surrounding lines in a Before block",
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
            "\n".join(drifted[:6]) + "\nedited since scaffolding, or scaffolded from a different version — the applier tests the block, not the file",
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
            "\n".join(stray_labels[:6]) + "\nthe tools ignore the label and a reader follows it to a file that is not there",
        )
    else:
        record("pass", "every block label names a file its task declares")

    # 4. Multi-file tasks map each block to a path
    print(f"\n{CYAN}[4] Multi-file task labels{NC}")
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
        for blk in [c for _i, c in code_blocks(strip_quoted(sec))]:
            for ln in blk.split("\n"):
                if re.search(r"(//|#|/\*)\s*\.\.\.", ln):
                    ellipsis.append(f"{tid}: {ln.strip()[:60]}")
    if ellipsis:
        record("fail", "ellipsis placeholder in a code block", "\n".join(ellipsis[:6]))
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
            "\n".join(history[:6]) + "\nsay it in the task's prose; cleanup leaves doc comments alone, so this one stays for ever",
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
            "\n".join(abbreviated[:6]) + "\nthe applier matches the Before text exactly; an abbreviation never matches",
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
                ", ".join(sorted(set(stubs))[:10]),
            )
        else:
            record("pass", f"{mode} blueprint has no stub markers")

    # 5a. Guide mode's one promise: the bodies are the developer's work. "No body logic"
    #     lived only in the prompt, so a skeleton that quietly carried a branch or a query
    #     read as compliant. Control flow inside an authored block is the tell — a
    #     signature and a not-implemented marker need none of it.
    if mode.startswith("guide"):
        # Guide modes only — in a full-code mode the numbering skips from [5] to [7].
        print(f"\n{CYAN}[6] Guide-mode bodies{NC}")
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
        )
        # The same basename reading the scaffold validator uses: a file with one of these
        # in its name holds behavior, and a guide skeleton for it has to carry a marker.
        BEHAVIORAL = re.compile(r"(service|handler|usecase|use_case|interactor|controller|scheduler|test|spec\.)", re.I)
        smuggled, unmarked, dictated = [], [], []
        for tid, sec in sections.items():
            kinds = dict(file_kinds(sec))
            new_behavioral = [f for f, k in kinds.items() if k == "new" and BEHAVIORAL.search(os.path.basename(f))]
            # An After is authored content — only the Before is a quotation — and in a
            # guide blueprint the behaviour changes usually live in modify hunks, so
            # skipping them checked the promise everywhere except where it mattered.
            blocks = [c for _i, c in code_blocks(strip_quoted(sec), content_only=True)]
            blocks += after_additions(sec)
            if new_behavioral and blocks and not any(MARKER.search(b) for b in blocks):
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
                # The marker's message, where no code check has ever looked.
                for m in re.finditer(r"""(?:TODO|NotImplementedError|UnsupportedOperationException|panic|todo!|fatalError)\s*\(\s*["'`](.+?)["'`]\s*\)""", blk, re.S):
                    hit = CODE_IN_PROSE.search(m.group(1))
                    if hit:
                        # The fragment, not the opening of the message: a reviewer had to
                        # bisect one marker twelve times to find what had fired.
                        frag = hit.group(0).strip()
                        at = m.group(1).find(frag)
                        around = m.group(1)[max(0, at - 20): at + len(frag) + 20].strip()
                        dictated.append(f"{tid}: a marker message spells out the body — {frag!r} in …{around}…")
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
                "\n".join(unlabelled_markers[:6])
                + "\n--markers and cleanup trace a marker to its task by that id; without it the marker is orphaned",
            )

        demolished = []
        for tid, sec in sections.items():
            for first, n in body_replaced_by_marker(sec):
                demolished.append(f"{tid}: replaces {n} line(s) of working code with a marker — first is {first[:46]!r}")
        if demolished:
            record(
                "fail" if strict_guide else "warn",
                "a guide-mode hunk replaces existing code with a not-implemented marker",
                "\n".join(demolished[:6])
                + "\nthe applier's build compiles the skeleton and goes green; the behavior deleted here"
                  "\nshows up in the project's own tests, which that build never runs",
            )

        if dictated:
            record(
                "fail" if strict_guide else "warn",
                "a not-implemented marker's message spells out the code it is standing in for",
                "\n".join(dictated[:6])
                + "\nsay what to achieve and what to avoid; an exact expression makes typing transcription, which is what guide mode exists to avoid",
            )
        if unmarked:
            record(
                "fail" if strict_guide else "warn",
                "a guide-mode skeleton for a file with behavior carries no marker",
                "\n".join(unmarked[:6]) + "\na structural file (types, config, wiring) is complete on purpose; a service or a test is not",
            )
        if smuggled:
            record(
                "fail" if strict_guide else "warn",
                "a guide-mode block looks like it contains body logic",
                "\n".join(smuggled[:6]) + "\nguide skeletons carry signatures and markers; the branches are the developer's to write",
            )
        else:
            record("pass", "no guide-mode block carries body logic")

    # 5b. Regeneration discipline. The generate spec says a regeneration keeps unchanged
    #     tasks verbatim, so the diff stays reviewable — and until now that was a sentence
    #     in a prompt with nothing behind it. If the previous blueprint is in git, the
    #     claim is checkable: sources that did not move cannot justify rewritten tasks.
    print(f"\n{CYAN}[7] Regeneration{NC}")
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
                ", ".join(dropped[:12])
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
                ", ".join(rewritten[:12])
                + "\nunchanged inputs cannot justify new text — keep those tasks verbatim",
            )
        else:
            record(
                "pass",
                f"{len(rewritten)} of {len(sections)} task(s) rewritten, {len(sections) - len(rewritten)} kept verbatim",
                ", ".join(rewritten[:12]) if len(rewritten) <= 12 else "",
            )

    # 8. Staleness — the header records what the blueprint was built from, so drift is a
    #    fact to check rather than something everyone assumes away.
    print(f"\n{CYAN}[8] Freshness{NC}")
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
            record(
                "warn",
                f"{len(own_work)} stamped source(s) are edited by this blueprint's own tasks",
                "\n".join(own_work)
                + "\nexpected once that task is typed; cite such a file in the Why that needs it rather than stamping it",
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
    print(f"\n{CYAN}[9] Cited requirements reproduced{NC}")
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

    # 9b. A forward reference resolves. "the retry policy is defined in T019" is worse
    #     than an open question when T019 is not in the document: the reader stops looking.
    #     The Step 3d rule said so and nothing checked it — the one rule in that list with
    #     no machine behind it.
    print(f"\n{CYAN}[10] Forward references{NC}")
    known_ids = set(sections)
    # Pre-completed rows are real tasks too: a table row `| T004 | … |` delivers its work.
    known_ids |= {m.group(1) for m in re.finditer(r"^\|\s*\**\s*(T\d+)\b", bp, re.M)}
    # A slice's predecessors deliver their own tasks. Without this a split feature fails
    # here on every reference across the seam, which is most of them.
    known_ids |= chain_ids
    # Every id tasks.md declares is a task of this feature, wherever its section ends up.
    # Without this the first slice of a split cannot pass until the second exists, which
    # inverts the only order anyone would work in.
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
            "\n".join(unique[:8]) + "\na promise pointing at a task that never delivers is worse than an open question",
        )
    elif elsewhere:
        uniq2 = list(dict.fromkeys(elsewhere))
        record(
            "warn",
            f"{len(uniq2)} reference(s) point at a task of this feature that this blueprint does not carry",
            "\n".join(uniq2[:6]) + "\nexpected while a feature is split across slices, or before the rest is written",
        )
    else:
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
        print(f"\n{CYAN}[11] Open questions{NC}")
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
        print(f"\n{CYAN}[11] Open questions{NC}")
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
