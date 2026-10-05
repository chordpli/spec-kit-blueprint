// A documentation task checks its document, not bare CLI usage exit status.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const readme = await readFile('README.md', 'utf8');
assert.match(readme, /node bin\/ledger\.js history --file/);
assert.match(readme, /read.only/i);
assert.match(readme, /limit.*20|20.*limit/i);
console.log('PASS: documented history invocation, read-only contract and default limit');
