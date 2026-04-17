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
# Usage: bash validate-scaffold.sh [feature-dir]
#   feature-dir: specs/{feature}/ path (default: auto-detect from current branch)

set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
WARN=0
FAIL=0

pass()  { ((PASS++)); echo -e "  ${GREEN}✓${NC} $1"; }
warn()  { ((WARN++)); echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()  { ((FAIL++)); echo -e "  ${RED}✗${NC} $1"; }
header(){ echo -e "\n${CYAN}[$1]${NC}"; }

# === Resolve feature directory ===
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

if [[ -n "${1:-}" ]]; then
    FEATURE_DIR="$1"
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

echo -e "${CYAN}=== Blueprint Scaffold Validator ===${NC}"
echo "Feature: $FEATURE_DIR"
echo "Blueprint: $GUIDE"

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
while IFS= read -r line; do
    # Pattern 1: **File**: `path` (new...)
    if [[ "$line" =~ \*\*File\*\*:\ \`([^\`]+)\`.*\(new ]]; then
        NEW_FILES+=("${BASH_REMATCH[1]}")
    # Pattern 2: table row with "New" — | `path` | ... | New |
    elif [[ "$line" =~ \|[[:space:]]*\`?([a-zA-Z][^\`\|]+\.[a-zA-Z]+)\`?[[:space:]]*\|.*[Nn]ew ]]; then
        NEW_FILES+=("${BASH_REMATCH[1]}")
    # Pattern 3: backtick-quoted path with / and known extension
    elif [[ "$line" =~ \|[[:space:]]*\`([a-zA-Z][^\`]*\/[^\`]*\.[a-zA-Z]+)\`[[:space:]]*\| ]]; then
        NEW_FILES+=("${BASH_REMATCH[1]}")
    fi
done < "$GUIDE"

if [[ ${#NEW_FILES[@]} -eq 0 ]]; then
    warn "No NEW file paths detected in blueprint (check blueprint format)"
else
    for f in "${NEW_FILES[@]}"; do
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

    local has_todo=$(grep -ci "TODO" "$file" 2>/dev/null || echo 0)
    local has_not_impl=$(grep -ci "NotImplemented\|not_implemented\|raise NotImplementedError\|throw.*NotImplemented" "$file" 2>/dev/null || echo 0)

    if [[ "$has_todo" -gt 0 ]] || [[ "$has_not_impl" -gt 0 ]]; then
        pass "$rel_path — ${has_todo} TODO(s), ${has_not_impl} NotImplemented(s) [$label]"
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

    local has_todo=$(grep -ci "TODO" "$file" 2>/dev/null || echo 0)
    local has_not_impl=$(grep -ci "NotImplemented\|not_implemented\|raise NotImplementedError\|throw.*NotImplemented" "$file" 2>/dev/null || echo 0)

    if [[ "$has_todo" -eq 0 ]] && [[ "$has_not_impl" -eq 0 ]]; then
        # Count function/method definitions (language-agnostic patterns)
        local method_count=$(grep -cE "^\s*(def |fun |func |function |public |private |protected |async )" "$file" 2>/dev/null || echo 0)
        local line_count=$(wc -l < "$file" | tr -d ' ')

        if [[ "$method_count" -gt 1 ]] && [[ "$line_count" -gt 30 ]]; then
            fail "$rel_path — ${method_count} methods, ${line_count} lines, but NO TODO. May be over-implemented for scaffold mode."
        fi
    fi
}

OVER_IMPL_FOUND=false
ALL_CHECK_FILES=()
[[ ${#SERVICE_FILES[@]} -gt 0 ]] && ALL_CHECK_FILES+=("${SERVICE_FILES[@]}")
[[ ${#TEST_FILES[@]} -gt 0 ]] && ALL_CHECK_FILES+=("${TEST_FILES[@]}")

if [[ ${#ALL_CHECK_FILES[@]} -gt 0 ]]; then
    for f in "${ALL_CHECK_FILES[@]}"; do
        result=$(check_over_implementation "$f" 2>&1)
        if [[ -n "$result" ]]; then
            echo "$result"
            OVER_IMPL_FOUND=true
        fi
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
