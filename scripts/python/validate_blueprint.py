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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _blueprint_parse import (  # noqa: E402  (path set above)
    code_blocks,
    count_path_labels,
    file_kinds,
    file_paths,
    parse_mode,
    repo_root,
    resolve_feature_dir,
    split_tasks,
    strip_quoted,
)

# Both the identical-pair check and the dropped-line check read the same pairs. The gap
# between the two blocks may not contain another **Before**: with a plain `.*?` a
# generator that emitted Before(A), Before(B), After(C) paired A with C — a diff that is
# not in the document — and never reported the dangling Before at all.
BEFORE_AFTER_RE = re.compile(
    r"\*\*Before\*\*[^\n]*\n+```\w*\n(.*?)```"
    r"(?:(?!\*\*Before\*\*)[\s\S])*?"
    r"\*\*After\*\*[^\n]*\n+```\w*\n(.*?)```",
    re.S,
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
        present = set(sections) | precompleted
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

    # 3. Before blocks quote something that is actually there
    print(f"\n{CYAN}[3] Working-tree claims{NC}")
    out_of_range, moved_first, identical, ambiguous, misnumbered = [], [], [], [], []
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
        labels_at = [
            (m.start(), m.group(1))
            for m in re.finditer(r"^\*\*`([^`]+)`\*\*", sec, re.M)
            if m.group(1) in lengths
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
                if needle and text.count(needle) == 1:
                    actual = text[: text.index(needle)].count("\n") + 1
                    if actual != cites[0] and first_touch.get(named) in (None, tid):
                        misnumbered.append(f"{tid}: Before says line {cites[0]}, the quoted text is at line {actual} of {named}")
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
        if new_paths and not code_blocks(sec, content_only=True):
            empty_new.append(f"{tid}: declares {', '.join(new_paths)} (new) and carries no code block")
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
        CONTROL = re.compile(
            r"^\s*(if|for|while|switch|when|elif|else\s+if|do|try|catch|except|match)\b[\s({:]"
        )
        smuggled = []
        for tid, sec in sections.items():
            for blk in [c for _i, c in code_blocks(strip_quoted(sec))]:
                if re.search(r"TODO\(|NotImplementedError|UnsupportedOperationException|fatalError\(|todo!\(|unimplemented!\(", blk):
                    # A block that still carries its marker is a skeleton; a branch beside
                    # the marker is a hint the author started writing the body.
                    hits = [ln.strip() for ln in code_lines(blk) if CONTROL.match(ln)]
                    if len(hits) >= 2:
                        smuggled.append(f"{tid}: {len(hits)} control-flow lines beside a not-implemented marker")
                    continue
                hits = [ln.strip() for ln in code_lines(blk) if CONTROL.match(ln)]
                if len(hits) >= 3:
                    smuggled.append(f"{tid}: {len(hits)} control-flow lines in a block with no marker — {hits[0][:50]!r}")
        if smuggled:
            record(
                "warn",
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

        stale, unknown = [], []
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

    # 10. Open questions — not pass/fail, but a blocked task is the thing a reader
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
        print(f"\n{CYAN}[10] Open questions{NC}")
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
