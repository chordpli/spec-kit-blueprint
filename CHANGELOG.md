# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-08-21

### Added

- `validate_blueprint.py` — validates the blueprint document itself (task coverage, a Why per task, Before/After claims checked against the working tree, multi-file label discipline, placeholder scan), complementing the scaffold validator. Runs in every mode, including doc-only and guide where nothing is written to disk
- `guide` mode for `/speckit.blueprint.generate` — a design-guidance blueprint with signatures, rationale, implementation notes, pitfalls, and references but **no body code**, for learning-first workflows where the developer designs the logic; `guide scaffold` also writes compilable skeletons to disk

- `/speckit.blueprint.cleanup` command — post-implementation sweep of scaffold residue: stale `TODO(blueprint):` markers, narration comments, commented-out code. Report-only by default, `apply` to edit; never deletes honest unfinished markers or constraint comments
- `after_implement` hook (optional) prompting the cleanup sweep
- Two closure rules found by auditing a generated blueprint as a developer who has not read the design docs: requirements and acceptance criteria cited by task headers must be reproduced in the document (they were referenced 102 times and stated nowhere), and every "defined in T0NN" forward reference must actually be delivered by that task
- The dropped-anchor check compares positions instead of set membership: the real defect it was written for — a doc-comment opener deleted from the end of a hunk — was exempted by an unrelated opener at the top, while a legitimately rewritten condition was reported instead
- Over-implementation fails only when nearly every file that should carry a marker still does; mid-implementation, a finished file is normal and no longer fails
- Multi-file labels are counted whatever follows them, not only a colon
- Only a task's File declaration says what gets created; reference tables are no longer scraped for paths
- Cited requirements are now verified, not self-reported: the document validator fails when a task header names a requirement id whose text appears nowhere in the blueprint (markdown emphasis around the id still counts as a definition)
- Both validators print their version, so a stale installed copy is visible
- Rule and check for undetermined specs: what the artifacts do not decide, the blueprint does not decide either — it builds to the seam, marks the task blocked, and collects the gaps in an Open Questions section, which the document validator reports with its blocking count
- **Closure rules** (Step 3d) making the blueprint self-sufficient, enforced in self-verification: reproduce behavior-defining tables instead of citing them; every named type must resolve on its module's classpath (or the blueprint carries the task that adds the dependency); simulate every port/caller pair; verify every claim about the working tree (line numbers, Before≠After, add-vs-update ripples, contradicting comments in files the reader is sent to); close the type-to-schema loop (fields↔columns, NOT NULL suppliers) and the declaration loop (collaborators in constructors, no orphan types)
- **Why layer** in generated blueprints: per-task rationale traced to spec/plan/decision records (decision, rejected alternative, invariant to protect), per-phase background, and a Key Decisions table with rationale, trade-off, rejected alternative, and source columns
- Comment rules for generated code: constraint comments stay in code, narration stays in blueprint prose; scaffold markers use the greppable `TODO(blueprint): T{ID}` form
- `provides.scripts` declaration for `validate-scaffold.sh` in the manifest

### Fixed

- Cleanup now recognizes guide-mode markers: a not-implemented **call** carrying a task ID (Kotlin `TODO("T012: …")`) is a blueprint marker, always classified UNFINISHED, never removed. Previously only `TODO(blueprint):` comments were matched, so guide-mode scaffolds were invisible to cleanup
- Multi-file tasks: each code block must be labeled with its own path, and `validate-scaffold.sh` now extracts every path from a `**File**:` line instead of only the first — a task listing two files no longer maps content to the wrong file
- `validate-scaffold.sh` gained `--strict` for scaffolding done after a doc-only/guide blueprint was generated
- `validate-scaffold.sh` no longer fails doc-only/guide blueprints: it reads the `**Mode**:` line and only requires files on disk for scaffold modes. Mode parsing reads the leading token only, so prose mentioning another mode (e.g. a link to a scaffolding decision doc) no longer misclassifies the blueprint
- File-existence check skips placeholder/glob paths (`docs/2026-MM-DD-*.md`) instead of reporting them missing

### Changed

- Cleanup scope extends to files carrying this feature's blueprint/task-ID markers even when the blueprint never named them (reported separately as blueprint drift)
- Cleanup removal rules cover comment shape (own-line, trailing, block) and multi-language comment syntax (SQL, YAML, shell, JS); an executable not-implemented call such as Kotlin `TODO("…")` is never deleted by cleanup
- Cleanup must state plainly when no correctness check could be run rather than implying removals were verified
- `**Mode**:` line in generated blueprints must lead with the mode token (validation parses it)
- Guide-mode test skeletons must carry the project's real test imports and annotations, so the skeleton compiles
- Blueprint structure now mirrors current Spec Kit `tasks.md` organization: user-story phases, `[P]` parallel markers, `[US#]` story labels, and Checkpoint lines are preserved verbatim
- Step 1 additionally loads `research.md` and referenced decision records (ADRs) as rationale sources
- Self-verification also checks: phase/label fidelity to `tasks.md`, presence of a Why per task, cited sources per Key Decision, and no narration comments inside code blocks

## [1.0.0] - 2026-04-15

### Added

- `/speckit.blueprint.generate` command with two modes: doc-only, scaffold
- `/speckit.blueprint.validate` command for scaffold validation
- `after_tasks` hook for automatic blueprint generation
- `before_implement` hook as safety net when blueprint.md is missing
- Language-agnostic scaffold validation script (validate-scaffold.sh)
- Support for spec artifacts: tasks.md, spec.md, plan.md, data-model.md, contracts/
- Tags for catalog discoverability: blueprint, pre-implementation, review
- "The Gap This Extension Fills" section in README
- "Why Not Just Review the PR After Implementation?" FAQ section in README
