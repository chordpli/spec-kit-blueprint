"""_blueprint_parse.py — the one reading of a blueprint that every tool shares.

`validate_blueprint.py` and `apply_blueprint.py` both have to answer the same questions
about a document: where does a task begin and end, which files does it name, which of
them are new. They used to answer separately, and the answers drifted — a fix to the
path pattern landed in one and not the other, so a `.properties` target was invisible to
one tool and a real target to the next. Parsing lives here so a fix reaches both.

Everything is fence-aware. A blueprint quotes markdown, properties files and ADRs inside
its code blocks, so `### T001` and `**File**:` appear *inside* blocks as often as outside,
and a plain regex over the document reads those as structure.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

# Set here, not only in the two scripts that ship beside it: this module lives under the
# user's .specify/, and any third caller importing it would leave a __pycache__ there.
sys.dont_write_bytecode = True


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


# --- Document parsing -------------------------------------------------------------
#
# Everything below is fence-aware. A blueprint quotes markdown, properties files and
# ADRs inside its code blocks, so `^### ` and `^**File**:` occur *inside* blocks as
# often as outside them, and a plain regex over the document reads those as structure.

FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*(\S*)\s*$")


def scan(text: str):
    """Yield (index, line, inside_fence, block) — block is set on a fence's last line."""
    lines = text.split("\n")
    marker, opened_at = "", -1
    for i, line in enumerate(lines):
        if marker:
            m = FENCE_OPEN.match(line)
            if m and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker) and not m.group(2):
                yield i, line, True, "\n".join(lines[opened_at + 1:i]) + "\n"
                marker = ""
            else:
                yield i, line, True, None
            continue
        m = FENCE_OPEN.match(line)
        if m:
            marker, opened_at = m.group(1), i
            yield i, line, True, None
        else:
            yield i, line, False, None


MODES = ("guide scaffold", "guide-scaffold", "doc-only", "scaffold", "guide")


def stamped_head(text: str) -> str:
    """The commit the blueprint's **Sources** line records, or "" if it has none."""
    line = next((ln for ln in text.split(chr(10)) if ln.lower().startswith("**sources**")), "")
    m = re.search(r"\bHEAD\s+([0-9a-f]{6,40})", line)
    return m.group(1) if m else ""


def changed_since(root: str, head: str, rel_path: str):
    """Has `rel_path` changed since `head`? None when git cannot answer.

    Both tools need this and both were about to grow their own: a Before that is not in a
    file is a defect at the blueprint's commit and the implementation having happened on
    a tree that has moved, and only git can tell those apart.
    """
    if not (head and root):
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", root, "diff", "--quiet", head, "--", rel_path],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {0: False, 1: True}.get(proc.returncode)


def parse_mode(text: str) -> str:
    """The mode a blueprint header declares, canonicalised.

    Read three separate ways before this existed — once per script, each with its own
    tolerances — so a header written ``**Mode**: `guide` `` (backticked, the way the
    README and the generator's own tables spell every mode name) meant `guide` to one
    tool and `unknown` to the next, and only one of the three resolved the two-token
    `guide scaffold`.
    """
    line = next((ln for ln in text.split(chr(10)) if ln.lower().startswith("**mode**:")), "")
    if ":" not in line:
        return "unknown"
    value = line.split(":", 1)[1].strip().lower()
    # The rest of the line is prose that may name other modes (a link to a scaffolding
    # decision doc), so only the leading token or two are read.
    value = re.sub(r"[`*_]", "", value)
    head = " ".join(value.split()[:2])
    for name in MODES:
        if head.startswith(name):
            return "guide-scaffold" if name.startswith("guide s") or name == "guide-scaffold" else name
    return "unknown"


def writes_to_disk(mode: str) -> bool:
    """Does this mode put scaffold files on disk at generation time?"""
    return mode not in ("doc-only", "guide")


BOLD_LABEL = re.compile(r"^\*\*([^*`\n][^*\n]*?)\*\*")

# A block under this label is a command to run, not file content. Counting the ```bash
# under **Verification** reported every task that has one as carrying code the applier
# could not place, and the applier "left it alone" out loud.
#
# Only this one. The template puts a task's skeleton directly under its **Why** prose,
# so treating any other label as illustrative silently skips real content — a first
# version listed **Why** here and the applier reported T001 as "no code block".
ILLUSTRATIVE_LABELS = {"verification"}


def section_events(section: str):
    """The parts of a task section a tool acts on, in document order.

    Yields ``("label", path)`` for a `**`path`**` block label, ``("directive", d)`` for
    **Before** / **After** / **Replace entire file**, and ``("block", (info, text))`` for
    a fenced block that is file content. A block under an illustrative label (see
    ILLUSTRATIVE_LABELS) is not yielded at all.
    """
    info, illustrative = "", False
    for _, line, in_fence, block in scan(section):
        if block is not None:
            if not illustrative:
                yield "block", (info, block)
            info = ""
            continue
        if in_fence:
            m = FENCE_OPEN.match(line)
            if m and info == "":
                info = m.group(2)
            continue
        m = LABEL.match(line)
        if m and looks_like_path(m.group(1)):
            illustrative = False
            yield "label", m.group(1)
            continue
        if line.startswith("**Before**"):
            illustrative = False
            yield "directive", "before"
            # The line the Before claims to start at, when it says. The applier learns
            # where the text really is when it matches, and can compare.
            cm = re.search(r"\blines?[^\d\n]{0,4}(\d+)", line)
            if cm:
                yield "cite", int(cm.group(1))
        elif line.startswith("**After**"):
            illustrative = False
            yield "directive", "after"
        elif line.startswith("**") and "**Replace entire file**" in line:
            illustrative = False
            yield "directive", "replace"
        else:
            m = BOLD_LABEL.match(line)
            if m:
                illustrative = m.group(1).strip().rstrip(":").lower() in ILLUSTRATIVE_LABELS


def code_blocks(text: str, *, content_only: bool = False) -> list[tuple[str, str]]:
    """(info string, content) for every fenced block, in order.

    The regex the callers used, ```` ```\\w*\\n(.*?)``` ````, mispairs fences whenever an
    info string is not a bare word — ```` ```c++ ```` is skipped and its CLOSING fence
    becomes an opener, so prose is scanned as code and the block after it is invisible.
    A nested fence breaks it the same way. This uses the same scanner as everything else.

    With ``content_only`` the blocks under an illustrative label are left out.
    """
    if content_only:
        return [payload for kind, payload in section_events(text) if kind == "block"]
    out, info = [], ""
    for _, line, in_fence, block in scan(text):
        if block is not None:
            out.append((info, block))
            info = ""
        elif in_fence:
            m = FENCE_OPEN.match(line)
            if m and info == "":
                info = m.group(2)
    return out


def split_tasks(text: str) -> list[tuple[str, str]]:
    """(task id, section text) in document order.

    A section ends at the next heading of level 1-3, not at the next `### T...`.
    Blueprints put consolidated "Appendix" files under their own `###` heading with an
    explicit "check your work, not a third edit" note; running to the next task id
    would apply those appendices as if they were tasks.
    """
    lines = text.split("\n")
    starts: list[tuple[int, str]] = []
    ends: list[int] = []
    for i, line, in_fence, _ in scan(text):
        if in_fence or not line.startswith("#"):
            continue
        m = re.match(r"^#{1,3} ", line)
        if not m:
            continue
        ends.append(i)
        tid = re.match(r"^### (T\d+)\b", line)
        if tid:
            starts.append((i, tid.group(1)))
    out = []
    for at, tid in starts:
        stop = next((e for e in ends if e > at), len(lines))
        out.append((tid, "\n".join(lines[at:stop])))
    return out


# A declaration runs to the blank line, the next bold label, or the end of the section —
# and it may not be followed by any of them. Continuation lines are only taken while they
# look like more of the declaration (a backticked path, a kind, or a separator), so a
# following sentence that happens to cite a document is not read as a declared file.
FILE_DECL = re.compile(
    r"\*\*File\*\*:(?P<decl>[^\n]*(?:\n[^\n\S]*(?:[`,]|\()[^\n]*)*)",
)
# The kind may carry a note — `(new — moved from legacy/D.java)` is a form the scaffold
# validator has always accepted. Requiring the paren to close right after the word made
# those declarations kind-less, so the applier never wrote the file while the scaffold
# validator demanded it on disk.
KIND = re.compile(r"\((?:all\s+)?(new|modify|modified|delete|deleted)\b[^)]*\)", re.I)

# Build files carry no extension, and a path whose last dot-segment is long
# (`services/com.example.SpiProvider`) is still a path. A capped extension was the only
# test, so both were invisible to the Python tools and required by the Bash one.
DOTLESS_FILES = {
    "Dockerfile", "Makefile", "Procfile", "Jenkinsfile", "Gemfile", "Rakefile",
    "Brewfile", "Vagrantfile", "CODEOWNERS", "LICENSE", "NOTICE",
}


def looks_like_path(token: str) -> bool:
    """Is this backticked token a file path rather than prose or an identifier?"""
    # A space is legal in a path (`docs/my file.md`), so it cannot be disqualifying on
    # its own — only the shape below decides. A newline never appears in one.
    if not token or token != token.strip() or "\n" in token:
        return False
    if "/" in token:
        return True
    if re.search(r"\.[A-Za-z0-9]{1,10}$", token):
        return True
    return os.path.basename(token) in DOTLESS_FILES


def outside_fences(section: str) -> str:
    """The section with fenced content blanked out, line count preserved.

    A blueprint quotes markdown templates, ADRs and properties files, so `**File**:`
    appears inside code blocks as often as outside them. Searching the raw text reads a
    quoted declaration as a real one, and a task that only *documents* the format then
    has its example path written to disk by the applier.
    """
    return "\n".join("" if in_fence else line for _, line, in_fence, _ in scan(section))


def file_kinds(section: str) -> list[tuple[str, str]]:
    """Every path in a task's **File**: declaration, paired with its (new)/(modify) kind.

    The declaration wraps onto later lines and annotates each path separately, except
    when one trailing `(all modify)` covers the whole list — so an unannotated path
    inherits from the next annotated one, and failing that from the previous.
    """
    m = FILE_DECL.search(outside_fences(section))
    if not m:
        return []
    decl = m.group("decl")
    found: list[tuple[str, str | None]] = []
    for pm in re.finditer(r"`([^`]+)`", decl):
        path = pm.group(1)
        if not looks_like_path(path):
            continue
        tail = decl[pm.end():decl.find("`", pm.end()) if "`" in decl[pm.end():] else len(decl)]
        km = KIND.search(tail)
        kind = km.group(1).lower() if km else None
        # "modified" and "deleted" are the same kinds as "modify" and "delete";
        # rstrip("d") turned the first into "modifie".
        found.append((path, {"modified": "modify", "deleted": "delete"}.get(kind, kind)))
    kinds: list[tuple[str, str]] = []
    for i, (path, kind) in enumerate(found):
        if kind is None:
            kind = next((k for _, k in found[i + 1:] if k), None)
        if kind is None:
            kind = next((k for _, k in reversed(found[:i]) if k), "unknown")
        kinds.append((path, kind))
    return kinds


LABEL = re.compile(r"^\*\*`([^`]+)`\*\*")

# A `**`path`**` label above a code block, wherever it appears in a section.
LABEL_ANY = re.compile(r"\*\*`([^`]+)`\*\*")


def count_path_labels(text: str) -> int:
    """How many `**`path`**` block labels a section carries."""
    return sum(1 for m in LABEL_ANY.finditer(text) if looks_like_path(m.group(1)))


def file_paths(section: str) -> list[str]:
    """Every path a task declares, kind discarded."""
    return [p for p, _ in file_kinds(section)]


def strip_quoted(section: str) -> str:
    """Drop Before/After blocks — they quote existing code, not authored content."""
    return re.sub(r"\*\*(?:Before|After)\*\*[^\n]*\n+```\w*\n.*?```", "", section, flags=re.S)
