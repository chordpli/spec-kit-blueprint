// Example acceptance oracle with named cases, from the R17 guru ledger CSV export prototype.
// It lives in the feature directory (specs/NNN-feature/acceptance.mjs), beside the blueprint,
// and each task's Verification runs the cases it owns:
//   node specs/003-transfer-history-csv/acceptance.mjs library
//   node specs/003-transfer-history-csv/acceptance.mjs cli compat readonly
// Cases: library, cli, errors, compat, readonly. Unknown case names fail. Adapt the fixture
// and expectations to the next feature's spec; do not reuse ledger values blindly.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, statSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const CASES = ['library', 'cli', 'errors', 'compat', 'readonly'];
const wanted = process.argv.slice(2);
assert.ok(wanted.length > 0, `name at least one case: ${CASES.join(', ')}`);
for (const c of wanted) assert.ok(CASES.includes(c), `unknown case ${c}`);
const root = process.cwd();
const dir = mkdtempSync(join(tmpdir(), 'ledger-csv-'));
try {
 const file = join(dir, 'ledger.json');
 const header = 'requestId,from,to,amount,fromBalance,toBalance\r\n';
 const rows = [
  { requestId: 'a', from: 'alice', to: 'bob', amount: 7, fromBalance: 93, toBalance: 7 },
  { requestId: 'b,"\r\n', from: 'x\ry', to: 'z\nw', amount: 3, fromBalance: 9, toBalance: 12 },
  { requestId: 'c', from: 'bob', to: 'alice', amount: 2, fromBalance: 5, toBalance: 95 },
 ];
 const ledger = { version: 1, accounts: { alice: 95, bob: 5 }, requests: Object.fromEntries([rows[2], rows[1], rows[0]].map(r => [r.requestId, r])) };
 writeFileSync(file, JSON.stringify(ledger));
 const bytes = readFileSync(file); const meta = statSync(file); const names = readdirSync(dir);
 const csv = header + 'a,alice,bob,7,93,7\r\n"b,""\r\n","x\ry","z\nw",3,9,12\r\nc,bob,alice,2,5,95\r\n';
 const cli = (...args) => spawnSync(process.execPath, ['bin/ledger.js', 'history', '--file', file, ...args], { encoding: 'utf8' });
 const assertCli = (args, expected) => { const r=cli(...args); assert.equal(r.status,0,'valid CLI exit'); assert.equal(r.stderr,'','valid CLI stderr'); assert.equal(r.stdout,expected,'exact output bytes'); };
 const cases = {
  async library() {
   const module = await import(pathToFileURL(join(root, 'src/ledger.js')));
   assert.equal(typeof module.exportTransferHistoryCsv,'function','public exporter');
   const frozen = structuredClone(ledger);
   Object.values(frozen.requests).forEach(Object.freeze); Object.freeze(frozen.requests); Object.freeze(frozen.accounts); Object.freeze(frozen);
   const query=Object.freeze({account:'alice',after:'a',limit:1});
   assert.equal(module.exportTransferHistoryCsv(frozen,query),header+'c,bob,alice,2,5,95\r\n');
   assert.equal(module.exportTransferHistoryCsv(frozen),csv);
   assert.equal(JSON.stringify(frozen),bytes.toString());
   for (const q of [null,[],{limit:0},{limit:101},{limit:1.5},{account:1},{after:1}]) assert.throws(()=>module.exportTransferHistoryCsv(frozen,q),e=>e.code==='INVALID_HISTORY');
   const many={version:1,accounts:{alice:1000,bob:0},requests:{}};
   for(let n=0;n<101;n++){const id=String(n).padStart(3,'0');many.requests[id]={requestId:id,from:'alice',to:'bob',amount:1,fromBalance:999-n,toBalance:n+1};}
   assert.equal(module.exportTransferHistoryCsv(many).split('\r\n').length,22,'default20');
   assert.equal(module.exportTransferHistoryCsv(many,{limit:1}),header+'000,alice,bob,1,999,1\r\n');
   assert.equal(module.exportTransferHistoryCsv(many,{limit:100}).split('\r\n').length,102,'limit100');
  },
  async cli() {
   // Generation red control: the history command before this feature rejects --format csv.
   assertCli(['--format','csv'],csv);
   assertCli(['--format','csv','--account','alice','--after','a','--limit','1'],header+'c,bob,alice,2,5,95\r\n');
   assertCli(['--format','csv','--account','nobody'],header);
   const {main}=await import(pathToFileURL(join(root, 'src/cli.js')));let written='';const errors=[];
   assert.equal(await main(['history','--file',file,'--format','csv'],{write:s=>{written+=s;},log:()=>assert.fail('CSV must use write'),error:s=>errors.push(s)}),0);
   assert.equal(written,csv);assert.deepEqual(errors,[]);
  },
  async errors() {
   for(const args of [['--format','xml'],['--format'],['--format','csv','--format','json']]){
    const r=spawnSync(process.execPath,['bin/ledger.js','history','--file',join(dir,'absent.json'),...args],{encoding:'utf8'});
    assert.equal(r.status,2,'format error exit');assert.equal(r.stdout,'');assert.deepEqual(JSON.parse(r.stderr),{error:'INVALID_FORMAT',message:'format must be json or csv'});
   }
   for(const limit of ['0','101','bad']){const r=cli('--format','csv','--limit',limit);assert.equal(r.status,2,'limit error exit');assert.equal(r.stdout,'');assert.notEqual(r.stderr,'');}
  },
  async compat() {
   assertCli([],JSON.stringify(rows)+'\n');
   assertCli(['--format','json'],JSON.stringify(rows)+'\n');
  },
  async readonly() {
   for (const args of [['--format','csv'],['--format','json'],[]]) cli(...args);
   assert.deepEqual(readFileSync(file),bytes,'file bytes unchanged'); const after=statSync(file);
   assert.equal(after.ino,meta.ino,'inode unchanged');assert.equal(after.mtimeMs,meta.mtimeMs,'mtime unchanged');assert.deepEqual(readdirSync(dir),names,'no sidecars');
  },
 };
 for (const c of wanted) {
  try { await cases[c](); } catch (e) { e.message = `[case ${c}] ${e.message}`; throw e; }
  console.log(`case ${c}: passed`);
 }
} finally { rmSync(dir,{recursive:true,force:true}); }
