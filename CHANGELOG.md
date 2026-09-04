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
- The sandbox promise says what it covers. Every edit lands in the throwaway copy, but `--build` runs a shell command that can come from the blueprint's own `**Build**:` line, and a build writes wherever the developer running it can — so the command is printed before it runs and the README says to read it before pointing `--build` at a blueprint you did not generate
- Guide mode says how a file that changes is written: a new file that several tasks build up (each later task anchors on the tail of the skeleton the previous one left), and a change inside an existing body (a `TODO(blueprint):` marker inserted where the change goes, with the notes saying what it must achieve). Both use the ordinary Before/After form and need no tool support; the gap was that the form was never written down, so generators invented one each — `**Required end state**` in one run, a tail-anchored hunk in another — and only the second applies
- The README opens with a ten-line path for the reader who is here to type the code and learn from it, recommends `guide scaffold` over plain `guide` for that workflow, and tags each Step 3d closure rule with the projects it applies to, so a four-file CLI can skip the schema and classpath rules and know it lost nothing
- `review` says where each mode writes: `export` to `specs/{feature}/review-decisions.md`, `upstream` to `specs/{feature}/review-upstream.md`, `ask` to the conversation
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
- The scaffold validator ran on macOS and nowhere else: `((PASS++))` returns the value before the increment, so the very first `pass` call exited 1 and `set -e` killed the script before check 2 on every bash >= 4. On a Linux CI runner it printed one header and stopped, while still exiting red — three of its four checks had never run
- The applier could corrupt the file it was applying to. Its end-of-file newline allowance dropped the block's last newline unconditionally, so a Before of `    val fee = 0` matched inside `    val fee = 0L` and wrote `    val fee = feeOf(x)L` while reporting the task applied. The allowance now fires only where it was justified, at a region that really is at the end of the file
- `file_kinds` was not fence-aware, against the shared module's own headline promise. A task that documented the blueprint format, with a `**File**:` line quoted inside a markdown block and none of its own, adopted the quoted path — and the applier wrote it. The scaffold validator read fenced declarations and tables the same way, and demanded the example paths on disk
- The dropped-anchor check is counted, not positioned. Both earlier versions were wrong in both directions at once: a two-line Before put its closing brace in the opening window and failed a correct diff, while a `/**` four lines in fell between the windows and passed — the exact hunk the check was written for. It now compares how many times a structural line appears on each side, and reports as a warning, since a task that removes a block legitimately drops one
- `code_lines` treated a one-line docstring as an opening delimiter and never closed it, so everything after the commonest Python docstring form went unread and guide mode's one mechanically enforced promise never fired
- `copy_tree` matched its skip list at any depth and against files, so a Java or Go package directory named `build`, `dist` or `out` was dropped from the copy and `--build` failed with "cannot find symbol" while the report blamed the blueprint. Those names are skipped at the repository root now; `.git` and `node_modules` still anywhere
- `--build` no longer runs after a task failed to apply — it would have reported the applier's damage as the blueprint's — and is killed after 15 minutes instead of waiting for ever on the unverified code it exists to be suspicious of
- The freshness check resolved a stamped source by basename inside the feature directory first, so an unrelated file of the same name shadowed the real one and reported a byte-identical artifact as changed
- A duplicated task id no longer disappears: `dict(split_tasks(...))` kept only the last section, so the first went unchecked by every check and the section count printed one too few. The duplicate is now a failure of its own
- A `**Before**` with no `**After**` is reported instead of being paired with a later task's After — a diff that is not in the document. The applier already refused these, so the document validator was strictly weaker than the applier on a defect it exists to find
- A `(lines 40-500)` citation has both ends checked; only the first number was read, so the bound that mattered never was
- Code blocks are extracted with the shared fence scanner. The regex the checks used mispaired fences on any info string that was not a bare word — a ```` ```c++ ```` block made the following prose scan as code — and a nested fence hid a block entirely
- Paths with a space survive: the dedup ran through an unquoted command substitution, so `docs/my file.md` became two fabricated missing files, and the expansion was glob-subject as well
- `(new — moved from …)` is read as `new` again on both sides, `(New)` is matched case-insensitively by the scaffold validator, and both tools accept an extensionless build file and a path whose last dot-segment is long. The two disagreed on all four, each demanding a file the other never wrote
- `**Mode**` is parsed once, in the shared module, and tolerates the backticked spelling the README and the generator's own tables use — three parsers with three grammars meant a header read as `guide` by one tool and `unknown` by the next
- Applier failure messages name the file again instead of a six-level `../` chain, from comparing against an unresolved temporary path
- `--fresh` reports each violating file once, and spares a file too small to tell a written-complete body from a type the basename classifier mislabelled
- A blueprint whose declared paths are all placeholders says so, instead of printing nothing at all for the file-existence check
- A `(modify)` path that is not in the tree is a defect, not a file to create. The applier wrote the fragment to that path instead, producing a phantom file no source set compiles — so `--build` passed while the real file was never touched
- A block label has to look like a path. `**`Svc.transfer()`**` names a method, and a dot was enough to make the applier write that block to a file called `Svc.transfer()` at the tree root while reporting the declared path as edited
- Overwriting a declared-new file that is already on disk is now reported. It is the right thing to do while the tree holds scaffolds — guide-scaffold puts them there before implementation, and the compile gate depends on it — and the wrong thing once the tree holds the implementation, because the same overwrite discards the work and the build then describes the blueprint rather than your tree. The command spec claimed those files were left alone, which was never true
- A dangling symlink no longer aborts the copy, and a copy that fails part-way is cleaned up instead of leaking a temporary tree through an uncaught traceback
- A ```bash block under **Verification** is a command, not file content. Counting it reported every task that has one as carrying code the applier could not place, and the applier "left it alone" out loud. The two tools now read a task section through one shared event stream, which is also the only place that knows which labels are illustrative
- A Before that cites a line past the end of the file on disk, in a file an earlier task changes first, is a warning that names that task rather than a failure. The document cannot settle it — T008 edits the wiring T006 adds — and a correct blueprint could only pass by citing a number it knew was wrong. The applier settles it, since it applies in order and matches the text. The same warning covers a tree you have started implementing in
- A Before citation is attributed to the file the document names — on the Before line, or in the nearest `**`path`**` label above it — instead of to every file the task declares; the check was telling an author who had labelled the block to name the file they had already named
- The applier's summary and last line say when declared-new files were overwritten, in yellow; the per-task note alone let "applied and built cleanly" end a run that had just discarded an implementation
- The applier's copy starts without this blueprint's declared-new files. In `guide scaffold` mode the skeletons are already on disk, and a copy that kept them let the build pass over a task whose block was deleted or whose label was wrong — the skeleton filled the hole and the compiler never saw it. The most recommended mode had the weakest build gate, and the document said the opposite
- A task that declares a `(new)` file and gives it no block is a document failure, with the task id, before it is a javac trace
- A `(modify)` path that is not in the tree is checked before anything else in the task. At the write site, a task whose only block carried no label was reported "unanchored" first and never reached the check — a wrong path passed all three tools with exit 0
- Over-implementation is a warning unless `--fresh` says the scaffold was just written. The sibling ratio was meant to tell "just scaffolded" from "being implemented", but with four skeleton files the first one finished is 3/4 still marked, and the developer who had just implemented it honestly was told it "was written complete instead of stubbed"
- The skeleton population is read from the blueprint — every declared-new file whose block carries a marker — not guessed from the basename. A controller and a scheduler written complete at scaffold time were never looked at because their names matched neither `*service*` nor `*test*`
- An unlabelled hunk is measured against the task's `(modify)` files only, the rule the applier already uses to place it: a fifteen-line new exception class was being offered as the file a sixty-line service hunk might be quoting, and the warning told the author to name a file the tool then did not read
- After implementation, a guide-mode hunk whose added lines are all in the file and whose markers are gone is reported "implemented since" rather than "Before not found verbatim", which sent the reader hunting for a blueprint bug. A Before that is merely wrong by a character still fails
- An abbreviated Before (`// ... rest of file`) is a document failure by name; the placeholder check strips Before/After first, rightly, so the abbreviation reached the applier as an anonymous "not found"
- A Before whose text sits at a different line than the number it cites is a warning — in range is not the same as right, and the reader follows the number
- `--markers` lists each marker once: a file that several tasks build up is declared once per task, and the first version printed its markers that many times — four markers reported as nineteen. A marker whose message wraps to the next line (Python's `raise NotImplementedError(` with the string below) is printed with that line joined on, so the task id is visible
- The applier tallies hunks per task instead of stopping at the first one already in the file: a task with two hunks present and one that matched nothing is reported as exactly that — "implemented since, differently" — rather than "the After content is already in the file"
- The applier compares the line a Before cites with the line its text matched on, in the copy as the earlier tasks left it, and says so in the task's note. That is the one check no document-level tool can make, and it closes the case the document validator hands off
- One marker form: `TODO(blueprint): T{ID}: {instruction}` with the colon, the same shape as the executable markers' messages; the generate spec had said it two ways
- The generate spec says who it is for: the generator. A developer typing from the result reads 3a-G, 3b and 3c, as the README says, and none of the closure rules; the two lists differ because the two readers do
- Cleanup's remaining-work list also reads the unchecked Checklist rows, since a `(modify)` task leaves no marker on disk and a feature half done had an empty list
- Guide-mode body detection covers what an `**After**` block adds. A guide feature's behaviour changes live in modify hunks, so the mode's one mechanical promise was checked everywhere except where it mattered: a reviewer replaced an After's marker with a working body and every tool passed it. Context the After repeats from its Before stays a quotation
- A block label naming a path its task does not declare is a failure; the applier ignored it, fell back to the sole modified file, and reported the block as having no label at all
- A declaration written without its `(kind)` is checked for existence, and a task with a hunk but no `(modify)` file is a failure — two shapes of wrong path that passed every document check
- `--require-anchors` fails when a task is already in the tree or cannot be judged, so a CI job does not stay green over a tree that has moved past the blueprint
- A partly typed task is not counted among those already in the tree
- Both Python scripts take `--help` and refuse an unknown option instead of running as though it had not been typed; a typo in `--build` looked like a run that chose not to build
- The scaffold validator counts methods, not fields, and `--markers` joins a message split across concatenated string literals
- Guide-mode body detection reads the marker's message and expression bodies. A message that spells out the exact expression hands over the body inside a string, where no code check had ever looked, and a stream chain or a lambda is body logic with no control-flow keyword in it — half a Java body. Both were invisible; a reviewer found four dictated markers and a completed repository method in one blueprint that had passed
- A Before block that is not in the file it quotes, or is in it twice, is reported by the document validator — checked against the tree as the blueprint's commit left it, so an implemented tree does not report every hunk as wrong. Both tools ask git the same question now, through one shared helper
- "Already applied" says when only part of a task has landed, and a hunk whose anchor an earlier task moved says "cannot tell" rather than claiming the work is done
- The scaffold validator warns once per file rather than twice; a feature under implementation collected two warnings per file until none of the output was signal
- The shared parser sets `dont_write_bytecode` itself, so a third caller importing it does not leave a `__pycache__` in the user's tree
- The guide-mode `**Build**` warning matches a test runner, not the word `test`: `compileall -q pkg tests` names a directory, and it is the command the spec tells a Python project to stamp
- `if __name__ == "__main__":` is not body logic — 3a-G asks test skeletons to match the project's existing tests, and in Python those end with exactly that line
- The applier compares whole lines, not substrings, when deciding a hunk is already applied: `def select_entries(` matched inside the old signature and called an untouched task done. "Already applied" now needs every added line present, or a demonstrable duplicate if the hunk were applied; a hunk that is neither is reported as "cannot tell" and left out of the already-in-the-tree count
- The guide-mode anchor rule says which run to quote per language: a signature line alone works where the body is on it, and puts the new function between `def` and its body where it is not
- The marker-message check is narrow and quotes what fired. Measured against every blueprint written with this tool, its first version caught `&&` and `==` and nothing else, while its other rules fired only on honest prose — an arrow between two states, an API named mid-sentence, a semicolon between list items — so it trained authors to write expressions and avoid prose, the opposite of the rule. It now reports only what a reader could paste, and names the fragment: a reviewer had bisected one marker twelve times to find the cause
- `--strict-guide` turns the guide-mode body findings into failures, so a CI job can tell a guide blueprint that hands over a finished body from one that does not
- A marker message that does not begin with its task id is reported; `--markers` and cleanup trace markers to tasks by that id, and the generate spec asks for it
- A task declaring more than one new file must label a block with each; one block between two declarations passed, and the missing file surfaced as a compiler error
- The applier refuses a block label naming a path its task does not declare. Following the label wrote the block there anyway, which put a skeleton back immediately after the sweep had removed it — the reason a mistyped declaration still built
- The copy drops any undeclared file that was not in the stamped commit, not only those carrying markers: a structural skeleton carries none by design, and one was filling the hole a mistyped path had left
- A file that later tasks grow is no longer compared to its creating task's block. The "one new file, several tasks" form the spec recommends, scaffolded the way the spec recommends, reported a skeleton nobody had opened as edited since scaffolding — the drift check now looks only at files no other task touches
- `--markers` joins continuation lines for executable markers only. A comment marker has no closing paren to stop at, so the join ran on and pulled the code beneath it into the list cleanup is supposed to read
- The generator's reading list names Step 3-Sources, which holds the hash rule and the guide-mode build rule; without it a first blueprint stamps a git sha1 and a test command, and both are wrong
- Typing every hook first leaves the tree in the last task's shape, which is not an earlier Checkpoint's shape — the instruction now says so
- The validate spec says what to run while implementing: the project's tests, not this set
- Splitting a feature works. The README has always advised it past about thirty tasks, and the closure the tool is built on made it impossible: a reviewer split a 57-task feature at its user-story boundary and got ten dangling references in the first slice, twenty-five in the second, and a build failure in the second on the first's types. A later slice names its predecessor with `**Base**: specs/{slice}/blueprint.md`, and that one line is read from both ends — references across the seam resolve in either direction, coverage counts what the base delivers, and the applier applies the base's tasks first. The same 57-task feature now splits into two slices that each validate, apply and build
- `apply_blueprint.py --scaffold` writes the declared-new files from the verified copy into your tree, after a clean apply and only where nothing is already there. A generator writing forty skeletons by hand is where drift comes from; the copy holds exactly what the document says
- A forward reference that points at a task the document does not have is a failure. Step 3d asked for it and nothing checked it — the one closure rule with no machine behind it
- The generate command splits its reading guide by reader, not only by mode: a developer who will type from the blueprint reads 3a-G, 3b and 3c and stops, about forty lines, because the validators enforce the rest. Both reviewers asked for this, from opposite ends — the junior read 395 of 417 lines to write one, the senior would not expect a reviewer to read the 1,467 lines it produced
- The applier reads the commit the blueprint stamps and asks git whether a file has changed since. A Before that is not in a file that has moved is reported as implemented since, not as a failure — the guide-mode body-change hunk adds only a marker line, so no text heuristic could ever tell the two apart, and the command spec's "a failure means the blueprint is wrong" was sending developers after a bug that was not there. A mixed task, some hunks applied and some already there, is a warning rather than a tick
- A `(new)` file's label above the hunks no longer claims them: only a label for a file a hunk can edit attributes the hunks below it. The validator had measured a service hunk against the eighteen-line exception class declared beside it and failed a correct blueprint — the opposite of what its own spec said
- On a tree that has moved past the blueprint's commit, a hunk any of whose added lines are already in the file is reported as implemented since rather than applied; applying it registered a test the developer had already registered, twice
- The document validator fails a `(modify)` path that is not in the tree (unless an earlier task creates it) and a declared path that escapes the repository; a wrong path passed sixteen checks green because every check that read the file skipped it quietly
- The applier removes from its copy any file carrying a blueprint marker that no task declares — a deleted section left its skeleton on disk to fill the hole, and the build passed over it — and warns when a task id has more than one section
- A skeleton on disk that still carries its marker but is not the blueprint's block is a warning; nothing compared the two, so a method added to the file on disk passed all three tools
- One control-flow line beside a marker is enough to report a guide block, since a method written complete beside five that kept their markers is one `if`
- A missing `**Mode**:` line is a warning from all three tools instead of a silent unknown that skipped the guide checks; a guide-mode `**Build**:` that runs tests is a warning, since the skeletons throw by design
- The applier's per-task note lists the files it wrote, not every file the task declared, and a task that left a block unplaced is a warning rather than a tick
- The hunk-in-a-new-only-task message says what is wrong — the file should be declared `(modify)` — instead of asking for a label that fixes nothing
- Neither Python tool writes `__pycache__` into the user's `.specify/` any more
- The scaffold validator colours its output only on a terminal, like the Python tools
- `validate-scaffold.sh --markers` lists every marker left in the declared files, so cleanup's enumeration is mechanical and only its judgment is the model's
- Guide-mode body detection reads a block with no marker as suspect at one control-flow line, not three — a complete `claim()` with a single `if` passed — and reports a new service, handler, controller, scheduler or test whose block carries no marker at all
- An authored comment that narrates the blueprint's history ("moved verbatim", "pre-existing") is a warning: cleanup never touches a doc comment, so a sentence written for this document's reader would stay in the code for ever
- The generate command opens with a reading guide by mode and lists the shapes the validators read, so a first blueprint passes on format without reading the validators' source; its Rules section no longer restates six rules the Steps already state
- The command specs' Step 1 says what to do when `check-prerequisites.sh` cannot find the feature (newer spec-kit reads `.specify/feature.json`), the validate spec lists the ten sections the script actually prints, and the README's guide-mode size estimate matches what the closure rules produce
- Version banners agree: the applier printed 1.0.0 inside a 1.2.0 release, and the README's badge alt text still read 1.1.0
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
