# Blueprint: Idempotent Ledger Transfer

**Branch**: `main` | **Date**: 2026-09-17
**Mode**: guide scaffold — contracts and design guidance; behavioral bodies remain marked for the next developer
**Total Tasks**: 12 | **Files**: 3 new, 0 modified, 0 deleted
**Sources**: tasks.md@9e8876d7280e spec.md@c58411c781bb plan.md@9e0cb810f04d docs/r16-verification-boundary.md@4c9501143932 | HEAD b316e3f
**Build**: `npm run build`
**Test**: `node --test test/transfer.acceptance.test.js`
**Test Scope**: feature

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|---|---|---|---|---|
| D1 — integer minor units | Exact conservation matters more than decimal input convenience. | Floating-point currency can round. | plan.md §D1 | T005–T007 |
| D2 — durable outcomes | A retry must survive process restart. | An in-memory cache forgets requests. | plan.md §D2 | T008–T009 |
| D3 — validate before mutation | Every rejection must leave all state unchanged. | Rollback is fragile over plain objects. | plan.md §D3 | T006, T010 |
| D4 — atomic replacement | A successful transfer must not leave truncated JSON. | In-place writes can tear. | plan.md §D4 | T003, T011 |

## Requirements Reference

- **FR-001**: Transfer a positive integer number of minor units between distinct existing accounts while preserving the sum of balances.
- **FR-002**: Apply a request ID at most once; return the recorded success for identical input and reject changed input with `IDEMPOTENCY_CONFLICT` without mutation.
- **FR-003**: Reject a transfer exceeding the source balance with `INSUFFICIENT_FUNDS` without changing accounts or request history.
- **FR-004**: Unknown accounts, equal endpoints, and invalid amounts are validation failures without mutation.
- **FR-005**: Persist successful new transfers atomically; print stable JSON and exit 1 with JSON on expected domain failure.
- **SC-001**: Acceptance tests cover conservation, retry behavior, conflicts, and insufficient-funds non-mutation.
- **SC-002**: The command uses Node.js built-ins and a versioned JSON ledger.

## Domain and CLI Reference

The ledger is `{ version: 1, accounts: Record<string, integer>, requests: Record<string, outcome> }`. A transfer request has `requestId`, `from`, `to`, and positive integer `amount`. A recorded outcome has those four fields plus resulting `fromBalance` and `toBalance`. A replay response adds `replayed: true`; a new response uses `replayed: false`.

The command is `ledger transfer --file PATH --request ID --from ACCOUNT --to ACCOUNT --amount MINOR_UNITS`. Expected error codes are `ACCOUNT_NOT_FOUND`, `INVALID_TRANSFER`, `INSUFFICIENT_FUNDS`, and `IDEMPOTENCY_CONFLICT`.

## Implementation Order

```text
T001 -> (T002 || T003) -> T004 -> T005 -> T006 -> T007 -> T008 -> T009 -> T010 -> T011 -> T012
```

## Phase 1: Setup

**Why this phase**: The package and storage seam establish a dependency-free, loadable base before behavioral work. It supports SC-002 and protects later tasks from mixing filesystem and domain concerns.

### Pre-completed Tasks

| Task | File | Status | Why |
|---|---|---|---|
| T001: package and build gate | `package.json`, `scripts/build.mjs` | Already complete — syntax and imports load | Node built-ins satisfy SC-002 without install-time risk. |
| T002: stable domain error | `src/errors.js` | Already complete — `LedgerError` exposes code | A typed code keeps CLI output independent of message wording. |
| T003: JSON storage | `src/store.js` | Already complete — version check and atomic rename | D4 avoids partially written ledger files. |

**Checkpoint**: The project loads without external dependencies and storage can round-trip a valid ledger.

## Phase 2: Foundational

**Why this phase**: The executable seam and balance query make the repository runnable before transfer work. They provide the fixtures and compile gate needed by every story.

### Pre-completed Tasks

| Task | File | Status | Why |
|---|---|---|---|
| T004: entry point and sample | `bin/ledger.js`, `examples/ledger.json` | Already complete — executable imports CLI | The thin entry point prevents domain work from depending on process globals. |
| T005: balance lookup and baseline | `src/ledger.js`, `test/baseline.test.js` | Already complete — baseline test passes | A small passing test distinguishes a healthy harness from expected feature failures. |

**Checkpoint**: `npm run build` and the baseline test pass before transfer behavior exists.

## Phase 3: User Story 1 - Move funds safely (Priority: P1)

**Why this phase**: This phase delivers the first independently useful transfer and its conservation proof. Its independent test moves 40 from 100 to 25 and observes 60 and 65.

### T006 [US1]: Implement validated, balance-conserving transfer behavior

**File**: `src/ledger.js` (new)

**Requirements**: FR-001, FR-004

**Dependencies**: T002, T005

**Why**: D1 requires exact integer units and D3 requires every guard to finish before either balance changes. Mutating while validating was rejected because later failure would violate conservation.

```javascript
import { LedgerError } from "./errors.js";

export function balanceOf(ledger, accountId) {
  throw new Error("T005: pre-completed balance lookup is supplied by the accepted tree; this compatibility signature keeps the isolated guide application linkable.");
}

export function transfer(ledger, request) {
  throw new Error("T006: implement 001 FR-001 and FR-004 validation and balance-conserving transfer; preserve all state on every validation failure and avoid partial mutation (001 plan D1 and D3).");
}
```

**Implementation notes**:

1. Establish the ledger envelope, both account identities, distinct endpoints, and a positive safe integer amount as preconditions.
2. Preserve the sum of balances and change no unrelated account.
3. Produce the outcome fields defined in Domain and CLI Reference; leave replay policy for T008.

**Verification**: `node --test test/transfer.acceptance.test.js`

---

### T007 [US1]: Add conservation and validation scenarios

**File**: `test/transfer.acceptance.test.js` (new)

**Requirements**: FR-001, FR-004, SC-001

**Dependencies**: T006

**Why**: Conservation is the central invariant and needs observation at the public domain boundary. Testing private steps was rejected because it would permit a wrong final state.

```javascript
import assert from "node:assert/strict";
import test from "node:test";
import { transfer } from "../src/ledger.js";

test("transfer preserves the total balance", () => {
  throw new Error("T007: design the valid-transfer assertion for 001 FR-001, including exact endpoint balances and an unchanged total; avoid asserting implementation steps.");
});
```

**Implementation notes**:

1. Cover the independent-test values from User Story 1 and observe the returned outcome.
2. Add table-driven invalid request cases and assert full data non-mutation for each.

**Verification**: `node --test test/transfer.acceptance.test.js`

**Checkpoint**: A valid transfer changes only the two named balances and preserves their combined total.

## Phase 4: User Story 2 - Retry without double debit (Priority: P1)

**Why this phase**: This story makes retries safe after a caller loses a response. Its independent test submits one request twice and observes one balance change and equivalent outcomes.

### T008 [US2]: Add durable success recording and replay

**File**: `src/ledger.js` (new)

**Requirements**: FR-002

**Dependencies**: T006

**Why**: D2 records the outcome beside balances so the idempotency decision survives restart. Caching in the CLI was rejected because a second process could debit again.

```javascript
export function transfer(ledger, request) {
  throw new Error("T008: implement 001 FR-002 durable success recording, identical replay, and IDEMPOTENCY_CONFLICT for changed fields; compare the full request identity before any mutation (001 plan D2 and D3).");
}
```

**Implementation notes**:

1. Treat a stored request ID as a decision point before account validation or mutation.
2. Return the stored financial outcome for equal request fields and identify it as replayed.
3. Reject any differing request field with `LedgerError` code `IDEMPOTENCY_CONFLICT` and unchanged state.

**Verification**: `node --test test/transfer.acceptance.test.js`

---

### T009 [US2]: Add retry scenarios

**File**: `test/transfer.acceptance.test.js` (new)

**Requirements**: FR-002, SC-001

**Dependencies**: T008

**Why**: The risk is a second debit, so the test must observe balances, request history, and both outcomes. Checking only the returned flag was rejected as insufficient.

```javascript
test("an identical request is applied once", () => {
  throw new Error("T009: design identical-retry and conflict assertions for 001 FR-002; prove a single balance change and unchanged state on conflicting reuse.");
});
```

**Implementation notes**:

1. Submit one request twice against the same object and compare financial fields while checking replay status.
2. Reuse the ID with each transfer field changed in turn and prove rejection leaves state intact.

**Verification**: `node --test test/transfer.acceptance.test.js`

**Checkpoint**: Replaying identical input returns the recorded result without a second balance change.

## Phase 5: User Story 3 - Reject unaffordable transfers (Priority: P1)

**Why this phase**: The final story closes the non-mutation guarantee and exposes all domain behavior through the CLI. Its independent test attempts 11 from 10 and compares the full ledger before and after.

### T010 [US3]: Guarantee insufficient-funds rejection without mutation

**File**: `src/ledger.js` (new)

**Requirements**: FR-003

**Dependencies**: T006, T008

**Why**: D3 puts affordability before mutation so rejection needs no rollback. Recording failed requests was rejected because FR-003 requires request history to remain unchanged.

```javascript
export function transfer(ledger, request) {
  throw new Error("T010: implement 001 FR-003 insufficient-funds rejection with LedgerError code INSUFFICIENT_FUNDS; leave balances and requests unchanged and preserve the earlier replay behavior.");
}
```

**Implementation notes**:

1. Evaluate affordability only after request and account validation but before any write.
2. Keep the original ledger data structurally unchanged on rejection.

**Verification**: `node --test test/transfer.acceptance.test.js`

---

### T011 [US3]: Wire the transfer CLI

**File**: `src/cli.js` (new)

**Requirements**: FR-005, SC-002

**Dependencies**: T003, T010

**Why**: The CLI owns text parsing and persistence while `transfer` remains deterministic. Saving before domain success was rejected because expected failure must leave the file untouched.

```javascript
export async function main(argv, io = console) {
  throw new Error("T011: implement the 001 CLI Contract using loadLedger, transfer, and saveLedger; persist successful new outcomes only, emit stable JSON, and avoid writing for replay or LedgerError failure (001 plan D4).");
}
```

**Implementation notes**:

1. Require each named flag exactly once and parse the amount as a safe integer minor-unit value.
2. Load, invoke the domain operation, and save only a newly applied success.
3. Emit one JSON object through the injected output interface and translate expected errors to exit status 1.

**Verification**: `node --test test/transfer.acceptance.test.js`

---

### T012 [US3]: Complete insufficient-funds and CLI acceptance coverage

**File**: `test/transfer.acceptance.test.js` (new)

**Requirements**: FR-003, FR-005, SC-001

**Dependencies**: T010, T011

**Why**: Domain tests prove object behavior while a CLI test proves persistence and output coordination. Omitting the seam test would leave D4 and the exit contract unverified.

```javascript
test("insufficient funds changes no state", () => {
  throw new Error("T012: design 001 FR-003 and FR-005 domain and CLI assertions; prove the complete ledger and file remain unchanged on rejection and verify stable JSON and exit status.");
});
```

**Implementation notes**:

1. Deep-clone a ledger before the rejected domain call and compare every field afterward.
2. Use a temporary directory from `node:fs/promises.mkdtemp` and `node:os.tmpdir` for CLI persistence scenarios.
3. Cover successful save, replay without rewrite, and expected-error stderr/exit behavior.

**Verification**: `node --test test/transfer.acceptance.test.js`

**Checkpoint**: All acceptance tests pass and a rejected command leaves the ledger file unchanged.

## References

- Node.js test runner: https://nodejs.org/api/test.html
- Node.js filesystem promises: https://nodejs.org/api/fs.html#promises-api
- Node.js errors: https://nodejs.org/api/errors.html

## Open Questions

None. The feature artifacts close the domain, persistence, and CLI contracts; concurrent-writer locking is explicitly outside this feature.

## Checklist

- [X] T001: Create package and build gate ← already complete
- [X] T002: Define stable domain errors ← already complete
- [X] T003: Implement JSON load and atomic save ← already complete
- [X] T004: Create executable entry point and sample ledger ← already complete
- [X] T005: Implement balance lookup and baseline test ← already complete
- [X] T006: Implement validated, balance-conserving transfer
- [X] T007: Add conservation and validation scenarios
- [X] T008: Add durable success recording and replay
- [X] T009: Add retry scenarios
- [X] T010: Guarantee insufficient-funds rejection without mutation
- [X] T011: Wire transfer CLI
- [X] T012: Complete insufficient-funds and CLI acceptance coverage
