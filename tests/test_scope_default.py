"""`scope_default {project_id}`: the starting scope for a new agent task (README coordinator ruling, Wave 2C).

Uses the real scope engine; the runtime is a fake. No provider, network or Keychain.
"""
from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import service  # Puts pilot/ on the path for projects.
import budget
import projects
import scope
from agent_fakes import FakeAudit, FakeRuntime


class BuilderTests(unittest.TestCase):
    def test_project_default_is_workspace_only(self):
        document = scope.project_default('p1')
        self.assertIs(scope.validate(document, project_ids=['p1']), document)
        self.assertEqual(document['projects'], [{'project_id': 'p1', 'access': 'write', 'read': ['**'],
                                                 'write': ['**'], 'deny': []}])
        self.assertEqual(document['apps'], [])
        self.assertEqual(document['network'], {'default': 'deny', 'allow_hosts': [], 'deny_hosts': []})
        self.assertEqual(document['web_search'], 'deny')
        self.assertEqual(document['commands'], {'workspace': 'allow', 'allow': [], 'deny': []})
        self.assertEqual(document['limits'], {'token_budget': budget.DEFAULT_BUDGET,
                                              'time_limit_s': scope.DEFAULT_TIME_LIMIT_S})
        self.assertEqual((document['v'], document['version']), (1, 1))
        self.assertEqual(document['task_id'], scope.DRAFT_TASK_ID)

    def test_token_budget_and_registration(self):
        self.assertEqual(scope.project_default('p1', token_budget=5000)['limits']['token_budget'], 5000)
        self.assertEqual(scope.project_default('p1', token_budget=None)['limits']['token_budget'], budget.DEFAULT_BUDGET)
        with self.assertRaises(ValueError):
            scope.project_default('p1', token_budget=0)
        with self.assertRaisesRegex(ValueError, 'not registered'):
            scope.project_default('p1', project_ids=['p2'])
        with self.assertRaises(ValueError):
            scope.project_default('')

    def test_each_call_is_a_fresh_copy(self):
        first = scope.project_default('p1')
        first['projects'][0]['write'].append('x')
        self.assertEqual(scope.project_default('p1')['projects'][0]['write'], ['**'])


class FakeProvider:
    def status(self):
        return {'ready': True, 'message': 'fake'}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        repo = root / 'repo'
        repo.mkdir()
        git = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
        subprocess.run(git + ['init', '-q', '-b', 'main', str(repo)], check=True)
        (repo / 'main.py').write_text('print(1)\n')
        subprocess.run(git + ['-C', str(repo), 'add', '.'], check=True)
        subprocess.run(git + ['-C', str(repo), 'commit', '-qm', 'base'], check=True)
        self.audit = FakeAudit()
        self.app = service.Application(root / 'data', provider=FakeProvider(), scope_api=scope, audit_api=self.audit,
                                       runtime_factory=lambda task_id: FakeRuntime(),
                                       interrupt_grace_s=0.2)
        self.addCleanup(self.app.scheduler.shutdown, 5)
        project = projects.new_project(repo)
        with self.app.lock:
            self.app.state['projects'][project['id']] = project
            self.app.state['selected_project_id'] = project['id']
        self.project_id = project['id']

    def test_method_returns_a_valid_document_without_creating_a_task(self):
        before = json.dumps(self.app.state, sort_keys=True, default=str)
        result = self.app.handle('scope_default', {'project_id': self.project_id})
        self.assertEqual(set(result), {'scope'})
        document = result['scope']
        scope.validate(document, project_ids=[self.project_id])
        self.assertEqual(document['projects'][0]['project_id'], self.project_id)
        self.assertEqual(document['network']['default'], 'deny')
        self.assertEqual(document['apps'], [])
        self.assertEqual(json.dumps(self.app.state, sort_keys=True, default=str), before, 'nothing is created')
        self.assertEqual(self.audit.records, [])

    def test_project_token_budget_is_used_when_set(self):
        with self.app.lock:
            self.app.state['projects'][self.project_id]['token_budget'] = 12345
        self.assertEqual(self.app.handle('scope_default', {'project_id': self.project_id})['scope']['limits']['token_budget'], 12345)
        with self.app.lock:
            self.app.state['projects'][self.project_id]['token_budget'] = 'lots'
        self.assertEqual(self.app.handle('scope_default', {'project_id': self.project_id})['scope']['limits']['token_budget'],
                         budget.DEFAULT_BUDGET, 'a damaged saved budget falls back to the default')

    def test_unknown_project_is_refused(self):
        for value in ('ghost', None, 7):
            with self.assertRaisesRegex(ValueError, 'Unknown project'):
                self.app.handle('scope_default', {'project_id': value})

    def test_default_round_trips_through_agent_create(self):
        document = self.app.handle('scope_default', {'project_id': self.project_id})['scope']
        created = self.app.handle('agent_create', {'project_id': self.project_id, 'title': 'Fix it', 'scope': document})
        stored = self.app.handle('scope_get', {'task_id': created['task_id']})
        self.assertEqual(stored['scope']['task_id'], created['task_id'])
        self.assertEqual(stored['scope']['network'], document['network'])
        self.assertIsNone(stored['scope_approval'])
        self.assertEqual(stored['scope_digest'], created['scope_digest'])

    def test_routed_on_the_agent_pool_and_allowed_by_the_shell(self):
        self.assertIn('scope_default', service.AGENT_METHODS)
        swift = (ROOT / 'app/macos/main.swift').read_text()
        allowed = re.search(r'let allowedMethods: Set<String> = \[(.*?)\]', swift, re.S).group(1)
        self.assertIn('"scope_default"', allowed)


if __name__ == '__main__':
    unittest.main()
