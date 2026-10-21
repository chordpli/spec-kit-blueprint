# Blueprint: Declaration forms on disk

**Branch**: `018-forms` | **Date**: 2026-01-01
**Mode**: guide — signatures, Why, implementation notes and pitfalls; every body with behavior is a not-implemented marker
**Total Tasks**: 2 | **Files**: 2 new, 0 modified, 0 deleted
**Build**: `python3 -c "print('no build')"`
**Sources**: tasks.md@1a3c6c8d8c67

## Requirements Reference

- **FR-001**: a value is doubled, tripled or halved on request.
- **FR-002**: a value is negated.

## Implementation Order

```
T001 -> T002
```

## Phase 1

### T001: Create `src/forms.js`

**File**: `src/forms.js` (new)

**Requirements**: FR-001

**Why**: Three small functions, one per factor, so a caller names the operation it wants (018 FR-001).

```javascript
export function doubled(value) {
  throw new Error("T001: return twice the value (018 FR-001).");
}

export function tripled(value) {
  throw new Error("T001: return three times the value (018 FR-001).");
}

export function halved(value) {
  throw new Error("T001: return half the value (018 FR-001).");
}
```

**Verification**: `python3 -c "print('forms')"`

### T002: Create `pkg/kept.py`

**File**: `pkg/kept.py` (new)

**Requirements**: FR-002

**Why**: Negation lives beside its inverse check so both read the same sign rule (018 FR-002).

```python
def negated(value):
    raise NotImplementedError("T002: return the value with its sign flipped (018 FR-002).")


def is_negative(value):
    raise NotImplementedError("T002: say whether the value is below zero (018 FR-002).")
```

**Verification**: `python3 -c "print('kept')"`

## Open Questions

| # | Question | Blocking? |
|---|----------|-----------|
| — | none | no |

## Checklist

- [X] T001: create `src/forms.js`
- [X] T002: create `pkg/kept.py`
