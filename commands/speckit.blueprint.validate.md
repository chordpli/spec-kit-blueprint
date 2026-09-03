---
description: "Check the blueprint document, apply its code to a throwaway tree, and validate scaffold files on disk"
---

# Validate Blueprint

Validate a blueprint three ways: the document holds together, the code inside it actually works, and — in scaffold mode — the right things landed on disk.

## User Input

```text
$ARGUMENTS
```

If arguments contain a directory path, use it as the feature directory. Otherwise, auto-detect from the current branch.

## Prerequisites

- `blueprint.md` must exist (run `/speckit.blueprint.generate` first)
- The applier is a **pre-implementation** tool — run it before the tasks are typed, not after
- The scaffold validator needs scaffold mode to have been used, or `--strict`

## Execution

Run all three from the repository root, in this order:

```bash
python3 .specify/extensions/blueprint/scripts/python/validate_blueprint.py "$FEATURE_DIR"
python3 .specify/extensions/blueprint/scripts/python/apply_blueprint.py "$FEATURE_DIR" --build
bash .specify/extensions/blueprint/scripts/bash/validate-scaffold.sh "$FEATURE_DIR"
```

Each answers a different question:

| Script | Question it answers |
|--------|---------------------|
| `validate_blueprint.py` | Does the document hold together? |
| `apply_blueprint.py` | Does its code actually work? |
| `validate-scaffold.sh` | Did scaffold mode put the right things on disk? |

The document validator runs in every mode — a doc-only or guide blueprint has no files on disk to check, but its own contents still have to hold up. The applier also runs in every mode, and is the only one of the three that hands the blueprint to a compiler. The scaffold validator short-circuits for the file-less modes unless you pass `--strict`.

`apply_blueprint.py` takes `--require-anchors`, which fails the run when a task's code anchors to
no position, or when nothing anchored at all. Leave it off locally — a guide blueprint of pure
instructions legitimately applies nothing — and turn it on in CI, where "verified nothing" and
"verified everything" must not share an exit code. `--build` runs a shell command, which comes from
the blueprint's own `**Build**:` line when it has one; it is printed before it runs, skipped when a
task failed to apply, and killed after 15 minutes.

The document validator's line-reference check reads the files as they are on disk. A task that cites a line an earlier task adds — the wiring T006 inserts is what T008 edits — is past the end of the file on disk, and so is every citation once you have started implementing and your files no longer match the skeleton lengths. Both are reported as a warning that names the earlier task, not as a failure; the applier is the check that settles them, because it applies the tasks in order and matches the Before text itself — and when the text matches on a different line than the Before cites, in the copy as the earlier tasks left it, the applier says so in that task's note.

`--markers` turns the scaffold validator into a listing: every blueprint marker and not-implemented call left in the files the blueprint declares, as `path:line: text`, and nothing else on stdout. It is the mechanical half of `/speckit.blueprint.cleanup`, so two runs of that command start from the same list.

A hunk the applier can neither place nor recognise, in a file that has changed since the blueprint's commit, is reported as "cannot tell" and is not counted among the tasks already in the tree: it may be implemented differently, or an earlier task may have moved its anchor, and claiming either would be a guess.

A missing or unreadable `**Mode**:` line is a warning from all three tools rather than a silent `unknown`, since the guide-mode checks and the placeholder rules hang on it. In a guide-mode blueprint a `**Build**:` command that invokes a test runner is a warning too: the skeletons throw by design. A path that merely contains the word `tests` does not count — `compileall -q pkg tests` is the compile check the spec asks a Python project to stamp.

The applier removes from its copy any file that carries a blueprint marker but that no task declares — the residue of a deleted or renamed task — and says so, so that file cannot stand in for the task the document no longer has. It also warns when a task id has more than one section, since it applies both.

Two flags say what the scaffold validator cannot see for itself. `--strict` validates files on disk even when
the blueprint records a file-less mode — for scaffolding done after generation. `--fresh` says the
scaffold has only just been written, so a file with no not-implemented marker is the mode being
broken rather than a task someone has since finished; run the validator with it immediately after
scaffolding, and without it once implementation is under way.

Where `$FEATURE_DIR` is the `specs/{feature}/` directory path. If not provided by the user, resolve it automatically:

1. Get the current git branch name
2. Extract the numeric prefix (e.g., `003` from `003-user-auth`)
3. Find the matching directory under `specs/`

All three scripts do this themselves when the argument is omitted.

## Validation Checks

### Document checks (`validate_blueprint.py`)

Format-level, so they hold for any language. Eleven numbered sections, in the order the script runs them (section 6 prints only in the guide modes, so a full-code run goes from [5] to [7]):

1. **Task coverage**: every task id declared in `tasks.md` has a section or a pre-completed row (missing `tasks.md` is a warning, not a failure); the same id with two sections is a failure
2. **Rationale (Why)**: every task section carries a `**Why**`
3. **Working-tree claims**:
   - every declared `(modify)` file is in the tree — unless an earlier task creates it — and no declared path resolves outside the repository. A wrong `(modify)` path passed sixteen checks green before this, because every check that reads the file skipped it quietly
   - a line number cited in a `**Before**` label — both ends of a range — is within the file it quotes. The file is the one named on the Before line, else the nearest `**`path`**` label above, else the task's sole `(modify)` file; a `(new)` file is never a candidate, since a hunk cannot edit a file that does not exist yet. A citation past the end of a file that an *earlier task* changes is a warning naming that task, because disk cannot settle it and the applier can; a citation past the end of any other file is a failure
   - the quoted text is where the number says it is — a Before that says line 2 over text at line 5 is a warning; the applier matches text, but the reader follows the number
   - every `**Before**` is followed by its `**After**`; a dangling Before is a failure, not a pair with the next task's After
   - every `**After**` differs from its `**Before**` — an identical pair is not a diff
   - no `**Before**` is abbreviated (`// ... rest of file`); it has to quote the file verbatim or the applier never matches it
   - no authored comment narrates the blueprint's history ("moved verbatim", "pre-existing", "unchanged from") — that sentence is for this document's reader, and cleanup never touches a doc comment, so it would stay in the code for ever. A warning
   - no `**Before**` quotes a structural line (a closing brace, `/**`, `*/`, `end`, a closing tag) more times than its `**After**` returns it — a warning, since a task that removes a block legitimately drops one
   - every task that declares a `(new)` file gives it a code block
   - a skeleton on disk that still carries its marker is the blueprint's block for it, verbatim — a warning when it is not, since the applier tests the block and the scaffold validator only counts markers
   - every `modify` task anchors its code to a position — a content block with no `**Before**`/`**After**` pair, no path label, and no `**Replace entire file**` marker is a warning, because the applier cannot place it. A block under `**Verification**` is a command, not content, and is not counted
4. **Multi-file task labels**: a task naming more than one file labels each authored code block with its path
5. **Placeholder content**: no ellipsis stubs (`// ...`, `# ...`) in any mode; in `doc-only`/`scaffold` modes, additionally no `TODO`/`FIXME`/`HACK`/`XXX` markers in code blocks
6. **Guide-mode bodies** (guide modes only): a skeleton block with any control flow beside its marker — one `if` is a method written complete beside five that kept theirs — or in a block with no marker — comments and docstrings excluded — is reported as body logic the developer was meant to write; and a new file whose name says it holds behavior (service, handler, controller, scheduler, test) whose block carries no marker at all is reported too, since the marker is what makes a skeleton a skeleton. Warnings: the boundary between a skeleton and an implementation is a judgment
7. **Regeneration**: when the committed `blueprint.md` carries the same `**Sources**` hashes, a task whose section changed anyway is a failure — regeneration keeps unchanged tasks verbatim so the diff stays reviewable
8. **Freshness**: the header's `**Sources**` stamp records each source artifact as `name@hash`; the script re-hashes those files and fails when one has changed since the blueprint was generated. No stamp at all is a warning
9. **Cited requirements reproduced**: every requirement id cited in a `**Requirements**` line (`FR-`, `NFR-`, `SC-`, `AC-`, `US-`) is also stated somewhere else in the document — a citation alone leaves a reader working from this file unable to look it up
10. **Forward references**: every task id a task's prose points at — "defined in T019", "see T019", a `**Dependencies**` entry — has a section or a pre-completed row. A promise pointing at a task that never delivers is worse than an open question, because the reader stops looking
11. **Open questions**: counts the rows of the `## Open Questions` section and how many are blocking. Only printed when that section exists, and never a failure — a blocking row is a warning

Before/After blocks are stripped before the placeholder and multi-file checks: they quote existing code, not content the blueprint authored. The abbreviation check in section 3 is the one check that reads them.

### Applying the blueprint (`apply_blueprint.py`)

The document checks read the blueprint's shape. This one reads its content: it copies the working tree into a temporary directory, types every task's code into that copy in document order, and — with `--build` — runs the project's build there. A blueprint that claims its code compiles either survives that or it does not.

The copy is a plain recursive copy, not `git worktree add`, so it needs neither a git repo nor a clean index and cannot touch your own tree. It skips `.git`, common build and dependency directories, and any bare directory name listed in `.gitignore`.

The copy starts **without this blueprint's declared-new files**. In `guide scaffold` mode the skeletons are already on disk, and a copy that kept them let the build pass over a task whose block was missing or mislabelled — the skeleton filled the hole and the compiler never saw it. A file the blueprint declares new is a file the blueprint has to supply, so those are removed from the copy before the first task is applied, and the run says how many were.

**How a task is applied**:

- A `**Before**`/`**After**` pair replaces the Before text in the target file. The match is verbatim and must be unique
- `**Replace entire file**` writes the block as the whole file
- A block introduced by a **`path`** label, or the single block of a single `(new)` file, is written as that file
- A `(delete)`-only task, a task with no `**File**:` declaration, and a block the document never anchors are all skipped and reported

**Flags**:

- `--build` — run the project's build in the copy and report its exit code. The command comes from a `**Build**: <command>` line in the blueprint header if there is one; otherwise the script picks the first of `tools/build.sh`, `gradlew`, `package.json`, `Makefile` it finds, falling back to `python3 -m unittest discover` for a tree with tests. If nothing matches, the build is skipped with a warning
- `--keep` — print the copy's path instead of deleting it, so you can inspect the applied result

**A failure on a tree at the blueprint's commit means the blueprint is wrong, not the applier.** The header's `**Sources**` line stamps that commit; on a tree that has moved past it, a Before that no longer matches in a file git says has changed is reported as implemented since, not as a failure. Applying is deterministic and unforgiving on purpose: a `**Before**` block that is not in the file verbatim, or is there twice, is reported as a defect and never repaired by guesswork. Silent repair is what lets a lossy hunk reach a reader as if it were sound. When the applier reports `T0NN FAILED`, fix that task's Before block against the real file and run it again.

**Run it before the work is done.** The applier answers a question about a tree the blueprint has not been typed into yet. Once the implementation exists, a Before block no longer matches — the file already holds the After — and the run reports those tasks as already applied. A declared-new file that is already on disk is overwritten in the copy, which is right while the tree holds scaffolds (guide-scaffold mode puts them there before implementation) and wrong once it holds the implementation: the same overwrite discards the work, and the build then describes the blueprint rather than your tree. The run says how many files it overwrote for that reason. A blueprint validated after implementation tells you nothing about the blueprint.

Exit code 1 if any task failed to apply or the build exited non-zero. Note that a run in which nothing was applied still exits 0; the script says so explicitly, and warns that the build result describes the working tree rather than the blueprint.

### Scaffold checks (`validate-scaffold.sh`)

The script reads the `**Mode**:` line from `blueprint.md` first, taking only the first two tokens. `doc-only` and `guide` write nothing to disk, so for those modes checks 1-3 run informationally — file existence is reported as a present/missing count and passes either way, and check 4 is skipped entirely. Scaffold modes (`scaffold`, `guide scaffold`) run all four. `--strict` forces the on-disk checks regardless of mode, for scaffolding done after the blueprint was generated.

1. **Blueprint Document**: verifies `blueprint.md` exists (a hard exit if not)
2. **File Existence**: all NEW files declared in the blueprint's `**File**:` lines exist on disk (placeholder/glob paths such as `docs/2026-MM-DD-*.md` are skipped)
3. **TODO Markers**: service/handler and test files among those NEW files carry a `TODO` or a language-native not-implemented marker (`NotImplementedError`, `TODO(`, `unimplemented!(`, `UnsupportedOperationException`, …), confirming they were scaffolded rather than implemented
4. **Over-Implementation Detection**: a skeleton file with no marker, more than one method and more than 30 lines is suspicious. Without `--fresh` it is a **warning**, whatever its siblings look like: a finished file is normal during implementation, and with four skeletons the first one finished already looks like "most siblings still marked". With `--fresh` it is a failure, since the caller has said nothing is implemented yet. The skeleton population is every declared-new file whose blueprint block carries a marker, plus anything the basename says is a service or a test — a controller or a scheduler written complete used to escape because its name matched nothing

## Output

All three scripts output color-coded results:

- Green checkmarks for passing checks
- Yellow warnings for non-critical issues
- Red failures for problems that must be fixed

Exit code 0 means pass (possibly with warnings), exit code 1 means failure, exit code 2 (Python scripts) means the feature directory could not be resolved.

## Troubleshooting

### "blueprint.md not found"

Run `/speckit.blueprint.generate` first. For the scaffold checks specifically, generate in `scaffold` mode.

### "N source artifact(s) changed since this blueprint was generated"

The `**Sources**` stamp no longer matches `spec.md`, `plan.md` or `tasks.md` on disk. Regenerate the blueprint, or state in the document why the difference is fine.

### "no **Sources** stamp"

The blueprint predates the stamp, so staleness cannot be checked at all. Regenerate to add one.

### "modify task has code that is not anchored to a position"

A task edits an existing file but its code block says nothing about where it goes — prose like "append this at the end" reads fine and is not a position. Quote the surrounding lines in a `**Before**` block, or mark the block `**Replace entire file**`.

### "T0NN FAILED — Before block not found verbatim"

The task's `**Before**` does not match the file it claims to edit. This is a defect in the blueprint: open the real file, copy the lines as they are, and rewrite the Before block. Do not adjust the applier.

### "Before block matches N places — the anchor is ambiguous"

The quoted region occurs more than once in the file, so there is no single place to apply it. Widen the `**Before**` block until it is unique.

### "no build command declared and none recognised"

`--build` found nothing to run. Add a `**Build**: <command>` line to the blueprint header.

### "File MISSING"

A file referenced in the blueprint was not created. Re-run `/speckit.blueprint.generate scaffold` or create the file manually.

### "NO TODO markers found"

A service or test file appears fully implemented. In scaffold mode, business logic should carry TODO markers. Check whether the file was generated outside scaffold mode — or, if the feature is already implemented, this warning is expected.
