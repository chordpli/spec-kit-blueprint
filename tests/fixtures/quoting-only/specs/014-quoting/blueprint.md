# Blueprint: Everything worth reporting sits inside a quotation

**Branch**: `014-quoting` | **Date**: 2026-01-01
**Mode**: guide scaffold — signatures, Why, implementation notes and pitfalls; every body with behavior is a not-implemented marker; declared-new files are written to disk as skeletons
**Total Tasks**: 5 | **Files**: 1 new, 1 modified, 0 deleted
**Build**: `python3 -c "pass"`
**Sources**: tasks.md@3c1302a4093c

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|----------|-----------------------------|----------------------|--------|-------|
| 014 D1 — one report object | the three sums share a row set and would otherwise be read three times | three free functions | plan.md | T001, T002 |

## Requirements Reference

- **FR-001**: a report states the total, the count and the widths of the rows it rendered.
- **FR-002**: the legacy renderer keeps its signature.

## Implementation Order

```
T001 -> T002 -> T003 -> T004 -> T005
```

## Phase 1

### T001: Create `pkg/report.py`

**File**: `pkg/report.py` (new)

**Requirements**: FR-001

**Why**: The three sums share one row set, so reading it once and asking three questions
of it is cheaper than three passes — and the cost only matters because the caller reports
per merchant.

```python
class Report:
    def total(self, rows):
        raise NotImplementedError(
            "T001: sum the rendered rows, and decide there what an unrendered row "
            "contributes; count, widest and narrowest all inherit that answer "
            "(014 FR-001)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T002: Add `count` beside T001's marker

**File**: `pkg/report.py` (modify)

**Requirements**: FR-001

**Why**: A count that disagrees with the total is the bug this pair exists to make
visible, so the two live next to each other.

**Before** (lines 1-7):

```python
class Report:
    def total(self, rows):
        raise NotImplementedError(
            "T001: sum the rendered rows, and decide there what an unrendered row "
            "contributes; count, widest and narrowest all inherit that answer "
            "(014 FR-001)."
        )
```

**After**:

```python
class Report:
    def total(self, rows):
        raise NotImplementedError(
            "T001: sum the rendered rows, and decide there what an unrendered row "
            "contributes; count, widest and narrowest all inherit that answer "
            "(014 FR-001)."
        )

    def count(self, rows):
        raise NotImplementedError(
            "T002: how many rows rendered, under the same rule you chose in T001 "
            "(014 FR-001)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T003: Add `widest` beside T001's marker

**File**: `pkg/report.py` (modify)

**Requirements**: FR-001

**Why**: The width questions are a pair and belong beside the total, whose rendering
rule they inherit.

**Before** (lines 1-7):

```python
class Report:
    def total(self, rows):
        raise NotImplementedError(
            "T001: sum the rendered rows, and decide there what an unrendered row "
            "contributes; count, widest and narrowest all inherit that answer "
            "(014 FR-001)."
        )
```

**After**:

```python
class Report:
    def total(self, rows):
        raise NotImplementedError(
            "T001: sum the rendered rows, and decide there what an unrendered row "
            "contributes; count, widest and narrowest all inherit that answer "
            "(014 FR-001)."
        )

    def widest(self, rows):
        raise NotImplementedError(
            "T003: the widest rendered row, measured the way the renderer measures "
            "(014 FR-001)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T004: Add `narrowest` beside T001's marker

**File**: `pkg/report.py` (modify)

**Requirements**: FR-001

**Why**: The other half of the pair, kept separate so the empty-row-set answer can differ
between them without one hiding the other.

**Before** (lines 1-7):

```python
class Report:
    def total(self, rows):
        raise NotImplementedError(
            "T001: sum the rendered rows, and decide there what an unrendered row "
            "contributes; count, widest and narrowest all inherit that answer "
            "(014 FR-001)."
        )
```

**After**:

```python
class Report:
    def total(self, rows):
        raise NotImplementedError(
            "T001: sum the rendered rows, and decide there what an unrendered row "
            "contributes; count, widest and narrowest all inherit that answer "
            "(014 FR-001)."
        )

    def narrowest(self, rows):
        raise NotImplementedError(
            "T004: the narrowest rendered row; an empty row set is a decision, not an "
            "error (014 FR-001)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T005: Modify `pkg/legacy.py`

**File**: `pkg/legacy.py` (modify)

**Requirements**: FR-002

**Why**: The legacy renderer keeps its signature and grows one seam, so its callers do
not move and the report can be built beside it rather than through it.

**Before** (lines 1-11):

```python
def render(rows):
    # moved verbatim from the old module
    if not rows:
        return ""
    return ",".join(rows)


def width(rows):
    raise NotImplementedError(
        "an earlier feature left this one, and its message names no task at all"
    )
```

**After**:

```python
def render(rows):
    # moved verbatim from the old module
    if not rows:
        return ""
    return ",".join(rows)


def width(rows):
    raise NotImplementedError(
        "an earlier feature left this one, and its message names no task at all"
    )


def report(rows):
    raise NotImplementedError(
        "T005: hand the rows to Report and return what it says, without rendering "
        "them a second time (014 FR-002)."
    )
```

**Verification**:

```bash
# ... the rest of the suite is not this task's business
python3 -c "pass"
```

---

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [ ] T001: create `pkg/report.py`
- [ ] T002: add `count`
- [ ] T003: add `widest`
- [ ] T004: add `narrowest`
- [ ] T005: modify `pkg/legacy.py`
