"""Executable contracts for verification scope, ownership and bounded evidence."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import os
import shutil
import subprocess
import sys
import unittest
import warnings
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'scripts/python/apply_blueprint.py'
spec = importlib.util.spec_from_file_location('scope_applier', MODULE)
applier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(applier)


class ScopeContracts(unittest.TestCase):
    def run_gate(self, tasks, header='', scope='all', base=None, partial=False):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'a.py').write_text('assert True\n')
            Path(root, 'b.py').write_text('raise AssertionError("B remains red")\n')
            def tree(_):
                import shutil
                dest = tempfile.mkdtemp()
                shutil.copytree(root, dest, dirs_exist_ok=True)
                return dest
            out = io.StringIO()
            with patch.object(applier, 'copy_tree', tree), contextlib.redirect_stdout(out):
                rc = applier.run_verifications(root, tasks, header, False, scope, base, partial)
            return rc, out.getvalue()

    def test_feature_a_isolated_from_red_repository_b(self):
        a = [('specs/a/T001', '**Verification**: `python3 a.py`')]
        header = '**Test**: `python3 b.py`\n**Test Scope**: repository\n'
        rc, out = self.run_gate(a, header, 'feature')
        self.assertEqual(rc, 0)
        self.assertIn('omitted from feature gate', out)
        self.assertEqual(self.run_gate(a, header)[0], 1)

    def test_duplicate_task_ids_have_separate_qualified_owners(self):
        a = [('specs/a/T001', '**Verification**: `python3 a.py`')]
        b = [('specs/b/T001', '**Verification**: `python3 b.py`')]
        rc, out = self.run_gate(b, base=a)
        self.assertEqual(rc, 1)
        self.assertIn('results passed: specs/a/T001', out)
        self.assertIn('results failed: specs/b/T001', out)
        self.assertIn('Selected task proof: 1 covered; 0 without runnable commands', out)
        self.assertIn('Base task proof: 1 covered; 0 without runnable commands', out)

    def test_header_dedup_preserves_header_result(self):
        tasks = [('specs/a/T001', '**Verification**: `python3 a.py`')]
        rc, out = self.run_gate(tasks, '**Test**: `python3 a.py`\n**Test Scope**: feature', 'feature')
        self.assertEqual(rc, 0)
        self.assertIn('ran 1 distinct command', out)
        self.assertIn('Header result [feature]: passed', out)

    def test_no_tasks_no_proof_fails(self):
        rc, out = self.run_gate([])
        self.assertEqual(rc, 1)
        self.assertIn('behavior verification unavailable', out)

    def test_missing_task_proof_cannot_complete_feature(self):
        rc, out = self.run_gate([('specs/a/T001', '**Verification**: inspect manually')], scope='feature')
        self.assertGreater(rc, 0)
        self.assertIn('lack runnable verification', out)

    def test_through_is_bounded(self):
        rc, out = self.run_gate([('specs/a/T001', '**Verification**: `python3 a.py`')], partial=True)
        self.assertEqual(rc, 0)
        self.assertIn('future tasks and complete feature behavior are unverified', out)

    def test_unspecified_header_refuses_feature_gate(self):
        rc, out = self.run_gate([('specs/a/T001', '**Verification**: `python3 a.py`')],
                                '**Test**: `python3 b.py`', 'feature')
        self.assertEqual(rc, 2)
        self.assertIn('scope is unspecified', out)

    def test_heredoc_assertions_are_executed(self):
        section = "**Verification**:\n```bash\npython3 - <<'PYCODE'\nassert False, 'body executed'\nPYCODE\n```\n"
        rc, out = self.run_gate([('specs/a/T001', section)])
        self.assertEqual(rc, 1)
        self.assertIn('body executed', out)
        passing = section.replace("assert False, 'body executed'", 'assert True')
        self.assertEqual(self.run_gate([('specs/a/T001', passing)])[0], 0)

    def test_multicommand_block_fails_at_first_failure(self):
        section = '**Verification**:\n```bash\npython3 b.py\npython3 a.py\n```'
        self.assertEqual(self.run_gate([('specs/a/T001', section)])[0], 1)

    def test_quoted_verification_is_not_executed(self):
        section = '> **Verification**:\n> ```bash\n> python3 b.py\n> ```'
        self.assertEqual(applier.verification_commands(section), [])

    def test_strict_header_count_mismatch_fails(self):
        fixture = MODULE.parents[2] / 'tests/fixtures/clean-guide'
        with tempfile.TemporaryDirectory() as root:
            shutil.copytree(fixture, root, dirs_exist_ok=True)
            bp = Path(root, 'specs/012-clean/blueprint.md')
            bp.write_text(bp.read_text().replace('1 new, 1 modified', '9 new, 1 modified'))
            validator = MODULE.with_name('validate_blueprint.py')
            def run(flags):
                return subprocess.run([sys.executable, str(validator), 'specs/012-clean', *flags],
                                      cwd=root, capture_output=True, text=True)
            normal, strict = run([]), run(['--strict-guide'])
            self.assertEqual(normal.returncode, 0, normal.stdout)
            self.assertEqual(strict.returncode, 1, strict.stdout)
            self.assertIn('header\'s file counts do not match', strict.stdout)

    def test_foreign_marker_still_fails_both_bash_versions(self):
        fixture = MODULE.parents[2] / 'tests/fixtures/guide-done-marker'
        scaffold = MODULE.parents[1] / 'bash/validate-scaffold.sh'
        shells = ['/bin/bash', '/opt/homebrew/bin/bash']
        for shell in shells:
            if not Path(shell).exists():
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as root:
                shutil.copytree(fixture, root, dirs_exist_ok=True)
                store = Path(root, 'pkg/store.py')
                store.write_text(store.read_text().replace('T001:', 'T999:'))
                result = subprocess.run([shell, str(scaffold), 'specs/012-clean', '--done'],
                                        cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('other task IDs 1', result.stdout)
                self.assertIn('behavior verification not executed', result.stdout)

    def test_base_application_and_selected_denominators_are_separate(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root, 'specs/a')
            feature = Path(root, 'specs/b')
            base.mkdir(parents=True)
            feature.mkdir(parents=True)
            base.joinpath('blueprint.md').write_text(
                '**Mode**: scaffold\n### T001: Write base\n**File**: `base.py` (new)\n'
                '```python\nBASE = 1\n```\n### T002: Read references\nNo file needed.\n')
            feature.joinpath('blueprint.md').write_text(
                '**Mode**: scaffold\n**Base**: specs/a/blueprint.md\n'
                '### T001: Write selected\n**File**: `selected.py` (new)\n'
                '```python\nSELECTED = 1\n```\n')
            def tree(_):
                dest = tempfile.mkdtemp()
                shutil.copytree(root, dest, dirs_exist_ok=True)
                return dest
            out = io.StringIO()
            with warnings.catch_warnings(), \
                 patch.object(applier, 'repo_root', lambda: root), \
                 patch.object(applier, 'copy_tree', tree), \
                 patch.object(sys, 'argv', ['apply_blueprint.py', str(feature)]), \
                 contextlib.redirect_stdout(out):
                warnings.simplefilter("ignore", ResourceWarning)
                applier.main()
            self.assertIn('Selected application coverage: 1 of 1 task(s) wrote blocks (100%)', out.getvalue())
            self.assertIn('Base application: 1 of 2 task(s) wrote blocks; 1 no-op/reference; 0 not applied', out.getvalue())
            self.assertIn('does not prove behavior', out.getvalue())

    # --- R17: task proof is not feature proof ---------------------------------------

    def test_human_review_prose_is_not_executed(self):
        # The backticked example a reviewer is told to look for is not a command.
        section = ('**Verification**: Human review: confirm README contains '
                   '`python3 b.py` and the exit code it prints.')
        self.assertEqual(applier.verification_commands(section), [])
        self.assertEqual(len(applier.human_reviews(section)), 1)
        tasks = [('specs/a/T001', '**Verification**: `python3 a.py`'), ('specs/a/T002', section)]
        rc, out = self.run_gate(tasks, scope='feature')
        self.assertEqual(rc, 0, out)
        self.assertIn('human evidence not supplied', out)
        self.assertIn('not counted as passed: specs/a/T002', out)
        self.assertNotIn('B remains red', out)
        # A static assertion beside a human line runs; the human part is still listed.
        both = ('**Verification**: `python3 a.py`\n\nHuman review: the wording reads correctly.')
        rc, out = self.run_gate([('specs/a/T003', both)], scope='feature')
        self.assertEqual(rc, 0, out)
        self.assertIn('Task-specific command results passed: specs/a/T003', out)
        self.assertIn('not counted as passed: specs/a/T003', out)

    def test_shared_command_is_claimed_coverage_not_task_status(self):
        shared = '**Verification**: `python3 b.py`'
        tasks = [('specs/a/T001', shared), ('specs/a/T002', shared),
                 ('specs/a/T003', '**Verification**: `python3 a.py`')]
        rc, out = self.run_gate(tasks, scope='feature')
        self.assertEqual(rc, 1)
        self.assertIn('Task-specific command results passed: specs/a/T003', out)
        self.assertIn('Shared command results failed (one result for every claiming task;', out)
        self.assertIn('specs/a/T001, specs/a/T002', out)
        self.assertNotIn('Task-specific command results failed', out)
        self.assertIn('Feature behavior proof: 1 of 2 distinct command(s) passed; 1 failed', out)

    def test_test_file_not_run_by_its_proof_is_unmeasured(self):
        writes_test = ('**File**: `tests/test_store.py` (new)\n\n'
                       '**Verification**: `python3 a.py`')
        rc, out = self.run_gate([('specs/a/T001', writes_test)], scope='feature')
        self.assertEqual(rc, 0)
        self.assertIn('test bodies are unmeasured', out)
        self.assertIn('specs/a/T001 tests/test_store.py', out)
        runs_it = writes_test.replace('`python3 a.py`', '`python3 a.py tests/test_store.py`')
        self.assertNotIn('unmeasured', self.run_gate([('specs/a/T001', runs_it)], scope='feature')[1]
                         .split('Proof summary')[0])
        suite = writes_test.replace('`python3 a.py`', '`python3 -m unittest discover`')
        self.assertTrue(applier.runs_file(applier.verification_commands(suite), 'tests/test_store.py'))
        self.assertFalse(applier.runs_file(['python3 -m unittest tests/test_other.py'], 'tests/test_store.py'))

    def test_test_file_run_by_class_name_is_measured(self):
        # R14 senior: a project runner takes the test class, not the path.
        java = 'src/test/java/ledger/CancellationSuccessTest.java'
        self.assertTrue(applier.runs_file(['./tools/test-cancellation.sh ledger.CancellationSuccessTest'], java))
        self.assertTrue(applier.runs_file(['python3 -m unittest tests.test_store'], 'tests/test_store.py'))
        self.assertFalse(applier.runs_file(['./tools/test-cancellation.sh ledger.CancellationSuccessTestX'], java))
        self.assertFalse(applier.runs_file(['node test/report.js'], 'test/report.test.js'))

    def test_nested_copy_is_refused_by_all_three_tools(self):
        # A copy inside a repository, with no .git of its own, belongs to that repository.
        # R17 printed the root and warned; R18 guru measured the warning beside exit 0 and
        # 12 of 12 on an unimplemented copy inside a finished project. All three refuse.
        validator = MODULE.with_name('validate_blueprint.py')
        scaffold = MODULE.parents[1] / 'bash/validate-scaffold.sh'
        with tempfile.TemporaryDirectory() as outer:
            outer = os.path.realpath(outer)
            subprocess.run(['git', 'init', '-q'], cwd=outer, check=True)
            for base in (outer, os.path.join(outer, 'copy')):
                Path(base, 'specs/a').mkdir(parents=True)
                Path(base, 'specs/a/blueprint.md').write_text(
                    '**Mode**: guide\n### T001: Check\n**Verification**: `python3 -c "print(1)"`\n')
            Path(outer, 'src').mkdir()
            inner = os.path.join(outer, 'copy')
            py = [('apply', [sys.executable, str(MODULE), 'specs/a', '--verify']),
                  ('validate', [sys.executable, str(validator), 'specs/a'])]
            for name, cmd in py:
                with self.subTest(tool=name):
                    nested = subprocess.run(cmd, cwd=inner, capture_output=True, text=True)
                    self.assertEqual(nested.returncode, 2, nested.stdout)
                    self.assertIn(f'Repository root: {outer}', nested.stdout)
                    self.assertIn(f'the feature directory is in {inner}/specs', nested.stdout)
                    # Controls: the root itself, a subdirectory naming the feature from the
                    # root, and a subdirectory naming it relative to where it stands.
                    for cwd, arg in ((outer, 'specs/a'), (os.path.join(outer, 'src'), 'specs/a'),
                                     (os.path.join(outer, 'src'), '../specs/a')):
                        own = subprocess.run([c if c != 'specs/a' else arg for c in cmd],
                                             cwd=cwd, capture_output=True, text=True)
                        self.assertNotEqual(own.returncode, 2, (cwd, arg, own.stdout))
                        self.assertNotIn('the feature directory is in', own.stdout)
            for shell in ('/bin/bash', '/opt/homebrew/bin/bash'):
                if not Path(shell).exists():
                    continue
                with self.subTest(shell=shell):
                    nested = subprocess.run([shell, str(scaffold), 'specs/a'], cwd=inner,
                                            capture_output=True, text=True)
                    self.assertEqual(nested.returncode, 2, nested.stdout + nested.stderr)
                    self.assertIn(f'Repository root: {outer}', nested.stdout)
                    self.assertIn(f'the feature directory is in {inner}/specs', nested.stderr)
                    for cwd, arg in ((outer, 'specs/a'), (os.path.join(outer, 'src'), 'specs/a'),
                                     (os.path.join(outer, 'src'), '../specs/a')):
                        plain = subprocess.run([shell, str(scaffold), arg], cwd=cwd,
                                               capture_output=True, text=True)
                        self.assertEqual(plain.returncode, 0, (cwd, arg, plain.stdout + plain.stderr))
                        self.assertNotIn('the feature directory is in', plain.stderr)

    # --- R18: a test task is proven against the skeleton, not by the app's state -------

    CALC_BP = """# Blueprint: calc

**Mode**: guide — signatures and markers; the developer types the bodies
**Sources**: HEAD {head}

### T001: Double a number

**File**: `pkg/calc.py` (new)

**Why**: one function doubles.

```python
def double(x):
    raise NotImplementedError("T001: return twice x")
```

**Verification**: `python3 -c "from pkg.calc import double; assert double(2) == 4"`

### T002: Test doubling

**File**: `tests/test_calc.py` (new)

**Dependencies**: T001

**Why**: the test fixes the contract.

```python
import unittest
from pkg.calc import double


class CalcTest(unittest.TestCase):
    def test_double(self):
        raise NotImplementedError("T002: assert double(3) is 6")
```

**Verification**: `python3 -m unittest tests.test_calc`
"""
    CALC_TEST = ("import unittest\nfrom pkg.calc import double\n\n\nclass CalcTest(unittest.TestCase):\n"
                 "    def test_double(self):\n        {body}\n")

    def calc_repo(self, root, impl, body):
        git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false']
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        Path(root, 'pkg').mkdir()
        Path(root, 'pkg/__init__.py').write_text('')
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(git + ['commit', '-qm', 'base'], cwd=root, check=True)
        head = subprocess.check_output(['git', 'rev-parse', '--short=12', 'HEAD'], cwd=root, text=True).strip()
        Path(root, 'specs/020-calc').mkdir(parents=True)
        Path(root, 'specs/020-calc/blueprint.md').write_text(self.CALC_BP.format(head=head))
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run(git + ['commit', '-qm', 'blueprint'], cwd=root, check=True)
        Path(root, 'pkg/calc.py').write_text(f'def double(x):\n    return {impl}\n')
        Path(root, 'tests').mkdir()
        Path(root, 'tests/test_calc.py').write_text(self.CALC_TEST.format(body=body))
        proc = subprocess.run([sys.executable, str(MODULE), 'specs/020-calc', '--verify', '--verify-scope', 'feature'],
                              cwd=root, capture_output=True, text=True, env=dict(os.environ, NO_COLOR='1'))
        return proc.returncode, proc.stdout

    def test_test_task_is_proven_against_the_skeleton(self):
        real = 'self.assertEqual(double(3), 6)'
        with tempfile.TemporaryDirectory() as root:
            rc, out = self.calc_repo(root, 'x * 2', real)
            self.assertEqual(rc, 0, out)
            self.assertIn('red on the blueprint\'s skeleton and green here (the test discriminates): specs/020-calc/T002', out)
            self.assertIn('task-specific 2 passed, 0 failed', out)
            self.assertIn('test tasks non-discriminating 0, not measured 0', out)
        # R18 guru: `assert.ok(true)` beside the subject's name passed as task proof.
        with tempfile.TemporaryDirectory() as root:
            rc, out = self.calc_repo(root, 'x * 2', 'self.assertTrue(True)  # double(3) == 6')
            self.assertEqual(rc, 0, out)
            self.assertIn('1 test task(s) pass on the blueprint\'s skeleton as well as here', out)
            self.assertIn('Task-specific command results passed: specs/020-calc/T001\n', out)
            self.assertIn('task-specific 1 passed, 0 failed', out)
            self.assertIn('test tasks non-discriminating 1', out)

    def test_red_test_task_behind_a_red_dependency_is_not_its_own_failure(self):
        # R18 guru: a finished test task was reported failed because the code it tests was.
        with tempfile.TemporaryDirectory() as root:
            rc, out = self.calc_repo(root, 'x * 3', 'self.assertEqual(double(3), 6)')
            self.assertEqual(rc, 1, out)
            self.assertIn('Task-specific command results failed: specs/020-calc/T001\n', out)
            self.assertIn('failed behind a failed dependency (not separable from it): specs/020-calc/T002 <- T001', out)
            self.assertIn('2 failed (1 behind a failed dependency)', out)
        self.assertEqual(applier.blocked_by([('a/T001', ''), ('a/T002', '**Dependencies**: T001')],
                                            {'a/T002'}), {})

    def test_human_evidence_is_tied_to_the_bytes_reviewed(self):
        section = '**File**: `README.md` (modify)\n\n**Verification**: Human review: reads well.'
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'specs/020-calc').mkdir(parents=True)
            Path(root, 'README.md').write_text('# calc\n')
            state, template = applier.human_evidence(root, 'specs/020-calc/T003', section)
            self.assertEqual(state, 'missing')
            sha = applier._blob_sha(os.path.join(root, 'README.md'))
            self.assertEqual(sha, subprocess.check_output(['git', 'hash-object', 'README.md'], cwd=root, text=True).strip())
            self.assertIn(f'T003: <reviewer> <YYYY-MM-DD> README.md@{sha[:12]}', template)
            evidence = Path(root, 'specs/020-calc', applier.HUMAN_EVIDENCE_FILE)
            evidence.write_text(f'T003: rev 2026-10-20 README.md@{sha[:7]}\n')
            self.assertEqual(applier.human_evidence(root, 'specs/020-calc/T003', section),
                             ('supplied', 'rev 2026-10-20'))
            Path(root, 'README.md').write_text('# calc, edited\n')
            self.assertEqual(applier.human_evidence(root, 'specs/020-calc/T003', section)[0], 'stale')
            evidence.write_text('T003: rev 2026-10-20\n')
            self.assertEqual(applier.human_evidence(root, 'specs/020-calc/T003', section)[0], 'stale')

    # --- R18: declarations are read without comments, in any binding form ------------

    def test_declaration_forms_and_comments_both_bash_versions(self):
        # R18 guru: `export const f = (…) =>` failed --done; a header left in a comment passed.
        fixture = MODULE.parents[2] / 'tests/fixtures/js-declaration-forms'
        scaffold = MODULE.parents[1] / 'bash/validate-scaffold.sh'
        for shell in ('/bin/bash', '/opt/homebrew/bin/bash'):
            if not Path(shell).exists():
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as root:
                shutil.copytree(fixture, root, dirs_exist_ok=True)
                result = subprocess.run([shell, str(scaffold), 'specs/018-forms', '--done'],
                                        cwd=root, capture_output=True, text=True,
                                        env=dict(os.environ, NO_COLOR='1'))
                out = result.stdout
                self.assertEqual(result.returncode, 1, out)
                self.assertIn('declares `halved` and the file does not declare it', out)
                self.assertIn('declares `negated` and the file does not declare it', out)
                self.assertNotIn('`doubled`', out)
                self.assertNotIn('`tripled`', out)

    def test_scope_is_not_guessed(self):
        self.assertEqual(applier.test_scope('**Test**: `npm test`'), 'unspecified')
        self.assertEqual(applier.test_scope('**Test Scope**: feature'), 'feature')


if __name__ == '__main__':
    unittest.main()
