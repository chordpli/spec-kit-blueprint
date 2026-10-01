# R15 R14 project history capsule (tracked corpus)

This capsule preserves the three R14 project repositories as compact Git bundles.
Each bundle contains the complete history reachable from that project's final `HEAD`; the adjacent `.verify.txt` file is the `git bundle verify` output.

| project | bundle | final HEAD |
|---|---:|---|
| novice | 262,037 bytes | `1bb97526918b00c834d0fe6a5771c0cc0ecdc344` |
| senior | 270,596 bytes | `751a30839d9741eabdebd476ae9ed05ab7bee4a6` |
| guru | 290,548 bytes | `cf57436065292db3c1c5adc0173a7a40a78f129e` |

The exact SHA-256 values and baseline/half/complete/evidence commits are in `PROJECTS.json`.
No credential-like tracked paths (`.env`, credential, secret, token, password, or key names) were found in these project indexes.

To restore one project into a new directory:

```sh
git clone tests/corpus/s7/projects/project-novice.bundle novice
cd novice
git checkout -q 1bb97526918b00c834d0fe6a5771c0cc0ecdc344
```

From this directory, replace the bundle and final commit for `senior` or `guru` using `PROJECTS.json`; verify first with `git bundle verify project-*.bundle`.
