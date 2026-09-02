# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-09-02

Everything here came out of two people using the extension on real projects and
reporting what broke. The theme is the same in both directions: the tool stated
obligations it never collected on — that its code compiles, that the developer can
explain their choices — and now it checks them.

### Added

- Two closure rules found by auditing a generated blueprint as a developer who has not read the design docs: requirements and acceptance criteria cited by task headers must be reproduced in the document (they were referenced 102 times and stated nowhere), and every "defined in T0NN" forward reference must actually be delivered by that task
- `apply_blueprint.py` — applies a blueprint to a throwaway copy of the tree and builds it, so the document's central claim is checked by a compiler rather than asserted by its author. Deterministic: an anchor that does not match verbatim is a reported defect, never a guess
- `/speckit.blueprint.review` — after implementing, asks about the decisions the blueprint delegated, grades the answers against the code and the blueprint, and exports a decision list for the PR
- `review upstream` — the doubts typing raises about earlier stages now have somewhere to go. Transcribing a signature is when a design gets tested, and the doubt is usually about spec.md or a decision record rather than the line under the cursor. The mode reads each task's **Why** to find which artifact the doubt is aimed at, then separates the three cases that feel identical at the keyboard — the developer misread it, the blueprint misquoted it, or the artifact does not hold — and only the last becomes a change request
- `**Sources**` and `**Build**` header stamps, with the document validator failing a blueprint whose inputs have moved; regeneration keeps unchanged tasks verbatim so the diff stays reviewable
- Rule and check for undetermined specs: what the artifacts do not decide, the blueprint does not decide either — it builds to the seam, marks the task blocked, and collects the gaps in an Open Questions section, which the document validator reports with its blocking count
- Two rules that lived only in the prompt are now checked: a regeneration that rewrites tasks whose sources never moved fails against the committed blueprint, and a guide-mode block carrying control flow beside its marker is flagged as body logic the developer was supposed to write
- `_blueprint_parse.py` — one reading of a blueprint shared by both Python tools, after a path fix landed in one and not the other and quietly disabled a check in the second
- `validate-scaffold.sh --fresh` — states that the scaffold has only just been written, which is the one thing the script cannot see for itself. Its over-implementation check reads the sibling files to guess whether implementation has started, and when every file was written complete there are no marked siblings left to read

### Fixed

- The applier refuses a declared path that resolves outside its throwaway copy, and no longer preserves symlinks into it — an absolute or `../` target in a blueprint could write to the real filesystem, against the one promise the tool makes
- `(modified)` and `(deleted)` are read as the kinds they are; a `rstrip("d")` turned the first into `modifie`, so a correct blueprint was reported as declaring no modified file
- A `**File**:` declaration is recognised at the end of a section, and stops before following prose, which was being read as more declared files
- Task coverage counts task sections and pre-completed rows, not every task id in the document — the checklist the template requires made the check unfailable
- The dropped-anchor check uses non-overlapping edge windows; in a hunk under ten lines the head and tail windows overlapped and the deletion it exists to catch passed
- The regeneration check compares only the source hashes, not the `| HEAD` suffix that moves on any unrelated commit
- The Open Questions section ends at a heading of its own depth instead of swallowing the rest of the document
- Kind and label parsing in the validator go through the shared module, so `(modified)`, `(all modify)`, labels without a trailing colon, and ten-character extensions all agree with the applier
- The scaffold validator recognises `(all new)` and repository-root files, and reads paths without word-splitting or glob-expanding them
- The scaffold validator's line-joining pass no longer deletes its own input: a table or a paragraph written directly under a `**File**:` line, with no blank line between, was folded into that line and never re-emitted, so the declarations it carried were invisible. Only continuations are folded now
- A table row whose status cell reads `New` declares a file again, not only one reading `new file`
- A file-less mode reports which checks were skipped instead of "All checks passed"
- The guide-mode body check ignores comments and doc comments, which describe control flow constantly
- An empty `**Mode**:` value no longer crashes both Python tools with an IndexError
- `--require-anchors` makes the applier fail when a task's code is not anchored, or when nothing anchored at all — off by default, because a guide blueprint of pure instructions legitimately applies nothing, and on in CI, where "verified nothing" and "verified everything" must not share an exit code
- The command spec and manifest describe the checks that actually run; three whole sections and half of a fourth had gone undocumented
- The scaffold validator no longer special-cases one project's wording for a moved file
- The dropped-anchor check compares positions instead of set membership: the real defect it was written for — a doc-comment opener deleted from the end of a hunk — was exempted by an unrelated opener at the top, while a legitimately rewritten condition was reported instead
- Over-implementation fails only when nearly every file that should carry a marker still does; mid-implementation, a finished file is normal and no longer fails
- Multi-file labels are counted whatever follows them, not only a colon
- Only a task's File declaration says what gets created; reference tables are no longer scraped for paths
- Guide-mode blueprints stamp a compile or syntax check as their `**Build**`, never a test run — guide skeletons are not-implemented by design, so a test command is red before the developer starts, and in a compiled language that trap hides itself
- The document validator warns when a modify task's code is not anchored to a position, so prose like "append this at the end" is caught before the applier fails on it
- Cited requirements are now verified, not self-reported: the document validator fails when a task header names a requirement id whose text appears nowhere in the blueprint (markdown emphasis around the id still counts as a definition)
- Both validators print their version, so a stale installed copy is visible
- The applier reports an edit already present in the tree as `already applied` rather than as a missing anchor, so running it after implementing points at the real problem

## [1.1.0] - 2026-08-21

### Added

- `validate_blueprint.py` — validates the blueprint document itself (task coverage, a Why per task, Before/After claims checked against the working tree, multi-file label discipline, placeholder scan), complementing the scaffold validator. Runs in every mode, including doc-only and guide where nothing is written to disk
- `guide` mode for `/speckit.blueprint.generate` — a design-guidance blueprint with signatures, rationale, implementation notes, pitfalls, and references but **no body code**, for learning-first workflows where the developer designs the logic; `guide scaffold` also writes compilable skeletons to disk

- `/speckit.blueprint.cleanup` command — post-implementation sweep of scaffold residue: stale `TODO(blueprint):` markers, narration comments, commented-out code. Report-only by default, `apply` to edit; never deletes honest unfinished markers or constraint comments
- `after_implement` hook (optional) prompting the cleanup sweep
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
