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

set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_VERSION="1.1.0"

PASS=0
WARN=0
FAIL=0

pass()  { ((PASS++)); echo -e "  ${GREEN}✓${NC} $1"; }
warn()  { ((WARN++)); echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()  { ((FAIL++)); echo -e "  ${RED}✗${NC} $1"; }
header(){ echo -e "\n${CYAN}[$1]${NC}"; }

# grep -c prints "0" and exits 1 when nothing matches, so `$(grep -c … || echo 0)`
# yields "0\n0" and breaks every arithmetic test downstream. Always emit one integer.
# Language-native "not implemented yet" forms. A guide-mode skeleton body is one of
# these, so missing them makes an untouched skeleton look fully implemented.
NOT_IMPL_RE='NotImplemented\|not_implemented\|NotImplementedError\|UnsupportedOperationException\|NotImplementedException\|fatalError(\|todo!(\|unimplemented!(\|panic(.TODO\|panic(.not implemented'

count_matches() {
    local n
    n=$(grep "$@" 2>/dev/null) || n=0
    printf '%s' "${n:-0}"
}

# === Resolve feature directory ===
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

STRICT=false
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --strict) STRICT=true ;;
        *)        ARGS+=("$arg") ;;
    esac
done

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
    MODE_TOKENS="$(echo "${MODE_LINE#*:}" | tr '[:upper:]' '[:lower:]' | awk '{print $1, $2}')"
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
# A **File**: declaration may wrap onto following lines; join it back into one
# logical line before parsing, or every path after the first is invisible here.
JOINED=$(awk '
    /^\*\*File\*\*:/ { buf = $0; joining = 1; next }
    joining && NF > 0    { buf = buf " " $0; next }
    joining && NF == 0   { print buf; joining = 0; print; next }
    { print }
    END { if (joining) print buf }
' "$GUIDE")

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
                if [[ "$token_path" == */* ]] && [[ "$token_path" == *.* ]]; then
                    pending+=("$token_path")
                fi
            else
                # a (kind) closes the run of paths collected since the last one
                if [[ "$token_kind" == new* ]] || [[ "$token_kind" == *"— 이동"* ]]; then
                    for pp in "${pending[@]}"; do NEW_FILES+=("$pp"); done
                fi
                pending=()
            fi
        done
    # Pattern 2: table row with "New" — | `path` | ... | New |
    elif [[ "$line" =~ \|[[:space:]]*\`?([a-zA-Z][^\`\|]+\.[a-zA-Z]+)\`?[[:space:]]*\|.*[Nn]ew ]]; then
        NEW_FILES+=("${BASH_REMATCH[1]}")
    # Pattern 3: backtick-quoted path with / and known extension
    elif [[ "$line" =~ \|[[:space:]]*\`([a-zA-Z][^\`]*\/[^\`]*\.[a-zA-Z]+)\`[[:space:]]*\| ]]; then
        NEW_FILES+=("${BASH_REMATCH[1]}")
    fi
done <<< "$JOINED"

# The patterns above can match the same path twice (a File line and a table row),
# which would report and count that file twice.
if [[ ${#NEW_FILES[@]} -gt 0 ]]; then
    NEW_FILES=($(printf '%s\n' "${NEW_FILES[@]}" | awk '!seen[$0]++'))
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
    for f in "${NEW_FILES[@]}"; do
        # Skip placeholder/glob paths (e.g. docs/2026-MM-DD-*.md) — not real targets
        if [[ "$f" == *"*"* ]] || [[ "$f" == *"MM-DD"* ]] || [[ "$f" == *"{"* ]]; then
            continue
        fi
        FULL_PATH="$REPO_ROOT/$f"
        if [[ -f "$FULL_PATH" ]]; then
            pass "$f exists"
        else
            fail "$f MISSING"
        fi
    done
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
    echo -e "\n${GREEN}All checks passed${NC} (doc-only/guide blueprint — pass --strict to validate files scaffolded after generation)"
    exit 0
fi

# Collect scaffold files referenced in the blueprint that exist on disk
SCAFFOLD_FILES=()
SERVICE_FILES=()
TEST_FILES=()

for f in "${NEW_FILES[@]}"; do
    FULL_PATH="$REPO_ROOT/$f"
    [[ -f "$FULL_PATH" ]] || continue

    basename_f="$(basename "$f")"
    basename_lower="$(echo "$basename_f" | tr '[:upper:]' '[:lower:]')"

    # Detect service/handler files (language-agnostic)
    if [[ "$basename_lower" == *service* ]] || [[ "$basename_lower" == *handler* ]] || \
       [[ "$basename_lower" == *usecase* ]] || [[ "$basename_lower" == *use_case* ]] || \
       [[ "$basename_lower" == *interactor* ]]; then
        SERVICE_FILES+=("$FULL_PATH")
    # Detect test files (language-agnostic)
    elif [[ "$basename_lower" == *test* ]] || [[ "$basename_lower" == *spec.* ]] || \
         [[ "$basename_lower" == test_* ]] || [[ "$basename_lower" == *_test.* ]]; then
        TEST_FILES+=("$FULL_PATH")
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
        method_count=$(count_matches -cE "^[[:space:]]*(def |fun |func |function |public |private |protected |async )" "$file")
        local line_count=$(wc -l < "$file" | tr -d ' ')

        if [[ "$method_count" -gt 1 ]] && [[ "$line_count" -gt 30 ]]; then
            # A file with no marker is normal once you have implemented it — but if its
            # SIBLING scaffold files still carry markers, nothing has been implemented yet
            # and this one was written complete against the mode's rules. That case breaks
            # the build (it can call APIs no other task has created), so it fails.
            if [[ "$MARKED_SCAFFOLDS" -gt 0 ]]; then
                fail "$rel_path — ${method_count} methods, ${line_count} lines, no markers, while ${MARKED_SCAFFOLDS} sibling scaffold file(s) still have them. This file was written complete instead of stubbed."
            else
                warn "$rel_path — ${method_count} methods, ${line_count} lines, no markers left. Expected once you have implemented it; look closer only if this file was just scaffolded."
            fi
            OVER_IMPL_FOUND=true
        fi
    fi
}

# How many scaffold files still carry a not-implemented marker. Zero means the
# developer has implemented; non-zero means we are still looking at fresh scaffolds.
MARKED_SCAFFOLDS=0
for f in "${SCAFFOLD_FILES[@]}"; do
    [[ -f "$f" ]] || continue
    n_todo=$(count_matches -ci "TODO" "$f")
    n_impl=$(count_matches -ci "$NOT_IMPL_RE" "$f")
    if [[ "$n_todo" -gt 0 ]] || [[ "$n_impl" -gt 0 ]]; then
        MARKED_SCAFFOLDS=$((MARKED_SCAFFOLDS + 1))
    fi
done

OVER_IMPL_FOUND=false
ALL_CHECK_FILES=()
[[ ${#SERVICE_FILES[@]} -gt 0 ]] && ALL_CHECK_FILES+=("${SERVICE_FILES[@]}")
[[ ${#TEST_FILES[@]} -gt 0 ]] && ALL_CHECK_FILES+=("${TEST_FILES[@]}")

if [[ ${#ALL_CHECK_FILES[@]} -gt 0 ]]; then
    # Called directly, not in $( ), so warn()/fail() counters survive.
    for f in $(printf '%s\n' "${ALL_CHECK_FILES[@]}" | awk '!seen[$0]++'); do
        check_over_implementation "$f"
    done
fi

if [[ "$OVER_IMPL_FOUND" == false ]]; then
    pass "No over-implemented scaffold files detected"
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
