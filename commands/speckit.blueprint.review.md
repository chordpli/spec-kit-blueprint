---
description: "Check what the developer decided after implementing, and export the decision list for review"
---

# Blueprint Review

## Why This Exists

A blueprint states obligations and never collects on them. A guide-mode task says "decide the rounding and be able to explain why"; the developer types the first form that comes to mind, twenty-three tests go green, and nothing ever asks. Green tests measure behavior, not understanding — and the developer who cannot reconstruct the reason a week later did not learn the design, they transcribed it. That is precisely the failure this extension exists to prevent, and until now nothing in it looked at the developer's output: `/speckit.blueprint.validate` checks the document, `/speckit.blueprint.cleanup` checks the residue. This command checks the person.

The second cost is paid by the reviewer. From the final diff, nobody can tell which lines the blueprint dictated and which the developer designed alone. A reviewer who wants to ask a useful question must first read the whole blueprint — so they don't, and attention spreads evenly across code that deserves it very unevenly. The lines nobody agreed on in advance are exactly the lines review is for.

This command runs **after implementing a phase or story and before opening the PR**. It asks about the decisions the blueprint delegated, grades the answers against what the blueprint and the code actually say, and exports a decision list a reviewer can use without opening `blueprint.md`. It reads code — it never writes it.

## User Input

```text
$ARGUMENTS
```

| Keyword | Mode | Behavior |
|---------|------|----------|
| _(default)_ | `ask` | Extract decisions, ask the questions, wait for answers, grade, export. |
| `export` | `export` | Skip the questions entirely. Produce only the decision list for the PR description. |

The rest of the argument is the **scope**: a phase (`Phase 3`), a user story (`US2`), a task range (`T012-T018`), or a single task ID. A directory path overrides the feature directory (otherwise auto-detect from the current branch, same as `/speckit.blueprint.validate`).

With no scope given, the scope is **every implemented task in the feature**, across all phases — that is the unit the developer just finished and the unit the PR will cover. Name a phase, a story, or a range explicitly to narrow it. Step 2 decides what "implemented" means and makes the command state the scope it picked before it asks anything.

## Workflow

### Step 1: Load the Blueprint and Resolve Scope

Run the prerequisites check from the repository root:

```bash
.specify/scripts/bash/check-prerequisites.sh --json --paths-only
```

Parse `FEATURE_DIR` and load `blueprint.md`. Read the `**Mode**:` token from the header — it tells you how much the blueprint dictated, which changes where the questions come from (Step 3). If the header carries a `**Sources**:` line, compare the recorded hashes against the current artifacts; on a mismatch, say so in the report and continue — the questions still stand, but the blueprint they came from is describing an older intention.

Resolve the scope to a concrete task list — Step 2 decides which tasks count as implemented, and what the scope is when the arguments name none — then read **the developer's actual files** for those tasks from disk. Every question and every verdict must be grounded in the code as it exists now, not in what the blueprint said it would be.

### Step 2: Decide What Is Implemented, Then Refuse to Run on Nothing

A fabricated quiz is worse than no quiz — it teaches the developer that the exercise is theater. So the scope has to rest on evidence in the code, and a file sitting on disk is not evidence.

**What counts as implemented.** Judge each task by what its `**File**:` label says it does:

| Task kind | Implemented when |
|-----------|------------------|
| `new` | The file exists and carries a real body — no `TODO(blueprint):` for this task, no not-implemented call standing in for the work |
| `modify` | The change the task prescribes is **present in the file**. Existence proves nothing here — the file was there before the task was. Look for the substance of the `**After**` block: the symbols, calls, or lines that distinguish it from its `**Before**`, matched by meaning rather than character-for-character, since names and formatting drift while typing. For a task whose change is a structural instruction with no diff, or a guide-mode note, look for what the instruction asks for — the registration, the field, the entry, the wired call |
| `delete` | The file is gone |

Two consequences, both of them things the file-exists test gets wrong:

- **A task that names several paths, or carries several Before/After blocks, is implemented only when every one of its changes is present.** Three registrations prescribed and one typed is a partially implemented task, and a partially implemented task is not implemented.
- Where the **Verification** criterion can be checked by reading — a named symbol, an added route, a config key — check it, and let it override a guess. Where it needs a run, do not claim it; the marker and content evidence above stands on its own.

**Choosing the scope.** With no scope in the arguments, select **every implemented task in the feature**, across all phases. Tasks that fail the table above are left out of the selection, not treated as a stop. An explicit scope argument overrides this and is taken as given: asked for `Phase 3`, review Phase 3.

**Say which scope you selected, and why, before asking anything.** One line, before the first question:

```
Scope: 14 implemented tasks across Phases 2-6. Excluded: T017 (2 of its 3 route registrations missing from Router.kt), T018 (README has no `runOnce` section).
```

A guess the developer can see is a guess they can correct; a silent one sends them into a quiz about the wrong code.

Then stop, with the message, whenever:

| Condition | Message |
|-----------|---------|
| No `blueprint.md` | "No blueprint.md found — run `/speckit.blueprint.generate` first." |
| Scope names a phase/story/task not in the blueprint | "Scope `{arg}` is not in this blueprint. Available: {phases}." |
| Nothing in scope is implemented | "Nothing in {scope} is implemented — {per task, what is missing: no file, a `TODO(blueprint):` or not-implemented body still standing, or a prescribed change absent from the file}. Implement first, then run this." |
| A scope named in the arguments is only partly implemented | "{n} of {m} tasks in {scope} are not implemented — {per task, what is missing}. Implement first, then run this." |
| Fewer than two genuine decisions across the whole selection | Report the decisions found, say the selection is too mechanical to quiz, and skip to the export. |

Partial implementation of a **named** scope is a stop, not a partial quiz: half-typed code produces questions about code the developer already knows is unfinished, and the answers grade nothing. The default scope never contains an unfinished task to begin with — but it must still list what it excluded, so a skipped task is visible rather than quietly lost.

The "too mechanical" outcome judges the whole selection. It is the right answer when a feature really did have almost nothing delegated to it, and it must never be reached by looking at one trivial phase while a phase full of decisions goes unexamined.

### Step 3: Separate What Was Dictated from What Was Delegated

The blueprint records both halves. Extract them for the scope:

| Source | Where it lives in the blueprint | What it yields |
|--------|--------------------------------|----------------|
| **Delegated decision** | Guide-mode implementation notes that say *decide*, *choose*, *you must be able to explain/justify*; a not-implemented message that poses a choice; a named pitfall the notes deliberately leave unresolved | The developer's own decision — the primary question source |
| **Key Decision** | Key Decisions rows whose Tasks column intersects the scope | A decision the code must embody; ask where it lands and what breaks if reversed |
| **Divergence** | Code that does something other than what the blueprint prescribes | The developer's own decision, made against the plan — always worth a question |
| **Silently resolved Open Question** | An Open Questions row whose blocked tasks are now implemented | An assumption nobody agreed to; ask what they assumed and who still has to confirm it |

Mode changes the balance, not the method. In `guide`/`guide scaffold` the first row dominates. In `doc-only`/`scaffold` the blueprint dictated the bodies, so most decisions are dictated — lean on Key Decisions and divergences, and say plainly in the report that this scope had little delegated to it. A short honest quiz beats a padded one.

Everything a task dictated *and* the code follows faithfully is **not** a question. It is a row in the export.

### Step 4: Ask — Never Tell

Write the questions. Aim for **5**; never exceed 8. Fewer than 5 is a legitimate outcome when the scope holds fewer real decisions — say so instead of padding.

Rules for a question:

- **Name a real location.** `models.py:55`, or a symbol you verified exists in the file on disk. A question about code in general collects an answer about code in general.
- **Ask why, not whether.** "Did you understand the idempotency design?" collects a yes and teaches nothing.
- **Force the alternative into view.** The useful form names the choice and a boundary where the options part company.
- **One decision per question**, and no two questions on the same line.
- **Never reveal the answer.** Do not quote the blueprint's Why, its implementation notes, or its rejected alternative while asking. Do not narrow a genuine choice down to one option. The point is to check comprehension, not to hand it over.

| | Question |
|---|---|
| **Bad** | "Did you understand the percentage calculation?" |
| **Bad** | "Why did you use floor here, given that rounding up would over-report?" — the answer is in the question |
| **Good** | "`models.py:55` rounds the percentage — which of floor/round did you choose, and what does each return at 99.6%?" |

Output the questions numbered, then **stop and wait**. Do not answer them yourself, do not guess what the developer would say, and do not proceed to Step 5 on invented answers. If the command is running with no human to answer — a scripted or agent-driven run — print the questions, say that grading needs a person, and end there. A quiz you both write and grade is not evidence of anything.

### Step 5: Grade Against the Blueprint and the Code

When the answers come back, judge each one against what the blueprint says and what the code does. Three verdicts:

| Verdict | Condition | What the report must contain |
|---------|-----------|------------------------------|
| **MATCHES** | The answer agrees with the blueprint's rationale and the code confirms it | The line or blueprint section that confirms it |
| **DIVERGES** | Defensible, but rests on a different reason than the blueprint's | Both reasons, side by side, and which one the code actually implements. Differing is allowed when they can defend it — say that |
| **DOES NOT HOLD** | The code or the blueprint contradicts the answer | The exact line or blueprint sentence that contradicts it |

Grading rules:

- **Never bluff agreement.** An ungraded quiz teaches nothing, and a graded-generous one teaches something false. If you cannot tell whether an answer holds, say "cannot verify from the code" — that is a fourth honest outcome, not a reason to grade MATCHES.
- **Cite evidence for every verdict.** A verdict without a `file:line` or a blueprint section reference is an opinion.
- **"I don't remember" is the finding, not a failure.** Grade it DOES NOT HOLD, record it without editorializing, and move on to the rationale.
- **Now reveal the reasoning.** After the verdict — and only after — quote the blueprint's Why, Key Decision, or rejected alternative for that question. This is the moment the exercise pays off. Where the blueprint has no rationale because the decision was delegated, say that too: the developer owns this one, and their answer is now its documentation.
- Where an answer surfaces a genuine defect in the blueprint, report it as such. The developer being right about a design the blueprint got wrong is a valid result.

### Step 6: Export the Decision List

Produce a section the developer can paste into the PR description verbatim. It must stand on its own — a reviewer reads this instead of the blueprint, so reproduce the reasons rather than citing them:

```markdown
## Design decisions in this change

### Agreed in the blueprint before implementation

Review these for correct application, not for design — the rationale was settled up front.

| Decision | Where in the code | Reason |
|----------|-------------------|--------|
| {decision} | `{file}:{line}` | {the blueprint's rationale, reproduced} |

### Decided during implementation

No prior agreement exists for these. This is where review attention pays off.

| Decision | Where in the code | Developer's reason | Review status |
|----------|-------------------|--------------------|---------------|
| {decision} | `{file}:{line}` | {their answer, as given} | {matches blueprint intent / diverges — {how} / unverified} |

### Open for the reviewer

- {question graded DOES NOT HOLD, or an assumption resolved without agreement — with the task ID and who can confirm it}
```

In `export` mode, produce this section only: the first table from the blueprint, the second from delegated decisions and divergences with the reason column left as `not stated — {file}:{line}` where no answer was collected. An unfilled reason is honest; an invented one is not.

### Step 7: Close the Loop

- If every task in scope is implemented, its blueprint markers are gone, and its Verification criterion is met, ensure the task is checked `[X]` in the `blueprint.md` Checklist — the same condition and the same limits as `/speckit.blueprint.cleanup` Step 6. If the checklist does not use `- [ ] T{ID}` rows, or `blueprint.md` is not writable, skip the update and say so in the report.
- The checklist tracks implementation, not comprehension. A DOES NOT HOLD verdict never unchecks a task and never edits the blueprint — it belongs in the report and in the export's "Open for the reviewer" list.
- Suggest the next step: fix what the grading surfaced, then open the PR with the exported section.

## Rules

- **Ask before telling**: no blueprint rationale, implementation note, or rejected alternative appears before the developer has answered. After grading, quoting it is the whole point.
- **Never grade your own answers**: if no human answered, the command ends at the questions.
- **Never bluff a verdict**: cite the line or the blueprint section, or say you cannot verify. Sycophantic grading is the one failure mode that makes this command worse than useless.
- **Ground every question in code on disk**: read the developer's files; never quiz from the blueprint's version of what the code would be.
- **Read-only on code**: this command never edits source files. The single write it may make is checking off completed tasks in `blueprint.md`'s Checklist, under Step 7's conditions.
- **State the scope before quizzing**: name the tasks selected and the ones excluded, with the reason each was excluded. A wrong guess about scope must be visible to the developer, not silent.
- **Implemented means the change is there**: for a task that modifies an existing file, look for what the task prescribed; a file on disk proves only that it was on disk before.
- **Stop rather than fabricate**: no blueprint, an unknown scope, or an unimplemented one gets the message and a stop.
- **Five questions, not fifteen**: aim for 5, cap at 8, and go under when the scope holds fewer real decisions. A long quiz gets skimmed, and a skimmed quiz grades nothing.
- **The export must stand alone**: reproduce reasons in it; a reviewer who has to open `blueprint.md` to use it is back where they started.
- Follow the language used in existing spec/plan/tasks documents when writing questions and the report.
