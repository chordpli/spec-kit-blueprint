# Blueprint: Row summary with node:test tests

**Branch**: `016-registration` | **Date**: 2026-01-01
**Mode**: guide — signatures, Why, implementation notes and pitfalls; every body with behavior is a not-implemented marker
**Total Tasks**: 3 | **Files**: 3 new, 0 modified, 0 deleted
**Build**: `python3 -c "print('no build')"`
**Sources**: tasks.md@54c5af6663d0

## Requirements Reference

- **FR-001**: the summary counts rows.
- **FR-002**: a row is formatted as its fields joined by commas.

## Implementation Order

```
T001 -> T002 -> T003
```

## Phase 1

### T001: Create `src/report.js`

**File**: `src/report.js` (new)

**Requirements**: FR-001

**Why**: One function owns counting so the CLI and the tests agree on it (016 FR-001).

```javascript
export function summarize(rows) {
  throw new Error("T001: return the number of rows; an empty list is 0 (016 FR-001).");
}
```

**Verification**: `python3 -c "print('summarize')"`

### T002: Create `test/report.test.js`

**File**: `test/report.test.js` (new)

**Requirements**: FR-001

**Why**: The registration call below is node:test's API, not a declaration this file owns.
A finished test written on one line must not be reported as missing it.

```javascript
import test from "node:test";

test("summarize counts rows", () => {
  throw new Error("T002: assert summarize([]) is 0 and summarize([a, b]) is 2 (016 FR-001).");
});
```

**Verification**: `python3 -c "import sys; assert 'summarize' in open(sys.argv[1]).read()" test/report.test.js`

### T003: Create `src/format.js`

**File**: `src/format.js` (new)

**Requirements**: FR-002

**Why**: Formatting is separate from counting so either can change alone (016 FR-002).

```javascript
export function formatRow(row) {
  throw new Error("T003: join the row's fields with commas (016 FR-002).");
}
```

**Verification**: `python3 -c "print('format')"`

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [X] T001: create `src/report.js`
- [X] T002: create `test/report.test.js`
- [X] T003: create `src/format.js`
