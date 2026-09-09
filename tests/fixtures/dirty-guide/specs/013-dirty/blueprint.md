# Blueprint: One document that trips the checks

**Branch**: `013-dirty` | **Date**: 2026-01-01
**Mode**: guide scaffold — signatures, Why, implementation notes and pitfalls; every body with behavior is a not-implemented marker; declared-new files are written to disk as skeletons
**Total Tasks**: 7 | **Files**: 3 new, 2 modified, 0 deleted
**Build**: `python3 -c "pass"`
**Sources**: tasks.md@000000deadbe

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|----------|-----------------------------|----------------------|--------|-------|
| D1 — one renderer | the callers already share a shape | two renderers | plan.md | T001, T002 |

## Requirements Reference

- **FR-001**: rows render in the order given.
- **FR-002**: the total counts only rows that rendered.

## Implementation Order

```
T001 -> T002 -> T003 -> T004 -> T005 -> T006 -> T007
```

## Phase 1

### T001: Create `pkg/one.py` and `pkg/two.py`

**File**: `pkg/one.py` (new), `pkg/two.py` (new)

**Requirements**: FR-001

**Why**: Two seams arrive together because the second is meaningless without the first,
and splitting them across tasks would leave a half hour where neither compiles.

```python
class One:
    # moved verbatim from the old module
    def render(self, rows):
        # ...
        raise NotImplementedError(
            "T001: render rows in the order given, without sorting them (013 FR-001)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T002: Modify `pkg/legacy.py`

**File**: `pkg/legacy.py` (modify), `pkg/one.py` (modify)

**Requirements**: FR-002

**Why**: The legacy renderer keeps its signature and grows a counter beside it, so the
callers do not move.

**Before** (lines 1-3):

```python
def render(rows):
    """Render rows."""
    # ... rest of file
```

**After**:

```python
def render(rows):
    """Render rows."""
    raise NotImplementedError(
        "T002: render through One rather than joining here (013 FR-002)."
    )
```

**Verification**: `python3 -c "pass"`.

---

### T003: Modify `pkg/one.py` beside T001's marker

**File**: `pkg/one.py` (modify)

**Requirements**: FR-001

**Why**: A second seam on the same class, quoting the first task's marker as context.

**Before** (lines 2-5):

```python
    def render(self, rows):
        raise NotImplementedError(
            "T001: render rows in the order given, without sorting them (013 FR-001)."
        )
```

**After**:

```python
    def render(self, rows):
        raise NotImplementedError(
            "T001: render rows in the order given, without sorting them (013 FR-001)."
        )

    def width(self):
        if self.rows:
            raise NotImplementedError(
                "T003: report the widest rendered row (013 FR-001)."
            )
```

**Verification**: `python3 -c "pass"`.

---

### T004: Modify `pkg/one.py` again

**File**: `pkg/one.py` (modify)

**Requirements**: FR-001

**Why**: A third seam, again quoting the first task's marker as the context above it.

**Before** (lines 2-5):

```python
    def render(self, rows):
        raise NotImplementedError(
            "T001: render rows in the order given, without sorting them (013 FR-001)."
        )
```

**After**:

```python
    def render(self, rows):
        raise NotImplementedError(
            "T001: render rows in the order given, without sorting them (013 FR-001)."
        )

    def height(self):
        raise NotImplementedError(
            "T004: report how many rows rendered (013 FR-001)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T005: Modify `pkg/one.py` a third time

**File**: `pkg/one.py` (modify)

**Requirements**: FR-002

**Why**: The last seam, quoting the same context one more time.

**Before** (lines 2-5):

```python
    def render(self, rows):
        raise NotImplementedError(
            "T001: render rows in the order given, without sorting them (013 FR-001)."
        )
```

**After**:

```python
    def render(self, rows):
        raise NotImplementedError(
            "T001: render rows in the order given, without sorting them (013 FR-001)."
        )

    def area(self):
        raise NotImplementedError(
            "no task id here on purpose — the message never says which task owns it."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T006: Modify `pkg/wrapped.py`

**File**: `pkg/wrapped.py` (modify)

**Requirements**: FR-002

**Why**: One of the two seams goes away, which is legitimate — and the hunk therefore
returns one closing paren fewer than it quoted.

**Before** (lines 1-10):

```python
def one():
    raise NotImplementedError(
        "an old marker an earlier feature left here"
    )


def two():
    raise NotImplementedError(
        "and its neighbour, left at the same time"
    )
```

**After**:

```python
def one():
    raise NotImplementedError(
        "T006: fold what two() did into one(), and decide there what an empty input "
        "means (013 FR-002)."
    )
```

**Verification**: `python3 -c "pass"`.

---

### T007: Create `pkg/report_service.py`

**File**: `pkg/report_service.py` (new)

**Requirements**: FR-001

**Why**: The renderer's caller needs a seam it can stub, and a service is the shape the
rest of this package already uses.

```python
class ReportService:
    def run(self, rows):
        raise NotImplementedError(
            "T007: render through One and report what it produced (013 FR-001)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T007: Create `pkg/report_service.py` (the second half)

**File**: `pkg/report_service.py` (modify)

**Requirements**: FR-001

**Why**: Written as a second section under the same id — one task, two headings, which is
the shape check [1] exists to refuse.

**Verification**: `python3 -c "pass"`.

---

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [ ] T001: create `pkg/one.py` and `pkg/two.py`
- [ ] T002: modify `pkg/legacy.py`
- [ ] T003: add `width`
- [ ] T004: add `height`
- [ ] T005: add `area`
- [ ] T006: fold `two` into `one`
- [ ] T007: create `pkg/report_service.py`
