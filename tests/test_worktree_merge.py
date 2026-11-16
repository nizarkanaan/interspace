"""Review and merge (merge.md) against disposable git repositories only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

import audit  # noqa: E402
import scheduler  # noqa: E402
import service  # noqa: E402
import worktree_merge  # noqa: E402

TASK_ID = 'a' * 32
PROJECT_ID = 'b' * 32


def git(repo, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(['git', '-C', str(repo)] + list(args), capture_output=True, text=True, env=env, check=False)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class RepoCase(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.base = Path(self._folder.name).resolve()
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '--quiet', '-b', 'main')
        git(self.repo, 'config', 'user.name', 'Test User')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        self.write('README.md', 'one\ntwo\nthree\n')
        self.write('data.bin', b'\x00\x01\x02')
        self.commit('Initial')
        self.base_commit = git(self.repo, 'rev-parse', 'HEAD')
        git(self.repo, 'branch', 'dev')
        git(self.repo, 'checkout', '--quiet', '-b', 'interspace/task-aaaaaaaa')
        self.write('README.md', 'one\nTWO\nthree\nfour\n')
        self.write('src/new.py', 'print("hi")\n')
        self.write('data.bin', b'\x00\x01\x03')
        git(self.repo, 'mv', 'README.md', 'README.txt')
        self.commit('Task work')
        self.head = git(self.repo, 'rev-parse', 'HEAD')
        git(self.repo, 'checkout', '--quiet', 'main')

    def tearDown(self):
        self._folder.cleanup()

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)

    def commit(self, message):
        git(self.repo, 'add', '--all')
        git(self.repo, 'commit', '--quiet', '-m', message)

    def worktrees(self):
        return [line for line in git(self.repo, 'worktree', 'list', '--porcelain').splitlines() if line.startswith('worktree ')]


class SummaryTests(RepoCase):
    def test_files_counts_renames_binary_and_patch(self):
        result = worktree_merge.summary(str(self.repo), 'interspace/task-aaaaaaaa', self.base_commit)
        self.assertEqual(result['branch'], 'interspace/task-aaaaaaaa')
        self.assertEqual(result['base_commit'], self.base_commit)
        self.assertEqual(result['head_commit'], self.head)
        files = {f['path']: f for f in result['files']}
        self.assertEqual(files['src/new.py']['change'], 'add')
        self.assertEqual((files['src/new.py']['additions'], files['src/new.py']['deletions']), (1, 0))
        self.assertEqual(files['README.txt']['change'], 'rename')
        self.assertEqual(files['README.txt']['old_path'], 'README.md')
        self.assertTrue(files['data.bin']['binary'])
        self.assertEqual(files['data.bin']['change'], 'modify')
        self.assertIsNone(files['data.bin']['additions'])
        self.assertIn('+print("hi")', result['patch'])
        self.assertFalse(result['truncated'])

    def test_patch_is_capped(self):
        git(self.repo, 'checkout', '--quiet', 'interspace/task-aaaaaaaa')
        self.write('big.txt', ''.join('line %d with some padding text\n' % i for i in range(20000)))
        self.commit('Big')
        git(self.repo, 'checkout', '--quiet', 'main')
        result = worktree_merge.summary(str(self.repo), 'interspace/task-aaaaaaaa', self.base_commit)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['patch'].encode('utf-8')), worktree_merge.MAX_PATCH_BYTES)

    def test_unknown_branch_is_a_safe_error(self):
        with self.assertRaises(ValueError):
            worktree_merge.summary(str(self.repo), 'nope', self.base_commit)
        with self.assertRaises(ValueError):
            worktree_merge.summary(str(self.repo), '--output=x', self.base_commit)


class MergeTests(RepoCase):
    def merge(self, into='dev', expected=None, title='Fix parser'):
        return worktree_merge.merge(str(self.repo), 'interspace/task-aaaaaaaa', into,
                                    expected_head=expected or self.head, title=title)

    def test_clean_merge_advances_target_without_touching_checkout(self):
        (self.repo / 'scratch.txt').write_text('uncommitted\n')
        before_main = git(self.repo, 'rev-parse', 'main')
        result = self.merge()
        self.assertEqual(result['status'], 'merged', result)
        self.assertEqual(result['conflicts'], [])
        dev = git(self.repo, 'rev-parse', 'dev')
        self.assertEqual(result['merge_commit'], dev)
        self.assertEqual(git(self.repo, 'rev-list', '--parents', '-n', '1', dev).split()[1:],
                         [self.base_commit, self.head])
        self.assertEqual(git(self.repo, 'rev-parse', 'main'), before_main)
        self.assertEqual(git(self.repo, 'symbolic-ref', '--short', 'HEAD'), 'main')
        self.assertEqual((self.repo / 'scratch.txt').read_text(), 'uncommitted\n')
        self.assertTrue((self.repo / 'README.md').exists())
        self.assertEqual(len(self.worktrees()), 1)

    def test_message_has_title_and_no_trailers(self):
        result = self.merge(title='Fix parser\nCo-authored-by: Someone <x@y>')
        message = git(self.repo, 'log', '-1', '--format=%B', result['merge_commit'])
        self.assertEqual(message.strip(), 'Merge interspace task Fix parser Co-authored-by: Someone <x@y>')
        self.assertEqual(git(self.repo, 'log', '-1', '--format=%(trailers)', result['merge_commit']), '')

    def test_conflict_is_reported_and_aborted(self):
        git(self.repo, 'checkout', '--quiet', 'dev')
        self.write('src/new.py', 'print("other")\n')
        self.commit('Dev change')
        git(self.repo, 'checkout', '--quiet', 'main')
        dev_before = git(self.repo, 'rev-parse', 'dev')
        result = self.merge()
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['conflicts'], ['src/new.py'])
        self.assertIsNone(result['merge_commit'])
        self.assertEqual(git(self.repo, 'rev-parse', 'dev'), dev_before)
        self.assertEqual(len(self.worktrees()), 1)
        self.assertFalse(list((self.repo / '.git').glob('worktrees/*')))

    def test_stale_when_branch_moved(self):
        dev_before = git(self.repo, 'rev-parse', 'dev')
        result = self.merge(expected=self.base_commit)
        self.assertEqual(result['status'], 'stale')
        self.assertIsNone(result['merge_commit'])
        self.assertEqual(git(self.repo, 'rev-parse', 'dev'), dev_before)

    def test_dirty_when_target_is_checked_out(self):
        main_before = git(self.repo, 'rev-parse', 'main')
        result = self.merge(into='main')
        self.assertEqual(result['status'], 'dirty')
        self.assertIn('checked out', result['detail'])
        self.assertEqual(git(self.repo, 'rev-parse', 'main'), main_before)
        self.assertEqual(len(self.worktrees()), 1)

    def test_dirty_when_target_is_checked_out_in_another_worktree(self):
        other = self.base / 'other'
        git(self.repo, 'worktree', 'add', '--quiet', str(other), 'dev')
        result = self.merge(into='dev')
        self.assertEqual(result['status'], 'dirty')

    def test_unknown_target_is_a_safe_error(self):
        with self.assertRaises(ValueError):
            self.merge(into='missing')
        with self.assertRaises(ValueError):
            self.merge(into='-f')

    def test_temp_worktree_removed_when_git_fails(self):
        (self.repo / '.git' / 'refs' / 'heads' / 'dev.lock').write_text('')  # The ref update fails.
        dev_before = git(self.repo, 'rev-parse', 'dev')
        with self.assertRaises(ValueError):
            self.merge()
        self.assertEqual(git(self.repo, 'rev-parse', 'dev'), dev_before)
        self.assertEqual(len(self.worktrees()), 1)
        self.assertFalse(list((self.repo / '.git').glob('worktrees/*')))

    def test_user_hooks_never_run(self):
        hook = self.repo / '.git' / 'hooks' / 'pre-merge-commit'
        marker = self.base / 'hook-ran'
        hook.write_text('#!/bin/sh\ntouch "%s"\n' % marker)
        hook.chmod(0o755)
        self.assertEqual(self.merge()['status'], 'merged')
        self.assertFalse(marker.exists())


class FakeApp:
    def __init__(self, repo, storage):
        self.lock = threading.RLock()
        self.locks = scheduler.Locks()
        self.audit = audit.AuditLog(storage / 'audit')
        task = {'id': TASK_ID, 'title': 'Fix parser', 'mode': 'agent',
                'agent': {'project_id': PROJECT_ID, 'workspaces': {PROJECT_ID: {
                    'path': str(storage / 'ws'), 'branch': 'interspace/task-aaaaaaaa',
                    'base_commit': None, 'target_branch': 'interspace/task-aaaaaaaa'}}}}
        self.state = {'projects': {PROJECT_ID: {'id': PROJECT_ID, 'source_path': str(repo), 'tasks': {TASK_ID: task}}}}


class MethodTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.app = FakeApp(self.repo, self.base / 'storage')
        self.task = self.app.state['projects'][PROJECT_ID]['tasks'][TASK_ID]
        self.task['agent']['workspaces'][PROJECT_ID]['base_commit'] = self.base_commit

    def call(self, method, params):
        return worktree_merge.METHODS[method](self.app, params)

    def test_methods_are_registered(self):
        self.assertEqual(set(worktree_merge.METHODS), {'review_summary', 'review_merge', 'review_branches'})
        table = service.extension_methods(('worktree_merge',))
        self.assertEqual(set(table), set(worktree_merge.METHODS))

    def test_summary_reads_the_published_branch(self):
        result = self.call('review_summary', {'task_id': TASK_ID})
        self.assertEqual(result['branch'], 'interspace/task-aaaaaaaa')
        self.assertEqual(result['head_commit'], self.head)

    def test_summary_without_published_branch(self):
        self.task['agent']['workspaces'][PROJECT_ID]['target_branch'] = None
        with self.assertRaises(ValueError):
            self.call('review_summary', {'task_id': TASK_ID})
        with self.assertRaises(ValueError):
            self.call('review_summary', {'task_id': 'c' * 32})

    def test_branches_lists_local_branches_and_current(self):
        result = self.call('review_branches', {'project_id': PROJECT_ID})
        self.assertEqual(result['current'], 'main')
        self.assertEqual(sorted(result['branches']), ['dev', 'interspace/task-aaaaaaaa', 'main'])

    def test_merge_is_audited(self):
        result = self.call('review_merge', {'task_id': TASK_ID, 'into': 'dev', 'expected_head': self.head})
        self.assertEqual(result['status'], 'merged')
        stale = self.call('review_merge', {'task_id': TASK_ID, 'into': 'dev', 'expected_head': self.base_commit})
        self.assertEqual(stale['status'], 'stale')
        records = self.app.audit.read(task_id=TASK_ID)
        self.assertEqual(len(records), 2)
        merged = records[-1] if records[-1]['detail']['result'] == 'merged' else records[0]
        self.assertEqual(merged['actor'], 'user')
        self.assertEqual(merged['kind'], 'action')
        self.assertEqual(merged['outcome'], 'succeeded')
        self.assertEqual(merged['project_id'], PROJECT_ID)
        self.assertEqual(merged['detail'], {'branch': 'interspace/task-aaaaaaaa', 'into': 'dev', 'result': 'merged',
                                            'merge_commit': result['merge_commit']})
        failed = [r for r in records if r['detail']['result'] == 'stale'][0]
        self.assertEqual(failed['outcome'], 'failed')

    def test_merge_waits_for_the_project_lock(self):
        self.app.locks.acquire('project:' + PROJECT_ID, 'other-task', None)
        done = []
        worker = threading.Thread(target=lambda: done.append(
            self.call('review_merge', {'task_id': TASK_ID, 'into': 'dev', 'expected_head': self.head})))
        worker.start()
        worker.join(0.3)
        self.assertEqual(done, [])
        self.app.locks.release('project:' + PROJECT_ID, 'other-task')
        worker.join(10)
        self.assertEqual(done[0]['status'], 'merged')

    def test_bad_params(self):
        with self.assertRaises(ValueError):
            self.call('review_merge', {'task_id': TASK_ID, 'into': 'dev'})
        with self.assertRaises(ValueError):
            self.call('review_branches', {'project_id': 'missing'})


class ApplicationTests(unittest.TestCase):
    def test_application_dispatches_review_methods(self):
        class FakeAuth:
            def status(self):
                return {'state': 'signed_out'}
        with tempfile.TemporaryDirectory() as folder:
            app = service.Application(folder, provider=FakeAuth())
            try:
                self.assertIn('review_merge', app.extensions)
                with self.assertRaises(ValueError):
                    app.handle('review_branches', {'project_id': 'missing'})
            finally:
                app.scheduler.shutdown(timeout_s=5)


if __name__ == '__main__':
    unittest.main()
