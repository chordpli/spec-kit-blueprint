# Blueprint: The shape the rules recommend

**Branch**: `012-clean` | **Date**: 2026-01-01
**Mode**: guide scaffold — signatures, Why, implementation notes and pitfalls; every body with behavior is a not-implemented marker; declared-new files are written to disk as skeletons
**Total Tasks**: 2 | **Files**: 1 new, 1 modified, 0 deleted
**Build**: `python3 -c "import pkg.store"`
**Sources**: tasks.md@0be5b01267fc

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|----------|-----------------------------|----------------------|--------|-------|
| D1 — the store owns validation | every writer goes through it, so one guard covers them all | validate in each caller | plan.md | T001, T002 |

## Requirements Reference

- **FR-001**: a record is stored under a key that already exists only if the caller says so.
- **FR-002**: the command reports how many records it wrote.

## Implementation Order

```
T001 -> T002
```

## Phase 1

### T001: Create `pkg/store.py`

**File**: `pkg/store.py` (new)

**Requirements**: FR-001

**Why**: Every writer goes through this one entry point, so the overwrite decision belongs
here rather than in each caller (012 plan D1). The pitfall is that the existing key check
and the write must not be two separate passes over the same mapping — a caller that reads
then writes will race with itself once this is called from more than one place.

```python
class Store:
    def put(self, key, record, overwrite):
        raise NotImplementedError(
            "T001: store the record under key, and when the key is already present "
            "honour overwrite rather than deciding for the caller; the two callers "
            "disagree about which is right, which is why it is a parameter "
            "(012 FR-001)."
        )
```

**Verification**: `python3 -c "import pkg.store"`.

---

### T002: Modify `pkg/cli.py` to report what it wrote

**File**: `pkg/cli.py` (modify)

**Requirements**: FR-002

**Why**: The count belongs to the command rather than the store, because the store does
not know whether one call or twenty made up a run (012 plan D1).

**Before** (lines 1-2):

```python
def main(argv):
    return 0
```

**After**:

```python
def main(argv):
    raise NotImplementedError(
        "T002: write each record through Store.put and report how many were written, "
        "counting a refused overwrite as not written (012 FR-002)."
    )
    return 0
```

**Verification**: `python3 -c "import pkg.cli"`.

---

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [ ] T001: create `pkg/store.py`
- [ ] T002: report the count in `pkg/cli.py`
