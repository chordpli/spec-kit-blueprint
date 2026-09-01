# Blueprint

Pre-implementation blueprint generator. Reads spec artifacts and produces a single `blueprint.md` with complete, ready-to-use content for every task — so you can review, understand, and type through the implementation before `/speckit.implement` runs.

![Spec Kit >= 0.2.0](https://img.shields.io/badge/spec--kit-%3E%3D0.2.0-blue)
![Version 1.1.0](https://img.shields.io/badge/version-1.2.0-green)
![License MIT](https://img.shields.io/badge/license-MIT-brightgreen)

A [Spec Kit](https://github.com/github/spec-kit) community extension.

## Workflow Position

```
/speckit.specify                        → spec.md
/speckit.clarify                        → clarifications
/speckit.plan                           → plan.md
/speckit.tasks                          → tasks.md
                                          ↓ after_tasks hook (optional)
/speckit.blueprint.generate [mode]      → blueprint.md  ★
/speckit.implement                      → code
                                          ↓ after_implement hook (optional)
/speckit.blueprint.cleanup [apply]      → comment sweep  ★
/speckit.blueprint.review               → decisions + PR list  ★
/speckit.checklist                      → verify
```

Spec Kit's core workflow goes from `tasks.md` directly to `/speckit.implement`. This extension inserts a step between them: generate a complete blueprint, review it, then implement.

## What It Does

Reads `tasks.md`, `spec.md`, `plan.md` (and optionally `data-model.md`, `contracts/`) from the feature directory and generates `blueprint.md` containing:

- Complete content for every new file — ready to copy-paste or type through
- Before/after diffs for every modified file — with exact line references
- A **Why** for every task — the rationale traced to spec/plan/decision records: which decision dictates this shape, what was rejected, and which invariant to protect while typing
- Key decisions with rationale, trade-offs, rejected alternatives, and requirement traceability (FR-xxx → Task ID)
- Phases that mirror `tasks.md` exactly — including user-story organization, `[P]`/`[US#]` labels, and Checkpoints
- A task checklist at the end

Three modes:

| Mode | Output |
|------|--------|
| `doc-only` (default) | Complete-code `blueprint.md` only — nothing written to disk |
| `scaffold` | Complete-code `blueprint.md` + new files on disk (structural files complete, core logic as TODO stubs) |
| `guide` | Design-guidance `blueprint.md` — signatures, Why, implementation notes, pitfalls, references, **no body code**. For learning-first workflows where the developer designs the logic. Add `scaffold` (`guide scaffold`) to also write compilable skeletons to disk — for **new files only**, so a feature that is mostly edits to existing files gets few files or none |

## Why

When AI writes all the code, the developer can lose familiarity with the codebase. The blueprint gives you a chance to:

- **Read the implementation before it exists** — understand what files will be created, how they connect, and what patterns they follow
- **Learn the reasons, not just the shapes** — every task explains *why* it looks the way it does, so typing through it teaches design judgment, not transcription
- **Type through it yourself** — learn the project's conventions, spot design issues, and catch incorrect assumptions before any code is committed

The blueprint persists in `specs/{feature}/` as a record of what was intended — useful for onboarding, design review, or revisiting decisions later.

## Installation

```bash
specify extension add blueprint
```

From repository directly:

```bash
specify extension add blueprint --from https://github.com/chordpli/spec-kit-blueprint/archive/refs/tags/v1.2.0.zip
```

## Usage

### Generate (doc-only)

```
/speckit.blueprint.generate
```

Produces `specs/{feature}/blueprint.md`. No files created on disk.

### Generate (scaffold)

```
/speckit.blueprint.generate scaffold
```

Produces `blueprint.md` + creates new files on disk. Structural files (type definitions, interfaces, configuration, wiring) are complete. Core implementation and test files contain TODO stubs with requirements from the spec. The developer references `blueprint.md` for the full implementation.

### Generate (guide)

```
/speckit.blueprint.generate guide
/speckit.blueprint.generate guide scaffold
```

Produces a blueprint that hands over everything *except* the implementation: agreed signatures as compilable skeletons, per-task Why, ordered implementation notes (goals, edge cases, invariants — never line-by-line code), pitfalls, and official-doc references. Body logic and test assertions are deliberately absent — designing them is the developer's work. Use this when the project's rules say the human writes the business code.

### Implement after review

```
/speckit.implement
```

`/speckit.implement` can work entirely from `blueprint.md`. Review the blueprint, then run implement.

### Validate scaffold

```
/speckit.blueprint.validate
/speckit.blueprint.validate specs/003-user-auth
```

Runs two validators: one over `blueprint.md` itself (task coverage, a Why per task, Before/After claims that hold against the working tree, multi-file label discipline, no placeholders) and one over what scaffold mode wrote to disk (files exist, TODO markers present in core files, nothing over-implemented).

The document validator runs in every mode — a doc-only or guide blueprint has nothing on disk, but its own contents still have to hold up.

Exit code `0` = pass. Exit code `1` = failure.

### Clean up after implementation

```
/speckit.blueprint.cleanup
/speckit.blueprint.cleanup apply
```

After `/speckit.implement` (or manual typing), sweeps residue from the files the blueprint touches: stale `TODO(blueprint):` markers whose code is already implemented, narration comments that restate the code, and dead commented-out code. Report-only by default; `apply` removes what the report classifies as safe. Genuinely unfinished markers are never deleted — they are surfaced as the remaining work list.

## Choosing a mode

The modes are not interchangeable, and a team evaluation of this extension found the difference is mostly in review cost rather than output quality.

`guide` is the one that pays for itself. The blueprint carries contracts, rationale and pitfalls, so the review is about the design; the code review still happens where it always did, in the PR. `doc-only` and `scaffold` put the finished implementation in the document, which means the same code gets reviewed twice — once in the blueprint and again in the PR — and typing it through is transcription rather than design. Reach for those when you want a complete implementation to read before `/speckit.implement` runs, and for `guide` when you want the developer to design the bodies.

Two things worth deciding up front on a team:

- **Feature size.** A ~20-task feature produces roughly 1,600–1,900 lines in the full-code modes, and about a third of that in `guide` — the same 20-task feature came out at 1,612 lines as `doc-only` and 670 as `guide`. A 57-task feature produced 5,517. Past about 30 tasks the document stops being something anyone reads end to end — split the feature instead.
- **Lifetime.** `blueprint.md` describes an intention, and it goes stale the moment implementation diverges. Decide whether it is deleted at merge or kept as a record; an undeleted blueprint from six months ago is a confident, wrong document.

## Commands

### `/speckit.blueprint.generate [mode]`

| Argument | Description |
|----------|-------------|
| _(none)_ | doc-only — complete-code `blueprint.md` only |
| `scaffold` | Complete-code blueprint + stub files with TODO markers |
| `guide` | Design-guidance blueprint — contracts and notes, no body code |
| `guide scaffold` | Guide blueprint + compilable skeleton files on disk |

**Requires**: `tasks.md` in the feature directory.

**Produces**: `specs/{feature}/blueprint.md` — structured by phase and task, with full content blocks, before/after diffs, key decisions, implementation order, and checklist.

### `/speckit.blueprint.validate [feature-dir]`

| Argument | Description |
|----------|-------------|
| _(none)_ | Auto-detect feature directory from current branch |
| `specs/NNN-name` | Use specified directory |

**Checks**: blueprint exists, new files exist, TODO markers in core files, no over-implementation.

### `/speckit.blueprint.cleanup [mode]`

| Argument | Description |
|----------|-------------|
| _(none)_ | report — scan blueprint-touched files, classify findings, edit nothing |
| `apply` | Remove findings classified as STALE or NARRATION, then re-verify (build/tests) |

**Requires**: `blueprint.md` in the feature directory.

**Never removed**: honest unfinished markers, constraint/why comments, doc comments, license headers, pragmas.

### `/speckit.blueprint.review [ask|export] [scope]`

| Argument | Description |
|----------|-------------|
| _(none)_ | ask — quiz the decisions the blueprint delegated, then grade the answers |
| `export` | Skip the questions and produce the PR decision list only |
| `upstream` | Take the doubts typing raised and send them back to the artifacts that caused them |
| `US2`, `T012-T018`, a phase name | Limit the scope; defaults to every implemented task in the feature |

**Requires**: `blueprint.md`, and the tasks in scope actually implemented.

Run it after implementing and before opening the PR. It separates what the blueprint decided from
what it handed to you, asks about the second set against your real code, grades the answers, and
exports a list a reviewer can use without opening the blueprint. It never writes code, and never
answers its own questions.

`upstream` handles the other thing typing produces. Transcribing a signature is when an earlier
decision gets tested — you reach a shape that feels wrong, and the doubt is about `spec.md` or a
decision record, not about the line under your cursor. That doubt has nowhere to go and is gone by
the time the PR opens. This mode collects them, works out from each task's **Why** which artifact
and section the doubt is really aimed at, and separates the three cases that feel identical at the
keyboard: you misread the design, the blueprint misquoted it, or the artifact genuinely does not
hold. Only the last becomes a change request; the first two come back to you with the answer.

## Hooks

Three optional hooks, all prompted:

| Hook | When | Prompt |
|------|------|--------|
| `after_tasks` | After `/speckit.tasks` completes | "Generate blueprint from tasks?" |
| `after_implement` | After `/speckit.implement` completes | "Sweep leftover scaffold markers and stale comments?" |
| `after_implement` | Same event, after the sweep | "Review the decisions you made, and export them for the PR?" |

Answer `y` to run with default arguments (doc-only generation / report-only cleanup). You can always run the commands manually with different modes afterward.

Disable hook: `specify extension disable blueprint`

## Validation Scripts

The validate command runs two bundled scripts:

```bash
python3 .specify/extensions/blueprint/scripts/python/validate_blueprint.py specs/{feature}
python3 .specify/extensions/blueprint/scripts/python/apply_blueprint.py specs/{feature} --build
bash .specify/extensions/blueprint/scripts/bash/validate-scaffold.sh specs/{feature}
```

The middle one is the important one. It copies the working tree aside, types every task's code
into that copy the way a developer would, and runs the project's build — so "this blueprint
compiles" stops being a claim the generator makes about itself. Applying is deterministic: a
`**Before**` block that is not in the file verbatim, or is there twice, is reported as a defect
rather than repaired by guesswork. `--keep` leaves the copy behind to inspect; nothing ever
touches your own tree.

Color-coded output: green (pass), yellow (warning), red (failure). Both exit non-zero on failure, so they work in CI or a pre-commit hook.

Why a document validator: rules that live only in prose get followed inconsistently. Running this against two independently generated blueprints for the same feature caught the same defect in both — multi-file tasks that never said which code block belonged to which file — which no amount of reading had surfaced.

## Troubleshooting

| Error | Solution |
|-------|----------|
| "Run `/speckit.tasks` first" | Generate tasks before running blueprint |
| "blueprint.md not found" | Run `/speckit.blueprint.generate` first |
| "File MISSING" | Re-run scaffold mode or create the file manually |
| "No TODO markers found" | Core file may have been generated outside scaffold mode |
| Command not available | Check `specify extension list`, restart agent session, reinstall |

## License

MIT — see [LICENSE](LICENSE)

## Support

- **Issues**: <https://github.com/chordpli/spec-kit-blueprint/issues>
- **Spec Kit**: <https://github.com/github/spec-kit>

---

*Extension Version: 1.2.0 | Spec Kit: >=0.2.0*
