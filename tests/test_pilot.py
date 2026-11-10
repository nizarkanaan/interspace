import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('runner', Path(__file__).parents[1] / 'pilot/runner.py')
runner = importlib.util.module_from_spec(SPEC)
if SPEC.loader and Path(SPEC.origin).exists():
    SPEC.loader.exec_module(runner)


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.source = self.base / 'source'
        self.source.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.source / 'README.md').write_text('Committed evidence\nSecond line\n')
        (self.source / 'docs').mkdir()
        (self.source / 'docs/PROJECT_CONTEXT.md').write_text('Current context\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        (self.source / 'README.md').write_text('UNCOMMITTED secret draft\n')
        (self.source / 'private').mkdir()
        (self.source / 'private/notes.txt').write_text('PRIVATE')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.source), *args], text=True).strip()

    def prepare(self):
        return runner.prepare(self.source, self.base / 'storage')

    def result(self, verdict=None):
        data = {'summary': 'Evidence reviewed', 'findings': [{'claim': 'Documented', 'evidence': [{'source': 'README.md', 'start': 1, 'end': 1}]}], 'proposal': 'A bounded check, not executed'}
        if verdict:
            data['verdict'] = verdict
        return data

    def test_snapshot_uses_commit_and_preserves_dirty_checkout(self):
        before = self.git('status', '--porcelain')
        run = self.prepare()
        self.assertEqual((run / 'sources/README.md').read_text(), 'Committed evidence\nSecond line\n')
        self.assertFalse((run / 'sources/private').exists())
        self.assertEqual(before, self.git('status', '--porcelain'))
        self.assertTrue(runner.verify(run)['unchanged'])
        (self.source / 'README.md').write_text('Changed again')
        self.assertFalse(runner.verify(run)['unchanged'])

    def test_missing_required_context_fails_before_run_created(self):
        self.git('rm', 'docs/PROJECT_CONTEXT.md')
        self.git('commit', '-qm', 'remove context')
        with self.assertRaisesRegex(ValueError, 'required'):
            self.prepare()

    def test_completion_rejects_invalid_evidence_and_wrong_order(self):
        run = self.prepare()
        with self.assertRaisesRegex(ValueError, 'order'):
            runner.complete(run, 'reviewer', self.result('accept'))
        data = self.result()
        data['findings'][0]['evidence'][0]['source'] = '../private/notes.txt'
        with self.assertRaisesRegex(ValueError, 'source'):
            runner.complete(run, 'researcher', data)
        data = self.result()
        data['findings'][0]['evidence'][0]['end'] = 9999
        with self.assertRaisesRegex(ValueError, 'line'):
            runner.complete(run, 'researcher', data)

    def test_handoff_is_persisted_and_review_controls_outcome(self):
        run = self.prepare()
        runner.complete(run, 'researcher', self.result())
        self.assertEqual(json.loads((run / 'run.json').read_text())['stage'], 'reviewer')
        runner.complete(run, 'reviewer', self.result('revise'))
        self.assertEqual(json.loads((run / 'run.json').read_text())['stage'], 'needs_revision')
        with self.assertRaises(ValueError):
            runner.complete(run, 'researcher', self.result())

    def test_symlink_run_and_tampered_snapshot_rejected(self):
        run = self.prepare()
        link = self.base / 'link'
        link.symlink_to(run, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            runner.complete(link, 'researcher', self.result())
        (run / 'sources/README.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'hash'):
            runner.complete(run, 'researcher', self.result())

    def test_existing_run_relocated_into_source_is_rejected(self):
        run = self.prepare()
        relocated = self.source / run.name
        run.rename(relocated)
        (relocated / 'index.html').unlink()
        with self.assertRaisesRegex(ValueError, 'source project'):
            runner.render(relocated)
        self.assertFalse((relocated / 'index.html').exists())

    def test_symlink_snapshot_root_and_ancestor_are_rejected(self):
        run = self.prepare()
        outside = self.base / 'outside-snapshot'
        (run / 'sources').rename(outside)
        (run / 'sources').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            runner.render(run)
        (run / 'sources').unlink()
        outside.rename(run / 'sources')
        alias = self.base / 'storage-alias'
        alias.symlink_to(run.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            runner.render(alias / run.name)

    def test_citations_follow_lf_lines_not_unicode_separators(self):
        (self.source / 'README.md').write_text('One\u2028same LF line\nTwo\n')
        self.git('add', 'README.md')
        self.git('commit', '-qm', 'unicode fixture')
        run = self.prepare()
        data = self.result()
        data['findings'][0]['evidence'][0].update(start=3, end=3)
        with self.assertRaisesRegex(ValueError, 'line'):
            runner.complete(run, 'researcher', data)

    def test_render_does_not_inject_report_markup(self):
        run = self.prepare()
        data = self.result()
        data['summary'] = '</script><img src=x onerror=alert(1)>'
        runner.complete(run, 'researcher', data)
        output = runner.render(run).read_text()
        self.assertNotIn('</script><img', output)
        self.assertIn('\\u003c/script>', output)


if __name__ == '__main__':
    unittest.main()
