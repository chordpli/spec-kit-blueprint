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
