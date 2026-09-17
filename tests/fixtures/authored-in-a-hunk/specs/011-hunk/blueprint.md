# Blueprint: Authored inside a hunk

**Branch**: `011-hunk` | **Date**: 2026-01-01
**Mode**: guide scaffold — signatures, Why, implementation notes and pitfalls; every body with behavior is a not-implemented marker; declared-new files are written to disk as skeletons
**Total Tasks**: 1 | **Files**: 0 new, 1 modified, 0 deleted
**Build**: `python3 -c "pass"`

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|----------|-----------------------------|----------------------|--------|-------|
| D4 — reject at the edge | the caller cannot act on a partial row | repair the row | plan.md | T001 |

## Requirements Reference

- **FR-001**: a row with a non-positive amount is rejected.

## Implementation Order

```
T001
```

## Phase 1

### T001: Modify `pkg/rows.py` to reject a non-positive amount

**File**: `pkg/rows.py` (modify)

**Requirements**: FR-001

**Why**: In guide scaffold the modify hunks are what the developer copies into the tree by
hand, so everything a check can say about this document has to reach inside them. The
lines the **After** adds below are authored here; the lines it repeats are not.

**Before** (lines 1-3):

```python
def parse(row):
    """One row in, one row out."""
    return row
```

**After**:

```python
def parse(row):
    """One row in, one row out."""
    # the rejection is decided at the edge, not repaired downstream (plan D4)
    raise NotImplementedError(
        "T001: reject the row when amount <= 0 and return it otherwise; the caller has "
        "no way to act on a partial row (011 FR-001)."
    )
    return row
```

**Verification**: `python3 -c "pass"`.

---

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [ ] T001: reject a non-positive amount in `pkg/rows.py`
