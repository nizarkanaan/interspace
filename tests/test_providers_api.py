"""Backend methods for providers and routing (multi-provider/providers.md), with fake runtime classes."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'app' / 'backend') not in sys.path:
    sys.path.append(str(ROOT / 'app' / 'backend'))

import providers_api  # noqa: E402
import routing  # noqa: E402
from runtime import registry  # noqa: E402


class FakeApp:
    def __init__(self):
        self.lock = threading.RLock()
        self.state = {}
        self.storage = Path(tempfile.gettempdir())
        self.published = 0

    def publish(self):
        self.published += 1


def fake_runtime(status=None, sign_in=None, error=None):
    class Runtime:
        @classmethod
        def auth_status(cls, app):
            if error is not None:
                raise error
            return status

        @classmethod
        def begin_sign_in(cls, app):
            if error is not None:
                raise error
            return sign_in
    return Runtime


class ProvidersApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.runtimes = {
            'claude': fake_runtime({'provider': 'claude', 'state': 'signed_in', 'account': 'Claude subscription',
                                    'detail': 'ok'},
                                   {'provider': 'claude', 'kind': 'terminal', 'command': 'claude auth login',
                                    'detail': 'Run it.'}),
            'codex': fake_runtime({'provider': 'codex', 'state': 'signed_out', 'account': None, 'detail': 'Sign in.'},
                                  {'provider': 'codex', 'kind': 'device', 'url': 'https://auth.openai.com/codex/device',
                                   'code': 'ABCD-12345', 'detail': 'Open it.'}),
        }
        patcher = mock.patch.object(registry, 'runtime_class', lambda name: self.runtimes[registry.get(name)['name']])
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, method, params):
        return providers_api.METHODS[method](self.app, params)

    def test_methods_are_the_contract(self):
        self.assertEqual(set(providers_api.METHODS),
                         {'providers_list', 'provider_sign_in', 'provider_status', 'routing_update'})

    def test_providers_list(self):
        result = self.call('providers_list', {})
        json.dumps(result)
        self.assertEqual(result['providers'], registry.public())
        self.assertEqual([s['provider'] for s in result['status']], ['claude', 'codex'])
        self.assertEqual(result['status'][0]['state'], 'signed_in')
        self.assertEqual(result['routing'], routing.DEFAULT_ROUTING)

    def test_status_and_sign_in(self):
        self.assertEqual(self.call('provider_status', {'provider': 'codex'})['state'], 'signed_out')
        started = self.call('provider_sign_in', {'provider': 'codex'})
        self.assertEqual(started, {'provider': 'codex', 'kind': 'device', 'url': 'https://auth.openai.com/codex/device',
                                   'code': 'ABCD-12345', 'detail': 'Open it.'})
        self.assertEqual(self.call('provider_sign_in', {'provider': 'claude'}),
                         {'provider': 'claude', 'kind': 'terminal', 'command': 'claude auth login', 'detail': 'Run it.'})
        for bad in ({}, {'provider': 'gemini'}, {'provider': 3}):
            with self.subTest(params=bad), self.assertRaisesRegex(ValueError, 'Unknown provider.'):
                self.call('provider_status', bad)

    def test_results_are_filtered_to_the_contract_fields(self):
        self.runtimes['codex'] = fake_runtime(
            {'provider': 'codex', 'state': 'signed_in', 'account': 'ChatGPT', 'detail': 'ok', 'token': 'secret',
             'credential_path': '/x/auth.json'},
            {'provider': 'codex', 'kind': 'device', 'url': 'https://auth.openai.com/x', 'code': None, 'detail': '',
             'token': 'secret'})
        status = self.call('provider_status', {'provider': 'codex'})
        self.assertEqual(set(status), {'provider', 'state', 'account', 'detail'})
        started = self.call('provider_sign_in', {'provider': 'codex'})
        self.assertEqual(set(started), {'provider', 'kind', 'url', 'code', 'detail'})
        self.assertNotIn('secret', json.dumps([status, started]))

    def test_bad_runtime_answers_become_safe_errors(self):
        self.runtimes['codex'] = fake_runtime({'provider': 'claude', 'state': 'weird', 'account': 5, 'detail': None},
                                              {'kind': 'device', 'url': 'javascript:alert(1)', 'code': 'x'})
        status = self.call('provider_status', {'provider': 'codex'})
        self.assertEqual((status['provider'], status['state'], status['account']), ('codex', 'error', None))
        with self.assertRaises(ValueError):
            self.call('provider_sign_in', {'provider': 'codex'})
        self.runtimes['codex'] = fake_runtime(sign_in={'kind': 'terminal', 'command': 'rm -rf /'})
        with self.assertRaises(ValueError):
            self.call('provider_sign_in', {'provider': 'codex'})

    def test_runtime_exceptions(self):
        self.runtimes['codex'] = fake_runtime(error=ValueError('Install Codex first.'))
        status = self.call('provider_status', {'provider': 'codex'})
        self.assertEqual((status['state'], status['detail']), ('error', 'Install Codex first.'))
        with self.assertRaisesRegex(ValueError, 'Install Codex first.'):
            self.call('provider_sign_in', {'provider': 'codex'})
        self.runtimes['codex'] = fake_runtime(error=RuntimeError('/Users/x/.codex/auth.json token=abc'))
        status = self.call('provider_status', {'provider': 'codex'})
        self.assertEqual(status['state'], 'error')
        self.assertNotIn('auth.json', json.dumps(status))
        with self.assertRaises(ValueError) as raised:
            self.call('provider_sign_in', {'provider': 'codex'})
        self.assertNotIn('auth.json', str(raised.exception))
        # One provider failing never hides the others.
        listed = self.call('providers_list', {})
        self.assertEqual([s['state'] for s in listed['status']], ['signed_in', 'error'])

    def test_runtime_not_in_build(self):
        def missing(name):
            raise ValueError('The Codex runtime is not in this build yet.')
        with mock.patch.object(registry, 'runtime_class', missing):
            status = self.call('provider_status', {'provider': 'codex'})
        self.assertEqual(status['state'], 'error')

    def test_routing_update_validates_persists_and_publishes(self):
        value = routing.default()
        value['roles']['reviewer'] = {'provider': 'claude', 'model': 'claude-opus-5-5'}
        result = self.call('routing_update', {'routing': value})
        self.assertEqual(result['roles']['reviewer'], {'provider': 'claude', 'model': 'claude-opus-5-5'})
        self.assertEqual(self.app.state['routing'], result)
        self.assertIsNot(self.app.state['routing'], result)
        self.assertEqual(self.app.published, 1)
        self.assertEqual(self.call('providers_list', {})['routing'], result)
        bad = routing.default()
        bad['roles']['writer'] = {'provider': 'gemini', 'model': None}
        with self.assertRaises(ValueError):
            self.call('routing_update', {'routing': bad})
        with self.assertRaises(ValueError):
            self.call('routing_update', {})
        self.assertEqual(self.app.state['routing'], result)  # Unchanged after a refusal.
        self.assertEqual(self.app.published, 1)


class ServiceIntegrationTests(unittest.TestCase):
    def test_methods_reach_the_app_through_the_extension_hook(self):
        import service

        class FakeAuth:
            def status(self):
                return {'ready': False, 'message': ''}
        with tempfile.TemporaryDirectory() as folder:
            app = service.Application(folder, provider=FakeAuth())
            try:
                for name in providers_api.METHODS:
                    self.assertIn(name, app.extensions)
                value = routing.default()
                value['roles']['writer'] = {'provider': 'codex', 'model': 'gpt-5.5'}
                app.handle('routing_update', {'routing': value})
                saved = json.loads((Path(folder) / 'state.json').read_text())
                self.assertEqual(saved['routing']['roles']['writer'], {'provider': 'codex', 'model': 'gpt-5.5'})
            finally:
                app.scheduler.shutdown(timeout_s=5)


if __name__ == '__main__':
    unittest.main()
