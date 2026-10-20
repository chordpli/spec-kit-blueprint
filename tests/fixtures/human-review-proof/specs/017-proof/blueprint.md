# Blueprint: What each task's proof measured

**Branch**: `017-proof` | **Date**: 2026-01-01
**Mode**: guide — signatures, Why, implementation notes and pitfalls; every body with behavior is a not-implemented marker
**Total Tasks**: 4 | **Files**: 2 new, 2 modified, 0 deleted
**Build**: `python3 -c "import pkg.store"`
**Sources**: tasks.md@47565ba0e3d8

## Requirements Reference

- **FR-001**: a record is stored under its key.
- **FR-002**: the command reports how many records it wrote.
- **FR-003**: the README shows the command.

## Implementation Order

```
T001 -> T002 -> T003 -> T004
```

## Phase 1

### T001: Create `pkg/store.py`

**File**: `pkg/store.py` (new)

**Requirements**: FR-001

**Why**: One entry point owns the write (017 FR-001).

```python
class Store:
    def put(self, key, record):
        raise NotImplementedError("T001: store record under key (017 FR-001).")
```

**Verification**: `python3 -c "import pkg.store"`

### T002: Report the count in `pkg/cli.py`

**File**: `pkg/cli.py` (modify)

**Requirements**: FR-002

**Why**: The command, not the store, knows how many calls made up a run (017 FR-002).

**Before** (lines 1-2):

```python
def main(argv):
    return 0
```

**After**:

```python
def main(argv):
    raise NotImplementedError("T002: write each record and report the count (017 FR-002).")
    return 0
```

**Verification**: `python3 -c "import pkg.cli"`

### T003: Test the count in `tests/test_cli.py`

**File**: `tests/test_cli.py` (new)

**Requirements**: FR-002

**Why**: The count is the observable contract (017 FR-002). Its Verification below is the
same command T002 names, which proves the module imports and nothing about this test file.

```python
import unittest


class CliTest(unittest.TestCase):
    def test_reports_count(self):
        raise NotImplementedError("T003: assert main reports two writes for two records (017 FR-002).")
```

**Verification**: `python3 -c "import pkg.cli"`

### T004: Document the command in `README.md`

**File**: `README.md` (modify)

**Requirements**: FR-003

**Why**: Operators read the README before the code (017 FR-003).

**Verification**: Human review: confirm README shows `python3 -m pkg.missing --help` and the count it prints.

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [ ] T001: create `pkg/store.py`
- [ ] T002: report the count in `pkg/cli.py`
- [ ] T003: test the count
- [ ] T004: document the command
