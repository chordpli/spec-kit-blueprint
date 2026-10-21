#!/usr/bin/env python3
"""task_hunks.py BLUEPRINT ROOT HEAD — which (modify) tasks left their part of a file untouched.

validate-scaffold.sh --done asks this per task. Its own check is per file: a file a
(modify) task changes that is byte-identical to the stamp. Two tasks that edit one file
share that answer, so the later one was never seen to be missing. This prints one row per
task whose every hunk region still reads as the stamped commit had it:

    untouched<TAB>T006<TAB>src/ledger.js

and one row per task whose hunks could not be placed on the stamped files (not measured):

    unplaced<TAB>T006<TAB>why

Exit 0 when it could answer, 2 when it could not read the blueprint.
"""
from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apply_blueprint  # noqa: E402  (path set above)
from _blueprint_parse import split_tasks  # noqa: E402


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__.strip().split("\n")[0], file=sys.stderr)
        return 2
    bp_path, root, head = sys.argv[1:]
    try:
        with open(bp_path, encoding="utf-8", errors="replace") as f:
            bp = f.read()
    except OSError as exc:
        print(f"cannot read {bp_path}: {exc}", file=sys.stderr)
        return 2
    untouched, unplaced = apply_blueprint.untouched_tasks(root, head, split_tasks(bp))
    for tid, path in untouched:
        print(f"untouched\t{tid}\t{path}")
    for tid, why in unplaced.items():
        print(f"unplaced\t{tid}\t{why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
