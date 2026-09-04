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

# === Resolve feature directory ===
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

STRICT=false
FRESH=false
MARKERS=false
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --strict) STRICT=true ;;
        --fresh)  FRESH=true ;;
        --markers) MARKERS=true ;;
        *)        ARGS+=("$arg") ;;
    esac
done

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

if [[ "$MARKERS" == true ]]; then
    # This feature's task ids, so a marker belonging to an earlier feature can be named
    # as such rather than counted as work left here.
    IDS_FILE=$(mktemp)
    if [[ -f "$FEATURE_DIR/tasks.md" ]]; then
        grep -oE '^[[:space:]]*-[[:space:]]*\[[ xX]\][[:space:]]*T[0-9]+' "$FEATURE_DIR/tasks.md" 2>/dev/null \
            | grep -oE 'T[0-9]+' > "$IDS_FILE" || true
    fi
    # Every declared path, not only the new ones: a marker inserted into an existing
    # file by a (modify) task is residue too. Comment-syntax markers and executable
    # not-implemented calls both count; the judgment about each is cleanup's.
    # Deduplicated: a file that several tasks build up is declared once per task, and
    # the first version of this listing printed each of its markers that many times —
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
    found=0
    for f in "${DECLARED[@]}"; do
        [[ -f "$REPO_ROOT/$f" ]] || continue
        # A marker whose message wraps to the next line — Python's `raise
        # NotImplementedError(` with the "T001: …" string below it — is printed with
        # that line joined on, or the listing shows the call and never the task id.
        while IFS= read -r hit; do
            [[ -n "$hit" ]] || continue
            # Task ids restart at T001 in every feature, so a `T014:` marker left by an
            # earlier feature was listed as work still owed here — and both features had
            # a T014. What decides it is whether this blueprint wrote the marker: take a
            # distinctive run of its message and look for it in the document.
            probe="${hit#*T}"; probe="${probe#*: }"; probe="${probe:0:48}"
            if [[ ${#probe} -ge 16 ]] && ! grep -qF -- "$probe" "$GUIDE" 2>/dev/null; then
                echo "$f:$hit   [not written by this blueprint — an earlier feature left it]" >&3
            else
                echo "$f:$hit" >&3
            fi
            found=$((found + 1))
        done < <(awk -v re="TODO[(]blueprint[)]|$MARKER_ERE" '
            { lines[NR] = $0 }
            END {
                for (i = 1; i <= NR; i++) {
                    if (lines[i] !~ re) continue
                    out = lines[i]; sub(/^[ \t]+/, "", out)
                    if (out !~ /T[0-9]+:/ && i < NR) {
                        nxt = lines[i + 1]; sub(/^[ \t]+/, "", nxt)
                        if (nxt ~ /T[0-9]+:/) out = out " " nxt
                    }
                    # A message split across concatenated string literals showed only
                    # its first physical line. Executable markers only: a comment marker
                    # has no closing paren to stop at, so this ran on and pulled the code
                    # under it into the listing cleanup is supposed to read.
                    if (out ~ /(NotImplementedError|UnsupportedOperationException|NotImplementedException|fatalError|todo!|unimplemented!|panic)[[:space:]]*\(/) {
                        j = i
                        while (out !~ /\)[[:space:]]*;?[[:space:]]*$/ && j < NR && j - i < 6) {
                            j++; cont = lines[j]; sub(/^[ \t]+/, "", cont)
                            if (cont == "") break
                            out = out " " cont
                        }
                    }
                    print i ": " out
                }
            }' "$REPO_ROOT/$f")
    done
    rm -f "$IDS_FILE"
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
    for f in "${NEW_FILES[@]}"; do
        # Skip placeholder/glob paths (e.g. docs/2026-MM-DD-*.md) — not real targets
        if [[ "$f" == *"*"* ]] || [[ "$f" == *"MM-DD"* ]] || [[ "$f" == *"{"* ]]; then
            SKIPPED_PLACEHOLDERS+=("$f")
            continue
        fi
        CHECKED_ANY=true
        FULL_PATH="$REPO_ROOT/$f"
        if [[ -f "$FULL_PATH" ]]; then
            pass "$f exists"
        else
            fail "$f MISSING — the blueprint declares it and it is not on disk. Before scaffolding it: is the work somewhere else under another name?"
        fi
    done
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
DECLARED_SYMBOLS=()
if [[ ${#NEW_FILES[@]} -gt 0 ]]; then
    while IFS= read -r line; do
        [[ -n "$line" ]] && DECLARED_SYMBOLS+=("$line")
    done < <(PATHS_FILE=$(mktemp); printf '%s\n' "${NEW_FILES[@]}" > "$PATHS_FILE"; \
             awk -v pathsfile="$PATHS_FILE" '
        BEGIN { while ((getline line < pathsfile) > 0) if (line != "") want[line] = 1; close(pathsfile) }
        {
            t = $0; sub(/^[ \t]+/, "", t)
            fence = (substr(t, 1, 3) == "```" || substr(t, 1, 3) == "~~~")
            if (in_fence) {
                # One label, one block. Letting `armed` persist attributed a shared
                # helper block to two different test files, and both were reported
                # missing a class neither was supposed to declare.
                if (fence) { in_fence = 0; armed = ""; next }
                if (armed == "") next
                # A declaration, in the shapes the guide skeletons use. The name is the
                # word before the parameter list, or after class/interface/struct.
                if (match(t, /^(export[ \t]+)?(default[ \t]+)?(async[ \t]+)?(public|private|protected|internal|open|final|static|abstract|suspend)?[ \t]*(class|interface|struct|enum|object|record|trait)[ \t]+[A-Za-z_][A-Za-z0-9_]*/)) {
                    n = split(t, w, /[ \t]+/)
                    for (i = 1; i <= n; i++)
                        if (w[i] ~ /^(class|interface|struct|enum|object|record|trait)$/ && (i + 1) <= n) {
                            nm = w[i+1]; gsub(/[^A-Za-z0-9_].*$/, "", nm)
                            if (nm != "") print armed "\t" nm
                            break
                        }
                    next
                }
                if (match(t, /^(export[ \t]+)?(async[ \t]+)?(def|fun|func|function|sub)[ \t]+[A-Za-z_][A-Za-z0-9_]*/)) {
                    n = split(t, w, /[ \t]+/)
                    for (i = 1; i <= n; i++)
                        if (w[i] ~ /^(def|fun|func|function|sub)$/ && (i + 1) <= n) {
                            nm = w[i+1]; gsub(/[^A-Za-z0-9_].*$/, "", nm)
                            if (nm != "") print armed "\t" nm
                            break
                        }
                    next
                }
                # A C-family method: a parameter list, an identifier in front of it, no
                # assignment before it, and a body or a semicolon after. Without this a
                # Java skeleton contributed only its type names, so the file could be
                # missing every method it declares and still pass.
                # Not a statement. `throw new UnsupportedOperationException("T0NN: ...");`
                # ends in a paren-and-semicolon like a declaration does, and its last word
                # before the paren was reported as a symbol the file must contain.
                if (t ~ /^(throw|return|new|assert|super|this|import|package|@)[^A-Za-z0-9_]/) next
                if (t ~ /^[A-Za-z_@<][^=;]*\(/ && (t ~ /\{[ \t]*$/ || t ~ /;[ \t]*$/)) {
                    head2 = t; sub(/\(.*$/, "", head2)
                    nm = head2; sub(/^.*[^A-Za-z0-9_]/, "", nm)
                    if (nm != "" && nm !~ /^(if|for|while|switch|catch|return|new|do|else|synchronized|throw|assert|super|this)$/)
                        print armed "\t" nm
                    next
                }
                next
            }
            if (fence) { in_fence = 1; next }
            for (p in want) if (index($0, "`" p "`") > 0) armed = p
        }' "$GUIDE" | sort -u; rm -f "$PATHS_FILE")
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
        warn "$rel_path — NO TODO markers found (fully implemented or boilerplate?) [$label]"
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
            # Check 3 already warned about this file having no markers; a second warning
            # here says the same thing about the same file, and a feature under
            # implementation collected two per file until nothing in the output was signal.
            OVER_IMPL_FOUND=true
            return
            OVER_IMPL_FOUND=true
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

if [[ "$OVER_IMPL_FOUND" == false ]]; then
    pass "No over-implemented scaffold files detected"
fi

# =============================================
# CHECK 5: does each declared file hold what the blueprint says it declares?
# =============================================
if [[ ${#DECLARED_SYMBOLS[@]} -gt 0 ]]; then
    echo ""
    echo -e "${CYAN}=== Declared symbols ===${NC}"
    MISSING_SYMBOLS=0
    CHECKED_SYMBOLS=0
    for entry in "${DECLARED_SYMBOLS[@]}"; do
        sym_path="${entry%%$'\t'*}"
        sym_name="${entry##*$'\t'}"
        [[ -n "$sym_path" && -n "$sym_name" ]] || continue
        [[ -f "$REPO_ROOT/$sym_path" ]] || continue
        CHECKED_SYMBOLS=$((CHECKED_SYMBOLS + 1))
        if ! grep -q "[^A-Za-z0-9_]${sym_name}[^A-Za-z0-9_]\|^${sym_name}[^A-Za-z0-9_]" "$REPO_ROOT/$sym_path" 2>/dev/null; then
            # A failure only for a scaffold just written. Once implementation starts a
            # developer may rename what the blueprint called something else, and that is
            # their call to make; before then, a missing declaration is a task that never
            # landed on disk.
            if [[ "$FRESH" == true ]]; then
                fail "$sym_path — the blueprint declares \`$sym_name\` and the file does not have it"
            else
                warn "$sym_path — the blueprint declares \`$sym_name\` and the file does not have it (renamed, or the task never landed)"
            fi
            MISSING_SYMBOLS=$((MISSING_SYMBOLS + 1))
        fi
    done
    if [[ "$CHECKED_SYMBOLS" -eq 0 ]]; then
        warn "${#DECLARED_SYMBOLS[@]} declared symbol(s) read from the blueprint, and none of the files that should hold them are on disk yet"
    elif [[ "$MISSING_SYMBOLS" -eq 0 ]]; then
        pass "all $CHECKED_SYMBOLS declared symbol(s) are present in the files that should hold them"
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
