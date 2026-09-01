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


FILE_DECL = re.compile(r"\*\*File\*\*:(.*?)(?:\n\s*\n|\n(?=\*\*))", re.S)
KIND = re.compile(r"\((?:all\s+)?(new|modify|modified|delete|deleted)\)", re.I)


def file_kinds(section: str) -> list[tuple[str, str]]:
    """Every path in a task's **File**: declaration, paired with its (new)/(modify) kind.

    The declaration wraps onto later lines and annotates each path separately, except
    when one trailing `(all modify)` covers the whole list — so an unannotated path
    inherits from the next annotated one, and failing that from the previous.
    """
    m = FILE_DECL.search(section)
    if not m:
        return []
    decl = m.group(1)
    found: list[tuple[str, str | None]] = []
    for pm in re.finditer(r"`([^`]+)`", decl):
        path = pm.group(1)
        # Ten, not six: `config/app.properties` is a real target and a six-character
        # cap silently drops it, leaving the task looking like a process step.
        if not re.search(r"\.[A-Za-z0-9]{1,10}$", path):
            continue
        tail = decl[pm.end():decl.find("`", pm.end()) if "`" in decl[pm.end():] else len(decl)]
        km = KIND.search(tail)
        found.append((path, km.group(1).rstrip("d").lower() if km else None))
    kinds: list[tuple[str, str]] = []
    for i, (path, kind) in enumerate(found):
        if kind is None:
            kind = next((k for _, k in found[i + 1:] if k), None)
        if kind is None:
            kind = next((k for _, k in reversed(found[:i]) if k), "unknown")
        kinds.append((path, kind))
    return kinds


LABEL = re.compile(r"^\*\*`([^`]+)`\*\*")


def file_paths(section: str) -> list[str]:
    """Every path a task declares, kind discarded."""
    return [p for p, _ in file_kinds(section)]


def strip_quoted(section: str) -> str:
    """Drop Before/After blocks — they quote existing code, not authored content."""
    return re.sub(r"\*\*(?:Before|After)\*\*[^\n]*\n+```\w*\n.*?```", "", section, flags=re.S)
