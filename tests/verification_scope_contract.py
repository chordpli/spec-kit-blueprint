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

    def test_scope_is_not_guessed(self):
        self.assertEqual(applier.test_scope('**Test**: `npm test`'), 'unspecified')
        self.assertEqual(applier.test_scope('**Test Scope**: feature'), 'feature')


if __name__ == '__main__':
    unittest.main()
