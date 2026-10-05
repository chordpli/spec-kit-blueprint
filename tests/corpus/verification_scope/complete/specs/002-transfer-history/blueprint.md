# Blueprint: Transfer History Query

**Branch**: `002-transfer-history` | **Date**: 2026-09-30
**Mode**: guide — signatures, rationale, and safe markers; the developer writes behavior bodies
**Total Tasks**: 11 | **Files**: 1 new, 4 modified, 0 deleted
**Base**: specs/001-idempotent-transfer/blueprint.md
**Sources**: specs/002-transfer-history/tasks.md@068ddd0c467d specs/002-transfer-history/spec.md@85d19ab96d05 specs/002-transfer-history/plan.md@418ac7f2d074 specs/001-idempotent-transfer/blueprint.md@17ac2f48f18a docs/r16-verification-boundary.md@4c9501143932 | HEAD 864ad710e62e
**Build**: `npm run build`
**Test**: `node --test test/history.acceptance.test.js`
**Test Scope**: feature

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|---|---|---|---|---|
| D1 — derive from durable requests | Existing successful outcomes are the sole history source, so a read cannot drift from idempotency state. | A parallel history array duplicates data. | plan.md §D1 | T004, T006, T008 |
| D2 — request-ID ordering | Stored outcomes have no timestamp; lexical request-ID order is stable without changing feature 001's schema. | Inventing timestamps changes a completed durable contract. | plan.md §D2 | T004, T009 |
| D3 — validate and read only | Query validation precedes derivation, and no history path saves the ledger. | Persisting a query violates observable read-only behavior. | plan.md §D3 | T005–T011 |
| D4 — separate CLI grammar | History has only file/filter/cursor/limit flags. | Reusing transfer's required write flags makes the read API misleading. | plan.md §D4 | T003, T007, T010 |

## Requirements Reference

- **FR-001**: List only successful outcomes in `ledger.requests` and do not change balances or requests.
- **FR-002**: Return exactly `requestId`, `from`, `to`, `amount`, `fromBalance`, and `toBalance`, ordered ascending by `requestId`.
- **FR-003**: `account` includes records where it is either endpoint; omitted account includes all records.
- **FR-004**: `after` is exclusive; `limit` is an integer 1–100 and defaults to 20.
- **FR-005**: `ledger history --file PATH [--account ACCOUNT] [--after REQUEST_ID] [--limit COUNT]` emits one JSON array, with invalid grammar exiting 2 after usage on stderr.
- **FR-006**: Use Node.js built-ins and leave feature 001 transfer behavior unchanged.
- **SC-001**: Tests prove stable projection/order and no mutation.
- **SC-002**: Tests prove account filtering, cursor exclusivity, and limit boundaries.
- **SC-003**: CLI tests prove JSON output, invalid flags, and no file rewrite.

## Existing Contract Reference

Feature 001's ledger is `{ version: 1, accounts: Record<string, integer>, requests: Record<string, outcome> }`. Each stored outcome has `requestId`, `from`, `to`, `amount`, `fromBalance`, and `toBalance`; replay-only `replayed` is response metadata and is not a history field. `loadLedger(path)` reads the envelope, `saveLedger(path, ledger)` is the only persistence function, and `main(argv, io)` translates expected `LedgerError` instances for transfer. History must call `loadLedger` once, never `saveLedger`, and must not alter `transfer`.

## Implementation Order

```text
Base 001 complete -> (T001 || T002 || T003) -> T004 -> T005 -> (T006 || T007) -> T008 -> T009 -> T010 -> T011
```

## Phase 1: Setup

**Why this phase**: The public read contract, failing acceptance target, and documentation establish scope without changing completed transfer behavior. These independent tasks make the new feature visible while keeping its implementation absent.

### T001 [P]: Add the history-query contract and validation seam

**File**: `src/ledger.js` (modify)

**Requirements**: FR-001, FR-002, FR-004, FR-006

**Dependencies**: Base 001 T005–T010

**Why**: D3 requires invalid query inputs to fail before deriving results, while D1 forbids a second store. A loose object-shaped return was rejected because downstream CLI and test tasks need one named `listTransfers(ledger, query)` contract.

**Implementation Notes**: Accept a missing query as an empty object. Reject non-object query values, non-string supplied account/cursor values, and non-integer/out-of-range limits with `LedgerError("INVALID_HISTORY", ...)`; create that code only as an instance of the existing error class. Do not add a persisted field or timestamp.

**Pitfalls**: Do not return the stored outcome object itself: callers could mutate the ledger through the returned reference.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

### T002 [P]: Add failing history acceptance coverage

**File**: `test/history.acceptance.test.js` (new)

**Requirements**: SC-001, SC-002, SC-003

**Dependencies**: Base 001 T005, T011

**Why**: A new feature needs an observable red target before the domain function exists. The existing transfer suite was not expanded because feature 001's completed contract should remain independently meaningful.

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { listTransfers } from "../src/ledger.js";

test("history acceptance scenarios", () => {
  throw new Error("T002: add independent assertions for ordering, projection, filters, cursor, limits, CLI JSON, invalid flags, and byte-for-byte no-save behavior from spec.md SC-001 through SC-003; keep fixtures as stored successful outcomes.");
});
```

**Implementation Notes**: Keep domain fixtures in memory and use a temporary ledger file for CLI read-only assertions. Test exact projected object keys and compare the file bytes before and after each CLI query.

**Pitfalls**: Do not use `replayed` in expected history items; it is not persisted in `requests`.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

### T003 [P]: Document the history command and read-only guarantee

**File**: `README.md` (modify)

**Requirements**: FR-005, FR-006

**Dependencies**: Base 001 T004, T011

**Why**: D4 gives the command a grammar that operators need before they can use it. Documenting it beside the existing command is clearer than a separate manual that could drift.

**Implementation Notes**: State the default limit of 20, inclusive bounds 1–100, ascending request-ID order, and the exclusive cursor rule in prose. Keep transfer documentation unchanged.

**Pitfalls**: Do not promise chronological order: feature 001 has no timestamp.

**Verification**:
```bash
node --input-type=module <<'NODE'
// A documentation task checks its document, not bare CLI usage exit status.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const readme = await readFile('README.md', 'utf8');
assert.match(readme, /node bin\/ledger\.js history --file/);
assert.match(readme, /read.only/i);
assert.match(readme, /limit.*20|20.*limit/i);
console.log('PASS: documented history invocation, read-only contract and default limit');
NODE
```

**Checkpoint**: The intended public contract, acceptance target, and user-facing invocation are explicit; history behavior is not implemented.

## Phase 2: Foundational

**Why this phase**: The pure domain behavior has one deterministic pipeline before the CLI exposes it. This keeps filtering and cursor rules testable without filesystem concerns.

### T004: Define deterministic outcome projection and request-ID ordering

**File**: `src/ledger.js` (modify)

**Requirements**: FR-001, FR-002, SC-001

**Dependencies**: T001

**Why**: D1 and D2 make the durable request map the source and request ID the only available deterministic ordering key. Iteration order was rejected because it is an implementation detail that does not state a CLI contract.

**Implementation Notes**: In `listTransfers`, enumerate `Object.values(ledger.requests)`, sort by `requestId` with a comparator that returns -1, 0, or 1, then project new plain objects containing only the six FR-002 fields. Preserve the input ledger and every nested outcome.

**Pitfalls**: Do not use object insertion order or return references from `ledger.requests`.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

### T005: Validate optional query fields

**File**: `src/ledger.js` (modify)

**Requirements**: FR-003, FR-004, SC-002

**Dependencies**: T001, T004

**Why**: D3 prevents a malformed CLI value from yielding a partial result. Coercing strings such as `"01"` or decimals was rejected because the command contract calls for decimal digits representing a bounded integer.

**Implementation Notes**: Normalize omitted `account` and `after` to no filter/cursor, and omitted limit to 20. Domain callers receive an already parsed safe integer limit. Give validation errors the existing `LedgerError` shape so CLI error treatment remains consistent.

**Pitfalls**: `after` is exclusive, not inclusive; account matching is endpoint membership, not a substring search.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

**Checkpoint**: A valid query can be evaluated as a pure read without changing the ledger object.

## Phase 3: User Story 1 - Inspect recorded transfers (Priority: P1)

**Why this phase**: The first story makes the durable record observable without adding state or disturbing transfer. Its test establishes both response shape and read-only behavior.

### T006 [US1]: Implement all-history derivation

**File**: `src/ledger.js` (modify)

**Requirements**: FR-001, FR-002, SC-001

**Dependencies**: T004, T005

**Why**: D1 keeps the feature a projection over completed feature 001 outcomes. A history cache was rejected because a retry could update one representation but not the other.

**Implementation Notes**: Apply the normalized query pipeline to all stored outcomes and return an array even when no requests exist. Preserve exact integer amounts and balances.

**Pitfalls**: Never call `saveLedger`, `transfer`, or mutate an outcome while answering a query.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

### T007 [US1]: Add the history CLI command and no-save path

**File**: `src/cli.js` (modify), `bin/ledger.js` (modify)

**Requirements**: FR-005, FR-006, SC-003

**Dependencies**: T001, T006

**Why**: D4 isolates a read command from transfer parsing and persistence. Sending history through transfer's parser was rejected because it requires write-specific flags and could accidentally use the save branch.

**Implementation Notes**: Add `listTransfers` to the existing ledger import. For valid history arguments, load the file once, call the pure function, `io.log(JSON.stringify(items))`, and return 0. In `bin/ledger.js`, import `main`, invoke it with `process.argv.slice(2)`, set `process.exitCode` to its result, and route rejected errors to stderr with exit 1. Keep the transfer branch byte-for-byte behaviorally equivalent.

**Pitfalls**: Do not reuse `saveLedger` or emit one JSON object per item. The current entry point only imports `src/cli.js` and exits 0, so calling `main` is required for the documented command to run.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

### T008 [US1]: Prove projection, ordering, CLI output, and read-only behavior

**File**: `test/history.acceptance.test.js` (modify)

**Requirements**: SC-001, SC-003

**Dependencies**: T002, T006, T007

**Why**: FR-001 is observable only if tests compare the input ledger/file with its post-query state. A result-only test was rejected because it would miss a hidden write.

**Implementation Notes**: Assert lexical request-ID order, exact six-key item objects, `[]` for no matching outcomes, stdout's one JSON array, exit 0, and identical fixture bytes after success.

**Pitfalls**: Capture bytes before invoking the CLI; a JSON deep equality check cannot prove that the command avoided a rewrite.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

**Checkpoint**: An operator can list recorded transfers without changing the ledger file.

## Phase 4: User Story 2 - Narrow a history view (Priority: P2)

**Why this phase**: Filtering and pagination refine the same pure result stream, preserving the P1 no-mutation invariant.

### T009 [US2]: Apply account membership filtering and exclusive cursor

**File**: `src/ledger.js` (modify)

**Requirements**: FR-003, FR-004, SC-002

**Dependencies**: T006

**Why**: Filtering before limiting means a caller receives the requested number of matching results. Applying the cursor after limiting was rejected because it makes pages sparse and violates the documented ordered stream.

**Implementation Notes**: Keep an item when account equals `from` or `to`; after ordering, retain only IDs strictly greater than supplied `after`; then let T010 apply the normalized limit. Missing account/cursor means no corresponding filter.

**Pitfalls**: Do not include the cursor item itself or treat it as an error when it is absent from the stored history.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

### T010 [US2]: Apply bounded limit and command-specific flag validation

**File**: `src/cli.js` (modify)

**Requirements**: FR-004, FR-005, SC-002, SC-003

**Dependencies**: T007, T009

**Why**: D4 limits the CLI grammar to values history can use, while D3 turns invalid input into a stable usage error before loading or saving. Silently ignoring a duplicated filter was rejected because a typo could expose the wrong records.

**Implementation Notes**: Accept only `--file`, `--account`, `--after`, and `--limit`; require exactly one file and at most one of each optional flag. Validate decimal limit grammar before `Number`, then reject values outside 1–100 with the history usage and return 2.

**Pitfalls**: Do not accept transfer flags, a missing flag value, duplicate optional flags, negative values, decimals, or a zero limit.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

### T011 [US2]: Add filtering, cursor, boundary-limit, and invalid-flag coverage

**File**: `test/history.acceptance.test.js` (modify)

**Requirements**: SC-002, SC-003

**Dependencies**: T008, T009, T010

**Why**: Each filter branch changes a selection boundary but must retain the same read-only invariant. Covering only a happy page was rejected because it cannot distinguish inclusive from exclusive cursor behavior.

**Implementation Notes**: Cover sender and recipient membership, no matches, cursor equality exclusion, absent cursor acceptance, default 20, limits 1 and 100, and CLI exits 2 with usage for bad flags. Recheck fixture bytes after each CLI case.

**Pitfalls**: Keep transfer acceptance tests unchanged; these cases belong to the new feature's focused file so `--through` and direct verification remain meaningful.

**Verification**:
```bash
node --input-type=module <<'NODE'
// Run from the R14 guru ledger project: node tools/verify-transfer-history.mjs
// Assertions only: this file supplies no application implementation.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, stat, utimes } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'history-oracle-'));
try {
  const first = { requestId: 'req-01', from: 'beta', to: 'alpha', amount: 5, fromBalance: 70, toBalance: 55 };
  const second = { requestId: 'req-02', from: 'alpha', to: 'beta', amount: 10, fromBalance: 45, toBalance: 80 };
  const ledger = { version: 1, accounts: { alpha: 45, beta: 80 }, requests: { 'req-02': second, 'req-01': first } };
  const file = join(directory, 'ledger.json');
  await writeFile(file, `${JSON.stringify(ledger, null, 2)}\n`);
  // Make an identical-byte save observable too (atomic rewrite changes inode/mtime).
  await utimes(file, new Date('2000-01-01T00:00:00Z'), new Date('2000-01-01T00:00:00Z'));
  const metadata = await stat(file, { bigint: true });
  const bytes = await readFile(file);
  const result = spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, '--account', 'alpha', '--after', 'req-01', '--limit', '1'], { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `valid CLI failed: ${result.stderr}`);
  assert.equal(result.stderr, '', 'valid CLI must have empty stderr');
  assert.deepEqual(JSON.parse(result.stdout), [second], 'CLI must emit the exact filtered JSON result');
  assert.deepEqual(await readFile(file), bytes, 'read-only CLI must preserve every ledger byte');
  const after = await stat(file, { bigint: true });
  assert.equal(after.mtimeNs, metadata.mtimeNs, 'read-only CLI must not rewrite identical bytes');
  assert.equal(after.ino, metadata.ino, 'read-only CLI must not atomically replace the ledger');

  const { listTransfers } = await import(pathToFileURL(resolve('src/ledger.js')).href);
  const before = structuredClone(ledger);
  assert.deepEqual(listTransfers(ledger, {}), [first, second], 'history sorts by request ID');
  assert.deepEqual(listTransfers(ledger, { account: 'alpha', after: 'req-01', limit: 1 }), [second], 'filter and exclusive cursor precede limit');
  assert.deepEqual(listTransfers(ledger, { account: 'missing' }), [], 'absent account has no results');
  assert.throws(() => listTransfers(ledger, { limit: 0 }), error => error.code === 'INVALID_HISTORY');
  const detached = listTransfers(ledger, { limit: 1 });
  detached[0].amount = 999;
  assert.deepEqual(ledger, before, 'returned projections must be detached');
  console.log('PASS: transfer-history CLI and domain acceptance; ledger bytes unchanged');
} finally {
  await rm(directory, { recursive: true, force: true });
}
NODE
```

**Checkpoint**: Filtered and paged history is deterministic, bounded, and still read-only.

## Open Questions

None. The artifacts define a bounded read-only query and deliberately leave no schema or timestamp decision for this feature.

## Checklist

- [X] T001: Add history query contract and validation seam
- [X] T002: Add failing history acceptance coverage
- [X] T003: Document history command
- [X] T004: Define projection and ordering
- [X] T005: Validate query fields
- [X] T006: Derive all history
- [X] T007: Add history CLI command
- [X] T008: Prove P1 behavior
- [X] T009: Filter and cursor
- [X] T010: Bound limit and flags
- [X] T011: Prove P2 behavior
