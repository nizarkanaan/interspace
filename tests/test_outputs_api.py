"""`task_outputs` and `task_output_save` (research/tasks.md "Outputs"), with a fake save-panel bridge."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

import service  # Puts pilot/ on the path.
import outputs_api
from agent_fakes import FakeAudit, FakeRuntime, FakeScope


class FakeBridge:
    def __init__(self, answer=True):
        self.answer = answer
        self.calls = []

    def deliver(self, message):
        pass

    def save_panel(self, path, suggested_name):
        self.calls.append((path, suggested_name))
        return self.answer


class OutputsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.app = service.Application(self.root / 'data', scope_api=FakeScope(), audit_api=FakeAudit(),
                                       runtime_factory=lambda task_id: FakeRuntime(), interrupt_grace_s=0.2)
        self.addCleanup(self.app.scheduler.shutdown, 5)
        self.app.bridge = FakeBridge()
        with self.app.lock:
            self.app.state['research']['tasks']['r1'] = {
                'id': 'r1', 'title': 'Related work: Attention!', 'mode': 'agent', 'kind': 'research', 'draft': '',
                'token_budget': 1000, 'thread': [], 'pending': None, 'run_id': None, 'run_ids': [], 'error': '',
                'error_status': None, 'role': 'orchestrator', 'provider': 'claude', 'model': None,
                'scope': None, 'scope_approval': None,
                'agent': {'project_id': None, 'state': 'idle', 'detail': '', 'reason': None, 'turns': 1,
                          'active_s': 0.0, 'workspaces': {}}}
        self.folder = self.root / 'data' / 'tasks' / 'r1' / 'outputs'

    def write(self, name, text):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / name).write_text(text)

    def test_methods_are_registered(self):
        self.assertIn('task_outputs', self.app.extensions)
        self.assertIn('task_output_save', self.app.extensions)

    def test_lists_known_outputs_only(self):
        self.assertEqual(self.app.handle('task_outputs', {'task_id': 'r1'}), {'outputs': []})
        self.write('report.md', '# Report')
        self.write('references.bib', '@misc{a}')
        self.write('notes.txt', 'other')
        outputs = self.app.handle('task_outputs', {'task_id': 'r1'})['outputs']
        self.assertEqual([(o['name'], o['kind'], o['bytes']) for o in outputs],
                         [('report.md', 'report', 8), ('references.bib', 'bibtex', 8)])
        self.assertTrue(outputs[0]['updated_at'].endswith('Z'))
        with self.assertRaisesRegex(ValueError, 'Unknown task'):
            self.app.handle('task_outputs', {'task_id': 'nope'})

    def test_save_goes_through_the_save_panel(self):
        self.write('references.bib', '@misc{a}')
        self.assertEqual(self.app.handle('task_output_save', {'task_id': 'r1', 'name': 'references.bib'}), {'saved': True})
        self.assertEqual(self.app.bridge.calls, [(str(self.folder / 'references.bib'), 'related-work-attention.bib')])
        self.app.bridge.answer = {'ok': False, 'error': 'cancelled'}
        self.assertEqual(self.app.handle('task_output_save', {'task_id': 'r1', 'name': 'references.bib'}), {'saved': False})

    def test_save_refuses_unknown_missing_and_linked_files(self):
        for name in ('../state.json', 'notes.txt', None):
            with self.assertRaisesRegex(ValueError, 'Unknown output'):
                self.app.handle('task_output_save', {'task_id': 'r1', 'name': name})
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            self.app.handle('task_output_save', {'task_id': 'r1', 'name': 'report.md'})
        outside = self.root / 'outside.md'
        outside.write_text('private')
        self.folder.mkdir(parents=True)
        os.symlink(str(outside), str(self.folder / 'report.md'))
        with self.assertRaises(ValueError):
            self.app.handle('task_output_save', {'task_id': 'r1', 'name': 'report.md'})
        self.assertEqual(self.app.bridge.calls, [])

    def test_save_without_the_app_window(self):
        self.write('report.md', 'x')
        self.app.bridge = None
        with self.assertRaisesRegex(ValueError, 'app window'):
            self.app.handle('task_output_save', {'task_id': 'r1', 'name': 'report.md'})

    def test_suggested_names(self):
        self.assertEqual(outputs_api.suggested_name('', 'report.md'), 'research.md')
        self.assertEqual(outputs_api.suggested_name('Über ../../etc', 'references.bib'), 'ber-etc.bib')


if __name__ == '__main__':
    unittest.main()
