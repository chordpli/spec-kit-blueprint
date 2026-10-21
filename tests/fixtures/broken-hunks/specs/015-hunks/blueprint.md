# Blueprint: Every way a hunk can be wrong

**Branch**: `015-hunks` | **Date**: 2026-01-01
**Mode**: scaffold — full code for every task; declared-new files are written to disk
**Total Tasks**: 7 | **Files**: 0 new, 2 modified, 0 deleted
**Build**: `python3 -c "pass"`

Nine of the checks in section 3 are failures, and until this fixture existed not one of
them had ever fired inside the corpus. A check that has never been observed to speak can
be deleted, downgraded or quietly broken and the corpus will report `ok`. Every task here
carries exactly one defect, so a change to any one check moves exactly one line.

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|----------|-----------------------------|----------------------|--------|-------|
| 015 D1 — one defect per task | a fixture where two checks fire on one task cannot say which one changed | one big broken task | plan.md | T001 |

## Requirements Reference

- **FR-001**: the arithmetic helpers keep their signatures.

## Implementation Order

```
T001 -> T002 -> T003 -> T004 -> T005 -> T006 -> T007
```

## Phase 1

### T001: An After identical to its Before

**File**: `pkg/svc.py` (modify)

**Requirements**: FR-001

**Why**: A pair that changes nothing is not a diff, and the applier has nothing to do
with it.

**Before** (lines 9-10):

```python
def gamma(x):
    return x + 2
```

**After**:

```python
def gamma(x):
    return x + 2
```

**Verification**: `python3 -c "pass"`.

---

### T002: A Before that matches twice

**File**: `pkg/svc.py` (modify)

**Requirements**: FR-001

**Why**: The quoted region occurs in both `alpha` and `beta`, so there is no single place
to put the change.

**Before** (lines 2-2):

```python
    return x + 1
```

**After**:

```python
    return x + 3
```

**Verification**: `python3 -c "pass"`.

---

### T003: A Before that is not in the file

**File**: `pkg/svc.py` (modify)

**Requirements**: FR-001

**Why**: The quoted text was never in this file, so nothing can anchor to it.

**Before** (lines 1-2):

```python
def delta(x):
    return x - 1
```

**After**:

```python
def delta(x):
    return x - 2
```

**Verification**: `python3 -c "pass"`.

---

### T004: A Before with no After

**File**: `pkg/svc.py` (modify)

**Requirements**: FR-001

**Why**: A dangling Before must not pair with the next task's After.

**Before** (lines 5-6):

```python
def beta(x):
    return x + 1
```

**Verification**: `python3 -c "pass"`.

---

### T005: A modify file that is not in the tree

**File**: `pkg/absent.py` (modify)

**Requirements**: FR-001

**Why**: A path typo in a `(modify)` declaration used to pass every document check,
because every check that reads the file skipped it quietly.

**Verification**: `python3 -c "pass"`.

---

### T006: A block labelled with a path the task does not declare

**File**: `pkg/svc.py` (modify)

**Requirements**: FR-001

**Why**: Following the label wrote the block to a path the task never declared, which put
a file back after the sweep had removed it.

**`pkg/elsewhere.py`**

```python
def epsilon(x):
    return x + 4
```

**Verification**: `python3 -c "pass"`.

---

### T007: A block anchored to nothing

**File**: `pkg/svc.py` (modify)

**Requirements**: FR-001

**Why**: "Append this at the end of the file" reads fine and is not a position, so the
applier cannot place it.

```python
def zeta(x):
    return x + 5
```

**Verification**: `python3 -c "pass"`.

---

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [ ] T001: identical pair
- [ ] T002: ambiguous anchor
- [ ] T003: absent Before
- [ ] T004: dangling Before
- [ ] T005: absent modify file
- [ ] T006: mislabelled block
- [ ] T007: unanchored block
