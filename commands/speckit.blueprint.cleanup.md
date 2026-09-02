---
description: "Sweep leftover scaffold markers and stale comments after implementation"
---

# Blueprint Cleanup

## Why This Exists

Scaffold mode plants `TODO(blueprint): T{ID} ...` markers as typing guides, and implementation work often leaves other residue behind: stale TODO/FIXME notes for work that is actually done, narration comments that restate the code, and commented-out experiments. Left in place, they rot — the next reader can't tell a real debt marker from a forgotten one.

This command runs **after implementation** (`/speckit.implement` or manual typing) and sweeps that residue safely: it distinguishes markers that are *stale* (the code beneath them is implemented) from markers that are *honest* (the work is genuinely unfinished) — and it never deletes the honest ones.

## User Input

```text
$ARGUMENTS
```

| Keyword | Mode | Behavior |
|---------|------|----------|
| _(default)_ | `report` | Scan and report findings. No files edited. |
| `apply` | `apply` | Scan, report, then remove comments classified as safe-to-remove. |

A directory path in the arguments overrides the feature directory (otherwise auto-detect from the current branch, same as `/speckit.blueprint.validate`).

## Workflow

### Step 1: Determine Scope

Run the prerequisites check from the repository root:

```bash
.specify/scripts/bash/check-prerequisites.sh --json --paths-only
```

Parse `FEATURE_DIR` and load `blueprint.md` from it. If `blueprint.md` is missing, abort with: "No blueprint.md found — run `/speckit.blueprint.generate` first."

The scan scope is **the files the blueprint touches**: every NEW and MODIFIED file listed in the blueprint. Never scan the whole repository — pre-existing comments outside the feature are not this command's business.

Implementation always drifts from the plan, so extend the scope by one rule: also include files that are **not** named in the blueprint but carry a `TODO(blueprint):` marker or a marker naming one of this feature's task IDs. Report these under a separate "outside the blueprint" heading — a file the plan never mentioned is a signal the blueprint is stale, not just a cleanup target. Anything else stays out of scope.

### Step 2: Scan

For each in-scope file that exists on disk, collect every finding in these categories:

| Category | Pattern | Examples |
|----------|---------|----------|
| **Blueprint marker (comment)** | `TODO(blueprint): T{ID}` | Scaffold-mode typing guides |
| **Blueprint marker (executable)** | a not-implemented call whose message starts with a task ID — Kotlin `TODO("T012: …")`, Python `raise NotImplementedError("T012: …")`, Go `panic("T012: …")` | Guide-mode skeleton bodies |
| **Generic marker** | `TODO`, `FIXME`, `HACK`, `XXX` (comment context only) | Notes left during implementation |
| **Stub signal** | `NotImplementedError`, `throw ... NotImplemented`, empty body with placeholder comment | Unfinished logic |
| **Narration comment** | Comment that restates what the adjacent line visibly does, or copies blueprint prose/task text into the code | `// save the order`, `// Step 3: validate input` |
| **Commented-out code** | Contiguous comment block that parses as code | Dead experiments |

Match markers only inside comment syntax for the file's language — a TODO inside a string literal or test fixture data is not a finding. Blueprints touch more than one language: apply the same rules to SQL (`--`, `/* */`), shell/YAML/config (`#`), JS/TS, and templates, using each file's own comment syntax. Two language-specific cautions: a not-implemented **call** whose argument is a string (e.g. Kotlin's `TODO("…")`, which is executable code, not a comment) is a stub signal, not a comment finding — removing it changes behavior, so it is only ever UNFINISHED or replaced by the developer's implementation, never deleted by cleanup; and a `#` line in a YAML or SQL file that documents a required setting is a constraint comment, not narration.

### Step 3: Classify

For each finding, read the surrounding code and judge it:

| Verdict | Condition | Action in `apply` mode |
|---------|-----------|------------------------|
| **STALE** | Marker/stub **comment** text describes work the surrounding code already does | Remove the comment line(s) |
| **UNFINISHED** | The described work is genuinely not implemented | KEEP — report as a blocker |
| **NARRATION** | Restates visible code or duplicates blueprint prose; deleting it loses nothing | Remove |
| **KEEP** | Constraint/why comment the code cannot express (invariant, lock ordering, external spec link, chosen trade-off) | Keep — never touch |
| **UNSURE** | Cannot judge confidently from the code alone | Keep — flag for the developer |

Judgment rules:

- **When in doubt, keep.** A leftover comment is cheap; a deleted honest marker hides real debt.
- A `TODO(blueprint): T{ID}` marker is STALE only if the task's Verification criterion from `blueprint.md` is plausibly met by the code as written — check against the blueprint, not just against "code exists".
- An **executable** blueprint marker (a not-implemented call standing as a body) is UNFINISHED by definition — the body is the marker, so there is no implemented code beneath it to make it stale. Never remove one; report it as remaining work. The only exception is a marker left *beside* real code (unreachable after an early return, or a stale line above a finished body), which is a comment-shaped leftover and follows the STALE rule.
- Commented-out code is removable only when the live code clearly supersedes it; if it looks like an intentionally preserved alternative, mark UNSURE.
- Never remove license headers, annotations/pragmas, doc comments (Javadoc/KDoc/docstrings), or linter/formatter directives — these are not findings at all.

### Step 4: Report

Output a table, grouped by verdict, before touching anything:

```markdown
## Cleanup Report — {feature}

| File | Line | Category | Verdict | Comment (truncated) |
|------|------|----------|---------|---------------------|
| src/service/OrderService.kt | 42 | Blueprint marker | STALE | TODO(blueprint): T014 allocate inventory... |
| src/service/OrderService.kt | 87 | Generic marker | UNFINISHED | TODO handle partial refund |
...

**Summary**: {stale} stale, {narration} narration, {unfinished} unfinished (kept), {unsure} flagged, {keep} constraint comments untouched.
```

In `report` mode, stop here and suggest: "Run `/speckit.blueprint.cleanup apply` to remove the STALE and NARRATION findings."

### Step 5: Apply (apply mode only)

- **Take the rollback point first.** Before the first edit, copy every file you are about to touch
  to a scratch directory, keeping its relative path. `git stash` and `git checkout --` are not
  available here — the tree is usually dirty with the implementation work this command runs after,
  and reverting a file to HEAD would throw that away. The copies are what "restore the file" below
  means; delete them once the check passes.
- Remove only findings classified STALE or NARRATION. Delete the whole comment, and mind the comment's shape:
  - **Own-line comment**: delete the line, then collapse a resulting double blank line into one.
  - **Trailing comment** on a line of code: strip the comment, keep the code, drop the now-trailing whitespace.
  - **Block comment** (`/* … */`, multi-line `//` run): delete the whole block only if every line in it is part of the same finding; if a constraint line is mixed in, keep the block and remove nothing — a partially gutted block reads worse than the original.
  - Never leave dangling delimiters or an empty comment marker.
- After editing, re-run the project's quickest correctness signal (compile/build, or the test suite for the touched modules). If it fails, restore the file(s) that broke it from the copies taken above and report which removal caused the failure. If the project has **no** runnable check — or it cannot run in this environment (missing containers, no toolchain) — say so explicitly in the report instead of claiming verification; removals stay, but the report must not imply they were verified.
- Re-scan the edited files to confirm zero STALE/NARRATION findings remain.

### Step 6: Close the Loop

- If every blueprint marker for a task is gone (comment and executable alike) and its Verification criterion is met, ensure that task is checked `[X]` in the `blueprint.md` Checklist. Update it if not. If the checklist does not use `- [ ] T{ID}` rows, or `blueprint.md` is not writable, skip the update and say so in the report rather than reformatting someone else's document.
- Report UNFINISHED findings as the remaining work list — these are the honest debt the developer still owes, each with its task ID where known.

## Rules

- **Scope discipline**: only files listed in `blueprint.md`, plus files carrying this feature's blueprint/task-ID markers (reported separately). Never sweep the whole repo.
- **Report before apply**: `apply` still prints the full report first; removals must match reported verdicts exactly.
- **Never delete honest debt**: UNFINISHED and UNSURE findings are always kept and surfaced.
- **Never touch**: license headers, doc comments, annotations, pragmas, linter directives, comments in files the blueprint does not mention.
- **Verify after apply**: a cleanup that breaks the build is worse than no cleanup — run the correctness check and roll back on failure.
- Follow the language used in existing spec/plan/tasks documents when writing the report.
