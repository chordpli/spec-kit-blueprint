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

## The rule

**A check that reads code calls `_blueprint_parse.authored_blocks()` and nothing else.**

Not `strip_quoted` — that drops hunks entirely, and its regex needs a bare-word fence
info string, so ```` ```c++ ```` slips through it. Not the raw section — that counts
quotations as authorship. `authored_blocks()` is the one place the difference is
decided, and it tags each chunk with the role the document gave it (`block`, `after`,
`reprint`) so a check that assigns blame can tell a reprint from an authored block.

One check is exempt and says so in its own comment: the JavaScript invented-type check
needs the fence's language, which an After's added lines have nowhere to carry.

## Adding a check

1. Write it against `authored_blocks()`.
2. Measure it over a real corpus before you keep it. This is not optional and it is not
   ceremony: of the four prose rules proposed in one round, the corpus said two were
   clean (1 hit and 0 hits) and two were disasters (1,137 hits, all hyphenated English
   words like `zero-length`; 98 hits, all `text/csv`). The two disasters had been asked
   for by name, by two different reviewers.
3. Add a fixture here that proves it fires, and check that `quoted-not-authored` still
   passes — that is the one that catches this mistake.
4. Run `python3 scripts/python/self_test.py`.

## The fixtures

| fixture | what it pins down |
|---|---|
| `quoted-not-authored` | a marker authored once and quoted twice is one author; a bare id inside a reprinted file is not this document's to renumber |
| `authored-in-a-hunk` | the lines an After ADDS are authored — a check blind here is blind where guide mode's developer types |
| `clean-guide` | the shape the generate rules recommend produces no findings at all |
