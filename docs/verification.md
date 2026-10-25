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
- **Test-writing tasks** run the test file they write through the project's runner, naming
  its path on a line of its own. A test that passes proves nothing by itself: an emptied body
  passes, and so does `assert.ok(true)` with the subject's name in a comment beside it. So
  `--verify` reruns exactly the lines that name the test file on the blueprint's **skeleton**
  — the files this feature declares, restored to the stamped commit, with the blueprint
  applied over them so every declaration is in place and every body is its marker — with
  the current test file copied in. Red there and green on the tree: the test discriminates,
  and the task is passed. Green on both: `non-discriminating`, warned about and not counted
  as passed. A test file no command runs is flagged as unmeasured.
- **A test red on the whole skeleton can still be blind to its own target.** The skeleton
  undoes every task at once, so a test of the transfer limit goes red there because transfer
  itself is gone, not because the limit is. When a discriminating test task's
  `**Dependencies**` name a `(modify)` task, `--verify` runs it once more on your tree with
  only that task's regions put back: their stamped lines, except that a function or type the
  task adds keeps its declaration with the blueprint's marker body. Green there: `blind to
  their target`, warned about and not counted as passed. Putting the whole region back as the
  stamp had it took the new declarations away too, so a test that only imported one failed on
  the import and was counted as seeing the task (R20 `t3`). The test is then run once per
  region, each put back alone; regions it stays green over are listed as a hint, with their
  stamped line, and do not change the count. A region whose lines are only imports is not
  probed alone: a test that passes its own day leaves an import of the clock unused, and
  every R19 copy listed that line. Measured on the R19 guru copies: the three test
  tasks of the copy whose tests skip the limit (`t3`, `t3b`) are now named, the finished
  copy's are not. A dependency that only creates files is not probed this way — removing it
  breaks the test's import, so red there would mean nothing. The probe takes the
  `**Dependencies**` line as the test's target, but only a task whose files the test's command
  read: an honest library test whose line named the CLI task was reported blind to it (R19 ws
  004, R20 `t5`). Such a task is listed as `Not probed against a dependency the test never ran`.
- **A test that passes while the task it tests fails** is warned about and not counted as
  passed: a test that only parsed the output as JSON passed beside a statement command that
  printed `{}` (R20 `t4`). "Fails" means a red oracle case — or a failed command that names no
  case — that the target task **alone** owns. A case several tasks own, such as a
  compatibility case every task that could break it runs, is red for a reason that can be any
  owner's: held against the tests of each, it took seven honest tests out of the count on the
  R21 controls (one of them did what its task's Why said, leaving unchanged transfers to that
  shared case) and kept the two weak ones it should. A target that also has a red task among
  its own dependencies is not held against its test either: its red can be what it ran of
  theirs. Without that, R20 `m1a`, `m1b` and R21 `s04` each lost an honest CLI test to a
  library's or parser's defect.
- **What is red is stated about what ran, not about who wrote it.** A failed command is
  reported with the oracle case it stopped on — the case its error names as `[case NAME]`, or
  else the first of its cases that did not print `case NAME: passed` — and every task whose
  Verification runs that case: `movecompat (specs/007-account-freeze/acceptance.mjs): T010,
  T011, **Test** header`. A failed command that names no case is listed with its owners. A task
  owns a case because its Verification runs it; that is not where the defect is. Four releases
  tried to place defects by task — the task whose command failed, a dependency it failed
  "behind", the files its command read that other tasks wrote — and on the R21 controls, where
  three tasks share each file, the failed task held the defect in none of eight controls whose
  defect lay elsewhere, the read-file hint held it in 0 of 12, and a defective task was excused
  as failing behind a clean one. Those lines are gone. Test tasks' commands are still traced
  (the access time of each file the feature writes is set older than its modification time in
  the copy, and a read moves it), because the probes below use it; Python runs without a
  bytecode cache so imports are read from source, and so a probe that puts a region back
  within the same second is not served the cache of what it replaced.
- **Documentation tasks** get a static assertion on the text the spec fixes, and their
  example commands are run. A shell-fenced block (`sh`, `bash`, `shell`, `console`, `zsh`)
  that a doc task's After adds is a promise that the example runs. So `--verify` reads the
  shell blocks of that file **on disk** — the ones the stamped commit did not have — and runs
  each as written, in order, as a `set -e` script in a copy of its own (`$ ` lines of a
  `console` block are the commands, the rest is output). The blueprint's own block is not
  what is run: a README whose example drifted from the blueprint is what a reader types. A
  synopsis with placeholders (`ledger transfer <from> <to>`) is not a runnable example; put
  it in a `text` fence. Without the stamped commit the run is `not measured`. A tree that has
  moved past later features also runs their new blocks.
  **A transcript is compared, not only run.** In a block with `$ ` prompts, each command runs
  in one shell, in order, with stdout and stderr together, and must end 0; the lines under it
  are what it prints and must match (trailing blanks ignored). A refusal is shown that way:
  `$ cmd; echo "exit $?"` with the error and `exit 1` under it. A plain block, or a transcript
  command with nothing under it, that holds `|| echo`, `|| true`, `; true`, `set +e`, `$?` or a
  leading `!` ends 0 whatever its command did: it is warned about, not counted as a passing
  example, and its task is not counted as passed (`documentation examples masking a failure
  N`). The exit code does not change — the block ran and passed; what it proves is nothing.
  Measured on the R21 copies: a mistyped `--too` behind `|| echo` and a README "refused" line
  that succeeded both ended 0 and their task passed; now both are warned about, and the same
  READMEs written as transcripts fail on the first and pass on the finished tree.
  Judgement goes on a line that starts with `Human review:`.
  Nothing on that line is executed — a backticked example in it is a thing to look for, not
  a command. The reviewer records the review in the feature's `human-evidence.md`, one line
  per task: `T010: <reviewer> <YYYY-MM-DD> README.md@<sha>`, one `path@sha` for each file
  the task declares, the sha being `git hash-object <path>` (seven or more characters; the
  warning prints the exact line). Without it the task is `human evidence not supplied`:
  counted, not failed, never passed. When a recorded file changes, the record is `stale`
  and counts as not supplied again. A date that is not a calendar date (`9999-99-99`,
  `2026-02-30`) or lies more than one day past today in UTC makes the record `invalid`, also
  not supplied: a record from the future is a record nobody made yet, and the one day covers
  a reviewer east of UTC.

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
gate. Shared-only results, non-discriminating or target-blind test tasks, masked documentation
examples, human evidence not
supplied and unmeasured test files never change the exit code — exit 0 means the commands
passed. A pipeline that needs per-task proof reads the `Proof summary:` line and requires
`test tasks non-discriminating 0, not measured 0`, `shared-only 0`, `not supplied 0` (each
`Human review:` recorded in `human-evidence.md`), `test files unmeasured 0`,
`test tasks blind to their target 0`, `test tasks green while their target is red 0` and
`documentation examples masking a failure 0`.

Why non-discriminating is not exit 1: measured on the R18 guru feature's 22 control copies
and on 16 feature runs of three earlier projects, it fired only on the copy whose tests were
`assert.ok(true)` (six of six test tasks) and never on a finished or reformatted tree. But a
test of a structural file the skeleton writes complete, or of behavior the feature leaves
unchanged, passes on the skeleton by design, and no corpus here has one to measure the cost
on. The proof discriminates against the skeleton only: a weak test that a no-op
implementation also passes is still counted as proven — measured, a CLI test comparing
stdout to itself stayed "discriminating" on a copy whose `reverse` command returned 0 and
did nothing.

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
| scaffold-complete | feature `--done` command and exit | declared files and public symbols, no remaining markers, and every `(modify)` task changed its own regions of an existing file since the stamp, or brings names the file now has elsewhere with each non-import code line it adds (a warning); no runtime behavior |
| behavior-verified | focused assertion command, exit, tested scope and unmeasured contracts | the named assertions passed against the working tree |

Record **pass**, **fail**, or **not run** for each state, with the actual command.
A checklist tick, a smoke check, and `--done` do not promote behavior-verified.
Record Base task coverage separately from selected task coverage and header suite
scope. A shared-file foreign marker remains repository debt under the conservative
`--done` policy; a focused behavior pass does not erase it.

The [tracked three-state corpus](../tests/corpus/verification_scope/README.md)
contains self-contained generated blueprints and pinned Git commits for this
controlled example. Its expected exits and app-preservation boundary are explicit.
