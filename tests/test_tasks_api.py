"""Archive and delete tasks (docs/superpowers/specs/2026-11-20-archive-delete-design.md)."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(1, str(ROOT / 'tests'))

import tasks_api  # noqa: E402
from test_agent_service import ApplicationCase  # noqa: E402

GIT = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']


class ArchiveDeleteTests(ApplicationCase):
    def setUp(self):
        super().setUp()
        self.app = self.open()
        self.project_id = self.add_project(self.app)

    def git(self, *args):
        return subprocess.run(GIT + ['-C', str(self.repo)] + list(args), check=True, capture_output=True, text=True).stdout

    def published(self, task_id, name='interspace/task-x', commits=1):
        """A branch the task published, with `commits` commits not in main."""
        self.git('checkout', '-q', '-b', name)
        for i in range(commits):
            (self.repo / ('f%d.txt' % i)).write_text(str(i))
            self.git('add', '.')
            self.git('commit', '-qm', 'work %d' % i)
        self.git('checkout', '-q', 'main')
        with self.app.lock:
            self.app.store.task(task_id)['agent']['workspaces'] = {
                self.project_id: {'path': str(self.root / 'clone'), 'branch': name, 'base_commit': None,
                                  'target_branch': name}}
        return name

    def row(self, task_id):
        return next(r for r in self.app.handle('state', {})['tasks'] if r['id'] == task_id)

    def set_state(self, task_id, state):
        with self.app.lock:
            self.app.store.task(task_id)['agent']['state'] = state

    def test_archive_and_restore_and_working_tasks_are_refused(self):
        task_id = self.create(self.app, self.project_id)
        self.assertFalse(self.row(task_id)['archived'])
        self.assertEqual(self.app.handle('task_archive', {'task_id': task_id, 'archived': True}), {'archived': True})
        self.assertTrue(self.row(task_id)['archived'])
        self.app.handle('task_archive', {'task_id': task_id, 'archived': False})
        self.assertFalse(self.row(task_id)['archived'])
        for state in ('running', 'paused_team', 'queued'):
            self.set_state(task_id, state)
            with self.assertRaisesRegex(ValueError, 'Stop this task first'):
                self.app.handle('task_archive', {'task_id': task_id, 'archived': True})
            with self.assertRaisesRegex(ValueError, 'Stop this task first'):
                self.app.handle('task_delete', {'task_id': task_id, 'branches': 'keep'})
        with self.assertRaisesRegex(ValueError, 'archived must be true or false'):
            self.app.handle('task_archive', {'task_id': task_id, 'archived': 'yes'})

    def test_delete_check_reports_unmerged_commits_and_keep_leaves_the_branch(self):
        task_id = self.create(self.app, self.project_id)
        name = self.published(task_id, commits=2)
        events = Path(self.app.events.root) / task_id
        events.mkdir(parents=True, exist_ok=True)
        (events / 'events.jsonl').write_text('')
        clone = self.app.storage / 'workspaces' / task_id
        clone.mkdir(parents=True)
        check = self.app.handle('task_delete_check', {'task_id': task_id})
        self.assertEqual((check['working'], check['subagents']), (False, 0))
        [branch] = check['branches']
        self.assertEqual((branch['name'], branch['exists'], branch['ahead'], branch['into'], branch['checked_out']),
                         (name, True, 2, 'main', False))
        result = self.app.handle('task_delete', {'task_id': task_id, 'branches': 'keep'})
        self.assertEqual((result['deleted'], result['deleted_branches']), ([task_id], []))
        self.assertIn(name, self.git('branch', '--list', name))
        self.assertFalse(events.exists() or clone.exists())
        self.assertNotIn(task_id, [r['id'] for r in self.app.handle('state', {})['tasks']])
        with self.assertRaisesRegex(ValueError, 'Unknown task'):
            self.app.handle('task_delete_check', {'task_id': task_id})

    def test_delete_with_branches_removes_the_branch_and_audits_it(self):
        task_id = self.create(self.app, self.project_id)
        name = self.published(task_id)
        result = self.app.handle('task_delete', {'task_id': task_id, 'branches': 'delete'})
        self.assertEqual((result['deleted_branches'], result['kept_branches']), ([name], []))
        self.assertEqual(self.git('branch', '--list', name).strip(), '')
        [record] = [r for r in self.audit.records if (r.get('request') or {}).get('argv', [])[:2] == ['git', 'branch']]
        self.assertEqual((record['outcome'], record['detail']['branch']), ('succeeded', name))

    def test_a_checked_out_branch_is_never_deleted(self):
        task_id = self.create(self.app, self.project_id)
        name = self.published(task_id)
        self.git('checkout', '-q', name)
        check = self.app.handle('task_delete_check', {'task_id': task_id})
        self.assertTrue(check['branches'][0]['checked_out'])
        result = self.app.handle('task_delete', {'task_id': task_id, 'branches': 'delete'})
        self.assertEqual(result['deleted_branches'], [])
        self.assertEqual(result['kept_branches'][0]['reason'], 'It is checked out in your working copy.')
        self.assertIn(name, self.git('branch', '--list', name))

    def test_research_task_delete_removes_its_folders_and_selection(self):
        import scope
        import service
        from agent_fakes import FakeAudit, FakeRuntime
        self.app = service.Application(self.root / 'research-data', scope_api=scope, audit_api=FakeAudit(),
                                       runtime_factory=lambda task_id: FakeRuntime(), interrupt_grace_s=0.2)
        self.addCleanup(self.app.scheduler.shutdown, 5)
        created = self.app.handle('agent_create', {'project_id': None, 'kind': 'research', 'title': 'Q'})
        task_id = created['task_id']
        for folder in (Path(self.app.events.root) / task_id / 'outputs', self.app.storage / 'research-runs' / task_id):
            folder.mkdir(parents=True, exist_ok=True)
        (Path(self.app.events.root) / task_id / 'outputs' / 'report.md').write_text('# R')
        self.assertEqual(self.app.handle('task_delete_check', {'task_id': task_id})['branches'], [])
        self.app.handle('task_delete', {'task_id': task_id})
        public = self.app.handle('state', {})
        self.assertEqual(public['research']['tasks'], [])
        self.assertIsNone(public['research']['selected_task_id'])
        self.assertFalse((Path(self.app.events.root) / task_id).exists())
        self.assertFalse((self.app.storage / 'research-runs' / task_id).exists())

    def test_bad_arguments(self):
        task_id = self.create(self.app, self.project_id)
        with self.assertRaisesRegex(ValueError, "branches must be 'delete' or 'keep'"):
            self.app.handle('task_delete', {'task_id': task_id, 'branches': 'all'})
        with self.assertRaisesRegex(ValueError, 'Missing task_id'):
            self.app.handle('task_delete', {})

    def test_methods_are_in_the_swift_allowlist(self):
        swift = (ROOT / 'app/macos/main.swift').read_text()
        for method in tasks_api.METHODS:
            self.assertIn('"%s"' % method, swift)


if __name__ == '__main__':
    unittest.main()
