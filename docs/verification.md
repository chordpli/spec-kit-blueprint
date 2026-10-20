# Generate verification that observes acceptance

A successful process proves only that the process succeeded. For a behavior task,
write completed assertions in a fenced shell block under the task's
`**Verification**` heading, or invoke an assertion file the project already owns.
For example:

````markdown
**Verification**:
```bash
node --input-type=module <<'NODE'
import assert from 'node:assert/strict';
assert.fail('Replace this placeholder with spec-derived acceptance assertions');
NODE
```
````

The tool runs the entire fenced script fail-fast in its throwaway working-tree
copy. Guide/doc-only generation writes the blueprint, not a new helper or app file.
The assertions are complete test code, not a supplied implementation or a TODO that
passes. This Verification evidence does not change the guide-mode rule requiring
unimplemented application and application-test skeletons. Choose expected values
from the spec, not by copying the current output.

For a known valid CLI case, assert its exit status, exact parsed output, and
expected stderr. For read-only work, compare the input file bytes before and
after. A bare CLI invocation, redirected output, import, compile, or help command
is a smoke check; it cannot establish behavior completion.

## Task proof is not feature proof

`--verify` reports two axes. **Feature behavior proof** is the result of each distinct
command; the exit code is made of it. **Task proof** is what each task's own Verification
measured, and a shared command measures no single task:

- **Behavior tasks** get the oracle case for their contract. When several tasks would
  repeat one script, write a single oracle in the feature directory
  (`specs/NNN-feature/acceptance.mjs`) with a shared fixture and named cases, and map
  tasks to cases. A script copied under ten tasks fails all ten at its first assertion,
  so a half-built feature and an untouched one print the same. The
  [named-case example](examples/verification/acceptance-cases.mjs) is the prototype measured below.
- **Test-writing tasks** run the test file they write through the project's runner, plus
  a static check that the file asserts against its subject. An app oracle stays green when
  every test body is emptied; `--verify` flags a test file no command runs
  (`test bodies are unmeasured`).
- **Documentation tasks** get a static assertion on the text the spec fixes. Judgement
  goes on a line that starts with `Human review:`. Nothing on that line is executed — a
  backticked example in it is a thing to look for, not a command — and the task is listed
  as `human evidence not supplied`: counted, not failed, never passed. Record the human
  result yourself in the handoff.

Measured on the R17 guru CSV feature (886-line blueprint, one 52-line script under ten
tasks; prototype hand-converted to the form above, 398 lines plus a 78-line oracle). Same
eight trees, old and new tools: with the original form, emptied tests and a one-line
README exited 0 under both tools (the new tool now labels them shared-only, human evidence
not supplied and test bodies unmeasured instead of `passed`); with the oracle form both
exited 1 under both tools, the three app mutations still exited 1, the finished tree exited
0, and the half-built tree showed library and its tests passing with the CLI tasks red
instead of all ten red. The converted blueprint was written by hand, not by the generator.

## Exit policy for automation

Exit 1: a command failed, or under `--verify-scope feature` a selected task has neither a
command nor a `Human review:` line and no feature-scoped header covers it. Exit 2: a refused
gate. Shared-only results, human evidence not supplied and unmeasured test files never change
the exit code — exit 0 means the commands passed. A pipeline that needs per-task proof reads
the `Proof summary:` line and requires `shared-only 0`, `human evidence not supplied 0` and
`test files unmeasured 0`.

Every run prints `Repository root:`. A project copy without its own `.git` inside another
repository has that repository as its root, so its blueprint would be judged against the
enclosing project's files. All three tools refuse that run with exit 2: the feature directory
must be in the root's `specs/`. Run `git init` in the copy, or run from the root you mean.

## Reusable generation recipe

1. Identify an observable contract and a small deterministic input. State the
   expected output and forbidden side effect independently of the implementation.
2. Write the assertion block (or reuse an existing assertion artifact). Give every
   behavior task a runnable invocation;
   a feature suite may cover several tasks when its assertions name their contracts.
3. Run it against the unimplemented or half-implemented feature: record a failing
   assertion, not just an unrelated import/setup error. Do not implement the app to
   make this generation check green.
4. At implementation completion, run the same assertions there and
   record a pass. If unavailable during generation, mark the green control
   **not measured**; a new
   feature's verification is expected to remain red until implementation.
5. On isolated copies of the completed implementation, replace the CLI with a
   no-op that exits 0, add an unwanted state write, and corrupt a domain result.
   Each must fail the same assertions. Record the commands and outputs. These are
   finite controls for this contract, not automatic semantic proof.

The [Node history example](examples/verification/verify-transfer-history.mjs)
implements assertions for the R14 guru ledger project. From that project's root,
run `node /path/to/verify-transfer-history.mjs`.
For a self-contained generated blueprint, embed its assertion contents under Verification
in the Node heredoc shown above; no helper must be created in the application. It creates
its own nonempty ledger fixture, checks exact CLI JSON, empty stderr, exit 0 and
byte and inode/mtime preservation, and checks ordering, filtering, exclusive cursor, invalid
limit and detached results. It never writes application code. An empty result or
an empty app cannot satisfy this fixture. Reuse the pattern, adapting the input
and expectations to the next feature's spec; do not reuse ledger values blindly.

## Choose and report the verification boundary

Use a focused feature command in `**Test**` and optionally declare
`**Test Scope**: feature`. A whole repository suite uses `**Test Scope**: repository`.
An omitted scope is unspecified. This annotation declares the author's intended
boundary; the tool cannot prove which files a command exercises.

Default `--verify` preserves execution of Base tasks, selected tasks and the
header test. For a feature gate, use `--verify --verify-scope feature`: Base
commands and repository header tests are omitted visibly. A header without scope
is rejected (exit 2). Selected task commands run, and an explicitly feature-scoped header may cover missing
runnable task commands. No runnable proof fails this gate. Keep a repository
suite as a separate check: a red new feature should not turn a focused completed
feature's verification red. `--through` bounds selected tasks; a header suite may
still exercise more than that prefix, so report its declared scope separately.

## Record three completion states in a handoff

| State | Evidence | Guarantee |
|---|---|---|
| document-valid | document validator command and exit | document structure; no runtime behavior |
| scaffold-complete | feature `--done` command and exit | declared files/symbols and no remaining markers; no runtime behavior |
| behavior-verified | focused assertion command, exit, tested scope and unmeasured contracts | the named assertions passed against the working tree |

Record **pass**, **fail**, or **not run** for each state, with the actual command.
A checklist tick, a smoke check, and `--done` do not promote behavior-verified.
Record Base task coverage separately from selected task coverage and header suite
scope. A shared-file foreign marker remains repository debt under the conservative
`--done` policy; a focused behavior pass does not erase it.

The [tracked three-state corpus](../tests/corpus/verification_scope/README.md)
contains self-contained generated blueprints and pinned Git commits for this
controlled example. Its expected exits and app-preservation boundary are explicit.
