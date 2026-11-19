"""Routing defaults (docs/superpowers/specs/multi-provider/providers.md, "Routing defaults")."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'app' / 'backend') not in sys.path:
    sys.path.append(str(ROOT / 'app' / 'backend'))

import routing  # noqa: E402
from runtime import registry  # noqa: E402


class RoutingTests(unittest.TestCase):
    def test_defaults_match_the_contract(self):
        self.assertEqual(routing.ROLES, ('researcher', 'implementer', 'reviewer', 'tester', 'writer', 'citation_checker'))
        self.assertEqual(routing.WRITE_ROLES, ('implementer', 'tester'))
        self.assertEqual(routing.DEFAULT_ROUTING, {
            'v': 1, 'orchestrator': {'provider': 'claude', 'model': None},
            'roles': {'researcher': {'provider': 'codex', 'model': None},
                      'implementer': {'provider': 'claude', 'model': None},
                      'reviewer': {'provider': 'codex', 'model': None},
                      'tester': {'provider': 'claude', 'model': None},
                      'writer': {'provider': 'claude', 'model': None},
                      'citation_checker': {'provider': 'codex', 'model': None}}})
        self.assertEqual(routing.validate(routing.DEFAULT_ROUTING), routing.DEFAULT_ROUTING)

    def test_missing_roles_are_completed_from_the_defaults(self):
        saved = routing.default()
        del saved['roles']['citation_checker']
        saved['roles']['writer'] = {'provider': 'codex', 'model': None}
        checked = routing.validate(saved)
        self.assertEqual(checked['roles']['citation_checker'], {'provider': 'codex', 'model': None})
        self.assertEqual(checked['roles']['writer'], {'provider': 'codex', 'model': None})
        self.assertEqual(routing.current({'routing': saved})['roles']['writer']['provider'], 'codex')
        self.assertEqual(list(checked['roles']), list(routing.ROLES))

    def test_current_falls_back_to_defaults(self):
        self.assertEqual(routing.current({}), routing.DEFAULT_ROUTING)
        self.assertEqual(routing.current({'routing': 'damaged'}), routing.DEFAULT_ROUTING)
        saved = routing.default()
        saved['roles']['writer'] = {'provider': 'codex', 'model': 'gpt-5.5'}
        self.assertEqual(routing.current({'routing': saved})['roles']['writer'], {'provider': 'codex', 'model': 'gpt-5.5'})
        result = routing.current({})
        result['roles']['writer']['provider'] = 'codex'
        self.assertEqual(routing.DEFAULT_ROUTING['roles']['writer']['provider'], 'claude')  # Never shared.

    def test_validate_returns_a_clean_copy(self):
        value = routing.default()
        value['roles']['implementer']['model'] = 'claude-opus-5-5'
        checked = routing.validate(value)
        self.assertEqual(checked['roles']['implementer'], {'provider': 'claude', 'model': 'claude-opus-5-5'})
        self.assertIsNot(checked, value)
        json.dumps(checked)
        # v may be omitted; it is always written.
        del value['v']
        self.assertEqual(routing.validate(value)['v'], 1)

    def test_validate_refuses_bad_shapes(self):
        def changed(edit):
            value = routing.default()
            edit(value)
            return value
        bad = [
            None, [], 'x',
            changed(lambda v: v.update(v=2)),
            changed(lambda v: v.update(extra=1)),
            changed(lambda v: v.pop('orchestrator')),
            changed(lambda v: v['roles'].update(painter={'provider': 'claude', 'model': None})),
            changed(lambda v: v['roles'].update(writer={'provider': 'gemini', 'model': None})),
            changed(lambda v: v['roles'].update(writer={'provider': 'claude', 'model': 'sonnet'})),
            changed(lambda v: v['roles'].update(writer={'provider': 'codex', 'model': 'a b'})),
            changed(lambda v: v['roles'].update(writer={'provider': 'codex'})),
            changed(lambda v: v['roles'].update(writer={'provider': 'codex', 'model': None, 'x': 1})),
            changed(lambda v: v['roles'].update(writer='codex')),
            changed(lambda v: v.update(orchestrator={'provider': 'nope', 'model': None})),
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                routing.validate(value)

    def test_write_roles_need_a_write_provider(self):
        record = dict(registry.get('codex'), name='readonly', title='Read only',
                      capabilities={'write': False, 'web_search': True, 'approvals': True})
        registry.register(record)
        self.addCleanup(registry.unregister, 'readonly')
        value = routing.default()
        value['roles']['reviewer'] = {'provider': 'readonly', 'model': None}
        self.assertEqual(routing.validate(value)['roles']['reviewer']['provider'], 'readonly')
        for role in routing.WRITE_ROLES:
            refused = copy.deepcopy(value)
            refused['roles'][role] = {'provider': 'readonly', 'model': None}
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'cannot write'):
                routing.validate(refused)


if __name__ == '__main__':
    unittest.main()
