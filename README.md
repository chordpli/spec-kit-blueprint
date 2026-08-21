# Blueprint

Pre-implementation blueprint generator. Reads spec artifacts and produces a single `blueprint.md` with complete, ready-to-use content for every task — so you can review, understand, and type through the implementation before `/speckit.implement` runs.

![Spec Kit >= 0.2.0](https://img.shields.io/badge/spec--kit-%3E%3D0.2.0-blue)
![Version 1.1.0](https://img.shields.io/badge/version-1.1.0-green)
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
| `guide` | Design-guidance `blueprint.md` — signatures, Why, implementation notes, pitfalls, references, **no body code**. For learning-first workflows where the developer designs the logic. Add `scaffold` (`guide scaffold`) to also write compilable skeletons to disk |

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
specify extension add blueprint --from https://github.com/chordpli/spec-kit-blueprint/archive/refs/tags/v1.0.0.zip
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

Checks: blueprint exists, all referenced files exist on disk, TODO markers present in core files, no over-implemented scaffolds.

Exit code `0` = pass. Exit code `1` = failure.

### Clean up after implementation

```
/speckit.blueprint.cleanup
/speckit.blueprint.cleanup apply
```

After `/speckit.implement` (or manual typing), sweeps residue from the files the blueprint touches: stale `TODO(blueprint):` markers whose code is already implemented, narration comments that restate the code, and dead commented-out code. Report-only by default; `apply` removes what the report classifies as safe. Genuinely unfinished markers are never deleted — they are surfaced as the remaining work list.

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

## Hooks

Two optional hooks:

| Hook | When | Prompt |
|------|------|--------|
| `after_tasks` | After `/speckit.tasks` completes | "Generate blueprint from tasks?" |
| `after_implement` | After `/speckit.implement` completes | "Sweep leftover scaffold markers and stale comments?" |

Answer `y` to run with default arguments (doc-only generation / report-only cleanup). You can always run the commands manually with different modes afterward.

Disable hook: `specify extension disable blueprint`

## Validation Script

The validate command runs a bundled Bash script:

```bash
bash .specify/extensions/blueprint/scripts/bash/validate-scaffold.sh specs/{feature}
```

Color-coded output: green (pass), yellow (warning), red (failure). Usable in CI or pre-commit hooks.

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

*Extension Version: 1.1.0 | Spec Kit: >=0.2.0*
