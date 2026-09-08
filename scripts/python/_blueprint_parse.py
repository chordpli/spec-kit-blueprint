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


_COMMIT_KNOWN: dict = {}


def commit_known(root: str, head: str) -> bool:
    """Does this clone actually contain `head`?

    A shallow CI checkout, a fresh clone of a fork, a blueprint written on another
    machine: in all of them the stamped commit is simply absent, and every question
    asked of it answers no. That is a different fact from an answer, and the tools
    have to be able to tell them apart.
    """
    if not (head and root):
        return False
    key = (os.path.realpath(root), head)
    if key not in _COMMIT_KNOWN:
        try:
            proc = subprocess.run(
                ["git", "-C", root, "rev-parse", "--verify", "--quiet", head + "^{commit}"],
                capture_output=True, text=True, timeout=30,
            )
            _COMMIT_KNOWN[key] = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _COMMIT_KNOWN[key] = False
    return _COMMIT_KNOWN[key]


def in_commit(root: str, head: str, rel_path: str) -> bool:
    """Was `rel_path` in `head`? True when git cannot say — the file is presumed the tree's.

    This default used to be False, reasoning that a file git cannot vouch for is scaffold
    residue. In a clone without the stamped commit — a shallow checkout is the ordinary
    case, and the docs recommend running this in CI — every path answered "not in it", so
    the applier stripped the entire working tree out of its copy and reported the build
    failure that followed as the blueprint's fault.
    """
    if not (head and root):
        return True
    if not commit_known(root, head):
        return True
    try:
        proc = subprocess.run(
            ["git", "-C", root, "cat-file", "-e", f"{head}:{rel_path}"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    return proc.returncode == 0


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


def fenced_blocks(section: str) -> list:
    """(opening line index, index after the closing fence, content) for every fenced block.

    Read with the same scanner every other reader uses, so a label that sits *inside* a
    block is never mistaken for structure.
    """
    out, open_at = [], None
    for i, line, in_fence, block in scan(section):
        if block is not None:
            out.append((open_at if open_at is not None else i, i + 1, block))
            open_at = None
        elif in_fence and open_at is None:
            open_at = i
    if open_at is not None:  # a fence that never closes: everything after it is its body
        lines = section.split(chr(10))
        out.append((open_at, len(lines), chr(10).join(lines[open_at + 1:]) + chr(10)))
    return out


def before_after_pairs(section: str) -> list:
    """(before, after, offset of the **Before** label) for every pair in a section.

    This used to be one regex that counted exactly three backticks. A task whose quoted
    text is itself Markdown — a README update, which most features have — has to wrap its
    blocks in four, and then the regex read a Before with no After while the applier,
    which tracks fence length properly, applied the same document without complaint. Two
    of the three bundled scripts disagreed about the same file and no notation satisfied
    both. Fence handling lives here now, once.

    Fence-aware on BOTH halves. Reading the labels with a plain line test while reading
    the blocks with the scanner left the same divergence in a second shape: a task that
    quotes a shell example, and so carries a stray fence line, hid its **After** inside a
    block — the applier walked the blocks and reported "a Before with no After", and this
    function, which only looked at the line, paired them and reported the task clean.
    """
    lines = section.split(chr(10))
    offs, pos = [], 0
    for ln in lines:
        offs.append(pos)
        pos += len(ln) + 1
    blocks = fenced_blocks(section)
    inside = set()
    for a, b, _c in blocks:
        inside.update(range(a, b))

    def label_at_line(i: int) -> str:
        if i in inside:
            return ""
        t = lines[i].strip()
        if t.startswith("**Before**"):
            return "before"
        if t.startswith("**After**"):
            return "after"
        return ""

    def block_at(start: int):
        """(content, index after the closing fence) for the first block at or after start.

        None when another label comes first: prose may sit between a label and its block,
        but a second label means this one never had one.
        """
        for a, b, content in blocks:
            if a < start:
                continue
            for i in range(start, a):
                if label_at_line(i):
                    return None, i
            return content, b
        for i in range(start, len(lines)):
            if label_at_line(i):
                return None, i
        return None, len(lines)

    out, i = [], 0
    while i < len(lines):
        if label_at_line(i) == "before":
            label_at = offs[i]
            before, j = block_at(i + 1)
            if before is None:
                i = max(j, i + 1)
                continue
            # The After that closes this Before, with no second Before in between.
            k = j
            after = None
            while k < len(lines):
                kind = label_at_line(k)
                if kind == "before":
                    break
                if kind == "after":
                    after, k = block_at(k + 1)
                    break
                k += 1
            if after is not None:
                out.append((before, after, label_at))
                i = k
                continue
            i = j
            continue
        i += 1
    return out


def before_labels(section: str) -> int:
    """How many **Before** labels a section carries outside its code blocks."""
    return len(re.findall(r"^\*\*Before\*\*", outside_fences(section), re.M))


class _PairShim:
    """Keeps `.findall(sec)` and `.search(sec)` working for callers that only want pairs."""

    @staticmethod
    def findall(section: str) -> list:
        return [(b, a) for b, a, _o in before_after_pairs(section)]

    @staticmethod
    def search(section: str):
        return bool(before_after_pairs(section)) or None

    @staticmethod
    def match(section: str, pos: int = 0):
        for b, a, o in before_after_pairs(section):
            if o == pos:
                class _M:
                    @staticmethod
                    def group(n):
                        return b if n == 1 else a
                return _M
        return None


BEFORE_AFTER_RE = _PairShim

# JavaScript and TypeScript have no not-implemented type, so 3a-G gives them a plain
# `throw new Error(...)` — which is also how real code raises real errors. The task id is
# what makes one a marker, so it is required here and only here. Adding the form to the
# spec without adding it to the detectors left `--markers` answering "0 marker line(s)"
# for a file whose tests were failing, and cleanup called an unfinished feature done.
MARKER_CALL = re.compile(
    r"TODO\(blueprint\)"
    r"|(?:TODO|NotImplementedError|UnsupportedOperationException|NotImplementedException"
    r"|fatalError|todo!|unimplemented!|panic)\s*\(\s*[\"\'`]"
    r"|throw\s+new\s+Error\s*\(\s*[\"'`]\s*T\d{2,}\s*:"
)


# The same forms as MARKER_CALL, but recognised at the OPENING PAREN rather than at the
# first character of the message. A long message is written as `NotImplementedError(` and
# a newline, so MARKER_CALL — which requires the quote on the same line — sees no marker
# at all on the line that opens one.
MARKER_OPEN = re.compile(
    r"TODO\(blueprint\)"
    r"|(?<!class )(?<!extends )(?:NotImplementedError|UnsupportedOperationException"
    r"|NotImplementedException|fatalError|todo!|unimplemented!|panic)\s*\("
    r"|throw\s+new\s+Error\s*\(\s*(?:[\"'`]\s*T\d{2,}\s*:)?"
)


def marker_line_span(lines: list) -> set:
    """Indices of the lines a not-implemented marker call occupies, continuations included.

    A marker call is one expression, not one line. 3a-G asks its message to be a
    self-contained work instruction, which in Python means implicit string concatenation
    across several lines and in Java a text block — and every reader that tested one line
    at a time saw the first line as a marker and the rest as code. The check that reads a
    Before for "working code being deleted" then counted a marker's own message as the
    working code, and failed a document written exactly the way the spec teaches.
    """
    span: set = set()
    depth = 0
    for i, ln in enumerate(lines):
        if depth == 0:
            m = MARKER_OPEN.search(ln)
            if not m:
                continue
            for ch in ln[m.start():]:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            # A `TODO(blueprint):` comment is the whole line and balances at once.
            if depth <= 0:
                span.add(i)
                depth = 0
                continue
            span.add(i)
            continue
        span.add(i)
        for ch in ln:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        if depth <= 0:
            depth = 0
    return span


def body_replaced_by_marker(section: str) -> list:
    """(first line deleted, how many) for every hunk that trades working code for a marker.

    Guide mode hands the body to the developer, so a hunk written against code that is
    already there can prescribe deleting it — and a reviewer found one that replaced a
    tested 38-line method with a single throw. The applier compiled the skeleton, went
    green, and the project's own tests were where the loss showed. Nothing looked here.
    """
    out = []
    for before, after in BEFORE_AFTER_RE.findall(section):
        if not MARKER_CALL.search(after):
            continue
        # A marker in the Before does not mean there is no body to lose. 3a-G's own
        # recommended shape for a change inside an existing body is to insert a marker
        # comment, so skipping any hunk whose Before carried one made this check blind in
        # exactly the shape the document teaches: a Before with one `TODO(blueprint):`
        # line above twenty lines of tested code passed silently.
        kept = {ln.strip() for ln in after.split(chr(10))}
        b_lines = before.split(chr(10))
        marker_lines = marker_line_span(b_lines)
        gone = [
            ln.strip() for i, ln in enumerate(b_lines)
            if ln.strip() and ln.strip() not in kept
            and not ln.strip().startswith(("#", "//", "*", "/*", '"""'))
            and re.search(r"[A-Za-z]", ln)
            and i not in marker_lines
            and ln.strip() not in ("{", "}", "};", ")", ");", "else {", "try {")
        ]
        if len(gone) >= 2:
            out.append((gone[0], len(gone)))
    return out


def base_chain(text: str, feature_dir: str, root: str) -> list[tuple[str, str]]:
    """(path, text) of the blueprints this one continues, oldest first.

    A feature too large for one document is split, which the README advises — but the
    closure the tool is built on made splitting fail: the second slice's tasks refer to
    the first's, and every such reference read as a task that does not exist. A slice
    names its predecessor with `**Base**: specs/{other}/blueprint.md` in the header, and
    the tools read the chain as one document for the questions that span it.
    """
    seen, chain, current, where = set(), [], text, feature_dir
    for _ in range(8):  # a chain, not a cycle; eight slices is already too many
        line = next((ln for ln in current.split(chr(10)) if ln.lower().startswith("**base**:")), "")
        if ":" not in line:
            break
        raw = line.split(":", 1)[1].strip().strip("`").split("|")[0].strip()
        if not raw:
            break
        for cand in (os.path.join(root, raw), os.path.join(where, raw), raw):
            path = cand if cand.endswith(".md") else os.path.join(cand, "blueprint.md")
            if os.path.isfile(path):
                break
        else:
            break
        path = os.path.realpath(path)
        if path in seen:
            break
        seen.add(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                current = f.read()
        except OSError:
            break
        chain.append((path, current))
        where = os.path.dirname(path)
    chain.reverse()
    return chain


def dependent_slices(feature_dir: str, root: str) -> list[tuple[str, str]]:
    """(path, text) of the blueprints that name this one in their **Base** chain.

    The link is declared once, by the later slice, and read from both ends: the first
    slice legitimately says "consumed in T040" about work its successor delivers, and
    without this that reference is dangling in one direction while resolving in the other.
    """
    mine = os.path.realpath(os.path.join(feature_dir, "blueprint.md"))
    specs = os.path.join(root, "specs")
    out = []
    if not os.path.isdir(specs):
        return out
    for name in sorted(os.listdir(specs)):
        other_dir = os.path.join(specs, name)
        other = os.path.join(other_dir, "blueprint.md")
        if not os.path.isfile(other) or os.path.realpath(other) == mine:
            continue
        try:
            with open(other, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if any(os.path.realpath(cp) == mine for cp, _t in base_chain(text, other_dir, root)):
            out.append((other, text))
    return out


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
    """Drop Before/After blocks from a section's TEXT — a quotation, not authored content.

    For anything that reads CODE, use `authored_blocks` instead. This one is only for the
    text-level questions ("does this task's own prose declare the type it throws?"), and
    its regex needs the fence info string to be a bare word — ```` ```c++ ```` slips
    through it. `authored_blocks` uses the shared scanner and has neither problem.
    """
    return re.sub(r"\*\*(?:Before|After)\*\*[^\n]*\n+```\w*\n.*?```", "", section, flags=re.S)


def after_additions(section: str) -> list:
    """What each After block ADDS, as a block of lines.

    A modify hunk's After repeats the lines around the change; those are quotations of
    existing code, and scanning them reported an untouched `if` in the context as body
    logic. Only what the After adds was authored here.
    """
    out = []
    for before, after in BEFORE_AFTER_RE.findall(section):
        kept = {ln.strip() for ln in before.split("\n") if ln.strip()}
        added = [ln for ln in after.split("\n") if ln.strip() and ln.strip() not in kept]
        if added:
            out.append("\n".join(added))
    return out


# What a chunk of code in a task section IS, which decides whether the task wrote it.
#   "block"    a fenced block the task authors outright — a skeleton, a new file
#   "after"    the lines an **After** adds that its **Before** did not have
#   "reprint"  a **Replace entire file** block for a file that already exists: mostly a
#              quotation of code some earlier feature wrote, with this task's edits in it
AUTHORED_ROLES = ("block", "after", "reprint")


def authored_blocks(section: str, roles: bool = False) -> list:
    """THE separation of what a task wrote from what it quotes. Every code check uses it.

    A blueprint is half quotation: a `**Before**` shows the file as it is, an `**After**`
    repeats that context around the change, and `**Replace entire file**` reprints a whole
    existing file to change six lines of it. Counting any of that as this document's own
    writing is the single mistake this repository has made most often, in both directions
    — a check that read the raw section reported a quoted marker as a third author, and a
    check that dropped every hunk went blind in guide mode, where the developer types
    almost entirely inside hunks. Both shipped in the same release, ten lines apart, after
    the release notes had described the bug and called it fixed.

    So there is one function, and a check that reads code calls it and nothing else. It
    returns the chunks a task is answerable for: the fenced blocks that are neither a hunk
    nor an illustrative example, and the lines each **After** adds. A **Replace entire
    file** block is included too, because its text does reach the tree — but it is tagged
    `reprint`, because most of it was written by whoever wrote the file. Pass
    ``roles=True`` for ``(role, text)`` pairs and a check that assigns blame can tell the
    difference; a check that only looks for defects does not need to.

    Deciding this from the document alone is deliberate. An earlier attempt subtracted the
    file as it stands on disk, and on an implemented tree that made the document's own new
    lines look like quotations and silenced a real finding.
    """
    kinds = {}
    for _p, _k in file_kinds(section):
        kinds.setdefault(_p, _k)
    current = next(iter(kinds), None) if len(kinds) == 1 else None
    pending = None
    out = []
    for kind, payload in section_events(section):
        if kind == "label":
            current = payload
        elif kind == "directive":
            pending = payload
        elif kind == "block":
            _info, text = payload
            if pending in ("before", "after"):
                pending = None
                continue  # after_additions() below reads the pair
            if pending == "replace":
                pending = None
                # A replace of a file this task DECLARES NEW is authored outright; there
                # is no earlier version of it for anyone else to have written.
                new_file = current is not None and kinds.get(current) == "new"
                out.append(("block" if new_file else "reprint", text))
                continue
            out.append(("block", text))
    out += [("after", t) for t in after_additions(section)]
    out = [(r, t) for r, t in out if t.strip()]
    return out if roles else [t for _r, t in out]
