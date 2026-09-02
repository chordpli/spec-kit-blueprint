---
description: "Generate a pre-implementation blueprint from spec artifacts with optional file scaffolding"
---

# Blueprint Generator

## How to read this document

Steps 1, 2, 4b and 5 apply in every mode. The content rules are split by mode; read yours and skip the other:

| Mode | Read | Skip |
|------|------|------|
| `doc-only`, `scaffold` | Step 3, 3a, 3b, 3c, 3d (rules tagged for your project), Rules, Step 4 (`scaffold` only) | 3a-G |
| `guide`, `guide scaffold` | Step 3, the Before/After form in 3a (for files that change), 3a-G, 3b, 3c, 3d (rules tagged for your project), Rules, Step 4 (`guide scaffold` only) | 3a's completeness rules for full code |

This document is for whoever *generates* the blueprint. A developer who will only type from the result needs 3a-G, 3b and 3c to know what they are looking at — the README's short version — and none of the closure rules in 3d, which are the generator's checklist; the two lists differ because the two readers do.

The validators in Step 4b check the format this document asks for; the list there says what they expect, so a first blueprint can pass them without reading their source.

## Why This Exists

In AI-driven development, `/speckit.implement` can execute tasks directly — but the developer loses the chance to understand what's being built. This extension generates `blueprint.md` as a **pre-implementation blueprint** that sits between `/speckit.tasks` and `/speckit.implement`.

By typing through the blueprint, the developer:
- Learns the project's code conventions and architecture by following real examples
- Understands the structure and dependencies before code is written
- Catches design mistakes, missing edge cases, or incorrect assumptions early
- Stays code-literate even when AI handles the actual implementation

The blueprint is the single source of truth: every file, every change, every task — complete and ready to follow. And it is not just *what* to type: every task carries a **Why** — the design rationale, the decision it traces to, and what to pay attention to while typing. Code without reasons teaches nothing.

## User Input

```text
$ARGUMENTS
```

Parse the user's input for a mode keyword:

| Keyword | Mode | Behavior |
|---------|------|----------|
| _(default)_ | `doc-only` | Generate `blueprint.md` with complete code. No files created on disk. |
| `scaffold` | `scaffold` | Complete-code `blueprint.md` + create new files as scaffolds (structural files complete, core logic as TODO) |
| `guide` | `guide` | Generate `blueprint.md` with **contracts and design guidance, no body code** — signatures, Why, step-by-step implementation notes, pitfalls, references. The developer designs and types the bodies. No files created on disk. |
| `guide scaffold` | `guide-scaffold` | Guide-mode `blueprint.md` + create the same compilable skeletons on disk |

Examples:
- `/speckit.blueprint.generate` → doc-only (complete code)
- `/speckit.blueprint.generate scaffold` → complete-code blueprint + scaffold files
- `/speckit.blueprint.generate guide` → design-guidance blueprint, bodies left to the developer
- `/speckit.blueprint.generate guide scaffold` → guide blueprint + skeleton files on disk

**Choosing between full-code and guide**: `doc-only`/`scaffold` are for *reading and transcribing* a finished implementation — maximum review surface before `/speckit.implement`. `guide` is for **learning-first workflows where designing the body logic IS the learning**: the blueprint hands over everything *except* the implementation — the agreed contracts (signatures), the reasons, the invariants, the pitfalls, the references — and the developer writes the logic. Use `guide` when the project's rules say the human writes the business code (a constitution or CLAUDE.md rule), **or when the user asks for it** — the README recommends it for anyone who wants to design the bodies, and a repository with no such rule is not a reason to hand over finished code to someone who asked to write it.

> **Want full implementation?** Run `/speckit.implement` after reviewing the blueprint. The full-code blueprint is designed so that `/speckit.implement` can work entirely from `blueprint.md`. (A guide-mode blueprint is deliberately NOT sufficient for `/speckit.implement` — the bodies are the developer's work.)

## Workflow

### Step 1: Load Context

Run the prerequisites check from the repository root:

```bash
.specify/scripts/bash/check-prerequisites.sh --json --paths-only
```

If that script reports `Feature directory not found … .specify/feature.json`, the installed spec-kit resolves the feature from `.specify/feature.json` rather than the branch name; set `SPECIFY_FEATURE_DIRECTORY=specs/NNN-name` for the session, or run the specify command that writes that file. The extension's own scripts resolve the feature from the branch prefix themselves, so they are unaffected either way.

Parse `FEATURE_DIR` from the output. Then load the following spec artifacts from that directory:

- **Required**: `tasks.md`, `spec.md`, `plan.md`
- **Optional**: `data-model.md`, `contracts/` directory, `research.md`, decision records referenced by the spec/plan (e.g., `docs/decisions/`, ADRs)

If `tasks.md` is missing, abort with the message: "Run `/speckit.tasks` first."

Detect the organization of `tasks.md`. Current Spec Kit organizes tasks **by user story** (`Phase 1: Setup`, `Phase 2: Foundational`, `Phase 3+: User Story N (Priority: Pn)`, final `Polish` phase) with `[P]` parallel markers, `[US#]` story labels, and **Checkpoint** lines between phases. Older projects may use a flat Setup/Tests/Core/Integration/Polish layout. Either way: **the blueprint mirrors the exact phase structure of `tasks.md`** — never invent your own grouping.

Also read existing reference files to match project patterns:
1. For each directory that appears in `tasks.md` file paths, read 1-2 existing files in that directory to learn conventions
2. Read one example of each file type being generated (e.g., if generating a config file, read an existing config file first)
3. Limit reference reading to at most 10 files — enough to infer patterns, not enough to exhaust context

### Step 2: Extract and Categorize Files

Parse `tasks.md` to extract every file path mentioned. Check each path against disk and classify each task:

| Category | Condition | Blueprint Content |
|----------|-----------|-------------------|
| **New file** | Does not exist on disk | Full file content in blueprint |
| **Modified file** | Exists on disk, changes needed | Diff-style changes (before/after) with line references |
| **Delete file** | Task explicitly says "delete" | Deletion instruction + impact analysis |
| **Already complete** | File exists and already matches the task requirements | No code block needed — listed in Pre-completed Tasks table |

### Handling already-complete tasks

If a task's file already exists on disk and fully satisfies the task requirements (e.g., from a prior scaffolding phase), do NOT repeat the code in the blueprint body. Instead:

1. List it in a **Pre-completed Tasks** summary table at the top of each Phase
2. Mark it as `[X]` in the final Checklist
3. Keep the task ID — never merge multiple task IDs into one heading

### Step 3: Generate blueprint.md

Create `specs/{feature}/blueprint.md` with the following structure:

````markdown
# Blueprint: {Feature Name}

**Branch**: `{branch}` | **Date**: {date}
**Mode**: {doc-only|scaffold|guide|guide scaffold} — the mode token comes FIRST on this line;
any explanation follows after an em-dash. `/speckit.blueprint.validate` parses this token to decide
whether files are expected on disk.
**Total Tasks**: {count} | **Files**: {new} new, {modified} modified, {deleted} deleted
**Sources**: tasks.md@{sha12} spec.md@{sha12} plan.md@{sha12} | HEAD {short-sha}
**Build**: {the command that compiles or tests this project, from plan.md or the build files — omit the line if there is none}

## Key Decisions

| Decision | Why (rationale & trade-off) | Rejected alternative | Source | Tasks |
|----------|-----------------------------|----------------------|--------|-------|
| {Decision 1} | {Why this choice wins; what it costs} | {What was rejected and why} | {spec/plan/ADR §ref} | T{ID} |
| {Decision 2} | ... | ... | ... | T{ID}, T{ID} |

## Implementation Order

```
{Dependency graph derived from tasks.md — preserve [P] parallel markers and
user-story boundaries; show which stories can proceed independently}
```

---

## Phase N: {Phase Title — exactly as it appears in tasks.md, including story priority}

**Why this phase**: {2-4 sentences of background: what this phase delivers, why it comes now
(what it unblocks / what blocks it), and which requirement or user story it serves.
For user-story phases, restate the story's Goal and Independent Test from tasks.md.}

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T{ID}: {description} | `{path}` | Already complete — {brief reason} |

> Only include this table if the phase has already-complete tasks. Tasks listed here do NOT get a full heading or code block below.

---

### T{ID} {[P]} {[US#]}: {Task Description}

**File**: `{path/to/file}` ({new|modify|delete})

**Requirements**: FR-xxx, FR-yyy

**Dependencies**: T{prev}

**Why**: {1-4 sentences of rationale, traced to the spec artifacts: which decision or
pattern dictates this shape, what alternative was rejected and why, and — when
non-obvious — what to watch for while typing (the invariant being protected,
the failure mode being prevented).}

```{language-or-format}
{Complete file content for NEW files}
{OR diff-style before/after for MODIFIED files}
```

**Verification**: {How to verify this task is done}

---

{Repeat for each task that requires work}

**Checkpoint**: {Carry over the Checkpoint line from tasks.md at the end of each phase —
what should be independently functional/testable at this point}

## Open Questions

> Only include this section when the artifacts left something undetermined. Omit it entirely when they did not.

| # | Undecided | Blocks | Blocking? | Who can answer |
|---|-----------|--------|-----------|----------------|
| OQ-1 | {what the artifacts do not say} | T{ID}, T{ID} | yes/no | {spec owner, ADR, upstream team} |

## Checklist

- [X] T001: {description} ← already complete
- [ ] T002: {description}
- [ ] T003: {description}
...
````

### Step 3-Sources: Stamp what this blueprint was built from

A blueprint describes an intention, and it starts lying the moment its inputs move. Record what it
was generated from so that staleness is detectable instead of assumed:

- `**Sources**`: the first 12 characters of `sha256` for each artifact you read as a source of truth
  (`tasks.md`, `spec.md`, `plan.md`, plus any other you relied on), and the short commit the tree was
  at. `shasum -a 256 <file> | cut -c1-12` is enough.
- `**Build**`: the single command that checks this project's code, taken from `plan.md` or the build
  files you read in Step 1 — the applier uses it to confirm that this document's code actually works.
  Omit the line if the project genuinely has none.

  **In `guide` mode, stamp a compile or syntax check, never a test run.** Guide skeletons are
  not-implemented markers by design, so a test command fails by construction and tells you nothing.
  In a compiled language this hides itself — Kotlin's `TODO()` and Java's
  `UnsupportedOperationException` compile fine — but `python3 -m unittest` or `npm test` against
  guide skeletons is red before the developer writes a line. Stamp `python3 -m compileall src`,
  `tsc --noEmit`, `./gradlew compileKotlin` — whatever checks that the skeleton parses. The full
  test command belongs in the full-code modes, where the bodies are real.

**Regenerating**: if `blueprint.md` already exists, read it first. Keep the text of every task whose
inputs have not changed **verbatim**, rewrite only the tasks the changed artifacts touch, and end
your Step 5 report with `{kept} tasks kept, {rewritten} rewritten`. A regeneration that rewrites the
whole document produces a diff nobody can review, which in practice means the review is skipped —
and a blueprint nobody re-reads is worse than no blueprint, because it still looks authoritative.

### Step 3a: Content Rules (CRITICAL)

The blueprint is a **complete implementation blueprint**. A developer must be able to copy-paste every code block and have it work as-is (compile, run, apply, deploy — whatever "working" means for that file type).

> **ABSOLUTE RULE (full-code modes: `doc-only`, `scaffold`)**: `blueprint.md` NEVER contains `TODO`, `FIXME`, ellipsis placeholders (`// ...`, `# ...`), or any form of stub/incomplete content in any syntax. Whether scaffolds are written to disk does NOT affect the completeness of content in the blueprint itself. In `guide` mode this rule transforms: skeleton bodies are *supposed* to be not-implemented markers (see Step 3a-G) — but the guidance around them must be complete, and ellipsis abbreviation (`// ...`) is still forbidden everywhere.

**When one task covers more than one file** (a type and its enum, an entity and its repository): list every path on the `**File**:` line in the same order the blocks appear, AND label each code block with its own path immediately above it (`**`path/to/file.ext`**:`). Without the per-block label the file-to-block mapping is guesswork — a reader (or a script extracting the blueprint) will write the right content to the wrong file. Prefer one file per task; use this form only when the files are genuinely inseparable.

**For every NEW file**: Write the COMPLETE file content. Every declaration, every import, every function body must contain real, working content. No placeholders.

**For every MODIFIED file**: Show the change as before/after blocks:

````markdown
**Before** (line {N}):
```{language-or-format}
{existing content}
```

**After**:
```{language-or-format}
{new content}
```
````

**Before block rules**:
- Show the ACTUAL existing content — never abbreviate with `// ... stub` or `// ... rest of file`
- If the entire file should be replaced, write `**Replace entire file**:` followed by one code block with the full new content
- The Before block must contain enough real content for the developer to locate the exact insertion point by searching
- When a single file has multiple Before/After blocks, list them in **bottom-to-top order** (highest line number first) so applying changes sequentially does not shift earlier line references. If changes are too interleaved, use a single **Replace entire file** block instead.

**For core implementation files** (the primary logic of the project — whatever form that takes):
- Write complete implementation with all logic — no stubs, no TODO comments
- Reference requirement IDs (FR-xxx) for traceability

**For verification/test files**:
- Write complete test/verification content with real assertions and expected values
- Match the project's existing test patterns and conventions

**For configuration and infrastructure files**:
- Write complete, valid configuration — not partial snippets
- Never include real secrets — use obvious placeholders (`your-api-key-here`, `changeme`, `<REPLACE_ME>`)

### Step 3a-G: Guide Mode Content Rules

In `guide` mode, Step 3a's completeness rule applies to **guidance, not code**: every task must be implementable by the developer *without asking anything further*, but the blueprint never contains body logic. Per task:

- **Skeleton block**: one code block with the complete file skeleton — package/module declaration, imports, class/function **signatures exactly as agreed in plan/spec/contracts**, and each body as the language's canonical not-implemented form (e.g., Kotlin `TODO("...")`, Python `raise NotImplementedError("...")`, Go `panic("TODO: ...")`) whose message is a **self-contained work instruction**: what to implement, which spec section or official doc to consult, and the pitfall to avoid. Begin each message with the task ID (`T{ID}: ...`) so validation and cleanup can trace markers to tasks. The skeleton must compile/parse as written.
- **Implementation notes**: an ordered list of *what to achieve* in each body — behavior, edge cases, invariants to uphold, error handling — written as goals, never as line-by-line code dictation. Cite spec/plan/decision sections and official documentation URLs.
- **No body logic anywhere**: no branches, queries, transaction code, or assertion bodies — not in code blocks, not spelled out in prose so literally that typing it is transcription. If a body is genuinely one obvious line (a delegation, a constant), say so in the notes instead of coding it.
- **Test skeletons carry their framework**: in guide mode, test-file skeletons must include the project's real test imports and annotations (`@Test`, class-level framework annotations, fixtures wiring) exactly as the project's existing tests do — a test skeleton without its framework does not compile and fails the skeleton rule. Only the method bodies are not-implemented markers.
- **Test tasks**: name the scenarios, the fixtures/preconditions, and *what each assertion must establish* — never write the given/when/then bodies. Designing assertions is the developer's work.
- **Structural files** (schemas, config, wiring, DTO/type declarations with no logic): complete content is allowed even in guide mode — there is no design learning in transcribing a config file. Mark the boundary honestly: anything with behavior gets a skeleton, not content.
- The Why rules (Step 3b) and comment rules (Step 3c) apply unchanged — guide mode leans on them hardest.

**Guide mode and files that change.** Step 3a's Before/After form still says *where* an edit goes; in guide mode the After never carries a body. Two cases come up in every feature and both use the ordinary markers, so the applier and the validators read them without special handling:

- **One new file, several tasks.** The task that creates the file is `(new)` and carries the complete skeleton *as of that task*. Each later task that adds to it is `(modify)`: its Before quotes the smallest run of the previous skeleton that is unique in the file — usually the previous signature line alone; quoting its marker text too makes the Before long and breaks it the moment that message is edited — and its After repeats that run and adds the new signature with its marker. The developer sees the file grow the way the tasks are ordered, and the applier can type it in that order.
- **A change inside an existing body.** The body is the developer's work, so the After cannot contain it. Before quotes the lines around the spot; After is the same lines with one marker comment inserted where the change goes — `// TODO(blueprint): T0NN: <what to change and why>` in the file's comment syntax — and the implementation notes say what the change must achieve. Cleanup recognises that marker and sweeps it once the change is made.

A task that only *adds a signature* to an existing file is the first case with an existing file as the base: Before quotes the neighbouring declaration, After adds the new one with its marker.

### Step 3b: Why Rules — rationale that survives review

The **Why** blocks (per decision, per phase, per task) exist so the developer learns *reasons*, not just shapes. Rules:

- **Trace, don't invent**: Every Why must be grounded in `spec.md`, `plan.md`, `research.md`, decision records, or the project constitution. Cite the source (e.g., `plan.md §Locking`, `ADR-0007`). If no artifact explains a choice, write the honest engineering reason — never fabricate a source.
- **Name the alternative**: A rationale without a rejected alternative is a description, not a decision. Where the artifacts record what was rejected, include it; where they don't, say what the obvious alternative would have been and why it loses here.
- **State the stakes when they exist**: If the task protects an invariant (idempotency, atomicity, tenant isolation, ordering), the Why says *which* invariant and *how this code protects it*. This is what the developer must not break while typing.
- **Stay short**: 1-4 sentences per task. The Why is a lens, not an essay. If a task is genuinely mechanical (e.g., registering a route), one clause is enough — do not pad.

### Step 3c: Comment Rules — what belongs in code vs. in the blueprint

Every comment in a generated code block will be *typed into the codebase* by the developer — so only comments that deserve to live in the final code belong in code blocks:

- **Keep in code**: constraint comments the code itself cannot express — why a lock ordering exists, why a magic value was chosen, which invariant a guard protects, links to external specs. These survive cleanup because the next reader needs them.
- **Keep in the blueprint prose (NOT in code)**: narration ("now we save the order"), tutorial commentary, requirement restatements, anything explaining what the adjacent line visibly does. Put teaching text in the **Why** block or around the code block instead.
- **Scaffold-only markers**: TODO markers written to disk in scaffold mode (Step 4) MUST use the greppable form `TODO(blueprint): T{ID}: {requirement}` — the task id, a colon, then the instruction, the same shape as the executable markers' messages — one marker per unimplemented step. This lets `/speckit.blueprint.validate` verify scaffolds and `/speckit.blueprint.cleanup` find every leftover marker deterministically after implementation.

### Step 3d: Closure Rules — the blueprint must stand on its own

A blueprint fails the moment the reader has to leave it to learn *what to build*. These rules are what "self-sufficient" means concretely; they apply to every mode, and guide mode depends on them entirely.

Each rule below names the projects it applies to. A four-file CLI with no database skips the schema and classpath rules and loses nothing; read the tag before the rule.

- **Reproduce what defines behavior; cite only what explains it.** *(every project)* A table, branch matrix, state machine, or error catalog that the task must *implement* is carried inline — in the task, or in a shared reference section of the blueprint that the task links. A citation is acceptable only when deleting it would lose nothing, i.e. the blueprint prose already states the whole content. Self-check: if a task's instructions say "follow the X table" or "everything needed is in Y", X and Y must be present in this document.
- **Every symbol you name must resolve where you name it.** *(projects with modules or declared dependencies — a single-package script has one namespace and passes)* For each type the instructions tell the developer to catch, throw, call, or return, give the fully-qualified name and the module that supplies it, then check it against the target module's declared dependencies. If it is not on that module's classpath, the blueprint must include the task that adds the dependency — with whatever justification the project's rules require. Deferring a type to a later test ("the exact exception is confirmed by T0NN") is allowed only if every task that needs the type is marked as blocked on that test.
- **Simulate every port/caller pair before writing them out.** *(every project with more than one task; a port here is any function one task declares and another calls)* For each pair where one task declares a port and another consumes it: every parameter of the callee must be obtainable from the caller's declared inputs, and the call sequence the caller's instructions prescribe must be expressible with the methods that actually exist on the port. An instruction that requires an undeclared method is a defect, not developer freedom.
- **Verify every claim you make about the working tree.** *(every project)* Before blocks are verbatim quotes with correct line numbers, and the After block must actually differ from the Before — if the change cannot be expressed as a diff, give the structural instruction with no code block instead. Ripple claims must match reality: say "add this import" when there is no import to update, and name the signature changes the ripple forces on existing callers. Then read the files the blueprint sends the developer to (schema, existing adapters) and explicitly resolve any comment there that contradicts a decision in this blueprint — an unflagged contradiction sends the developer to the wrong source of truth.
- **Close the type-to-schema loop.** *(projects with a persistent schema)* Every field of every declared type maps to a column or is explicitly marked non-persistent, and every NOT NULL column of every table a task writes has a named supplier — a parameter, or a documented derivation inside a specific task.
- **Reproduce the requirements you cite, not just the design tables.** *(every project)* Every task header names requirement and acceptance-criteria ids (`FR-3.2`, `AC 4`). If their text lives only in `spec.md`, a reader working from the blueprint sees the label and never learns what it demands — the same failure as citing a design table, applied to the thing every task points at. Carry the requirement and acceptance-criteria statements the blueprint's tasks reference into a reference section of the document.
- **A forward reference must resolve.** *(every project)* When a task says a name, type, or decision "is defined in T0NN", open T0NN and confirm it is. A promise pointing at a task that never delivers is worse than an open question, because the reader stops looking.
- **What the artifacts do not decide, you do not decide either.** *(every project)* A blueprint's authority comes from the spec behind it, so a design you invented reads exactly like one that was agreed — and nothing downstream can tell them apart. When the artifacts leave a behavior, an integration, or a contract undetermined, build **to the seam and stop**: declare the port or interface the feature needs, write whatever local stand-in the spec does allow, say plainly in the task that it is a stand-in and not the real thing, and mark the task blocked. Collect every such gap in an **Open Questions** section — one row each for what is undecided, which tasks it blocks, whether it blocks the phase, and who can answer it. A named gap costs a conversation; an invented design costs the rebuild after someone ships it.
- **Close the declaration loop.** *(projects with constructor-injected collaborators; a module of plain functions has nothing to close)* Every collaborator the instructions require appears in the class's constructor parameter list and has its own task. Every type declared in one task is constructed by some task in the blueprint, or carries a label saying where it is first constructed (`declared here, first constructed in T0NN`) — an orphan type reads as an omission.

### Step 4: Optionally Create Files on Disk

Based on the mode determined in User Input. **This step is the ONLY place where TODO markers may appear (scaffold mode files on disk). The blueprint document itself is always complete.**

| Where | Core implementation | Structural / config |
|-------|--------------------|--------------------|
| `blueprint.md` | Complete — NO TODO | Complete — NO TODO |
| Scaffold files on disk | `TODO(blueprint):` stubs with requirements | Complete (same as blueprint) |

**`doc-only` / `guide`**: Skip file creation entirely. Only `blueprint.md` is written.

**`scaffold`**: For each NEW file, write to disk:
- **Structural files** (type definitions, interfaces/contracts, schemas, enums, configuration, routing/wiring): Write complete content (same as blueprint) — these are needed for other files to work
- **Core implementation files** (the files containing primary logic): Write the structure with `TODO(blueprint): T{ID}: {step-by-step requirement}` comments derived from the spec
- **Verification/test files**: Write the structure with `TODO(blueprint): T{ID}: {test scenario}` comments

**`guide-scaffold`**: For each NEW file, write the guide-mode skeleton from the blueprint to disk verbatim (structural files complete; behavioral files as compilable signature skeletons with self-contained not-implemented bodies).

Note: The scaffold files on disk are intentionally incomplete (TODO stubs). The developer references `blueprint.md` for the full implementation (full-code modes) or for the design guidance (guide mode). After implementation, `/speckit.blueprint.cleanup` sweeps any markers left behind.

**Modified files**: Never auto-edit in any mode. The blueprint provides the diff for manual or assisted application.

> **Need full file generation?** Skip this extension and run `/speckit.implement` directly — it generates complete files from your spec artifacts.

### Step 4b: Verification

Run the bundled validators rather than only re-reading your own output. A model auditing itself finds
what it was already looking for; these scripts find what it missed, and several rules below exist because
a read-through passed a blueprint the scripts then failed.

```bash
python3 .specify/extensions/blueprint/scripts/python/validate_blueprint.py "$FEATURE_DIR"
python3 .specify/extensions/blueprint/scripts/python/apply_blueprint.py "$FEATURE_DIR" --build
# scaffold modes only, right after Step 4 has written the files:
bash .specify/extensions/blueprint/scripts/bash/validate-scaffold.sh "$FEATURE_DIR" --fresh
```

The first checks the document; the second applies it to a throwaway copy of the tree and runs the
project's build, which is the only way to know that the code in here works. **Fix every failure and
run them again** — do not report a blueprint that its own validators reject. If the applier reports a
task it could not apply, that task's Before block does not match the file it claims to edit, which is
a defect in this document and not in the applier.

These are machine-checked, so they are not repeated as prose rules elsewhere: task coverage, a Why per
task, Before line references and edge anchors, multi-file labels, placeholder content, source freshness,
reproduced requirements, and open-question counts. The applier covers what the compiler knows: that
named types resolve, that calls match declarations, and that the tree still builds.

**The shapes the validators read.** Write these the way they are listed and the first run passes on
format; what remains is content.

- `**File**: `path` (new)` — one path per backticked span, its kind in parentheses right after it; a shared kind at the end of a list (`(all modify)`) covers the run before it
- `**Before** (lines N-M):` for a hunk, with the file in the label when the task declares more than one — `**Before** (`path`, lines N-M):` — or a `**`path`**:` label on the line above
- `**`path`**:` above every code block in a task that declares more than one file
- every id on a `**Requirements**:` line stated somewhere in the document, usually a Requirements Reference section
- `**Verification**:` before a block of commands, so the block is not read as file content
- `**Sources**:` and `**Build**:` in the header (Step 3-Sources)
- in guide modes: every skeleton for a file with behavior carries a marker whose message begins with the task id, and no control flow beside it

What no script can check, and what you must therefore check yourself before finalizing:

- **Secrets**: no API key, password, token, or connection string that looks real — placeholders only.
- **Guide-mode bodies**: skeleton bodies are not-implemented markers carrying self-contained
  instructions. Flag any skeleton with real body logic (branches, queries, assertions), and any marker
  message missing the what, the reference, or the pitfall when one is known.
- **Narration**: no comment inside a code block that merely restates the adjacent line (Step 3c).
- **Invention**: every task whose basis is absent from the artifacts is marked blocked and listed in
  Open Questions rather than filled with a plausible design (Step 3d).
- **Schema and declaration loops**: declared fields map to columns or are marked non-persistent; every
  NOT NULL column a task writes has a named supplier; every required collaborator appears in the
  constructor and has its own task (Step 3d).
- **Phase fidelity**: phases, order, `[P]` and `[US#]` labels, and Checkpoints match `tasks.md`.

### Step 5: Report

Output a summary:
- Path to the generated `blueprint.md`
- Mode used (`doc-only`, `scaffold`, `guide` or `guide scaffold`)
- File counts: {new} new, {modified} modified, {deleted} deleted
- If `scaffold` mode: list of files created on disk
- Suggested next step (e.g., "Review the blueprint, then run `/speckit.implement`. After implementing, run `/speckit.blueprint.cleanup` to sweep leftover scaffold markers.")

## Rules

The rules that live in a Step are stated there once and not again here: no placeholders in full-code modes and no body logic in guide modes (3a, 3a-G), one task per id and lean pre-completed tasks (Step 3), a traced Why on every task (3b), verbatim Before blocks (3a). What follows is only what no Step says.

- **Mirror tasks.md structure**: Phases, ordering, `[P]` markers, `[US#]` story labels, and Checkpoint lines come from `tasks.md` verbatim. The blueprint adds content and rationale — it never reorganizes the plan.
- **Read before generating**: Before generating content that calls or references existing modules/files, read their actual signatures and APIs from disk. Never assume interface shapes — verify against actual implementation to prevent mismatched names, parameters, or contracts.
- **Final version for multi-modified files**: If a file is modified 3 or more times across different phases, include a final consolidated version of the complete file as an appendix at the end of its last phase.
- **Dependency completeness**: When a task introduces new dependencies between modules, packages, or external libraries, include all necessary build/dependency configuration changes (build manifests, dependency declarations, module registrations) as explicit content blocks in the relevant task.
- **ZERO SECRETS**: `blueprint.md` and any files created on disk must NEVER contain real or realistic-looking secrets, passwords, API keys, tokens, or connection strings. Use obviously fake placeholders. For environment/config files with sensitive values, always use placeholder values and note that real values must be configured separately.
- **Configuration completeness**: When generated content references environment variables, config keys, or external service endpoints, the blueprint MUST include a corresponding configuration file change listing every new variable with a placeholder value and a comment explaining its purpose.
- **Migration/schema rules**: For tasks involving schema or state changes (database migrations, API version bumps, protocol changes, etc.), include both the forward change and the rollback/revert strategy where applicable. Preserve the project's naming conventions for versioned files.
- Output filename is always `blueprint.md` (lowercase)
- Follow the project's constitution and CLAUDE.md architecture rules
- Match existing patterns — read reference files before generating
- All content blocks must be complete and valid — a developer can copy-paste and it works
- Every task from `tasks.md` must appear in the blueprint — no omissions (either as a heading or in the Pre-completed table)
- Modified files show before/after diffs with line references (~{N})
- `blueprint.md` is the single source of truth — a developer should be able to implement the entire feature using only this document
- Use full file paths in all tables and headings — never abbreviate with `...`
- Follow the language used in existing spec/plan/tasks documents (do not switch languages mid-document)

## Markdown Formatting Rules

- After every bold label (`**Required changes**:`, `**Current state**:`, etc.) — add a blank line before content
- Before `**Requirements**:` — add a blank line
- Before and after every code block (```) — add a blank line
- After every `---` separator — add a blank line
- Numbered lists must have a blank line before the first item
