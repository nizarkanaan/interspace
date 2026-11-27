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


def fake_runtime(status=None, sign_in=None, error=None, sign_out=None):
    class Runtime:
        finishers = []

        @classmethod
        def auth_status(cls, app):
            if error is not None:
                raise error
            return status

        @classmethod
        def begin_sign_in(cls, app, on_finish=None):
            if error is not None:
                raise error
            cls.finishers.append(on_finish)
            return sign_in
    if sign_out is not None:
        Runtime.sign_out = classmethod(lambda cls, app: sign_out)
    return Runtime


class ProvidersApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        providers_api.clear_models_cache()
        self.addCleanup(providers_api.clear_models_cache)
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
                         {'providers_list', 'provider_models', 'provider_sign_in', 'provider_sign_out', 'provider_status',
                          'routing_update'})

    def test_sign_in_completion_updates_state_and_publishes(self):
        self.call('provider_sign_in', {'provider': 'codex'})
        finish = self.runtimes['codex'].finishers[-1]
        self.assertTrue(callable(finish))
        self.assertEqual(self.app.published, 0)
        self.runtimes['codex'] = fake_runtime({'provider': 'codex', 'state': 'signed_in', 'account': 'ChatGPT (pro)',
                                               'detail': 'ok', 'token': 'secret'})
        finish('success')
        self.assertEqual(self.app.state['provider_status']['codex'],
                         {'provider': 'codex', 'state': 'signed_in', 'account': 'ChatGPT (pro)', 'detail': 'ok'})
        self.assertEqual(self.app.published, 1)
        self.runtimes['codex'] = fake_runtime({'provider': 'codex', 'state': 'signed_out', 'account': None,
                                               'detail': 'Codex sign-in did not complete.'})
        finish('failed')
        self.assertEqual(self.app.state['provider_status']['codex']['state'], 'signed_out')
        self.assertEqual(self.app.published, 2)

    def test_sign_out(self):
        self.runtimes['codex'] = fake_runtime(sign_out={'provider': 'codex', 'state': 'signed_out', 'account': None,
                                                        'detail': 'Signed out.', 'token': 'x'})
        result = self.call('provider_sign_out', {'provider': 'codex'})
        self.assertEqual(result, {'provider': 'codex', 'state': 'signed_out', 'account': None, 'detail': 'Signed out.'})
        self.assertEqual(self.app.state['provider_status']['codex'], result)
        self.assertEqual(self.app.published, 1)
        # Claude uses the user's own CLI sign-in, which Interspace never signs out.
        with self.assertRaisesRegex(ValueError, 'claude auth logout'):
            self.call('provider_sign_out', {'provider': 'claude'})
        self.runtimes['codex'] = fake_runtime(error=RuntimeError('/x/auth.json'), sign_out={})
        self.runtimes['codex'].sign_out = classmethod(lambda cls, app: (_ for _ in ()).throw(RuntimeError('/x/auth.json')))
        with self.assertRaises(ValueError) as raised:
            self.call('provider_sign_out', {'provider': 'codex'})
        self.assertNotIn('auth.json', str(raised.exception))
        with self.assertRaisesRegex(ValueError, 'Unknown provider.'):
            self.call('provider_sign_out', {'provider': 'gemini'})

    def models_runtime(self, answers):
        """A Codex runtime whose `models` returns (or raises) the next of `answers`; counts its calls."""
        class Runtime:
            calls = 0

            @classmethod
            def models(cls, app):
                cls.calls += 1
                answer = answers[min(cls.calls, len(answers)) - 1]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        self.runtimes['codex'] = Runtime
        return Runtime

    def test_provider_models_claude_comes_from_the_registry(self):
        result = self.call('provider_models', {'provider': 'claude'})
        self.assertEqual(set(result), {'provider', 'models', 'error'})
        self.assertEqual(result['provider'], 'claude')
        self.assertEqual(result['error'], '')
        self.assertEqual([m['id'] for m in result['models']], ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5', 'claude-fable-5-2'])
        for model in result['models']:
            self.assertEqual(set(model), {'id', 'is_default', 'default_effort', 'efforts'})
            self.assertEqual(model['default_effort'], 'low')
            self.assertEqual(model['efforts'], ['low', 'medium', 'high', 'xhigh', 'max'])
        self.assertEqual([m['id'] for m in result['models'] if m['is_default']], ['claude-sonnet-5-5'])

    def test_provider_models_codex_is_cached_and_cut_to_the_contract(self):
        runtime = self.models_runtime([[{'id': 'gpt-x', 'is_default': True, 'default_effort': 'medium',
                                         'efforts': ['low', 'medium'], 'token': 'secret'}]])
        first = self.call('provider_models', {'provider': 'codex'})
        self.assertEqual(first, {'provider': 'codex', 'error': '', 'models': [
            {'id': 'gpt-x', 'is_default': True, 'default_effort': 'medium', 'efforts': ['low', 'medium']}]})
        first['models'].clear()  # A caller's edits never reach the cache.
        self.assertEqual(len(self.call('provider_models', {'provider': 'codex'})['models']), 1)
        self.assertEqual(runtime.calls, 1)

    def test_provider_models_failure_is_a_sentence_and_cached(self):
        runtime = self.models_runtime([ValueError('Sign in to Codex to see its models.')])
        for _ in range(2):
            self.assertEqual(self.call('provider_models', {'provider': 'codex'}),
                             {'provider': 'codex', 'models': [], 'error': 'Sign in to Codex to see its models.'})
        self.assertEqual(runtime.calls, 1)
        self.models_runtime([RuntimeError('/x/auth.json')])
        providers_api.clear_models_cache()
        result = self.call('provider_models', {'provider': 'codex'})
        self.assertEqual(result['models'], [])
        self.assertNotIn('auth.json', result['error'])
        self.assertTrue(result['error'])

    def test_transient_model_failures_are_never_cached(self):
        good = [{'id': 'gpt-x', 'is_default': True, 'default_effort': None, 'efforts': []}]
        for failure in (ValueError('Codex did not list its models in time. Try again.'),
                        ValueError('Codex did not start. Check its installation and try again.'),
                        ValueError('Install Codex CLI or the ChatGPT Mac app to see its models.'),
                        RuntimeError('boom')):
            runtime = self.models_runtime([failure, good])
            providers_api.clear_models_cache()
            self.assertEqual(self.call('provider_models', {'provider': 'codex'})['models'], [])
            self.assertEqual(len(self.call('provider_models', {'provider': 'codex'})['models']), 1)
            self.assertEqual(runtime.calls, 2)

    def test_provider_status_change_clears_the_models_cache(self):
        good = [{'id': 'gpt-x', 'is_default': True, 'default_effort': None, 'efforts': []}]
        runtime = self.models_runtime([good, good, good])
        states = iter(['signed_in', 'signed_in', 'signed_out'])
        runtime.auth_status = classmethod(lambda cls, app: {'provider': 'codex', 'state': next(states),
                                                            'account': None, 'detail': ''})
        self.call('provider_status', {'provider': 'codex'})
        self.call('provider_models', {'provider': 'codex'})
        self.call('provider_status', {'provider': 'codex'})
        self.call('provider_models', {'provider': 'codex'})
        self.assertEqual(runtime.calls, 1)  # Same state: still cached.
        self.call('provider_status', {'provider': 'codex'})
        self.call('provider_models', {'provider': 'codex'})
        self.assertEqual(runtime.calls, 2)

    def test_sign_out_and_finished_sign_in_clear_the_models_cache(self):
        good = [{'id': 'gpt-x', 'is_default': True, 'default_effort': None, 'efforts': []}]
        runtime = self.models_runtime([ValueError('Sign in to Codex to see its models.'), good, good, good])
        self.assertEqual(self.call('provider_models', {'provider': 'codex'})['models'], [])
        self.assertEqual(self.call('provider_models', {'provider': 'codex'})['models'], [])  # Still cached.
        runtime.begin_sign_in = classmethod(lambda cls, app, on_finish=None: (
            cls.finishers.append(on_finish) or {'provider': 'codex', 'kind': 'device',
                                                'url': 'https://auth.openai.com/codex/device', 'code': 'A-1',
                                                'detail': ''}))
        runtime.auth_status = classmethod(lambda cls, app: {'provider': 'codex', 'state': 'signed_in',
                                                            'account': 'x', 'detail': ''})
        runtime.finishers = []
        self.call('provider_sign_in', {'provider': 'codex'})
        runtime.finishers[-1]('success')
        self.assertEqual(len(self.call('provider_models', {'provider': 'codex'})['models']), 1)
        self.assertEqual(runtime.calls, 2)
        runtime.sign_out = classmethod(lambda cls, app: {'provider': 'codex', 'state': 'signed_out', 'account': None,
                                                         'detail': ''})
        self.call('provider_sign_out', {'provider': 'codex'})
        self.call('provider_models', {'provider': 'codex'})
        self.assertEqual(runtime.calls, 3)

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
        self.assertEqual(result['roles']['reviewer'], {'provider': 'claude', 'model': 'claude-opus-5-5', 'effort': None})
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
    def test_every_backend_method_is_allowed_by_the_shell(self):
        import re
        import service
        swift = (ROOT / 'app' / 'macos' / 'main.swift').read_text()
        allowed = set(re.findall(r'"([a-z_]+)"', re.search(r'let allowedMethods: Set<String> = \[(.*?)\]',
                                                            swift, re.S).group(1)))
        backend = set(service.AGENT_METHODS) | set(service.APP_METHODS) | set(service.extension_methods())
        native = {'add_project', 'select_project'}  # Sent by the shell itself after its folder picker.
        self.assertEqual(backend - allowed - native, set())

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
                self.assertEqual(saved['routing']['roles']['writer'], {'provider': 'codex', 'model': 'gpt-5.5', 'effort': None})
            finally:
                app.scheduler.shutdown(timeout_s=5)


if __name__ == '__main__':
    unittest.main()
