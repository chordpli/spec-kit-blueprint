# The regression corpus

Every fixture here is a blueprint plus the exact set of findings the tools must produce
for it. `scripts/python/self_test.py` runs them and fails on any difference.

## Why this exists

A blueprint is half quotation. A `**Before**` shows a file as it is; an `**After**`
repeats that context around the change; `**Replace entire file**` reprints a whole
existing file to change six lines of it. Mistaking any of it for what the document wrote
is the error this repository has made most often, in both directions:

- v1.1.0 diagnosed it in the multi-file-label check, which had dropped every hunk and so
  never fired on a task made only of hunks — nine rounds dead.
- The **same release**, ten lines away in the same file, shipped two new checks with the
  same error. One counted the next task's quotation of a marker as a second and third
  author. The other read only non-hunk blocks, which in guide mode is the half nobody
  types, and prescribed stamping this feature's number onto identifiers a previous
  feature had written.

Three reviewers found this independently. The lesson had been written down in a comment
and in the release notes, and it did not survive contact with the next check anybody
added. A comment is not a mechanism.

## What this corpus was worth, measured

The first version of it was three clean documents, each run through the three tools once
with no flags. A reviewer planted 46 regressions into a copy of the extension and asked
it about each one. **It caught 14.** By category: 7 of 14 attempts to undo the
authored/quoted judgment, 2 of 8 checks switched off outright, 0 of 5 checks downgraded
from failure to warning, and **0 of 9 defects this repository had already announced
fixing**. A second reviewer measured 4 of 12 independently.

Two things were wrong with it, and neither was the level of detail in `expected.txt` —
the reviewer tested that too, pinning per-section pass counts and the PASS/WARN/FAIL
summary, and the number did not move at all:

1. **Twelve flags change behaviour and the corpus ran none of them.** `--done`,
   `--markers`, `--fresh`, `--strict-guide` and the unknown-option guard could each be
   deleted outright and the corpus still said `3 of 3 ok`.
2. **Every fixture was a clean document.** A check that never fires cannot be observed to
   have been switched off or downgraded. That is why five checks could be lowered from
   fail to warn without a single one being noticed.

So the corpus now runs thirteen command lines per fixture, and three of the six fixtures
are **red on purpose**. The current score against the same 46 regressions is recorded in
the release notes.

## The rule

**A check that reads code calls `_blueprint_parse.authored_blocks()` and nothing else.**

Not `strip_quoted` — that drops hunks entirely, and its regex needs a bare-word fence
info string, so ```` ```c++ ```` slips through it. Not the raw section — that counts
quotations as authorship. `authored_blocks()` is the one place the difference is
decided, and it tags each chunk with the role the document gave it (`block`, `after`,
`reprint`) so a check that assigns blame can tell a reprint from an authored block.

**Three** checks are exempt, each saying so in its own comment beside the code:

| exempt check | why |
|---|---|
| the abbreviation check in section 3 | it reads `**Before**` blocks deliberately — the abbreviation is *in* the quotation |
| the JavaScript invented-type check | it needs the fence's language, which an After's added lines have nowhere to carry |
| the skeleton-drift check in section 3 | it compares a block to a file on disk byte for byte, so it needs the block as written rather than the lines an After adds |

This table said "one", `speckit.blueprint.validate.md` said "two", and the code had three.
A document about mechanisms that cannot count its own exceptions is the thing this corpus
exists to replace.

## Adding a check

1. Write it against `authored_blocks()`.
2. Measure it over a real corpus before you keep it. This is not optional and it is not
   ceremony: of the four prose rules proposed in one round, the corpus said two were
   clean (1 hit and 0 hits) and two were disasters (1,137 hits, all hyphenated English
   words like `zero-length`; 98 hits, all `text/csv`). The two disasters had been asked
   for by name, by two different reviewers.
3. **Add a fixture that makes it fire**, and check that `quoted-not-authored` and
   `quoting-only` still pass — those two catch the authorship mistake in its two
   directions.
4. Run `python3 scripts/python/self_test.py`.
5. Run `python3 scripts/python/self_test.py --coverage`. It lists every finding the three
   scripts can print that no fixture has ever produced. If yours is still on that list,
   step 3 did not happen.

## The fixtures

| fixture | red? | what it pins down |
|---|---|---|
| `clean-guide` | no | the shape the generate rules recommend produces no findings at all — including a `**Sources**` stamp that is current, which is the only fixture that exercises the freshness check's passing path |
| `quoted-not-authored` | no | a marker authored once and quoted **three** times is one author; a bare id inside a reprinted file is not this document's to renumber |
| `quoting-only` | no | every shape the code checks for — an ellipsis, a history comment, body logic, a marker with no task id — appears **only inside quotations**, so any check that starts reading the raw section speaks up. Also: a declared name that appears in the file as a mention rather than a declaration is still missing |
| `authored-in-a-hunk` | no | the lines an After ADDS are authored — a check blind here is blind where guide mode's developer types |
| `dirty-guide` | **yes** | fourteen checks that say nothing about a clean document: empty new file, unlabelled multi-file blocks, ellipsis, history comment, abbreviated Before, smuggled body, duplicate task id, lossy hunk, a stale `**Sources**` stamp, and markers on disk that `--markers` has to list |
| `broken-hunks` | **yes** | the six hunk failures in section 3 — identical pair, ambiguous anchor, absent Before, dangling Before, absent modify file, mislabelled block, unanchored block. None of them had ever fired inside this corpus |

Two of the red fixtures carry exactly one defect per task, so a change to any one check
moves exactly one line of `expected.txt`.

## Updating expected.txt

`--update` used to rewrite the files in silence. Plant a regression, run it, and the
corpus adopted the regression as its new truth; the docstring said "read the diff first",
which is a request rather than a mechanism. It now prints the diff whether you want it or
not and refuses to write. Writing takes a second flag:

```bash
python3 scripts/python/self_test.py --update                     # shows the diff, writes nothing
python3 scripts/python/self_test.py --update --i-read-the-diff   # writes it
```

Commit the fixture update in the same commit as the change that caused it. If any line of
the diff surprises you, that line is the regression this corpus exists to catch.
