# Blueprint: Quoted is not authored

**Branch**: `010-quoted` | **Date**: 2026-01-01
**Mode**: guide scaffold — signatures, Why, implementation notes and pitfalls; every body with behavior is a not-implemented marker; declared-new files are written to disk as skeletons
**Total Tasks**: 4 | **Files**: 1 new, 1 modified, 0 deleted
**Build**: `python3 -c "pass"`

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|----------|-----------------------------|----------------------|--------|-------|
| D1 — one class | the smallest thing that reproduces the shape | two classes | plan.md | T001, T002 |

## Requirements Reference

- **FR-001**: compute adds two integers and refuses a negative result.
- **FR-002**: describe returns text.
- **FR-003**: the report handler keeps its existing contract.

## Implementation Order

```
T001 -> T002 -> T003 -> T004
```

## Phase 1

### T001: Create `pkg/thing.py`

**File**: `pkg/thing.py` (new)

**Requirements**: FR-001

**Why**: The adder is the feature's one behaviour, so it is the one marker. Nothing else
in this file makes a decision.

```python
class Thing:
    def compute(self, a, b):
        raise NotImplementedError(
            "T001: add a and b, and refuse a negative result — the caller treats a "
            "negative as a programming error rather than a value (010 FR-001)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T002: Modify `pkg/thing.py` to add a second seam

**File**: `pkg/thing.py` (modify)

**Requirements**: FR-002

**Why**: `describe` is a second seam on the same class, so it arrives as a second marker
beside the first. Quoting T001's marker in the Before is the shape the generate rules ask
for, and it must not read as a second author of that message.

**Before** (lines 2-6):

```python
    def compute(self, a, b):
        raise NotImplementedError(
            "T001: add a and b, and refuse a negative result — the caller treats a "
            "negative as a programming error rather than a value (010 FR-001)."
        )
```

**After**:

```python
    def compute(self, a, b):
        raise NotImplementedError(
            "T001: add a and b, and refuse a negative result — the caller treats a "
            "negative as a programming error rather than a value (010 FR-001)."
        )

    def describe(self):
        raise NotImplementedError(
            "T002: name what compute does in one sentence, in the caller's vocabulary "
            "rather than this class's (010 FR-002)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T003: Modify `pkg/thing.py` to add a third seam

**File**: `pkg/thing.py` (modify)

**Requirements**: FR-002

**Why**: A third seam, quoting T001's marker one more time. Three is the number that
matters: the repetition check fires at three tasks, so with only two quoting tasks the
fixture could not tell a correct attribution from a wrong one — the check stayed silent
either way, and the table in `tests/fixtures/README.md` claimed a protection the fixture
did not provide.

**Before** (lines 2-6):

```python
    def compute(self, a, b):
        raise NotImplementedError(
            "T001: add a and b, and refuse a negative result — the caller treats a "
            "negative as a programming error rather than a value (010 FR-001)."
        )
```

**After**:

```python
    def compute(self, a, b):
        raise NotImplementedError(
            "T001: add a and b, and refuse a negative result — the caller treats a "
            "negative as a programming error rather than a value (010 FR-001)."
        )

    def summarise(self):
        raise NotImplementedError(
            "T003: one line for a log, and decide there whether it names the operands "
            "or only the outcome (010 FR-002)."
        )
```

**Verification**: `python3 -c "pass"`.

---

### T004: Modify `pkg/report.py` — reprint the handler unchanged apart from the new call

**File**: `pkg/report.py` (modify)

**Requirements**: FR-003

**Why**: The file is short enough to reprint whole. Its existing comment cites `OQ-4`,
which the feature that wrote this file owns — this task is not the place to renumber it.

**Replace entire file**:

```python
# The response shape was settled when this handler was written (OQ-4).
def handle(request):
    return {"body": request.get("body", "")}
```

**Verification**: `python3 -c "pass"`.

---

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [ ] T001: create `pkg/thing.py`
- [ ] T002: add `describe`
- [ ] T003: add `summarise`
- [ ] T004: reprint `pkg/report.py`
