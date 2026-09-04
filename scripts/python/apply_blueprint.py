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

sys.dont_write_bytecode = True  # the copy lives in the user's .specify/, and a __pycache__ there lands in git status

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _blueprint_parse import (  # noqa: E402  (path set above)
    base_chain,
    body_replaced_by_marker,
    changed_since,
    commit_known,
    dependent_slices,
    in_commit,
    file_kinds,
    parse_mode,
    section_events,
    stamped_head,
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


class Ambiguous(Exception):
    """The file has moved since the stamp and this hunk's work is not visibly in it.

    Neither "already applied" nor "the blueprint is wrong" can be shown, so the run says
    so rather than counting the task as done or sending the reader after a defect.
    """


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

    # Lines this hunk would add, compared whole and stripped. Substring comparison made
    # `def select_entries(` match inside the old signature and called an untouched task done.
    file_lines = {ln.strip() for ln in text.split("\n") if ln.strip()}
    added_now = [
        ln.strip() for ln in after.split("\n")
        if ln.strip() and ln.strip() not in before and re.search(r"[A-Za-z]", ln)
        and not re.search(r"\bT\d{3,}:", ln) and ln.strip() not in ("{", "}", "};", ")", ");")
    ]

    # Would applying duplicate something? A hunk whose Before still matches can still be
    # one the developer has already made their own way — the After registered three tests
    # and they had registered one, so applying it registered that one twice. Test the harm
    # directly rather than guessing from how many added lines happen to appear: a line the
    # After adds once, already in the file once, becomes two.
    # "Changed another way since HEAD" is a claim about the developer's file. A file the
    # copy is building out of this document has no developer's edits in it, and reading one
    # that way skipped a task nobody had typed — and then reported the run green.
    editable = in_commit(_root, _stamped_head, rel(path)) if _stamped_head else True
    # `None` means git could not answer — a shallow clone, a stamp from another machine.
    # Treating that as "not changed" turned the guard off completely and the hook was
    # applied a second time on top of itself, silently, under a green last line. The harm
    # test below is a direct question about this file and does not need the stamp; what
    # the stamp decides is only whether the answer is "you did this" or "I cannot tell".
    _changed = changed_since_stamp(rel(path))
    if editable and any(text.count(b) == 1 for b, _a in candidates):
        would_duplicate = [
            ln for ln in added_now
            if after.count(ln) == 1 and ln in file_lines and text.count(ln) == 1
            and ln not in ("pass", "return", "}", "});") and len(ln) > 12
            and _same_neighbour(text, after, ln)
        ]
        if would_duplicate:
            # How much of this hunk is in the file decides the headline: "already applied"
            # for a hunk that has landed, "partly" for one where a line or two has.
            here = sum(1 for ln in added_now if ln in file_lines)
            scope = "" if here == len(added_now) else f" of this task's {len(added_now)} added line(s), {here} present:"
            if _changed is None:
                raise Ambiguous(
                    f"{rel(path)}:{scope} applying this hunk would duplicate {would_duplicate[0][:50]!r},"
                    f" and this clone cannot resolve HEAD {_stamped_head} to say whether the change is"
                    f" already made or the file drifted — nothing was written"
                )
            if _changed is False and _stamped_head:
                # The file is exactly as the stamp saw it and the change is already in it:
                # nobody has done this since, so the document is prescribing a change its
                # own baseline already contains.
                raise Defect(
                    f"{rel(path)}:{scope} applying this hunk would duplicate {would_duplicate[0][:50]!r},"
                    f" which is already there in HEAD {_stamped_head} — the blueprint prescribes a change"
                    f" its own baseline already has"
                )
            raise AlreadyApplied(
                f"{rel(path)}:{scope} applying this hunk would duplicate {would_duplicate[0][:50]!r}, which is"
                f" already in the file — the change has been made another way since HEAD {_stamped_head}"
            )

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
    if changed_since_stamp(rel(path)):
        # All of them, not any: a guide skeleton's boilerplate — `raise NotImplementedError(`,
        # `def setUp(self) -> None:` — appears in every task's block, and one such line
        # counted a task nobody had started as done.
        if added_now and all(ln in file_lines for ln in added_now):
            raise AlreadyApplied(
                f"{rel(path)}: every line this hunk adds is already in the file, and the file has changed"
                f" since HEAD {_stamped_head} — implemented since"
            )
        # Changed, but this hunk's work is not visibly in it. Could be implemented
        # differently, could be an earlier task's edits having moved the anchor. Saying
        # which would be a guess, and a failure here sends the reader after a blueprint
        # bug that may not exist.
        raise Ambiguous(
            f"{rel(path)}: the Before is not in the file, which has changed since HEAD {_stamped_head}"
            f" — this task may be implemented differently, or an earlier task moved the anchor"
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
_root = ""
_stamped_head = ""


def changed_since_stamp(rel_path: str):
    """Has `rel_path` changed in the user's tree since the commit the blueprint stamps?"""
    return changed_since(_root, _stamped_head, rel_path)
# Declared-new files that were already on disk and were removed from the copy before applying.
_overwritten: list[str] = []


def rel(path: str) -> str:
    return os.path.relpath(path, _tree) if _tree else path


def _above(block: str, ln: str) -> str:
    """The nearest non-blank line above `ln` in `block`, stripped."""
    lines = [x.strip() for x in block.split("\n")]
    try:
        i = lines.index(ln)
    except ValueError:
        return ""
    for j in range(i - 1, -1, -1):
        if lines[j]:
            return lines[j]
    return ""


def _same_neighbour(text: str, after: str, ln: str) -> bool:
    """Would the After put this line where the file already has it?

    A method name repeats across classes: `def test_crosses_year_boundary` under two of
    them is not one line written twice. Comparing the line alone read the second class's
    method as the first's, called the hunk already applied, and skipped it.
    """
    want = _above(after, ln)
    return not want or _above(text, ln) == want


def apply_task(tree: str, section: str) -> tuple[str, int, set[str]]:
    """Apply one task section to the copied tree. Returns (note, blocks consumed)."""
    # A path declared twice keeps its FIRST kind: `(new)` then `(modify)` is a
    # create-then-edit narrative, and taking the last left the file unwritten.
    kinds: dict[str, str] = {}
    for _p, _k in file_kinds(section):
        kinds.setdefault(_p, _k)
    paths = list(kinds)
    if not paths:
        return "no file declared", 0, set()
    if all(k == "delete" for k in kinds.values()):
        return "delete task", 0, set()
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
        if not mods:
            raise Defect(
                "a Before/After hunk edits an existing file, and this task declares no (modify)"
                " file — if the file it edits already exists, declare it (modify), not (new)"
            )
        raise Defect(
            "a Before/After hunk follows a **`"
            + (current or "?")
            + f"`** block, and the task declares {len(mods)} modified files"
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
    hunks_already, hunks_missing, misnumbered, hunks_unclear = 0, [], [], []
    written: list[str] = []
    hunk_defects: list[Defect] = []

    for kind, payload in section_events(section):
        if kind == "label":
            # A label naming a path the task does not declare is how a block reached a
            # file nobody asked for: the orphan sweep removed the stale skeleton and this
            # wrote it straight back, so the build passed over a mistyped declaration.
            if payload not in kinds:
                raise Defect(
                    f"a code block is labelled `{payload}`, which this task does not declare"
                    " — fix the label or add the path to the **File**: line"
                )
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
                except Ambiguous as exc:
                    hunks_unclear.append(str(exc))
                except Defect as exc:
                    # Held, not raised: whether this is a defect depends on the other
                    # hunks. Beside one already in the file it is "implemented since,
                    # differently"; on its own it is the wrong Before it looks like.
                    hunk_defects.append(exc)
                else:
                    applied += 1
                    if rel(target) not in written:
                        written.append(rel(target))
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
                if rel(target) not in written:
                    written.append(rel(target))
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
                if rel(target) not in written:
                    written.append(rel(target))

    if before is not None:
        raise Defect(f"{before_at}: a **Before** block with no **After** after it")
    if hunk_defects and not hunks_already:
        raise hunk_defects[0]
    if hunks_unclear and not applied and not hunks_already:
        raise Ambiguous("\n  ".join(hunks_unclear[:3]))
    if hunks_already and not applied:
        # Nothing of this task's hunks applied fresh: the tree already holds the work,
        # and a hunk that matched neither Before nor After beside one that did is the
        # implementation having moved on, not a blueprint bug.
        total_hunks = hunks_already + len(hunk_defects) + len(hunks_unclear)
        summary = (
            f"{hunks_already} of this task's {total_hunks} hunk(s) already in the file"
            if total_hunks > hunks_already
            else f"{hunks_already} hunk(s) already in the file"
        )
        if hunk_defects:
            summary += f", {len(hunk_defects)} Before not found — implemented since, differently"
        raise AlreadyApplied(summary + "".join(f"\n  {m}" for m in hunks_missing[:3]))
    if applied:
        # Only the files this task actually wrote. Listing every declared path said a
        # file was edited when the block meant for it had been left alone.
        note = f"{applied} edit(s) -> {', '.join(written)}"
        if inferred:
            note += f"; {inferred} hunk(s) had no path label, resolved to the sole modified file"
        if unanchored:
            note += f"; {unanchored} unanchored block(s) left alone"
        if hunks_already:
            note += f"; {hunks_already} hunk(s) were already in the file or implemented since"
        if hunks_unclear:
            note += f"; {len(hunks_unclear)} hunk(s) could not be placed or recognised"
        if hunk_defects:
            note += f"; {len(hunk_defects)} hunk(s) matched nothing"
        if misnumbered:
            note += "".join(f"\n  line number: {m}" for m in misnumbered[:4])
        flags = set()
        if unanchored:
            flags.add("unanchored")
        if hunks_already:
            flags.add("moved")
        return note, applied, flags
    if unanchored:
        return f"{unanchored} code block(s) with no Before/After or Replace marker", 0, {"unanchored"}
    return "no code block", 0, set()


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
            rest = line.split(":", 1)[1].strip()
            # The header template teaches `— explanation` for the Mode line twelve lines
            # above and authors write the Build line the same way, usually with the
            # command in backticks. Stripping the ends left a backtick in the middle of
            # the command and the shell died on it: `unexpected EOF while looking for
            # matching ``'`.
            quoted = re.search(r"`([^`]+)`", rest)
            if quoted:
                return quoted.group(1).strip()
            return re.split(r"\s+[—–]\s+|\s+-{1,2}\s+", rest, 1)[0].strip()
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
    global _tree, _root, _stamped_head
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        print("Usage: apply_blueprint.py [specs/NNN-feature-name] [--build] [--keep] [--require-anchors]")
        print("\n  --build            run the project's build in the copy after applying")
        print("  --keep             print the copy's path instead of deleting it")
        print("  --require-anchors  fail when a task anchors nothing, or when nothing anchored at all")
        print("  --scaffold         after a clean apply, copy the declared-new files into your tree")
        print("\nExit 0 applied cleanly, 1 a task failed or the build did, 2 feature directory not resolved.")
        return 0
    do_build, keep = "--build" in argv, "--keep" in argv
    strict_anchors = "--require-anchors" in argv
    do_scaffold = "--scaffold" in argv
    KNOWN = {"--build", "--keep", "--require-anchors", "--scaffold"}
    unknown = [a for a in argv if a.startswith("-") and a not in KNOWN]
    if unknown:
        # A typo in --build looked like a run that simply chose not to build.
        print(f"{RED}ERROR: unknown option(s): {' '.join(unknown)}{NC}")
        print("Usage: apply_blueprint.py [specs/NNN-feature-name] [--build] [--keep] [--require-anchors]")
        return 2
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
    # A slice of a split feature needs its predecessors applied first: its Before blocks
    # quote the file as they leave it, and its code calls what they declare.
    chain = base_chain(bp, feature_dir, root)
    base_tasks = [(tid, sec) for _p, text in chain for tid, sec in split_tasks(text)]
    tasks = split_tasks(bp)
    _stamped_head = stamped_head(bp)
    _root = root

    print(f"{CYAN}=== Blueprint Applier {SCRIPT_VERSION} ==={NC}")
    print(f"Feature: {os.path.relpath(feature_dir, root)}")
    mode = parse_mode(bp)
    print(f"Mode: {mode} | {len(tasks)} task sections"
          + (f" (+{len(base_tasks)} from {len(chain)} base blueprint(s))" if chain else ""))
    if mode == "unknown":
        print(f"  {YELLOW}Mode is unknown — the header's **Mode**: line is missing or unreadable, so"
              f" mode-specific behaviour is off.{NC}")
    ids = [tid for tid, _ in tasks]
    dupes = sorted({t for t in ids if ids.count(t) > 1})
    if dupes:
        print(f"  {YELLOW}{len(dupes)} task id(s) have more than one section — each section is applied:"
              f" {', '.join(dupes)}{NC}")

    # realpath: on macOS mkdtemp returns /var/... and inside() resolves to /private/var/...,
    # so an unresolved _tree made every Defect message a six-level ../ chain.
    tree = copy_tree(root)
    _tree = os.path.realpath(tree)

    # Start from a tree WITHOUT this blueprint's new files. In guide-scaffold mode the
    # skeletons are already on disk, and a copy that keeps them lets the build pass over a
    # task whose block is missing or mislabelled — the skeleton fills the hole and the
    # compiler never sees it. A file the blueprint declares new is a file the blueprint
    # has to supply; removing it first is what makes the build a test of the document.
    for _tid, section in base_tasks + tasks:
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
    # A file on disk that carries a blueprint marker but that no task declares is residue
    # of a task the document no longer has — a deleted section, a renamed path. Left in
    # the copy it fills the hole the missing task left, and the build passes over it.
    declared_all = {p for _t, sec in base_tasks + tasks for p, _k in file_kinds(sec)}
    # A sibling slice's files are that slice's business, not residue of this one.
    for _cp, _ctext in dependent_slices(feature_dir, root):
        declared_all |= {p for _t, sec in split_tasks(_ctext) for p, _k in file_kinds(sec)}
    # The question is not "is this newer than the stamp" — an ADR, a golden fixture, a
    # test and .gitignore all are, and deleting them produced a build failure reported
    # against the blueprint. It is "did a blueprint put this here and does no task own it
    # now": undeclared, absent from the committed tree, and carrying a marker.
    head_known = commit_known(root, "HEAD")
    orphans = []
    # The executable marker forms and the scaffold comment — not a bare `T014:`, which
    # the extension's own command specs use in their examples under .specify/.
    marker = re.compile(
        r"TODO\(blueprint\)"
        r"|(?:NotImplementedError|UnsupportedOperationException|NotImplementedException|fatalError|todo!|unimplemented!|panic)\s*\(\s*\"?T\d{3,}:"
        r"|throw\s+new\s+Error\s*\(\s*[\"'`]\s*T\d{3,}\s*:"
    )
    for dirpath, dirnames, filenames in os.walk(tree):
        dirnames[:] = [d for d in dirnames if d not in SKIP_ANYWHERE | SKIP_AT_ROOT and not d.startswith(".")]
        for name in filenames:
            full = os.path.join(dirpath, name)
            relp = os.path.relpath(full, tree)
            if relp in declared_all or relp.startswith("specs" + os.sep):
                continue
            # Residue means: not in the stamped commit AND declared by nobody. A file
            # that WAS in that commit is the tree's, however it looks now — deleting one
            # because a sibling slice had put a marker in it removed a baseline class and
            # produced a build failure the blueprint was blamed for.
            if head_known and in_commit(root, "HEAD", relp):
                continue  # committed tree content, whatever it looks like
            try:
                if os.path.getsize(full) > 512_000:
                    continue
                with open(full, encoding="utf-8", errors="replace") as f:
                    if marker.search(f.read()):
                        orphans.append(relp)
            except OSError:
                continue
    for relp in orphans:
        os.remove(os.path.join(tree, relp))
    if orphans:
        why = "carry blueprint markers, are not in the committed tree, and no task declares them"
        print(f"  {YELLOW}{len(orphans)} file(s) {why};"
              f" removed from the copy so they cannot stand in for a missing task:{NC} "
              + ", ".join(orphans[:6]))
    print(f"Tree: {tree}\n")

    if base_tasks:
        print(f"{CYAN}[0] Applying {len(base_tasks)} task(s) from the base blueprint(s){NC}")
        base_failed = []
        for tid, section in base_tasks:
            try:
                apply_task(tree, section)
            except (Defect, AlreadyApplied, Ambiguous) as exc:
                base_failed.append(f"{tid}: {exc}")
        if base_failed:
            # The base is another slice's document; its problems are not this one's, but
            # this slice cannot be tested until they are fixed.
            record("warn", f"{len(base_failed)} base task(s) did not apply", "\n".join(base_failed[:4])
                   + "\nrun the applier in the base feature directory; this slice builds on top of it")
        else:
            record("pass", f"{len(base_tasks)} base task(s) applied")

    print(f"{CYAN}[1] Applying tasks in document order{NC}")
    failed, applied_tasks, unanchored_tasks, already, unclear = [], 0, [], [], []
    try:
        for tid, section in tasks:
            try:
                note, count, flags = apply_task(tree, section)
            except AlreadyApplied as exc:
                # Partly typed is not done: /speckit.blueprint.review counts a task with
                # one of three registrations written as unimplemented, and so does this.
                (unclear if " of this task's " in str(exc) or " of the " in str(exc) else already).append(tid)
                # "already applied" for a task where only some hunks are present says the
                # work is done when it is half done, which is the opposite of what
                # /speckit.blueprint.review means by implemented.
                partial = " (partly)" if " of this task's " in str(exc) else ""
                record("warn", f"{tid}  already applied{partial}", str(exc))
                continue
            except Ambiguous as exc:
                # Not counted as already in the tree: nobody showed that it is.
                unclear.append(tid)
                record("warn", f"{tid}  cannot tell", str(exc))
                continue
            except Defect as exc:
                failed.append(tid)
                record("fail", f"{tid}  FAILED", str(exc))
                continue
            if count and "moved" in flags:
                # Some hunks applied and some were already there: the tree is part-way
                # through this task, and a tick would say the blueprint was tested on it.
                applied_tasks += 1
                already.append(tid)
                record("warn", f"{tid}  applied over a tree that has moved on", note)
            elif count and "unanchored" in flags:
                # Applied, but a block was left unplaced: a tick here is what a reader
                # running without --build sees, and it is not the whole story.
                applied_tasks += 1
                unanchored_tasks.append(tid)
                record("warn", f"{tid}  applied, with a block left unplaced", note)
            elif count:
                applied_tasks += 1
                record("pass", f"{tid}  applied", note)
            elif "no file" in note or "delete" in note or note == "no code block":
                record("warn", f"{tid}  skipped ({note})")
            else:
                unanchored_tasks.append(tid)
                record("warn", f"{tid}  skipped ({note})")

        if unclear:
            print(f"\n  {YELLOW}{len(unclear)} task(s) could not be judged{NC} — their files have changed since"
                  "\n  this blueprint was generated, and their Before blocks are no longer in them. Run the"
                  "\n  applier before implementing, or against a tree that predates the work.")
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
        if strict_anchors and (already or unclear):
            # The CI flag's whole point is that "verified nothing" must not share an exit
            # code with "verified everything". A run whose copy discarded the
            # implementation to test the blueprint says nothing about the tree CI is
            # guarding, so it must not stay green there.
            print(f"\n  {YELLOW}--require-anchors: {len(already) + len(unclear)} task(s) are already in the tree or"
                  f" could not be judged — this run describes the blueprint, not this tree.{NC}")
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
                if not failed and _stamped_head:
                    moved = sorted({p for p in declared_all
                                    if changed_since(root, _stamped_head, p) is True})
                    if moved:
                        print(f"\n      {YELLOW}every task applied and the build still failed. {len(moved)} of the"
                              f" file(s) this blueprint writes have changed since HEAD {_stamped_head}:{NC} "
                              + ", ".join(moved[:6]))
                        print("      A blueprint describes the tree at its stamp. Run against a tree that has moved on,")
                        print("      a failure here is usually that distance rather than a defect in the document —")
                        print("      check the errors against the files listed before rewriting anything.")
            elif mode.startswith("guide"):
                print(f"      {YELLOW}a guide build compiles skeletons; it does not exercise behavior.{NC}")
                stripped = [
                    (tid, sum(n for _l, n in body_replaced_by_marker(sec)))
                    for tid, sec in base_tasks + tasks if body_replaced_by_marker(sec)
                ]
                if stripped:
                    print(f"      {YELLOW}{len(stripped)} task(s) replace working code with a marker: "
                          + ", ".join(f"{t} (-{n} lines)" for t, n in stripped[:6])
                          + f" — that behavior is gone from this copy and the build above cannot see it.{NC}")
        if do_scaffold and not failed:
            # The generator writing forty skeletons by hand is where drift comes from;
            # the copy already holds exactly what the document says, verified by the
            # build. Only files the blueprint declares new, and only ones not already
            # there: nothing existing is touched, which is the promise this flag bends
            # far enough and no further.
            written, skipped = [], []
            for _tid, section in base_tasks + tasks:
                for relp, kind in file_kinds(section):
                    if kind != "new":
                        continue
                    src, dst = os.path.join(tree, relp), os.path.join(root, relp)
                    if not os.path.isfile(src):
                        continue
                    if os.path.exists(dst):
                        skipped.append(relp)
                        continue
                    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                    shutil.copyfile(src, dst)
                    written.append(relp)
            print(f"\n{CYAN}=== Scaffold ==={NC}")
            print(f"  wrote {len(written)} new file(s) into {root}")
            if skipped:
                print(f"  {YELLOW}left {len(skipped)} file(s) alone — already on disk{NC}: " + ", ".join(skipped[:6]))
        elif do_scaffold:
            print(f"\n{YELLOW}--scaffold skipped: {len(failed)} task(s) did not apply.{NC}")
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
    elif already or unclear or _overwritten:
        # Still exit 0 — what was applied did apply — but not in green, and never without
        # naming what went untested. A skipped task has not seen a compiler, and a run
        # that says "applied and built" over one is the false pass this tool exists to
        # refuse. Same for a copy that discarded the implementation to test the document.
        names = already + unclear
        bits = []
        if names:
            bits.append(f"{len(names)} task(s) skipped: {', '.join(names[:8])}")
        if _overwritten:
            bits.append(f"{len(_overwritten)} declared-new file(s) removed from the copy first")
        print(f"\n{YELLOW}Blueprint applied{' and built' if do_build else ''} — {'; '.join(bits)}.{NC}")
        if names:
            print("      A skipped task never reached the build; this run says nothing about its code.")
            print("      Pass --require-anchors to make that a failure.")
        if _overwritten:
            print("      If those held your implementation, this run describes the blueprint, not your tree;")
            print("      if they were scaffolds, this is the run you wanted.")
    else:
        print(f"\n{GREEN}Blueprint applied{' and built' if do_build else ''} cleanly{NC}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
