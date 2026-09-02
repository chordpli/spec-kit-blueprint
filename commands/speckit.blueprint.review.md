---
description: "Check what the developer decided after implementing, export the decision list for review, and send the doubts typing raised back to the artifacts that caused them"
---

# Blueprint Review

## Why This Exists

A blueprint states obligations and never collects on them. A guide-mode task says "decide the rounding and be able to explain why"; the developer types the first form that comes to mind, twenty-three tests go green, and nothing ever asks. Green tests measure behavior, not understanding — and the developer who cannot reconstruct the reason a week later did not learn the design, they transcribed it. That is precisely the failure this extension exists to prevent, and until now nothing in it looked at the developer's output: `/speckit.blueprint.validate` checks the document, `/speckit.blueprint.cleanup` checks the residue. This command checks the person.

The second cost is paid by the reviewer. From the final diff, nobody can tell which lines the blueprint dictated and which the developer designed alone. A reviewer who wants to ask a useful question must first read the whole blueprint — so they don't, and attention spreads evenly across code that deserves it very unevenly. The lines nobody agreed on in advance are exactly the lines review is for.

The third cost is paid upstream, and it is paid in silence. Typing is when earlier decisions get tested: you are transcribing a signature, you reach a shape that feels wrong, and the doubt is not about the line under the cursor but about `spec.md`, `plan.md`, or a decision record. A blueprint is unusually good at producing that moment — it puts a decision, its rationale, its rejected alternative, and the code it yields on one screen, which is exactly the material you need to notice that an earlier decision does not hold. Until now this extension had nowhere to put it. Open Questions record what the *generator* could not decide; `ask` records what the *developer* decided; nothing recorded what the developer came to **doubt about the stages before the blueprint**. By the time the PR is open the doubt has been typed past and rationalized away, and the spec keeps the flaw.

This command runs **after implementing a phase or story and before opening the PR** — except in `upstream` mode, which runs while the typing is still happening. It asks about the decisions the blueprint delegated, grades the answers against what the blueprint and the code actually say, exports a decision list a reviewer can use without opening `blueprint.md`, and routes doubts back to the artifact that caused them. It reads code — it never writes it.

## User Input

```text
$ARGUMENTS
```

| Keyword | Mode | Behavior |
|---------|------|----------|
| _(default)_ | `ask` | Extract decisions, ask the questions, wait for answers, grade, export. |
| `export` | `export` | Skip the questions entirely. Produce only the decision list for the PR description. |
| `upstream` | `upstream` | Collect the doubts typing raised about the stages *before* the blueprint, classify them, and write a change request for each one the artifacts cannot answer. Does not require the scope to be implemented. |

The rest of the argument is the **scope**: a phase (`Phase 3`), a user story (`US2`), a task range (`T012-T018`), or a single task ID. A directory path overrides the feature directory (otherwise auto-detect from the current branch, same as `/speckit.blueprint.validate`). In `upstream` mode the remaining text may also be the doubt itself — `upstream T014 why is the lock taken here and not in the caller`.

With no scope given, the scope is **every implemented task in the feature**, across all phases — that is the unit the developer just finished and the unit the PR will cover. Name a phase, a story, or a range explicitly to narrow it. Step 2 decides what "implemented" means and makes the command state the scope it picked before it asks anything. `upstream` mode scopes differently, for reasons given in Step U1: it takes every task the developer has read or started, finished or not.

## Workflow

### Step 1: Load the Blueprint and Resolve Scope

Run the prerequisites check from the repository root:

```bash
.specify/scripts/bash/check-prerequisites.sh --json --paths-only
```

Parse `FEATURE_DIR` and load `blueprint.md`. Read the `**Mode**:` token from the header — it tells you how much the blueprint dictated, which changes where the questions come from (Step 3). If the header carries a `**Sources**:` line, compare the recorded hashes against the current artifacts; on a mismatch, say so in the report and continue — the questions still stand, but the blueprint they came from is describing an older intention.

Resolve the scope to a concrete task list — Step 2 decides which tasks count as implemented, and what the scope is when the arguments name none; in `upstream` mode Step U1 does, and implementation is not required — then read **the developer's actual files** for those tasks from disk. Every question and every verdict must be grounded in the code as it exists now, not in what the blueprint said it would be.

### Step 2: Decide What Is Implemented, Then Refuse to Run on Nothing

> This step governs `ask` and `export`. `upstream` mode keeps only the missing-blueprint stop and the unknown-scope stop; unimplemented code is its normal input, not a reason to stop. See Step U1.

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

**Where it goes.** `ask` prints its report to the conversation. `export` writes the section above to `specs/{feature}/review-decisions.md` and prints the path — it is the artifact the PR links, so it has to be a file. `upstream` writes its change requests to `specs/{feature}/review-upstream.md`, one file per run (append a dated heading when the file exists, never overwrite an earlier run's requests), and prints the path. These are the only files any mode writes.

### Step 7: Close the Loop

- If every task in scope is implemented, its blueprint markers are gone, and its Verification criterion is met, ensure the task is checked `[X]` in the `blueprint.md` Checklist — the same condition and the same limits as `/speckit.blueprint.cleanup` Step 6. If the checklist does not use `- [ ] T{ID}` rows, or `blueprint.md` is not writable, skip the update and say so in the report.
- The checklist tracks implementation, not comprehension. A DOES NOT HOLD verdict never unchecks a task and never edits the blueprint — it belongs in the report and in the export's "Open for the reviewer" list.
- Suggest the next step: fix what the grading surfaced, then open the PR with the exported section.

## Upstream Mode: Doubts That Point Backwards

`ask` runs forwards — it takes the blueprint as settled and checks the developer against it. `upstream` runs the other way: it takes the developer's doubt as the signal and checks the blueprint, and then the artifact behind it, against the code. Steps U1-U5 replace Steps 3-7; Step 1 still loads the blueprint and resolves the feature directory.

This mode adds **nothing** to the blueprint format. Everything it needs — a `**Why**` that cites its source, `**Requirements**` ids, a Key Decisions row with a `Source` column, an Open Questions table with an owner — is already required by `/speckit.blueprint.generate`. A per-task "doubt" field would be one more prose rule no script can enforce, on a generation spec that is already long, and the citation the Why already carries is a better address than anything a new field would hold.

### Step U1: Collect the Doubts — Never Invent Them

**Scope, and why it is not the implemented set.** Unlike `ask`, this mode does not require the scope to be implemented. The strongest doubts arrive three lines into a signature, before anything runs; a mode that waited for green tests would collect them after they had been argued away. The scope is every task the developer has read or started — with none named, the phase they are working in. Say the scope you picked, as Step 2 requires, and mark which tasks in it are unfinished, because Step U3 holds them to a different evidence bar.

**Where the doubts come from — two sources, and neither is you:**

1. **The developer states them**, in the arguments or in answer to the prompt below. A doubt in their own words is the input; paraphrase it in the report but never replace it.
2. **With no doubt given**, print one line per task in scope — the task id, what it does, and the address its Why resolves to — and ask which of them felt wrong while typing. Then **stop and wait**, on the same terms as Step 4: do not supply doubts on the developer's behalf, and do not proceed on invented ones. A manufactured doubt sent to a spec owner is worse than having no mode at all.

One thing you may raise unprompted: a contradiction you find between a task's Why and the section it cites while resolving addresses in Step U2. It carries its own evidence and needs nobody to have felt it. Label it *found, not reported*, and classify it like any other.

### Step U2: Address Each Doubt from Its Why

A doubt is useless until it has a destination. The blueprint already records one for every task, because Step 3b of the generation spec requires each Why to be traced to a real artifact and to cite it — `plan.md §Locking`, `ADR-0007`. That citation is the address.

| The doubt is about | Read | The address it yields |
|--------------------|------|-----------------------|
| the shape of one task's code | that task's `**Why**` | the artifact and section it cites — the primary address |
| what the task is meant to achieve at all | the task's `**Requirements**` ids | the requirement statement, reproduced in the blueprint's reference section and owned by `spec.md` |
| a choice several tasks share | the Key Decisions row whose Tasks column contains the task | the row's `Source`, plus its rejected alternative — which is often the answer rather than the address |
| the order things happen in | the phase's `**Why this phase**` | the story or plan section that fixed the ordering |

**When the Why cites no artifact.** Step 3b lets a Why give the honest engineering reason where no artifact explains the choice. Such a task has no upstream address: the blueprint is where that decision was born. A doubt landing there is not a change request — it is an Open Questions row that was never written, and it goes to whoever owns the blueprint. Say that, rather than posting it to the nearest plausible section. This mode spends one scarce thing, a spec owner's attention, and misdelivery spends it for nothing.

### Step U3: Classify — Three Things That Feel Identical While Typing

Three places hold the story: the **code** on disk, the **blueprint's account** of the design, and the **cited artifact** itself. Every doubt is a mismatch between two of them — and at the keyboard all three failures feel the same, *this shape is wrong*, which is why the developer cannot be asked to classify their own doubt. Read all three yourself before naming a class.

Compare them in this order. The order is the whole point: a blueprint that misquotes its source manufactures artifact defects that were never in the artifact, and checking the artifact last means filing one of them upstream.

| # | Comparison | Outcome |
|---|------------|---------|
| 1 | Open the cited section. Does it say what the blueprint says it says? | No → **BLUEPRINT MISREADS**. Stop — the artifact is fine. A section that admits both readings passes here; see the ambiguity rule below |
| 2 | Do the blueprint's Why, its rejected alternative, or the cited section already answer the doubt? | Yes → **ANSWERED**. Stop — it goes back to the developer |
| 3 | Does the artifact cover the case typing produced? | No, or covers it two ways at once → **ARTIFACT DOES NOT HOLD** |
| — | none of the three can be established | **UNCLASSIFIED** |

What each class costs and where it goes:

| Class | Whose defect | Evidence the report must carry | Destination |
|-------|--------------|--------------------------------|-------------|
| **ANSWERED** | nobody's — the design was there and was missed | the sentence that answers it, quoted, with its location | back to the developer (Step U4) |
| **BLUEPRINT MISREADS** | the blueprint's | the artifact's sentence and the blueprint's sentence, side by side | the blueprint's own fix list — correct the task or regenerate; upstream hears nothing |
| **ARTIFACT DOES NOT HOLD** | the artifact's | the concrete case the artifact does not cover, and where it appeared in the code | a change request (Step U5) |
| **UNCLASSIFIED** | unknown | all three readings, and the evidence that would settle it | the report, addressed to nobody |

Rules for classifying:

- **Never guess a class to avoid an UNCLASSIFIED.** This is the same discipline as "cannot verify from the code" in Step 5, and it matters more here, because the cost lands on someone else. A change request filed against a section that turns out to say the right thing costs a spec owner a reading and costs this mode its credibility — the second one will not get opened.
- **Staleness is not a misreading.** If Step 1's `**Sources**` check flagged the cited artifact as changed since generation, comparison 1 will fail for a blueprint that was correct when it was written. Re-run comparison 1 against the artifact as it stands now: if it passes, continue to comparison 2; if it still fails, report the blueprint as **stale** rather than wrong. The distinction decides who fixes it — stale is a regeneration, wrong needs a person.
- **Ambiguity is a defect, not a tie.** Where the cited section is compatible with both the blueprint's reading and the developer's, comparison 1 neither passes nor fails. That is `ARTIFACT DOES NOT HOLD`: an artifact that admits two readings has already failed at deciding. Its change request's evidence is the two readings, stated as such — do not dress an ambiguity up as a contradiction.
- **Where ambiguity and misreading are the same evidence.** The rule above needs a reading the section actually admits — and comparison 2 passes on the blueprint's reading alone, so an ambiguous section reaches ANSWERED before it ever reaches comparison 3. Break the tie on what the developer's reading rests on: a sentence in the section that supports it makes the section ambiguous, and the class is `ARTIFACT DOES NOT HOLD`; a reading nothing in the section's text supports makes it ANSWERED, and the report shows them the sentence. Where neither holds — the section is silent rather than ambiguous, and both readings are inventions — the class is UNCLASSIFIED, not whichever of the two is more useful. This is the one place the three classes rest on a judgment instead of a comparison, so the report names the reading it took and why.
- **The half-finished task.** Comparisons 1 and 2 are document work and need no code at all, so a doubt from a task typed halfway can still be ANSWERED or BLUEPRINT MISREADS with full evidence. Comparison 3 needs a case — but a case can exist before its code does: a signature with no defined behavior for an input, a type the artifact requires that no module supplies, a call order the declared port cannot express. Where the case exists only in code not yet written, record the doubt as **provisional**, say what would confirm it, and open no change request. A change request resting on code that does not exist is a prediction.

### Step U4: Return What Is Already Answered

This mode is not a complaint box, and the rule that keeps it from becoming one is stated here rather than implied. A doubt that names no line and no case is a feeling; a doubt the blueprint or the cited artifact already answers is a reading that did not happen. **Neither goes upstream.** Both go back to the developer — with the answer, not with a verdict:

```
Answered without going upstream

- T014, "why is the lock taken here and not in the caller" — blueprint.md T014 **Why**, and `plan.md §Locking` para 3: the caller may be a batch, and a lock held across a batch serializes tenants. The caller-side lock you were reaching for is that section's rejected alternative.
- T009, "the retry count feels arbitrary" — no line, no case: the doubt does not yet say what breaks at 3 that survives at 5. Bring it back with one.
```

In most runs this should be the longest section of the report. A run in which every doubt became a change request is a sign the classification was skipped, not a sign the spec is unusually bad — the same way a quiz where every answer MATCHES means the questions were too easy.

### Step U5: Write the Change Requests

One per surviving `ARTIFACT DOES NOT HOLD`, addressed to the artifact and section its Why cited. The reader is that section's owner, who has never opened `blueprint.md` and will not open it now:

```markdown
### CR-1 → `plan.md §Locking`

**Assumed**: {what the section takes for granted, quoted in its own words}
**Typing revealed**: {the case it does not cover — the input, state, or call order — and where it showed up: `OrderService.kt:88`, while typing T014}
**Affected**: T014, T017 — {what each had to do about it}
**What would have to change**: {the smallest edit that settles it: a sentence, a row in a table, a new decision record}
**Who can answer**: {the Open Questions "Who can answer" entry for this artifact, or the section's owner}
**Not verified**: {what you could not check — omit the line only when there is nothing}
```

Rules for a change request:

- **It must survive without the blueprint.** Quote the artifact's own sentence and describe the code in its own terms. A request whose evidence is "see T014" is a pointer, not a report. Task ids stay in it so the owner can trace back, but nothing load-bearing may live only there.
- **One doubt, one request** — two doubts about the same section stay two requests, unless a single edit settles both.
- **Say what would change, not only what is wrong.** The owner's next action is an edit to their document; a request that stops at the complaint makes them design the fix from scratch.
- **Carry the uncertainty.** `Not verified` is what keeps this mode usable a second time.

### How This Relates to Open Questions and to `ask`

An `ARTIFACT DOES NOT HOLD` doubt and an unanswered Open Questions row are the same finding at different times: both say the artifacts do not decide something the code needs. The generator finds them by reading artifacts; this mode finds them by typing against them. So they share machinery instead of duplicating it:

- **Check the Open Questions table before writing a change request.** If a row already names this gap, do not open a CR — attach the case typing produced to that row and address it to that row's owner. A second ticket for a known gap is noise; a known gap with a concrete case attached is an escalation.
- **Reuse the "Who can answer" column** as the addressee whenever a row names the same artifact. It is the only place the blueprint records who owns what.
- **`ask` hands doubts to this mode.** Two of its outcomes are doubts in disguise: a silently resolved Open Question (Step 3) and an answer that surfaces a genuine defect in the blueprint (Step 5). Run both through Step U3 rather than writing them into the export as prose. Where both modes ran in one session, the export's "Open for the reviewer" list cites the CR id and lets the change request carry the detail.
- **Neither mode edits an artifact.** `upstream` writes its requests to `specs/{feature}/review-upstream.md` and nothing else: it never touches `spec.md`, `plan.md`, a decision record, or `blueprint.md` — not even the Checklist that Step 7 may write, since nothing here established that a task is done.

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
- **Never manufacture a doubt**: `upstream` mode collects what the developer felt while typing. With nobody to state one, it ends at the prompt — the same discipline as never grading your own answers.
- **Check the blueprint against the artifact before blaming the artifact**: a blueprint that misquotes its source invents defects that were never upstream. Comparison order is not a preference; it is what keeps this mode from wasting a spec owner.
- **Say UNCLASSIFIED rather than guess**: an honest "these three readings, and here is what would settle it" beats a confident misdelivery. A wrong change request is paid for by someone who cannot see how it was produced.
- **A change request stands alone**: its reader has never opened `blueprint.md` and never will.
- **Read-only on the artifacts too**: `upstream` mode never edits `spec.md`, `plan.md`, or a decision record. It writes requests; a person decides.
- Follow the language used in existing spec/plan/tasks documents when writing questions and the report.
