#!/usr/bin/env python3
"""apply_blueprint.py — turn a blueprint's promise into machine evidence.

`validate_blueprint.py` checks the document's shape. This checks its *content*: it
copies the working tree aside, types every task's code into that copy the way a
developer would, and then builds it. A blueprint that says "this compiles" either
survives that or it does not.

Applying is deterministic and unforgiving on purpose. A `**Before**` block is an
anchor into a real file; if it is not there verbatim, or is there twice, the task is
reported as a defect rather than repaired by guesswork. Silent repair is what lets a
lossy hunk reach a reader as if it were sound.

The throwaway tree is a plain recursive copy, not `git worktree add`. A worktree needs
a git repo and a clean index, and the blueprint most worth checking is the one written
against uncommitted work; a copy needs neither and cannot touch the original.

Usage: python3 apply_blueprint.py [feature-dir] [--build] [--keep]
  feature-dir: specs/{feature}/ (default: auto-detect from the current branch)
  --build:     run the project's build in the copy and report its exit code
  --keep:      print the copy's path instead of deleting it
  --require-anchors:
               fail when a task's code is not anchored, or when nothing anchored at
               all. Off by default because a guide blueprint of pure instructions
               legitimately applies nothing; on in CI, where "verified nothing" and
               "verified everything" must not share an exit code.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _blueprint_parse import (  # noqa: E402  (path set above)
    file_kinds,
    parse_mode,
    section_events,
    repo_root,
    resolve_feature_dir,
    scan,
    split_tasks,
)
import tempfile

GREEN, YELLOW, RED, CYAN, NC = "\033[0;32m", "\033[0;33m", "\033[0;31m", "\033[0;36m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = YELLOW = RED = CYAN = NC = ""

SCRIPT_VERSION = "1.2.0"

# Regenerated, never authored, so copying them only slows the run down; .git would make
# the copy look like a second checkout. These names mean the same thing at any depth.
SKIP_ANYWHERE = {".git", "node_modules", "__pycache__", ".venv", ".gradle"}
# These are build output at the root of a project and ordinary package names below it.
# Matching them at any depth dropped `src/com/example/build/` from the copy, and --build
# then failed with "cannot find symbol" while the report blamed the blueprint.
SKIP_AT_ROOT = {"build", "target", "out", "dist"}

results: list[tuple[str, str, str]] = []  # (status, name, evidence)


def record(status: str, name: str, evidence: str = "") -> None:
    results.append((status, name, evidence))
    mark = {"pass": f"{GREEN}✓{NC}", "warn": f"{YELLOW}⚠{NC}", "fail": f"{RED}✗{NC}"}[status]
    print(f"  {mark} {name}")
    if evidence:
        for line in evidence.split("\n"):
            print(f"      {line}")




# --- Application ------------------------------------------------------------------


class Defect(Exception):
    """The blueprint cannot be applied as written. Never repaired, only reported."""


class AlreadyApplied(Exception):
    """The edit is already in the file — the tree has moved past this blueprint."""


def replace_once(path: str, before: str, after: str) -> int:
    """Replace the one occurrence of `before` with `after`; return its 1-based line."""
    if not os.path.isfile(path):
        raise Defect(f"{rel(path)}: Before block targets a file that does not exist")
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    candidates = [(before, after)]
    # The fence contributes the block's final newline; the quoted region may sit at the
    # end of a file that has none. That end-of-file case is the whole justification, so
    # it is the whole allowance: dropping the newline anywhere else un-anchors the block
    # from a line boundary, and `    val fee = 0` then matches inside `    val fee = 0L`
    # and writes `    val fee = feeOf(x)L` while reporting the task applied.
    if before.endswith("\n") and text.endswith(before[:-1]):
        candidates.append((before[:-1], after[:-1] if after.endswith("\n") else after))

    for b, a in candidates:
        n = text.count(b)
        if n == 1:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text.replace(b, a, 1))
            return text[: text.index(b)].count("\n") + 1
        if n > 1:
            raise Defect(f"{rel(path)}: Before block matches {n} places — the anchor is ambiguous")
    # Before the anchor is called a defect: has this edit already been made? Running the
    # applier on a feature that is already implemented is a category error — the tool
    # describes work that has not happened yet — and reporting "anchor not found" sends
    # the reader hunting for a blueprint bug that is not there.
    if after.strip() and after.strip() in text:
        raise AlreadyApplied(f"{rel(path)}: the After content is already in the file")
    # Guide mode: the After adds a signature with a marker body, and the developer then
    # replaces the marker — so after implementation neither the Before nor the After is in
    # the file, and "not found verbatim" sent the reader hunting for a blueprint bug. If
    # every line the After ADDS (markers aside) is in the file, the change has landed.
    added = [
        ln.strip() for ln in after.split("\n")
        if ln.strip() and ln.strip() not in before and not re.search(r"\bT\d{3,}:", ln)
        and re.search(r"[A-Za-z]", ln) and ln.strip() not in ("{", "}", "};", ")", ");")
    ]
    if len(added) >= 1 and all(ln in text for ln in added):
        raise AlreadyApplied(
            f"{rel(path)}: the lines the After adds are in the file and its markers are not — implemented since"
        )
    head = before.strip().split("\n")[0][:60]
    raise Defect(f"{rel(path)}: Before block not found verbatim (starts {head!r})")



def inside(tree: str, path: str) -> str:
    """Resolve `path` under `tree`, refusing anything that leaves it.

    Paths come out of the blueprint, and `os.path.join(tree, "/etc/passwd")` is
    `/etc/passwd` — an absolute or `../` target would write to the real filesystem,
    breaking the one promise this tool makes about not touching your tree. A symlink
    inside the copy is followed by open(), so the resolved path is checked too.
    """
    full = os.path.realpath(os.path.join(tree, path))
    root = os.path.realpath(tree)
    if full != root and not full.startswith(root + os.sep):
        raise Defect(f"{path}: declared path resolves outside the working copy")
    return full


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def write_file(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)


_tree = ""
# Declared-new files that were already on disk and were removed from the copy before applying.
_overwritten: list[str] = []


def rel(path: str) -> str:
    return os.path.relpath(path, _tree) if _tree else path


def apply_task(tree: str, section: str) -> tuple[str, int]:
    """Apply one task section to the copied tree. Returns (note, blocks consumed)."""
    # A path declared twice keeps its FIRST kind: `(new)` then `(modify)` is a
    # create-then-edit narrative, and taking the last left the file unwritten.
    kinds: dict[str, str] = {}
    for _p, _k in file_kinds(section):
        kinds.setdefault(_p, _k)
    paths = list(kinds)
    if not paths:
        return "no file declared", 0
    if all(k == "delete" for k in kinds.values()):
        return "delete task", 0
    # A (modify) path has to be in the tree before anything else is decided. Checked at
    # the write site, a task whose only block had no marker was reported "unanchored" and
    # never reached the check — a wrong path with an unlabelled block passed all three
    # tools with exit 0.
    for path, kind in kinds.items():
        if kind == "modify" and not os.path.isfile(inside(tree, path)):
            raise Defect(f"{path}: declared (modify) but not in the tree — the path is wrong, or the file is new and mislabelled")

    def hunk_target(current: str | None) -> str:
        """Which file a **Before**/**After** pair edits.

        A multi-file task labels its blocks, but a task that creates two files and edits
        a third often introduces the hunks in prose ("the four TransferService edits
        below") and leaves the last label pointing at a file it has finished writing. A
        hunk can only edit a declared `(modify)` path, so when there is exactly one it is
        the target and nothing is being guessed. When there are several, it is a real
        ambiguity in the document and the task fails.
        """
        if current and kinds.get(current) in ("modify", "unknown"):
            return current
        mods = [p for p, k in kinds.items() if k == "modify"]
        if len(mods) == 1:
            return mods[0]
        raise Defect(
            "a Before/After hunk follows a **`"
            + (current or "?")
            + "`** block, and the task declares "
            + (f"{len(mods)} modified files" if mods else "no modified file")
            + " — label the hunk with its path"
        )

    current = paths[0] if len(paths) == 1 else None
    # A single new file's one code block is that file, with nothing to announce it. For
    # a modify, a bare block could be a fragment or the whole file, so it needs saying.
    pending = "content" if current and kinds[current] == "new" else None
    before: str | None = None
    before_at: str | None = None
    cite: int | None = None
    applied, unanchored, seen, inferred = 0, 0, 0, 0
    # A task with several hunks against an implemented file used to stop at the first
    # one already present and report "the After content is already in the file" for
    # the whole task — true of that hunk, not of the two that no longer matched at all.
    hunks_already, hunks_missing, misnumbered = 0, [], []
    hunk_defects: list[Defect] = []

    for kind, payload in section_events(section):
        if kind == "label":
            current, pending = payload, "content"
        elif kind == "cite":
            cite = payload
            continue
        elif kind == "directive":
            if payload == "before":
                resolved = hunk_target(current)
                inferred += resolved != current
                before_at = resolved
                cite = None
            pending = payload
        else:
            _info, payload = payload
            seen += 1
            if pending is None:
                unanchored += 1
                continue
            if pending in ("before", "after"):
                target = inside(tree, before_at or "")
            elif current is None:
                raise Defect("multi-file task has a code block before any **`path`** label")
            else:
                target = inside(tree, current)
            if pending == "before":
                before = payload
                pending = None
            elif pending == "after":
                if before is None:
                    raise Defect("an **After** block with no **Before** before it")
                try:
                    at = replace_once(target, before, payload)
                except AlreadyApplied as exc:
                    hunks_already += 1
                    hunks_missing.append(str(exc))
                except Defect as exc:
                    # Held, not raised: whether this is a defect depends on the other
                    # hunks. Beside one already in the file it is "implemented since,
                    # differently"; on its own it is the wrong Before it looks like.
                    hunk_defects.append(exc)
                else:
                    applied += 1
                    # The number the Before cites against the line the text was found on,
                    # in the copy as the earlier tasks left it. The document validator
                    # cannot check a file an earlier task changes; this is the one place
                    # that can, and a reader following the number deserves to know.
                    if cite is not None and at != cite:
                        misnumbered.append(f"{rel(target)}: Before says line {cite}, matched at line {at}")
                before, pending = None, None
            elif pending == "replace":
                write_file(target, payload)
                pending, applied = None, applied + 1
            elif pending == "content":
                pending = None
                declared = kinds.get(current)
                exists = os.path.exists(target)
                # A (new) target that exists here was written by an earlier task of this
                # run — the copy started without any of the blueprint's new files.
                if declared not in ("new", None) and not exists:
                    # A `(modify)` path that is not in the tree is a wrong path in the
                    # blueprint. Creating it from the fragment made a phantom file that
                    # no source set compiles, so --build passed and nothing was changed.
                    raise Defect(
                        f"{rel(target)}: declared ({declared}) but not in the tree —"
                        " the path is wrong, or the file is new and mislabelled"
                    )
                if exists and declared != "new":
                    # No **Before**, no **Replace entire file** — whether this block is the
                    # file or a piece of it is not written down anywhere, so it is not applied.
                    unanchored += 1
                    continue
                write_file(target, payload)
                applied += 1

    if before is not None:
        raise Defect(f"{before_at}: a **Before** block with no **After** after it")
    if hunk_defects and not hunks_already:
        raise hunk_defects[0]
    if hunks_already and not applied:
        # Nothing of this task's hunks applied fresh: the tree already holds the work,
        # and a hunk that matched neither Before nor After beside one that did is the
        # implementation having moved on, not a blueprint bug.
        summary = f"{hunks_already} hunk(s) already in the file"
        if hunk_defects:
            summary += f", {len(hunk_defects)} Before not found — implemented since, differently"
        raise AlreadyApplied(summary + "".join(f"\n  {m}" for m in hunks_missing[:3]))
    if applied:
        note = f"{applied} edit(s) -> {', '.join(sorted(set(paths)))}"
        if inferred:
            note += f"; {inferred} hunk(s) had no path label, resolved to the sole modified file"
        if unanchored:
            note += f"; {unanchored} unanchored block(s) left alone"
        if hunks_already:
            note += f"; {hunks_already} hunk(s) were already in the file"
        if hunk_defects:
            note += f"; {len(hunk_defects)} hunk(s) matched nothing"
        if misnumbered:
            note += "".join(f"\n  line number: {m}" for m in misnumbered[:4])
        return note, applied
    if unanchored:
        return f"{unanchored} code block(s) with no Before/After or Replace marker", 0
    return "no code block", 0


# --- Copying and building ---------------------------------------------------------


def gitignored_dirs(root: str) -> set[str]:
    """Bare directory names from .gitignore. Anything with a glob or a path is left in."""
    names = set()
    path = os.path.join(root, ".gitignore")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.strip().rstrip("/")
            if line and not line.startswith(("#", "!")) and not re.search(r"[*?\[\]/]", line):
                names.add(line)
    return names


def copy_tree(root: str) -> str:
    # A bare name in .gitignore matches at any depth, which is how git reads it too.
    anywhere = SKIP_ANYWHERE | gitignored_dirs(root)
    real_root = os.path.realpath(root)
    dest = tempfile.mkdtemp(prefix="blueprint-apply-")

    def ignore(directory: str, names: list[str]) -> list[str]:
        drop = anywhere | SKIP_AT_ROOT if os.path.realpath(directory) == real_root else anywhere
        # Directories only. A source file named `dist` or `out` is authored content.
        return [n for n in names if n in drop and os.path.isdir(os.path.join(directory, n))]

    try:
        shutil.copytree(root, dest, dirs_exist_ok=True, symlinks=False,
                        ignore_dangling_symlinks=True, ignore=ignore)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


BUILD_CANDIDATES = [
    ("tools/build.sh", "bash tools/build.sh"),
    ("gradlew", "./gradlew build"),
    ("package.json", "npm test"),
    ("Makefile", "make test"),
    (None, "python3 -m unittest discover"),
]


def build_command(tree: str, blueprint: str) -> str | None:
    for _, line, in_fence, _ in scan(blueprint):
        if not in_fence and line.startswith("**Build**:"):
            return line.split(":", 1)[1].strip().strip("`")
    for marker, cmd in BUILD_CANDIDATES:
        if marker and os.path.exists(os.path.join(tree, marker)):
            return cmd
    # Nothing declared and nothing recognised. A Python tree at least has a discover
    # target; inventing a command for anything else would only report its own failure.
    if any(f.startswith("test") for f in os.listdir(tree)) or os.path.isdir(os.path.join(tree, "tests")):
        return "python3 -m unittest discover"
    return None


BUILD_TIMEOUT = 900


def run_build(tree: str, cmd: str) -> int:
    print(f"\n{CYAN}=== Build ==={NC}")
    # The command can come from the blueprint's own **Build**: line, so it is shown
    # before it runs — this is a shell command out of a generated document.
    print(f"  $ {cmd}")
    print(f"  (in {tree}, limit {BUILD_TIMEOUT}s)")
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=tree, capture_output=True, text=True, timeout=BUILD_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        # A build that hangs is a failed build. Without a limit the applier waits for
        # ever on exactly the code it exists to be suspicious of.
        record("fail", f"build did not finish within {BUILD_TIMEOUT}s", cmd)
        return 1
    tail = (proc.stdout + proc.stderr).rstrip().split("\n")[-20:]
    record(
        "pass" if proc.returncode == 0 else "fail",
        f"exit code {proc.returncode}",
        "\n".join(tail),
    )
    return proc.returncode


def main() -> int:
    global _tree
    argv = sys.argv[1:]
    do_build, keep = "--build" in argv, "--keep" in argv
    strict_anchors = "--require-anchors" in argv
    args = [a for a in argv if not a.startswith("--")]

    root = repo_root()
    feature_dir = resolve_feature_dir(root, args[0] if args else None)
    if not feature_dir or not os.path.isdir(feature_dir):
        print(f"{RED}ERROR: feature directory not found.{NC}")
        print("Usage: apply_blueprint.py [specs/NNN-feature-name] [--build] [--keep] [--require-anchors]")
        return 2

    bp_path = os.path.join(feature_dir, "blueprint.md")
    if not os.path.isfile(bp_path):
        print(f"{RED}blueprint.md not found — run /speckit.blueprint.generate first.{NC}")
        return 1
    bp = open(bp_path, encoding="utf-8", errors="replace").read()
    tasks = split_tasks(bp)

    print(f"{CYAN}=== Blueprint Applier {SCRIPT_VERSION} ==={NC}")
    print(f"Feature: {os.path.relpath(feature_dir, root)}")
    print(f"Mode: {parse_mode(bp)} | {len(tasks)} task sections")

    # realpath: on macOS mkdtemp returns /var/... and inside() resolves to /private/var/...,
    # so an unresolved _tree made every Defect message a six-level ../ chain.
    tree = copy_tree(root)
    _tree = os.path.realpath(tree)

    # Start from a tree WITHOUT this blueprint's new files. In guide-scaffold mode the
    # skeletons are already on disk, and a copy that keeps them lets the build pass over a
    # task whose block is missing or mislabelled — the skeleton fills the hole and the
    # compiler never sees it. A file the blueprint declares new is a file the blueprint
    # has to supply; removing it first is what makes the build a test of the document.
    for _tid, section in tasks:
        for path, kind in file_kinds(section):
            if kind != "new" or path in _overwritten:
                continue
            try:
                full = inside(tree, path)
            except Defect:
                continue  # reported when the task itself is applied
            if os.path.isfile(full):
                os.remove(full)
                _overwritten.append(path)
    if _overwritten:
        print(f"  {YELLOW}{len(_overwritten)} declared-new file(s) were already on disk and were removed from"
              f" the copy first{NC} — the build tests what the blueprint supplies, not what the tree holds")
    print(f"Tree: {tree}\n")

    print(f"{CYAN}[1] Applying tasks in document order{NC}")
    failed, applied_tasks, unanchored_tasks, already = [], 0, [], []
    try:
        for tid, section in tasks:
            try:
                note, count = apply_task(tree, section)
            except AlreadyApplied as exc:
                already.append(tid)
                record("warn", f"{tid}  already applied", str(exc))
                continue
            except Defect as exc:
                failed.append(tid)
                record("fail", f"{tid}  FAILED", str(exc))
                continue
            if count:
                applied_tasks += 1
                record("pass", f"{tid}  applied", note)
            elif "no file" in note or "delete" in note or note == "no code block":
                record("warn", f"{tid}  skipped ({note})")
            else:
                unanchored_tasks.append(tid)
                record("warn", f"{tid}  skipped ({note})")

        if already:
            print(
                f"\n  {YELLOW}{len(already)} task(s) are already in the tree{NC} — this blueprint describes"
                "\n  work that is done, so applying it does not test anything. Run the applier before"
                "\n  implementing, or against a tree that predates the work."
            )

        print(f"\n{CYAN}=== Summary ==={NC}")
        print(f"  applied: {applied_tasks}  skipped: {len(tasks) - applied_tasks - len(failed)}"
              f"  {RED}FAILED{NC}: {len(failed)}"
              + (f"  {YELLOW}replaced{NC}: {len(_overwritten)} declared-new file(s) that were on disk" if _overwritten else ""))
        if unanchored_tasks:
            print(f"  {YELLOW}{len(unanchored_tasks)} task(s) carry code no marker anchors to a"
                  f" position: {', '.join(unanchored_tasks[:10])}{NC}")

        rc = 1 if failed else 0
        if strict_anchors and (unanchored_tasks or applied_tasks == 0):
            rc = 1
        if do_build and failed:
            print(f"\n{YELLOW}Build skipped — {len(failed)} task(s) did not apply, so a build here"
                  f" would report the applier's damage, not the blueprint's.{NC}")
        elif do_build:
            cmd = build_command(tree, bp)
            if cmd is None:
                print(f"\n{YELLOW}WARN: no build command declared and none recognised — build skipped.{NC}")
                print("      Add a `**Build**: <command>` line to the blueprint header.")
            elif run_build(tree, cmd) != 0:
                rc = 1
    finally:
        if keep:
            print(f"\nTree kept at: {tree}")
        else:
            shutil.rmtree(tree, ignore_errors=True)

    if rc:
        print(f"\n{RED}Blueprint did NOT apply cleanly{NC}")
    elif applied_tasks == 0:
        # A build that passes over an unchanged tree is evidence about the tree, not
        # about the blueprint, and saying "applied cleanly" here would claim otherwise.
        print(f"\n{YELLOW}Nothing was applied — no task anchored its code to a position in a file.{NC}")
        print("      The build result above describes the working tree, not this blueprint.")
        print("      Pass --require-anchors to make this a failure.")
    elif _overwritten:
        # Still exit 0 — the apply and the build did succeed — but not in green. After
        # the work is done the same overwrite discards it, and a green last line then
        # says the tree is fine when it is the blueprint that was just tested.
        print(f"\n{YELLOW}Blueprint applied{' and built' if do_build else ''} — from a copy that had"
              f" {len(_overwritten)} declared-new file(s) removed first.{NC}")
        print("      If those held your implementation, this run describes the blueprint, not your tree;")
        print("      if they were scaffolds, this is the run you wanted.")
    else:
        print(f"\n{GREEN}Blueprint applied{' and built' if do_build else ''} cleanly{NC}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
