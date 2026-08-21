---
description: "Validate scaffold files against the blueprint"
---

# Validate Blueprint Scaffold

Validate that scaffold files created by `/speckit.blueprint.generate scaffold` are correct — files exist, TODO markers are present in business logic, and no scaffold file is over-implemented.

## User Input

```text
$ARGUMENTS
```

If arguments contain a directory path, use it as the feature directory. Otherwise, auto-detect from the current branch.

## Prerequisites

- `blueprint.md` must exist (run `/speckit.blueprint.generate` first)
- Scaffold mode must have been used to create files

## Execution

Run both validators from the repository root. The first checks the blueprint document, the second checks what it put on disk:

```bash
python3 .specify/extensions/blueprint/scripts/python/validate_blueprint.py "$FEATURE_DIR"
bash .specify/extensions/blueprint/scripts/bash/validate-scaffold.sh "$FEATURE_DIR"
```

The document validator runs in every mode — a doc-only or guide blueprint has no files on disk to check, but its own contents still have to hold up. The scaffold validator short-circuits for those modes unless you pass `--strict`.

Where `$FEATURE_DIR` is the `specs/{feature}/` directory path. If not provided by the user, resolve it automatically:

1. Get the current git branch name
2. Extract the numeric prefix (e.g., `003` from `003-user-auth`)
3. Find the matching directory under `specs/`

## Validation Checks

### Document checks (`validate_blueprint.py`)

Format-level, so they hold for any language:

1. **Task coverage**: every task id in `tasks.md` reaches the blueprint
2. **Rationale**: every task section carries a `**Why**`
3. **Working-tree claims**: `Before` line references land inside their files, and every `After` differs from its `Before`
4. **Multi-file labels**: a task naming more than one file labels each authored code block with its path
5. **Placeholders**: no ellipsis stubs; in `doc-only`/`scaffold` modes, no TODO/FIXME markers in code blocks

### Scaffold checks (`validate-scaffold.sh`)

The script reads the `**Mode**:` line from `blueprint.md` first. `doc-only` and `guide` write nothing to disk, so for those modes only check 1 runs and missing files are reported as expected, not as failures. Scaffold modes (`scaffold`, `guide scaffold`) run all four checks:

1. **Blueprint Document**: Verifies `blueprint.md` exists
2. **File Existence**: All NEW files referenced in the blueprint exist on disk (placeholder/glob paths such as `docs/2026-MM-DD-*.md` are skipped)
3. **TODO Markers**: Service and test files contain TODO comments (confirming scaffold mode)
4. **Over-Implementation Detection**: No scaffold file is suspiciously complete (zero TODOs + many methods + many lines)

## Output

The script outputs color-coded results:
- Green checkmarks for passing checks
- Yellow warnings for non-critical issues
- Red failures for problems that must be fixed

Exit code 0 means pass (possibly with warnings), exit code 1 means failure.

## Troubleshooting

### "blueprint.md not found"
Run `/speckit.blueprint.generate scaffold` first to generate the blueprint and scaffold files.

### "File MISSING"
A file referenced in the blueprint was not created. Re-run `/speckit.blueprint.generate scaffold` or create the file manually.

### "No TODO markers found"
A service or test file appears fully implemented. In scaffold mode, business logic should contain TODO comments. Check if the file should have been generated in scaffold mode.
