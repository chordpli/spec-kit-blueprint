# R14 guru controlled verification generation

These assets retain the exact before/half/complete application commits from the
existing S7 guru Git bundle. Only the two blueprint documents and a new generation
input are overlaid; application source, CLI, tests, package and original spec/task
inputs stay unchanged. A and B task IDs intentionally overlap.

`manifest.json` pins commits, asset hashes and expected command exits. Each
blueprint carries runnable Node heredoc assertions under Verification; no helper
file must be created in the app. The new `docs/r16-verification-boundary.md` is the
actual R16 generation input explaining focused scope and acceptance evidence; its
hash is stamped in Sources to justify changed verification text. B restamps the
modified Base blueprint. B's header `1 new, 3 modified` is separately corrected
to `1 new, 4 modified`, matching its existing task declarations; no new app task
or app implementation is supplied.

To reproduce, clone `tests/corpus/s7/projects/project-guru.bundle` into an unused
output directory for each state, checkout the manifest's exact commit, and copy
that state's `specs/` and `docs/` assets over the clone. From each clone, invoke
the extension source's absolute script paths:

```bash
python3 /path/to/extension/scripts/python/validate_blueprint.py specs/001-idempotent-transfer --strict-guide
python3 /path/to/extension/scripts/python/validate_blueprint.py specs/002-transfer-history --strict-guide
python3 /path/to/extension/scripts/python/apply_blueprint.py specs/001-idempotent-transfer --verify --verify-scope feature
python3 /path/to/extension/scripts/python/apply_blueprint.py specs/002-transfer-history --verify --verify-scope feature
npm test
```

| State | A/B document | A focused | B focused | Repository suite |
|---|---:|---:|---:|---:|
| before | 0 / 0 | 0 | 1 | 1 |
| half | 0 / 0 | 0 | 1 | 0 |
| complete | 0 / 0 | 0 | 0 | 0 |

B's red result in before/half is the no-output CLI failing the JSON assertion;
before also fails the documentation assertion. Half's original repository suite
is green despite the CLI defect; the new focused assertion closes that observed
hole. Complete passes without changing application files. No-op CLI, unwanted
write and domain mutations are separate controls against completed-app copies;
the real before/half states are not synthetic fault injection.

This is a controlled regeneration example derived from the reusable generation
recipe, not a blinded new-feature study or a fresh guru score. Passing the declared
assertions does not prove every business contract.
