"""Provider registry (docs/superpowers/specs/multi-provider/providers.md)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'app' / 'backend') not in sys.path:
    sys.path.append(str(ROOT / 'app' / 'backend'))

from runtime import registry  # noqa: E402


class RegistryTests(unittest.TestCase):
    def test_names_in_registry_order_and_default(self):
        self.assertEqual(registry.names(), ('claude', 'codex'))
        self.assertEqual(registry.DEFAULT_PROVIDER, 'claude')
        self.assertIn(registry.DEFAULT_PROVIDER, registry.names())

    def test_get_and_unknown(self):
        self.assertEqual(registry.get('claude')['title'], 'Claude')
        self.assertEqual(registry.get('codex')['charge_fields'], ('input_tokens', 'output_tokens'))
        for bad in ('gemini', None, 3, '', 'CLAUDE'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'Unknown provider.'):
                registry.get(bad)

    def test_get_returns_a_copy(self):
        registry.get('claude')['models'] = ('x',)
        registry.get('claude')['capabilities']['write'] = False
        self.assertEqual(registry.get('claude')['models'][0], 'claude-sonnet-5-5')
        self.assertTrue(registry.get('claude')['capabilities']['write'])

    def test_claude_models_are_full_ids(self):
        claude = registry.get('claude')
        self.assertEqual(claude['models'], ('claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5', 'claude-fable-5-2'))
        self.assertEqual(claude['default_model'], 'claude-sonnet-5-5')
        self.assertEqual(claude['charge_fields'], ('input_tokens', 'cache_creation_input_tokens',
                                                   'cache_read_input_tokens', 'output_tokens'))

    def test_check_model(self):
        self.assertEqual(registry.check_model('claude', None), 'claude-sonnet-5-5')
        self.assertEqual(registry.check_model('claude', 'claude-opus-5-5'), 'claude-opus-5-5')
        self.assertIsNone(registry.check_model('codex', None))  # The CLI's own default.
        self.assertEqual(registry.check_model('codex', 'gpt-5.5-codex'), 'gpt-5.5-codex')
        for provider, bad in (('claude', 'sonnet'), ('claude', 'gpt-5'), ('claude', ''), ('codex', ''),
                              ('codex', 'a b'), ('codex', 'x' * 65), ('codex', 'a/b'), ('codex', 5),
                              ('codex', 'gpt\n')):
            with self.subTest(provider=provider, model=bad), self.assertRaises(ValueError):
                registry.check_model(provider, bad)
        with self.assertRaisesRegex(ValueError, 'Unknown provider.'):
            registry.check_model('gemini', None)

    def test_public_is_json_safe_and_has_no_internals(self):
        public = registry.public()
        json.dumps(public)
        self.assertEqual([p['name'] for p in public], ['claude', 'codex'])
        self.assertEqual(set(public[0]), {'name', 'title', 'models', 'default_model', 'capabilities'})
        self.assertEqual(public[0]['models'], ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5', 'claude-fable-5-2'])
        self.assertEqual(public[1]['models'], [])
        self.assertIsNone(public[1]['default_model'])

    def test_runtime_class_imports_lazily(self):
        self.assertEqual(registry.runtime_class('codex').__name__, 'CodexRuntime')
        self.assertEqual(registry.runtime_class('claude').__name__, 'ClaudeRuntime')
        with self.assertRaises(ValueError):
            registry.runtime_class('gemini')

    def test_runtime_class_reports_missing_module_as_value_error(self):
        registry.register(dict(registry.get('codex'), name='later', title='Later', runtime='runtime.nope:Nope'))
        self.addCleanup(registry.unregister, 'later')
        with self.assertRaisesRegex(ValueError, 'not in this build'):
            registry.runtime_class('later')

    def test_register_validates_records(self):
        good = dict(registry.get('codex'), name='later', title='Later', runtime='runtime.later:LaterRuntime',
                    capabilities={'write': False, 'web_search': True, 'approvals': True})
        registry.register(good)
        self.addCleanup(registry.unregister, 'later')
        self.assertEqual(registry.names(), ('claude', 'codex', 'later'))
        self.assertFalse(registry.get('later')['capabilities']['write'])
        with self.assertRaisesRegex(ValueError, 'already'):
            registry.register(good)
        broken = [
            {k: v for k, v in good.items() if k != 'charge_fields'},
            dict(good, name='x1', charge_fields=()),
            dict(good, name='x2', charge_fields=('input_tokens', 3)),
            dict(good, name='x3', runtime='nocolon'),
            dict(good, name='x4', default_model='m', models=('a',)),
            dict(good, name='x5', capabilities={'write': True}),
            dict(good, name='Bad Name'),
            dict(good, name='x6', models=('bad id',)),
        ]
        for record in broken:
            with self.subTest(record=record.get('name')), self.assertRaises(ValueError):
                registry.register(record)
        self.assertEqual(registry.names(), ('claude', 'codex', 'later'))

    def test_charge_rule_names(self):
        self.assertEqual(registry.charge_rule('codex'), 'codex.input+output')
        self.assertEqual(registry.charge_rule('claude'), 'claude.input+cache_creation+cache_read+output')

    def test_check_effort(self):
        self.assertEqual(registry.PROVIDERS['claude']['efforts'], ('low', 'medium', 'high', 'xhigh', 'max'))
        self.assertEqual(registry.PROVIDERS['codex']['efforts'], ())
        self.assertEqual(registry.check_effort('claude', 'max'), 'max')
        self.assertIsNone(registry.check_effort('claude', None))
        self.assertEqual(registry.check_effort('codex', 'minimal'), 'minimal')
        with self.assertRaises(ValueError):
            registry.check_effort('codex', 'High!')
        with self.assertRaises(ValueError):
            registry.check_effort('claude', 'minimal')


if __name__ == '__main__':
    unittest.main()
