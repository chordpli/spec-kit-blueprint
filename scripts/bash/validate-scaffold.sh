#!/usr/bin/env bash
#
# validate-scaffold.sh — blueprint scaffold validation script
#
# Checks:
#   1. Does blueprint.md exist?
#   2. Do all NEW files referenced in the blueprint exist on disk?
#   3. Do scaffold files contain TODO markers? (business logic not yet implemented)
#   4. Are any scaffold files over-implemented? (no TODOs in files that should have them)
#
# Usage: bash validate-scaffold.sh [feature-dir] [--strict]
#   feature-dir: specs/{feature}/ path (default: auto-detect from current branch)
#   --strict:    validate files on disk even when blueprint.md records a doc-only/guide
#                mode — for scaffolding done after the blueprint was generated
#   --markers:   list every blueprint marker and not-implemented call left in the files the
#                blueprint declares, as path:line: text, and exit — the mechanical half of
#                /speckit.blueprint.cleanup, so two runs of it start from the same list
#   --fresh:     the scaffold was just written and nothing is implemented yet, so a
#                file with no not-implemented marker is the mode being broken, not
#                work in progress. Without it the script cannot tell the two apart
#                and only warns.

set -eo pipefail

# Colour only when someone is looking. The Python tools already do this; a CI log with
# escape codes in it is the kind of thing a reviewer notices before anything else.
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; NC=''
fi

SCRIPT_VERSION="1.2.0"

PASS=0
WARN=0
FAIL=0

# Counters are assignments, not (( )). `((PASS++))` evaluates to the OLD value, so the
# very first call returns status 1, and under `set -e` that killed the script before
# check 2 on every bash >= 4 — the whole validator silently did nothing on Linux CI
# while still exiting red.
pass()  { PASS=$((PASS + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
warn()  { WARN=$((WARN + 1)); echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()  { FAIL=$((FAIL + 1)); echo -e "  ${RED}✗${NC} $1"; }
header(){ echo -e "\n${CYAN}[$1]${NC}"; }

# grep -c prints "0" and exits 1 when nothing matches, so `$(grep -c … || echo 0)`
# yields "0\n0" and breaks every arithmetic test downstream. Always emit one integer.
# Language-native "not implemented yet" forms. A guide-mode skeleton body is one of
# these, so missing them makes an untouched skeleton look fully implemented.
# JS and TS have no not-implemented type, so 3a-G gives them `throw new Error("T0NN: …")`.
# That is also how real code raises real errors, so the task id is what makes it a marker.
# Keep this vocabulary in step with MARKER_CALL in scripts/python/_blueprint_parse.py.
NOT_IMPL_RE='NotImplemented\|not_implemented\|NotImplementedError\|UnsupportedOperationException\|NotImplementedException\|fatalError(\|todo!(\|unimplemented!(\|panic(.TODO\|panic(.not implemented\|throw new Error(.T[0-9]'

# Kept in step with DOTLESS_FILES in scripts/python/_blueprint_parse.py.
DOTLESS_FILES="Dockerfile Makefile Procfile Jenkinsfile Gemfile Rakefile Brewfile Vagrantfile CODEOWNERS LICENSE NOTICE"

# Bracketed parens, not escaped: awk -v strips a backslash, and `fatalError\(` reached the
# regex as `fatalError(` — an unbalanced group that aborted the scan.
MARKER_ERE='TODO|NotImplemented|not_implemented|UnsupportedOperationException|NotImplementedException|fatalError[(]|todo![(]|unimplemented![(]|panic[(].TODO|panic[(].not implemented|throw new Error[(].T[0-9]'

count_matches() {
    local n
    n=$(grep "$@" 2>/dev/null) || n=0
    printf '%s' "${n:-0}"
}

# One reading of "what does this line declare", used on both sides of check 5: on the
# blueprint's code blocks to learn what the document promises, and on the file on disk to
# learn what it actually holds. They used to be different — extraction here, a word grep
# there — and the grep was the weaker half by far: a deleted method whose name survives in
# the line that CALLS it passed, which is most names. Measured on one corpus, 101 of 146
# declared symbols could be deleted without this check moving.
DECL_AWK=$(cat <<'AWK'
function declname(t,   n, w, i, nm, head2, before) {
    if (match(t, /^(export[ \t]+)?(default[ \t]+)?(async[ \t]+)?(public|private|protected|internal|open|final|static|abstract|suspend)?[ \t]*(class|interface|struct|enum|object|record|trait)[ \t]+[A-Za-z_][A-Za-z0-9_]*/)) {
        n = split(t, w, /[ \t]+/)
        for (i = 1; i <= n; i++)
            if (w[i] ~ /^(class|interface|struct|enum|object|record|trait)$/ && (i + 1) <= n) {
                nm = w[i+1]; gsub(/[^A-Za-z0-9_].*$/, "", nm); return nm
            }
        return ""
    }
    if (match(t, /^(export[ \t]+)?(async[ \t]+)?(def|fun|func|function|sub)[ \t]+[A-Za-z_][A-Za-z0-9_]*/)) {
        n = split(t, w, /[ \t]+/)
        for (i = 1; i <= n; i++)
            if (w[i] ~ /^(def|fun|func|function|sub)$/ && (i + 1) <= n) {
                nm = w[i+1]; gsub(/[^A-Za-z0-9_].*$/, "", nm); return nm
            }
        return ""
    }
    # Not a statement. `throw new UnsupportedOperationException("T0NN: ...");` ends in a
    # paren-and-semicolon like a declaration does, and its last word before the paren was
    # reported as a symbol the file must contain.
    if (t ~ /^(throw|return|new|assert|super|this|import|package|@)[^A-Za-z0-9_]/) return ""
    if (t ~ /^[A-Za-z_@<][^=;]*\(/ && (t ~ /\{[ \t]*$/ || t ~ /;[ \t]*$/)) {
        head2 = t; sub(/\(.*$/, "", head2); sub(/[ \t]+$/, "", head2)
        nm = head2; sub(/^.*[^A-Za-z0-9_]/, "", nm)
        if (nm == "" || nm ~ /^(if|for|while|switch|catch|return|new|do|else|synchronized|throw|assert|super|this)$/) return ""
        before = substr(head2, 1, length(head2) - length(nm))
        # A dotted receiver in front of the name makes it a CALL, not a declaration.
        # `System.out.println("PayoutHoldTest");` and `Objects.requireNonNull(id, "id");`
        # were both read as declarations the file had to contain, so the tool told a
        # developer the blueprint "declares `println`". It does not; saying so is worse
        # than saying nothing.
        if (before ~ /\.[ \t]*$/) return ""
        # Nothing at all in front of the name and a semicolon after it is a bare call
        # statement — `heldMerchantGetsNoPayout();`. A declaration carries a type, a
        # modifier or a keyword; only a body-opening `{` excuses having none (JS and
        # Kotlin method shorthand).
        if (before ~ /^[ \t]*$/ && t !~ /\{[ \t]*$/) return ""
        return nm
    }
    return ""
}
AWK
)

# === Resolve feature directory ===
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

USAGE="Usage: $0 [specs/NNN-feature-name] [--strict] [--fresh] [--done] [--markers] [--all]"
STRICT=false
FRESH=false
MARKERS=false
DONE=false
ALL=false
ARGS=()
PASSTHROUGH=()
for arg in "$@"; do
    case "$arg" in
        --strict) STRICT=true; PASSTHROUGH+=("$arg") ;;
        --fresh)  FRESH=true; PASSTHROUGH+=("$arg") ;;
        --markers) MARKERS=true; PASSTHROUGH+=("$arg") ;;
        --done)   DONE=true; PASSTHROUGH+=("$arg") ;;
        --all)    ALL=true ;;
        --help|-h)
            echo "$USAGE"
            echo "  --fresh    the scaffold was just written; a declared file with no marker is a defect"
            echo "  --done     the feature is finished; a declared file that still has a marker is a defect"
            echo "  --markers  list the markers left in the declared files, and exit"
            echo "  --strict   check files on disk even in a mode that writes none"
            echo "  --all      run over every specs/*/ that has a blueprint, and fail if any does"
            exit 0 ;;
        # A typo swallowed silently is a gate that quietly stops being one. `--frsh`
        # turned two failures into a warning and exit 1 into exit 0, and nothing said so;
        # the two Python tools got this guard a release ago and this one did not, and its
        # flags are the ones that decide FAIL from WARN.
        -*)
            echo -e "${RED}ERROR: unknown option: $arg${NC}" >&2
            echo "$USAGE" >&2
            exit 2 ;;
        *)        ARGS+=("$arg") ;;
    esac
done

if [[ "$FRESH" == true ]] && [[ "$DONE" == true ]]; then
    echo -e "${RED}ERROR: --fresh and --done are opposite claims about the same tree.${NC}" >&2
    exit 2
fi

# --all sweeps the repository instead of one feature.
#
# Every check here is scoped to the files ONE blueprint declares, which means the
# question "is anything in this repository still unfinished" needs one run per feature —
# and to know which feature to ask about you have to already know the answer. A reviewer
# carried twenty-two markers across five finished features and only found them by typing
# --done against a blueprint they had guessed at. This is the sweep that makes --done a
# gate a repository can run rather than a question a person has to think of.
if [[ "$ALL" == true ]]; then
    if [[ ${#ARGS[@]} -gt 0 ]]; then
        echo -e "${RED}ERROR: --all runs over every feature; do not also name one.${NC}" >&2
        exit 2
    fi
    SWEEP_RC=0
    SWEEP_BAD=()
    SWEEP_N=0
    for d in "$REPO_ROOT"/specs/*/; do
        [[ -f "$d/blueprint.md" ]] || continue
        SWEEP_N=$((SWEEP_N + 1))
        rel="${d#$REPO_ROOT/}"; rel="${rel%/}"
        [[ "$MARKERS" == true ]] || echo -e "\n${CYAN}########## $rel ##########${NC}"
        # `|| true` under `set -e`: a red feature must not stop the sweep at the first one.
        bash "$0" "$rel" "${PASSTHROUGH[@]}" || {
            SWEEP_RC=1
            SWEEP_BAD+=("$rel")
        }
    done
    if [[ "$SWEEP_N" -eq 0 ]]; then
        echo -e "${YELLOW}no specs/*/blueprint.md found — nothing to sweep${NC}" >&2
        exit 0
    fi
    if [[ "$MARKERS" != true ]]; then
        echo -e "\n${CYAN}########## sweep ##########${NC}"
        if [[ ${#SWEEP_BAD[@]} -gt 0 ]]; then
            echo -e "  ${RED}✗ ${#SWEEP_BAD[@]} of $SWEEP_N feature(s) did not pass: $(printf '%s, ' "${SWEEP_BAD[@]}" | sed 's/, $//')${NC}"
        else
            echo -e "  ${GREEN}✓ all $SWEEP_N feature(s) passed${NC}"
        fi
    fi
    exit "$SWEEP_RC"
fi

# --markers is a listing, so stdout carries only the list; the banner and the check
# headers go nowhere, and the count goes to stderr.
if [[ "$MARKERS" == true ]]; then
    exec 3>&1 1>/dev/null
fi

if [[ -n "${ARGS[0]:-}" ]]; then
    FEATURE_DIR="${ARGS[0]}"
else
    BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
    if [[ "$BRANCH" =~ ^([0-9]{3})- ]]; then
        PREFIX="${BASH_REMATCH[1]}"
        FEATURE_DIR=$(find "$REPO_ROOT/specs" -maxdepth 1 -type d -name "${PREFIX}-*" 2>/dev/null | head -1)
    elif [[ "$BRANCH" =~ ^([0-9]{8}-)  ]]; then
        PREFIX="${BASH_REMATCH[1]}"
        FEATURE_DIR=$(find "$REPO_ROOT/specs" -maxdepth 1 -type d -name "${PREFIX}*" 2>/dev/null | head -1)
    fi
fi

if [[ -z "${FEATURE_DIR:-}" ]] || [[ ! -d "$FEATURE_DIR" ]]; then
    echo -e "${RED}ERROR: Feature directory not found.${NC}"
    echo "Usage: $0 [specs/NNN-feature-name]"
    exit 1
fi

GUIDE="$FEATURE_DIR/blueprint.md"

echo -e "${CYAN}=== Blueprint Scaffold Validator ${SCRIPT_VERSION} ===${NC}"
echo "Feature: $FEATURE_DIR"
echo "Blueprint: $GUIDE"

# === Detect the mode the blueprint was generated in ===
# doc-only and guide write nothing to disk, so "file missing" is the expected
# state there, not a failure. Only scaffold modes are validated strictly.
MODE="unknown"
if [[ -f "$GUIDE" ]]; then
    # Only the mode token itself is parsed — the rest of the line is prose that may
    # mention other mode names (e.g. a link to a scaffolding decision doc).
    MODE_LINE="$(grep -m1 -i '^\*\*Mode\*\*:' "$GUIDE" || true)"
    # Backticks and emphasis stripped: README.md and the generator's own tables spell
    # every mode name as `guide`, and a header copied from them read as "unknown" here
    # while the Python tools accepted it.
    MODE_TOKENS="$(echo "${MODE_LINE#*:}" | tr -d '`*_' | tr '[:upper:]' '[:lower:]' | awk '{print $1, $2}')"
    case "$MODE_TOKENS" in
        "guide scaffold"*) MODE="guide-scaffold" ;;
        guide-scaffold*)   MODE="guide-scaffold" ;;
        guide*)            MODE="guide" ;;
        scaffold*)         MODE="scaffold" ;;
        doc-only*)         MODE="doc-only" ;;
    esac
fi

SCAFFOLD_EXPECTED=true
case "$MODE" in
    doc-only|guide) SCAFFOLD_EXPECTED=false ;;
esac
if [[ "$STRICT" == true ]]; then
    SCAFFOLD_EXPECTED=true
    echo "Mode: $MODE (--strict: validating files on disk anyway)"
else
    echo "Mode: $MODE"
fi
if [[ "$MODE" == "unknown" ]] && [[ "$MARKERS" != true ]]; then
    echo -e "  ${YELLOW}⚠${NC} the header's **Mode**: line is missing or unreadable — validating as a scaffold run"
fi

# =============================================
# CHECK 1: blueprint.md existence
# =============================================
header "1. Blueprint Document"

if [[ -f "$GUIDE" ]]; then
    pass "blueprint.md exists"
else
    fail "blueprint.md not found at $GUIDE"
    echo -e "\n${RED}Blueprint document is required. Run /speckit.blueprint.generate first.${NC}"
    exit 1
fi

# =============================================
# CHECK 2: NEW files from blueprint exist on disk
# =============================================
header "2. File Existence (NEW files from blueprint)"

NEW_FILES=()
# A blueprint quotes markdown templates, ADRs and properties files inside its code
# blocks, so `**File**:` lines and file tables appear *inside* fences as often as
# outside them. Blank the fenced lines first, the way the Python parser does, or a task
# that merely documents the blueprint format has its example path demanded on disk.
UNFENCED=$(awk '
    {
        t = $0; sub(/^[ \t]+/, "", t)
        ch = substr(t, 1, 1); n = 0
        if (ch == "`" || ch == "~") { while (substr(t, n + 1, 1) == ch) n++ }
        rest = substr(t, n + 1); sub(/[ \t]+$/, "", rest)
        if (fence_ch == "") {
            if (n >= 3) { fence_ch = ch; fence_n = n; print ""; next }
            print; next
        }
        if (n >= 3 && ch == fence_ch && n >= fence_n && rest == "") fence_ch = ""
        print ""; next
    }
' "$GUIDE")

# A **File**: declaration may wrap onto following lines; join it back into one
# logical line before parsing, or every path after the first is invisible here.
JOINED=$(awk '
    /^\*\*File\*\*:/ { if (joining) print buf; buf = $0; joining = 1; next }
    # Only a genuine continuation is folded back in. A wrapped **File**: line resumes
    # with another `path`, a comma, or a (kind) — the same shapes the Python parser
    # accepts. Anything else is a line of its own and must survive, or a table or a
    # paragraph written directly under a File line is deleted from the input and the
    # declarations it carries are never seen.
    joining && /^[[:space:]]*[`,(]/ { buf = buf " " $0; next }
    joining              { print buf; joining = 0; print; next }
    { print }
    END { if (joining) print buf }
' <<< "$UNFENCED")

while IFS= read -r line; do
    # Pattern 1: **File**: `path` (kind), `path` (kind) — each path carries its own
    # kind, and a shared kind at the end applies to the run of paths before it.
    # Matching the whole line on "(new" would mark a `(modify)` sibling as new.
    if [[ "$line" =~ \*\*File\*\*: ]]; then
        rest="${line#*\*\*File\*\*:}"
        pending=()
        while [[ "$rest" =~ ^[^\`\(]*(\`([^\`]+)\`|\(([^\)]*)\))(.*)$ ]]; do
            token_path="${BASH_REMATCH[2]}"
            token_kind="${BASH_REMATCH[3]}"
            rest="${BASH_REMATCH[4]}"
            if [[ -n "$token_path" ]]; then
                # Same shape rule the Python parser applies: a path sits in a directory,
                # carries a short extension, or is one of the extensionless build files.
                # A dot alone rejected `Dockerfile` and accepted nothing the others did
                # not. Spaces are legal in a path, so they do not disqualify a token.
                if [[ "$token_path" == */* ]] || \
                   [[ "$token_path" =~ \.[A-Za-z0-9]{1,10}$ ]] || \
                   [[ " $DOTLESS_FILES " == *" $(basename "$token_path") "* ]]; then
                    pending+=("$token_path")
                fi
            else
                # a (kind) closes the run of paths collected since the last one.
                # "new", "all new", "new — moved from …" all create files here. Compared
                # lowercased, or a declaration written `(New)` is silently never checked.
                token_kind="$(echo "$token_kind" | tr '"'"'[:upper:]'"'"' '"'"'[:lower:]'"'"')"
                if [[ "$token_kind" == new* ]] || [[ "$token_kind" == "all new"* ]]; then
                    for pp in "${pending[@]}"; do NEW_FILES+=("$pp"); done
                fi
                pending=()
            fi
        done
    # Only a task's **File**: declaration says what gets created. Scraping table rows
    # also swept the reference sections the generator is required to write (existing-type
    # API tables, requirement tables), reporting their paths as files that never appeared.
    elif [[ "$line" =~ \|[[:space:]]*\`?([a-zA-Z][^\`\|]+\.[a-zA-Z]+)\`?[[:space:]]*\| ]]; then
        row_path="${BASH_REMATCH[1]}"
        # A file row declares a creation only when a cell says so. "New" or "New file"
        # standing alone as a status cell counts; the word "new" inside a sentence does
        # not, or every pre-completed row that mentions a new field is reported missing.
        if [[ "$line" =~ \|[[:space:]]*[Nn]ew([[:space:]]+file)?[[:space:]]*(\||$) ]]; then
            NEW_FILES+=("$row_path")
        fi
    fi
done <<< "$JOINED"

# The patterns above can match the same path twice (a File line and a table row),
# which would report and count that file twice.
if [[ ${#NEW_FILES[@]} -gt 0 ]]; then
    # Deduped in the shell, not through a command substitution. `NEW_FILES=($(...))`
    # word-split `docs/my file.md` into two fabricated paths and glob-expanded anything
    # carrying a `*`.
    DEDUPED=()
    for p in "${NEW_FILES[@]}"; do
        dup=false
        for q in "${DEDUPED[@]}"; do [[ "$q" == "$p" ]] && dup=true && break; done
        [[ "$dup" == true ]] || DEDUPED+=("$p")
    done
    NEW_FILES=("${DEDUPED[@]}")
fi

# Every declared path, not only the new ones: a marker inserted into an existing file by
# a (modify) task is residue too. Comment-syntax markers and executable not-implemented
# calls both count; the judgment about each is cleanup's.
# Deduplicated: a file that several tasks build up is declared once per task, and the
# first version of this listing printed each of its markers that many times —
# "19 marker line(s) in 13 declared file(s)" for four markers in four files.
DECLARED=()
while IFS= read -r line; do
    [[ "$line" =~ \*\*File\*\*: ]] || continue
    rest="${line#*\*\*File\*\*:}"
    while [[ "$rest" =~ ^[^\`]*\`([^\`]+)\`(.*)$ ]]; do
        cand="${BASH_REMATCH[1]}"; rest="${BASH_REMATCH[2]}"
        dup=false
        for q in "${DECLARED[@]}"; do [[ "$q" == "$cand" ]] && dup=true && break; done
        [[ "$dup" == true ]] || DECLARED+=("$cand")
    done
done <<< "$JOINED"

# This feature's own task ids. A marker is traced to its task by the id its message
# begins with — the rule the cleanup spec states in prose — and the ids restart at T001
# in every feature, so the id alone cannot settle a collision. The listing below uses
# both: the id says whether a task here could own it, the wording says whether this
# document wrote it, and the three answers that produces are different sentences.
OWN_IDS=""
if [[ -f "$FEATURE_DIR/tasks.md" ]]; then
    OWN_IDS=$(grep -oE '^[[:space:]]*(-[[:space:]]*\[[ xX]\][[:space:]]*)?T[0-9]+' "$FEATURE_DIR/tasks.md" 2>/dev/null \
        | grep -oE 'T[0-9]+' | sort -u || true)
fi
if [[ -z "$OWN_IDS" ]]; then
    OWN_IDS=$(grep -oE '^###[[:space:]]+T[0-9]+' "$GUIDE" 2>/dev/null | grep -oE 'T[0-9]+' | sort -u || true)
fi

# The blueprint as one line, every run of whitespace collapsed to a single space.
#
# A marker's message wraps twice and in two unrelated places: once in the document, where
# the generator wrapped its prose, and once in the file, where the language wrapped the
# string literal. Reading a run of characters out of one and searching the other for it
# verbatim therefore fails whenever the run crosses either wrap — and the run is taken
# from the START of the message, which is exactly where a long message is still on its
# first physical line in one place and already on its second in the other. Measured on a
# tree this extension had just scaffolded: four of five markers written out of the
# blueprint byte-for-byte were labelled "the wording is not the blueprint's".
#
# Flattening both sides removes the question. It costs one pass over the document.
GUIDE_FLAT=$(tr '\n' ' ' < "$GUIDE" 2>/dev/null | tr -s '[:space:]' ' ' || true)

# Is this marker message the blueprint's own wording? Both sides flattened; a message too
# short to be distinctive is not evidence either way and counts as the document's.
bp_has_wording() {
    local msg flat
    msg="$1"
    flat=$(printf '%s' "$msg" | tr '\n' ' ' | tr -s '[:space:]' ' ')
    flat="${flat# }"
    flat="${flat:0:48}"
    [[ ${#flat} -lt 16 ]] && return 0
    case "$GUIDE_FLAT" in
        *"$flat"*) return 0 ;;
    esac
    return 1
}

# One extractor for every reader of a marker on disk.
#
# A marker's message wraps: Python's `raise NotImplementedError(` puts its string on the
# next line, and that is the shape this extension's own --scaffold writes. Anything that
# reads a marker one physical line at a time sees the call and never the task id. The
# --markers listing learned to join those lines; check 3a below was written afterwards
# and did not, so on a tree holding thirty-three wrapped markers it found none of them
# and printed "no task ticked [X] still has its marker in the file" in the same run in
# which check 3b reported all thirty-three. Both now read the same joined text.
#
# Emits `<line number>: <joined text>` for every line that carries a marker.
MARKER_JOIN_AWK='
    { lines[NR] = $0 }
    END {
        for (i = 1; i <= NR; i++) {
            if (lines[i] !~ re) continue
            out = lines[i]; sub(/^[ \t]+/, "", out)
            # How far the message has already been consumed. Without this the
            # continuation loop below started again at i and appended line i+1 a
            # second time, so every wrapped marker printed its first string
            # literal twice — reported on a marker copied verbatim out of the
            # blueprint, which is the commonest shape there is.
            last = i
            if (out !~ /T[0-9]+:/ && i < NR) {
                nxt = lines[i + 1]; sub(/^[ \t]+/, "", nxt)
                if (nxt ~ /T[0-9]+:/) { out = out " " nxt; last = i + 1 }
            }
            # A message split across concatenated string literals showed only
            # its first physical line. Executable markers only: a comment marker
            # has no closing paren to stop at, so this ran on and pulled the code
            # under it into the listing cleanup is supposed to read.
            if (out ~ /(NotImplementedError|UnsupportedOperationException|NotImplementedException|fatalError|todo!|unimplemented!|panic)[[:space:]]*\(/) {
                j = last
                while (out !~ /\)[[:space:]]*;?[[:space:]]*$/ && j < NR && j - i < 6) {
                    j++; cont = lines[j]; sub(/^[ \t]+/, "", cont)
                    if (cont == "") break
                    out = out " " cont
                }
            }
            print i ": " out
        }
    }'

# The task id a joined marker line claims, and the message after it — or nothing when the
# line carries a marker whose message does not begin with a task id. Sets MK_ID / MK_MSG.
MK_OWNER_RE='(NotImplementedError|UnsupportedOperationException|NotImplementedException|fatalError|todo!|unimplemented!|panic)[[:space:]]*\([[:space:]]*["'"'"'`]?[[:space:]]*T[0-9]+[[:space:]]*:'
MK_TODO_RE='TODO\(blueprint\)[^T]*T[0-9]+[[:space:]]*:'
marker_owner() {
    local joined="$1"
    MK_ID=""; MK_MSG=""
    if [[ "$joined" =~ $MK_OWNER_RE ]] || [[ "$joined" =~ $MK_TODO_RE ]]; then
        MK_ID=$(printf '%s' "${BASH_REMATCH[0]}" | grep -oE 'T[0-9]+' | head -1 || true)
        [[ -n "$MK_ID" ]] || return 1
        MK_MSG="${joined#*$MK_ID:}"
        MK_MSG=$(printf '%s' "$MK_MSG" | sed -e 's/^[[:space:]]*//' -e 's/["'"'"'`]//g')
        return 0
    fi
    return 1
}

if [[ "$MARKERS" == true ]]; then
    found=0
    for f in "${DECLARED[@]}"; do
        [[ -f "$REPO_ROOT/$f" ]] || continue
        # A marker whose message wraps to the next line — Python's `raise
        # NotImplementedError(` with the "T001: …" string below it — is printed with
        # that line joined on, or the listing shows the call and never the task id.
        while IFS= read -r hit; do
            [[ -n "$hit" ]] || continue
            # Three states, not two. The old rule was one string comparison: if a
            # distinctive run of the message is not in the document, say an earlier
            # feature left it. That labelled a developer's OWN debt as somebody else's
            # the moment they reworded a marker or shortened it while half-implementing —
            # and cleanup's whole job is to separate this feature's honest debt from
            # residue, so its input was wrong in the direction that hides work.
            #
            # The task id decides who COULD own it; the wording decides whether this
            # document wrote it. Neither alone is enough — ids restart at T001 in every
            # feature — so both are read and the uncertain case says it is uncertain.
            # `|| true`, and it is load-bearing. `set -eo pipefail` is on, grep exits 1
            # when it matches nothing, and a command substitution in an assignment hands
            # that status to the shell — so the listing DIED on the first marker whose
            # message carries no task id, printed nothing further, and exited 1. That is
            # exactly the `[not this feature's]` case the three-way label exists for, and
            # /speckit.blueprint.cleanup starts from this listing: its mechanical half was
            # being silently truncated at the one marker it most needed to show.
            mk_id="$(printf '%s' "$hit" | grep -oE 'T[0-9]+' | head -1 || true)"
            probe="${hit#*T}"; probe="${probe#*: }"
            verbatim=false
            bp_has_wording "$probe" && verbatim=true
            id_is_ours=false
            if [[ -n "$mk_id" ]] && printf '%s\n' "$OWN_IDS" | grep -qx -- "$mk_id"; then
                id_is_ours=true
            fi
            if [[ "$verbatim" == true ]] || [[ -z "$mk_id" ]]; then
                echo "$f:$hit" >&3
            elif [[ "$id_is_ours" == true ]]; then
                echo "$f:$hit   [$mk_id is this feature's task; the wording is not the blueprint's — reworded here, or an earlier feature also had $mk_id]" >&3
            else
                echo "$f:$hit   [not this feature's — no task $mk_id here, and the wording is not the blueprint's]" >&3
            fi
            found=$((found + 1))
        done < <(awk -v re="TODO[(]blueprint[)]|$MARKER_ERE" "$MARKER_JOIN_AWK" "$REPO_ROOT/$f")
    done
    echo "  ($found marker line(s) in ${#DECLARED[@]} declared file(s))" >&2
    exit 0
fi

if [[ ${#NEW_FILES[@]} -eq 0 ]]; then
    warn "No NEW file paths detected in blueprint (check blueprint format)"
elif [[ "$SCAFFOLD_EXPECTED" == false ]]; then
    MISSING_COUNT=0
    PRESENT_COUNT=0
    for f in "${NEW_FILES[@]}"; do
        if [[ -f "$REPO_ROOT/$f" ]]; then
            PRESENT_COUNT=$((PRESENT_COUNT + 1))
        else
            MISSING_COUNT=$((MISSING_COUNT + 1))
        fi
    done
    pass "$MODE mode writes nothing to disk — file existence not required (${PRESENT_COUNT} present, ${MISSING_COUNT} not yet created)"
else
    CHECKED_ANY=false
    SKIPPED_PLACEHOLDERS=()
    MISSING_FILES=()
    PRESENT_FILES=0
    for f in "${NEW_FILES[@]}"; do
        # Skip placeholder/glob paths (e.g. docs/2026-MM-DD-*.md) — not real targets
        if [[ "$f" == *"*"* ]] || [[ "$f" == *"MM-DD"* ]] || [[ "$f" == *"{"* ]]; then
            SKIPPED_PLACEHOLDERS+=("$f")
            continue
        fi
        CHECKED_ANY=true
        FULL_PATH="$REPO_ROOT/$f"
        if [[ -f "$FULL_PATH" ]]; then
            PRESENT_FILES=$((PRESENT_FILES + 1))
        else
            MISSING_FILES+=("$f")
        fi
    done
    # One fact, one finding. Eight absent files used to be eight failures with the same
    # sentence repeated after each — the largest single block of output this script
    # produced, and every line of it said the same thing.
    if [[ ${#MISSING_FILES[@]} -gt 0 ]]; then
        SHOWN=("${MISSING_FILES[@]:0:8}")
        MORE=""
        [[ ${#MISSING_FILES[@]} -gt 8 ]] && MORE=" (+$(( ${#MISSING_FILES[@]} - 8 )) more)"
        fail "${#MISSING_FILES[@]} declared file(s) are not on disk: $(printf '%s, ' "${SHOWN[@]}" | sed 's/, $//')${MORE}"
        echo "      Before scaffolding them: is the work somewhere else under another name?"
    fi
    if [[ "$PRESENT_FILES" -gt 0 ]]; then
        pass "$PRESENT_FILES declared file(s) exist"
    fi
    # A blueprint whose only declarations are placeholders printed nothing here at all —
    # no pass, no warn, no fail — which reads as a clean check.
    if [[ "$CHECKED_ANY" == false ]] && [[ ${#SKIPPED_PLACEHOLDERS[@]} -gt 0 ]]; then
        warn "every declared path is a placeholder or glob (${SKIPPED_PLACEHOLDERS[*]}) — nothing to check"
    fi
fi

# =============================================
# CHECK 3: TODO markers in scaffold files
# =============================================
header "3. TODO Markers in Scaffold Files"

if [[ "$SCAFFOLD_EXPECTED" == false ]]; then
    pass "$MODE mode — no scaffold files on disk to check"
    echo ""
    echo -e "${CYAN}=== Summary ===${NC}"
    echo -e "  ${GREEN}PASS${NC}: $PASS"
    echo -e "  ${YELLOW}WARN${NC}: $WARN"
    echo -e "  ${RED}FAIL${NC}: $FAIL"
    if [[ $FAIL -gt 0 ]]; then
        echo -e "\n${RED}Validation FAILED — $FAIL issue(s) found${NC}"
        exit 1
    fi
    # Not "all checks passed" — checks 2-4 were skipped, not satisfied. Saying so here
    # keeps a mode line from reading as a clean scaffold run.
    echo -e "\n${GREEN}Blueprint checks passed${NC} — $MODE mode writes nothing to disk, so the file, marker and over-implementation checks were skipped. Pass --strict to run them against files scaffolded after generation."
    exit 0
fi

# Which declared-new files does the BLUEPRINT give a not-implemented marker? Those are
# the skeletons, whatever they are called. The basename guess below (`*service*`,
# `*test*`) was the only test before, and a controller or a scheduler written complete
# at scaffold time was never looked at because its name matched nothing.
BLUEPRINT_MARKER_FILES=()
if [[ ${#NEW_FILES[@]} -gt 0 ]]; then
    while IFS= read -r p; do
        [[ -n "$p" ]] && BLUEPRINT_MARKER_FILES+=("$p")
    done < <(PATHS_FILE=$(mktemp); printf '%s\n' "${NEW_FILES[@]}" > "$PATHS_FILE"; \
             awk -v pathsfile="$PATHS_FILE" -v re="$MARKER_ERE" '
        # Paths come through a file: macOS awk refuses a newline inside a -v value.
        BEGIN { while ((getline line < pathsfile) > 0) if (line != "") want[line] = 1; close(pathsfile) }
        {
            t = $0; sub(/^[ \t]+/, "", t)
            fence = (substr(t, 1, 3) == "```" || substr(t, 1, 3) == "~~~")
            if (in_fence) {
                if (fence) { in_fence = 0; if (armed != "" && hit) print armed; armed = ""; hit = 0; next }
                if (armed != "" && $0 ~ re) hit = 1
                next
            }
            if (fence) { in_fence = 1; next }
            # Outside a fence, the last path named in backticks is the file the next
            # block belongs to — the **File**: line for a single-file task, the
            # **`path`**: label above each block for a multi-file one.
            for (p in want) if (index($0, "`" p "`") > 0) armed = p
        }' "$GUIDE"; rm -f "$PATHS_FILE")
fi

# What each declared-new file's block says it declares. The script checked that a file
# exists and that it carries markers; nothing checked that it holds what the blueprint
# said it would, so a task whose hunks never landed left a file that passes with two
# functions missing — reported in three rounds running.
# The population used to be NEW_FILES and nothing else, and that is where the check
# stopped paying. A feature that sprinkles new files is checked; a feature that edits
# existing code is not, and editing existing code is what work in a mature codebase looks
# like. Measured across four features of one repository, declarations introduced by
# (modify) hooks and therefore unchecked: 4, 3, 21, and 38 — the last against 7 checked.
#
# What a hunk introduces is what its **After** has and its **Before** does not: the After
# repeats the surrounding lines, and reading it whole would demand every neighbour it
# quotes. Rows are tagged `new` or `hook` because the two have different lifecycles — a
# skeleton's declarations are on disk the moment it is scaffolded, a hook's arrive only
# when the developer types them.
DECLARED_SYMBOLS=()
if [[ ${#DECLARED[@]} -gt 0 ]]; then
    while IFS= read -r line; do
        [[ -n "$line" ]] && DECLARED_SYMBOLS+=("$line")
    done < <(PATHS_FILE=$(mktemp); NEWF=$(mktemp); \
             printf '%s\n' "${DECLARED[@]}" > "$PATHS_FILE"; \
             { [[ ${#NEW_FILES[@]} -gt 0 ]] && printf '%s\n' "${NEW_FILES[@]}"; } > "$NEWF"; \
             awk -v pathsfile="$PATHS_FILE" -v newfile="$NEWF" "$DECL_AWK"'
        BEGIN {
            while ((getline line < pathsfile) > 0) if (line != "") want[line] = 1
            close(pathsfile)
            while ((getline line < newfile) > 0) if (line != "") isnew[line] = 1
            close(newfile)
        }
        {
            t = $0; sub(/^[ \t]+/, "", t)
            fence = (substr(t, 1, 3) == "```" || substr(t, 1, 3) == "~~~")
            if (in_fence) {
                if (fence) {
                    in_fence = 0
                    if (role == "before") { role = "seen_before" } else { role = ""; armed = "" }
                    next
                }
                if (armed == "") next
                if (role == "before") { before[t] = 1; next }
                nm = declname(t)
                if (nm == "") next
                # A hook only introduces what its Before did not already show.
                if (role == "after" && (t in before)) next
                if (role == "after") print armed "\thook\t" nm
                else if (isnew[armed]) print armed "\tnew\t" nm
                next
            }
            if (fence) { in_fence = 1; next }
            # One label, one block. Letting `armed` persist attributed a shared helper
            # block to two different test files, and both were reported missing a class
            # neither was supposed to declare.
            # Only a line that DECLARES a path arms one: the task heading, the **File**:
            # declaration, a **`path`** block label, or a **Before** that names its file —
            # which is the form the generate rules teach for a multi-file modify task, and
            # the only thing that says which of nine files a hunk edits. Scanning every
            # line for a backticked path was survivable while the vocabulary was new files
            # only; once every declared path is in it, a **Why** paragraph citing
            # `config/app.properties` re-points the next code block at a properties file
            # and four real declarations stop being checked. Measured: exactly that, on
            # the first feature tried.
            if ($0 ~ /^###/ || $0 ~ /^\*\*File\*\*/ || $0 ~ /^\*\*`/ || $0 ~ /^\*\*Before\*\*/)
                for (p in want) if (index($0, "`" p "`") > 0) armed = p
            if ($0 ~ /^\*\*Before\*\*/) { role = "before"; delete before; next }
            if ($0 ~ /^\*\*After\*\*/) { role = (role == "seen_before" ? "after" : ""); next }
            if ($0 ~ /^\*\*/ && $0 !~ /^\*\*`/) { if (role != "seen_before") role = "" }
        }' "$GUIDE" | sort -u; rm -f "$PATHS_FILE" "$NEWF")
fi

# Collect scaffold files referenced in the blueprint that exist on disk
SCAFFOLD_FILES=()
SERVICE_FILES=()
TEST_FILES=()
SKELETON_FILES=()

for f in "${NEW_FILES[@]}"; do
    FULL_PATH="$REPO_ROOT/$f"
    [[ -f "$FULL_PATH" ]] || continue

    basename_f="$(basename "$f")"
    basename_lower="$(echo "$basename_f" | tr '[:upper:]' '[:lower:]')"

    in_blueprint_markers=false
    for m in "${BLUEPRINT_MARKER_FILES[@]}"; do [[ "$m" == "$f" ]] && in_blueprint_markers=true && break; done

    # Detect service/handler files (language-agnostic)
    if [[ "$basename_lower" == *service* ]] || [[ "$basename_lower" == *handler* ]] || \
       [[ "$basename_lower" == *usecase* ]] || [[ "$basename_lower" == *use_case* ]] || \
       [[ "$basename_lower" == *interactor* ]]; then
        SERVICE_FILES+=("$FULL_PATH")
    # Detect test files (language-agnostic)
    elif [[ "$basename_lower" == *test* ]] || [[ "$basename_lower" == *spec.* ]] || \
         [[ "$basename_lower" == test_* ]] || [[ "$basename_lower" == *_test.* ]]; then
        TEST_FILES+=("$FULL_PATH")
    elif [[ "$in_blueprint_markers" == true ]] || [[ ${#BLUEPRINT_MARKER_FILES[@]} -eq 0 ]]; then
        # Or the blueprint carries no markers at all. In `scaffold` and `doc-only` the
        # document holds complete code by definition, so "the blueprint gives this file a
        # marker" is false for every file — and a core logic file whose name matched none
        # of the patterns above was checked for existence and nothing else. The stubs are
        # on disk in scaffold mode, which is exactly where the marker check should look.
        SKELETON_FILES+=("$FULL_PATH")
    fi

    SCAFFOLD_FILES+=("$FULL_PATH")
done

# Files that carry no marker and are not being judged, because without --fresh a file with
# no marker is an implemented file. This used to be one warning per file, and it was 34 of
# the 45 findings this script produced over one corpus — the single loudest thing it said,
# and it said it about work that was finished.
IMPLEMENTED_FILES=()
MARKED_FILES=0

check_todo_in_file() {
    local file="$1"
    local label="$2"
    local rel_path="${file#$REPO_ROOT/}"

    if [[ ! -f "$file" ]]; then
        return
    fi

    local has_todo has_bp_todo has_not_impl
    has_todo=$(count_matches -ci "TODO" "$file")
    has_bp_todo=$(count_matches -c "TODO(blueprint)" "$file")
    has_not_impl=$(count_matches -ci "$NOT_IMPL_RE" "$file")

    if [[ "$has_todo" -gt 0 ]] || [[ "$has_not_impl" -gt 0 ]]; then
        MARKED_FILES=$((MARKED_FILES + 1))
        # This tick is the thing --done exists to answer. The pass condition is "the file
        # still carries a marker", so the greenest output this script can produce is the
        # output of a feature nobody implemented. The verdict itself is one section below,
        # over every declared file rather than only the new ones.
        pass "$rel_path — ${has_todo} TODO(s) (${has_bp_todo} blueprint markers), ${has_not_impl} NotImplemented(s) [$label]"
    elif [[ "$FRESH" == true ]]; then
        local m_count l_count
        # A method has a parameter list. Without that, `private final Money amount;` and
        # `public interface X {` counted as methods, and the failure line said "9 methods"
        # about a file with four — reported three rounds running, and the number is the
        # only evidence the line offers.
        m_count=$(count_matches -cE "^[[:space:]]*(def |fun |func |function |public |private |protected |async )[^;=]*[(]" "$file")
        l_count=$(wc -l < "$file" | tr -d ' ')
        if [[ "$m_count" -gt 1 ]] && [[ "$l_count" -gt 30 ]]; then
            fail "$rel_path — ${m_count} methods, ${l_count} lines, NO not-implemented marker, in a scaffold just written [$label]"
        else
            # Too small to tell a written-complete body from a type or a config file the
            # basename classifier happened to catch.
            warn "$rel_path — no markers, but only ${m_count} method(s)/${l_count} lines, too small to call. If implementation has started, run without --fresh; if this is a type or config file whose name matched by accident, ignore it [$label]"
        fi
    else
        IMPLEMENTED_FILES+=("$rel_path")
    fi
}

echo ""
echo "  Services/Handlers:"
if [[ ${#SERVICE_FILES[@]} -eq 0 ]]; then
    echo "    (no service/handler files to check)"
else
    for f in "${SERVICE_FILES[@]}"; do
        check_todo_in_file "$f" "Service"
    done
fi

echo ""
echo "  Tests:"
if [[ ${#TEST_FILES[@]} -eq 0 ]]; then
    echo "    (no test files to check)"
else
    for f in "${TEST_FILES[@]}"; do
        check_todo_in_file "$f" "Test"
    done
fi

echo ""
echo "  Other skeletons (the blueprint gives them a marker):"
if [[ ${#SKELETON_FILES[@]} -eq 0 ]]; then
    echo "    (none)"
else
    for f in "${SKELETON_FILES[@]}"; do
        check_todo_in_file "$f" "Skeleton"
    done
fi

# The count, once, instead of one warning per file. `--fresh` is how a caller says the
# scaffold was just written; without it a file with no marker is a file someone finished,
# which is the point of the exercise and not a finding.
if [[ ${#IMPLEMENTED_FILES[@]} -gt 0 ]]; then
    echo ""
    pass "${#IMPLEMENTED_FILES[@]} of $(( ${#IMPLEMENTED_FILES[@]} + MARKED_FILES )) declared skeleton(s) carry no marker — implemented, or written complete on purpose. Pass --fresh to judge a scaffold nobody has touched yet"
fi

# =============================================
# CHECK 3a: the Checklist against the markers on disk
# =============================================
# `- [X] T003` is the document saying that task is complete. Nothing read it. A generator
# produced a blueprint whose thirteen rows were all [X] at the commit that created it,
# with no line of the feature written, and it passed all three tools — the first thing
# the developer saw on opening the document was a checklist saying the work was done.
#
# The test is the same one --markers uses to decide who wrote a marker, and it needs both
# halves: the id must be a task of this feature AND the wording must be this blueprint's,
# because task ids restart at T001 in every feature. Measured over 118 blueprints: the id
# alone fires on 56 of them, almost all on a `T014:` an earlier feature left behind. Both
# halves together fire on 6, and the ones I read are real — a task ticked complete whose
# own marker is still sitting in the file, verbatim.
if [[ ${#DECLARED[@]} -gt 0 ]] && [[ -n "$OWN_IDS" ]]; then
    CHECKED_ROWS=$(grep -oE '^[[:space:]]*-[[:space:]]*\[[xX]\][[:space:]]*T[0-9]+' "$GUIDE" 2>/dev/null \
        | grep -oE 'T[0-9]+' | sort -u || true)
    if [[ -n "$CHECKED_ROWS" ]]; then
        header "3a. Checklist against the markers on disk"
        LIVE_TICKED=()
        for f in "${DECLARED[@]}"; do
            [[ -f "$REPO_ROOT/$f" ]] || continue
            while IFS= read -r hit; do
                [[ -n "$hit" ]] || continue
                # The same joined text --markers reads, and the same two-halves test.
                # This block used to run its own awk that required the marker call and
                # the `T0NN:` to be on one physical LINE. Python wraps them onto two, and
                # so does this extension's own --scaffold, so on a tree of thirty-three
                # markers written by this tool the check matched none of them: it printed
                # "no task ticked [X] still has its marker in the file" in the same run in
                # which check 3b named the files carrying them. Folding the marker onto
                # one line — changing not a character of its wording — made it fire at
                # once. The count this check was measured at (6 of 118 blueprints) was a
                # parser's blind spot as much as a rule's precision.
                marker_owner "$hit" || continue
                printf '%s\n' "$CHECKED_ROWS" | grep -qx -- "$MK_ID" || continue
                bp_has_wording "$MK_MSG" || continue
                [[ ${#MK_MSG} -ge 16 ]] || continue
                dup=false
                for q in "${LIVE_TICKED[@]}"; do [[ "${q%% *}" == "$MK_ID" ]] && dup=true && break; done
                [[ "$dup" == true ]] || LIVE_TICKED+=("$MK_ID ($f)")
            done < <(awk -v re="TODO[(]blueprint[)]|$MARKER_ERE" "$MARKER_JOIN_AWK" "$REPO_ROOT/$f")
        done
        if [[ ${#LIVE_TICKED[@]} -gt 0 ]]; then
            SHOWN=("${LIVE_TICKED[@]:0:6}")
            MORE=""
            [[ ${#LIVE_TICKED[@]} -gt 6 ]] && MORE=" (+$(( ${#LIVE_TICKED[@]} - 6 )) more)"
            MSG="${#LIVE_TICKED[@]} task(s) are ticked [X] and their own marker is still in the file: $(printf '%s, ' "${SHOWN[@]}" | sed 's/, $//')${MORE}"
            if [[ "$DONE" == true ]]; then
                fail "$MSG"
            else
                warn "$MSG"
            fi
            echo "      The Checklist is a claim the document makes; untick them or finish the bodies."
        else
            pass "no task ticked [X] still has its marker in the file"
        fi
    fi
fi

# =============================================
# CHECK 3b: --done — nothing declared still carries a marker
# =============================================
# The opposite claim to --fresh, and the one nobody could make. Without --fresh a file
# with a marker is a green tick, and with --fresh a file WITHOUT one is a failure, so a
# finished feature had no setting that could say "this should be done now". Measured
# consequence: one repository crossed five features leaving fourteen not-implemented
# markers in production code and two test classes its runner never calls, and this script
# printed "All checks passed" over every one of them — the tool's own green being the
# exact output of the state it exists to prevent.
#
# Every DECLARED file, not only the new ones: a (modify) task leaves its marker inside a
# file that already existed, and those never entered the classification above.
if [[ "$DONE" == true ]]; then
    header "3b. Feature declared done"
    DONE_LEFT=()
    for f in "${DECLARED[@]}"; do
        [[ -f "$REPO_ROOT/$f" ]] || continue
        n_bp=$(count_matches -c "TODO(blueprint)" "$REPO_ROOT/$f")
        n_impl=$(count_matches -ci "$NOT_IMPL_RE" "$REPO_ROOT/$f")
        if [[ "$n_bp" -gt 0 ]] || [[ "$n_impl" -gt 0 ]]; then
            DONE_LEFT+=("$f ($(( n_bp + n_impl )))")
        fi
    done
    if [[ ${#DONE_LEFT[@]} -gt 0 ]]; then
        SHOWN=("${DONE_LEFT[@]:0:8}")
        MORE=""
        [[ ${#DONE_LEFT[@]} -gt 8 ]] && MORE=" (+$(( ${#DONE_LEFT[@]} - 8 )) more)"
        fail "${#DONE_LEFT[@]} declared file(s) still carry a not-implemented marker: $(printf '%s, ' "${SHOWN[@]}" | sed 's/, $//')${MORE}"
        echo "      --done says this feature is finished. Run /speckit.blueprint.cleanup, or drop --done."
    else
        pass "no declared file carries a not-implemented marker"
    fi
fi

# =============================================
# CHECK 4: Over-implementation detection
# =============================================
header "4. Over-Implementation Detection"

check_over_implementation() {
    local file="$1"
    local rel_path="${file#$REPO_ROOT/}"

    [[ -f "$file" ]] || return

    local has_todo has_not_impl
    has_todo=$(count_matches -ci "TODO" "$file")
    has_not_impl=$(count_matches -ci "$NOT_IMPL_RE" "$file")

    if [[ "$has_todo" -eq 0 ]] && [[ "$has_not_impl" -eq 0 ]]; then
        # Count function/method definitions (language-agnostic patterns)
        local method_count
        method_count=$(count_matches -cE "^[[:space:]]*(def |fun |func |function |public |private |protected |async |static |[A-Za-z_][A-Za-z0-9_<>,. ]*[[:space:]]+[a-zA-Z_][a-zA-Z0-9_]*[[:space:]]*\()[^;]*\(" "$file")
        local line_count=$(wc -l < "$file" | tr -d ' ')

        if [[ "$method_count" -gt 1 ]] && [[ "$line_count" -gt 30 ]]; then
            # A file with no marker is normal once you have implemented it — but if its
            # SIBLING scaffold files still carry markers, nothing has been implemented yet
            # and this one was written complete against the mode's rules. That case breaks
            # the build (it can call APIs no other task has created), so it fails.
            # Fresh scaffold or work in progress? During implementation some files are
            # done and some are not, and a finished file is not a violation. Only when
            # nearly every sibling still carries a marker is nothing implemented yet —
            # and then a complete file is the mode being broken, which breaks the build.
            # The ratio below reads the siblings to guess whether implementation has
            # started. When every file was written complete there are no marked
            # siblings left to read, and the guess lands on "already implemented" —
            # exactly the total violation this check exists for. Only the caller knows
            # which it is, so --fresh says it outright.
            if [[ "$FRESH" == true ]]; then
                # Already reported by check 3, which applies the same size test under
                # --fresh. Counting it here made every violating file two failures.
                return
            fi
            # Without --fresh this cannot be a failure. The sibling ratio was meant to
            # tell "just scaffolded" from "being implemented", but with four marker files
            # the first one finished is 3/4 still marked, and the developer who had just
            # implemented it honestly was told it "was written complete instead of
            # stubbed". Only the caller knows which it is, and --fresh is how they say so.
            # Check 3 already accounts for this file; a second finding here says the same
            # thing about the same file, and a feature under implementation collected two
            # per file until nothing in the output was signal. Counted, not reported — the
            # section says once, below, what it can and cannot judge.
            OVER_IMPL_COMPLETE=$((OVER_IMPL_COMPLETE + 1))
        fi
    fi
}

# How many scaffold files still carry a not-implemented marker. Zero means the
# developer has implemented; non-zero means we are still looking at fresh scaffolds.
MARKED_SCAFFOLDS=0
TOTAL_SCAFFOLDS=0
# Only files the mode says should carry markers count here. Structural scaffolds
# (types, config, wiring) are written complete on purpose, and counting them would
# dilute the ratio until a fresh scaffold looks like work in progress.
MARKER_POPULATION=()
[[ ${#SERVICE_FILES[@]} -gt 0 ]] && MARKER_POPULATION+=("${SERVICE_FILES[@]}")
[[ ${#TEST_FILES[@]} -gt 0 ]] && MARKER_POPULATION+=("${TEST_FILES[@]}")
[[ ${#SKELETON_FILES[@]} -gt 0 ]] && MARKER_POPULATION+=("${SKELETON_FILES[@]}")
for f in "${MARKER_POPULATION[@]}"; do
    [[ -f "$f" ]] || continue
    n_todo=$(count_matches -ci "TODO" "$f")
    n_impl=$(count_matches -ci "$NOT_IMPL_RE" "$f")
    TOTAL_SCAFFOLDS=$((TOTAL_SCAFFOLDS + 1))
    if [[ "$n_todo" -gt 0 ]] || [[ "$n_impl" -gt 0 ]]; then
        MARKED_SCAFFOLDS=$((MARKED_SCAFFOLDS + 1))
    fi
done

OVER_IMPL_FOUND=false
OVER_IMPL_COMPLETE=0
ALL_CHECK_FILES=()
[[ ${#SERVICE_FILES[@]} -gt 0 ]] && ALL_CHECK_FILES+=("${SERVICE_FILES[@]}")
[[ ${#TEST_FILES[@]} -gt 0 ]] && ALL_CHECK_FILES+=("${TEST_FILES[@]}")
[[ ${#SKELETON_FILES[@]} -gt 0 ]] && ALL_CHECK_FILES+=("${SKELETON_FILES[@]}")

if [[ ${#ALL_CHECK_FILES[@]} -gt 0 ]]; then
    # Called directly, not in $( ), so warn()/fail() counters survive.
    SEEN_CHECK=()
    for f in "${ALL_CHECK_FILES[@]}"; do
        # Quoted, so a scaffold path containing a space stays one path.
        dup=false
        for g in "${SEEN_CHECK[@]}"; do [[ "$g" == "$f" ]] && dup=true && break; done
        [[ "$dup" == true ]] && continue
        SEEN_CHECK+=("$f")
        check_over_implementation "$f"
    done
fi

# A section that prints a heading and then nothing reads as "something was found and the
# tool will not say what". This one did exactly that on every run where implementation had
# started, because the only branch that fired set a flag and returned without printing.
if [[ "$OVER_IMPL_FOUND" == true ]]; then
    :
elif [[ "$OVER_IMPL_COMPLETE" -gt 0 ]]; then
    pass "$OVER_IMPL_COMPLETE file(s) are written complete with no marker — over-implementation is only a verdict on a fresh scaffold; pass --fresh to make it one"
else
    pass "No over-implemented scaffold files detected"
fi

# =============================================
# CHECK 5: does each declared file hold what the blueprint says it declares?
# =============================================
# Names this file DECLARES, cached per file. The old test asked whether the name appeared
# anywhere in the file, which the line that calls a deleted method satisfies; deleting
# `usedToday` from a 90-line policy left `Money used = usedToday(accountId);` behind, and
# the check answered "all 19 declared symbol(s) are present" over a tree that would not
# compile.
DISK_SYMBOL_CACHE_KEY=""
DISK_SYMBOL_CACHE=""
file_declares() {
    local file="$1" name="$2"
    if [[ "$DISK_SYMBOL_CACHE_KEY" != "$file" ]]; then
        DISK_SYMBOL_CACHE_KEY="$file"
        DISK_SYMBOL_CACHE=$(awk "$DECL_AWK"'
            {
                t = $0; sub(/^[ \t]+/, "", t)
                nm = declname(t)
                if (nm != "") { print nm; next }
                # A signature wrapped over several lines ends in neither `{` nor `;`, so
                # declname cannot see it. A name immediately in front of "(" still counts
                # unless what precedes it makes the line a call: a dot, an operator, an
                # open paren or comma, one of the call keywords, or nothing at all.
                s = $0
                while (match(s, /[A-Za-z_][A-Za-z0-9_]*[ \t]*\(/)) {
                    nm = substr(s, RSTART, RLENGTH)
                    sub(/[ \t]*\(?$/, "", nm)
                    before = substr(s, 1, RSTART - 1); sub(/[ \t]+$/, "", before)
                    if (before != "" && before !~ /[.]$/ \
                        && before !~ /[=,(+*\/!&|?:<>[-]$/ \
                        && before !~ /(^|[^A-Za-z0-9_])(return|new|throw|await|yield|not|and|or)$/)
                        print nm
                    s = substr(s, RSTART + RLENGTH)
                }
            }' "$file" 2>/dev/null | sort -u)
    fi
    printf '%s\n' "$DISK_SYMBOL_CACHE" | grep -qx -- "$name"
}

if [[ ${#DECLARED_SYMBOLS[@]} -gt 0 ]]; then
    echo ""
    echo -e "${CYAN}=== Declared symbols ===${NC}"
    MISSING_SYMBOLS=0
    CHECKED_SYMBOLS=0
    HOOK_CHECKED=0
    HOOK_PENDING=0
    MISSING_HOOKS=()
    for entry in "${DECLARED_SYMBOLS[@]}"; do
        sym_path="${entry%%$'\t'*}"
        sym_rest="${entry#*$'\t'}"
        sym_origin="${sym_rest%%$'\t'*}"
        sym_name="${sym_rest##*$'\t'}"
        [[ -n "$sym_path" && -n "$sym_name" ]] || continue
        [[ -f "$REPO_ROOT/$sym_path" ]] || continue
        # A declaration a (modify) hook introduces is not on disk until the developer
        # types the hunk, so on a fresh scaffold its absence is the expected state, not a
        # defect. --fresh must not fail on it; --done must.
        if [[ "$sym_origin" == "hook" ]] && [[ "$FRESH" == true ]]; then
            HOOK_PENDING=$((HOOK_PENDING + 1))
            continue
        fi
        CHECKED_SYMBOLS=$((CHECKED_SYMBOLS + 1))
        [[ "$sym_origin" == "hook" ]] && HOOK_CHECKED=$((HOOK_CHECKED + 1))
        if ! file_declares "$REPO_ROOT/$sym_path" "$sym_name"; then
            MISSING_SYMBOLS=$((MISSING_SYMBOLS + 1))
            # A failure only for a tree whose state the caller has declared. Mid-flight a
            # developer may rename what the blueprint called something else, and that is
            # their call to make; on a fresh scaffold a missing skeleton declaration is a
            # task that never landed, and on a finished feature it is work not done.
            if [[ "$sym_origin" == "hook" ]]; then
                # One finding, not one per symbol. A hook's declarations arrive as the
                # developer types, so on a tree where the feature has not been started
                # every one of them is absent at once: measured, fourteen on one feature,
                # which is the wall of identical lines this script spent a release
                # removing. The names are still here, four of them and a count.
                MISSING_HOOKS+=("$sym_path \`$sym_name\`")
                continue
            fi
            # A third state between the two flags, read off the tree instead of asked for.
            # "Mid-flight" is the reason this is a warning by default — but a file with no
            # not-implemented marker anywhere in it is a file nobody is mid-flight on.
            # Either the symbol was renamed (the blueprint is stale and the document is
            # the fix) or it is gone. A reviewer deleted a declared function outright,
            # leaving a tree whose application would not start, and the default run said
            # `PASSED with warnings` and exit 0; --done caught it, and --done is a flag
            # you have to know to type. This costs no false positives on a half-typed
            # file, because a half-typed file still has its marker.
            if [[ "$FRESH" == true ]] || [[ "$DONE" == true ]]; then
                fail "$sym_path — the blueprint declares \`$sym_name\` and the file does not declare it"
            elif ! grep -q "$NOT_IMPL_RE" "$REPO_ROOT/$sym_path" 2>/dev/null \
                 && ! grep -qE 'TODO\(blueprint\)' "$REPO_ROOT/$sym_path" 2>/dev/null; then
                fail "$sym_path — the blueprint declares \`$sym_name\`, the file does not declare it, and the file carries no marker: nothing here is unfinished, so the name was renamed or removed"
            else
                warn "$sym_path — the blueprint declares \`$sym_name\` and the file does not declare it (renamed, or the task never landed)"
            fi
        fi
    done
    if [[ ${#MISSING_HOOKS[@]} -gt 0 ]]; then
        SHOWN=("${MISSING_HOOKS[@]:0:4}")
        MORE=""
        [[ ${#MISSING_HOOKS[@]} -gt 4 ]] && MORE=" (+$(( ${#MISSING_HOOKS[@]} - 4 )) more)"
        MSG="${#MISSING_HOOKS[@]} declaration(s) a (modify) hook introduces are not in the file: $(printf '%s, ' "${SHOWN[@]}" | sed 's/, $//')${MORE}"
        if [[ "$DONE" == true ]]; then
            fail "$MSG"
        else
            warn "$MSG — typed under another name, or the hunk was never typed"
        fi
    fi
    if [[ "$CHECKED_SYMBOLS" -eq 0 ]]; then
        warn "${#DECLARED_SYMBOLS[@]} declared symbol(s) read from the blueprint, and none of the files that should hold them are on disk yet"
    elif [[ "$MISSING_SYMBOLS" -eq 0 ]]; then
        pass "all $CHECKED_SYMBOLS declared symbol(s) are present in the files that should hold them ($HOOK_CHECKED introduced by a (modify) hook)"
    fi
    if [[ "$HOOK_PENDING" -gt 0 ]]; then
        pass "$HOOK_PENDING symbol(s) a (modify) hook introduces are not judged on a fresh scaffold — the developer types those"
    fi
fi

# =============================================
# SUMMARY
# =============================================
echo ""
echo -e "${CYAN}=== Summary ===${NC}"
echo -e "  ${GREEN}PASS${NC}: $PASS"
echo -e "  ${YELLOW}WARN${NC}: $WARN"
echo -e "  ${RED}FAIL${NC}: $FAIL"

echo -e "  After implementing, run /speckit.blueprint.cleanup to sweep leftover markers."

if [[ $FAIL -gt 0 ]]; then
    echo -e "\n${RED}Validation FAILED — $FAIL issue(s) found${NC}"
    exit 1
elif [[ $WARN -gt 0 ]]; then
    echo -e "\n${YELLOW}Validation PASSED with warnings${NC}"
    exit 0
else
    echo -e "\n${GREEN}All checks passed${NC}"
    exit 0
fi
