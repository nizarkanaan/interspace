"""Codex sign-in, status and sign-out on the app-owned CODEX_HOME, against the fake app-server (spike-0b.md).

No real Codex, sign-in or network.
"""
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'app' / 'backend') not in sys.path:
    sys.path.append(str(ROOT / 'app' / 'backend'))

import codex_auth  # noqa: E402
from runtime import codex  # noqa: E402

FAKE = Path(__file__).resolve().parent / 'fixtures' / 'codex' / 'fake_app_server.py'


class App:
    def __init__(self, storage):
        self.storage = Path(storage)
        self.lock = threading.RLock()


class CodexAuthCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.storage = self.root / 'data'
        self.storage.mkdir()
        self.app = App(self.storage)
        self.home = self.storage / 'codex-home'
        self.log = self.root / 'log.jsonl'
        self.scenario({})
        self.binary = self.root / 'bin' / 'codex'
        self.binary.parent.mkdir()
        self.binary.write_text('#!/bin/sh\nexec %s %s %s %s "$@"\n' % tuple(
            shlex.quote(str(p)) for p in (sys.executable, FAKE, self.root / 'scenario.json', self.log)))
        self.binary.chmod(0o755)
        patcher = mock.patch.object(codex, 'find_binary', lambda: str(self.binary))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(codex_auth.cancel_all)

    def scenario(self, value):
        (self.root / 'scenario.json').write_text(json.dumps(value))

    def logged(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def launches(self):
        return [e for e in self.logged() if 'argv' in e]

    def sent(self, method):
        return [e['in'] for e in self.logged() if 'in' in e and e['in'].get('method') == method]

    def wait_until(self, check, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return True
            time.sleep(0.02)
        return False


class StatusTests(CodexAuthCase):
    def test_signed_in_keeps_only_type_and_plan(self):
        self.scenario({'account': {'type': 'chatgpt', 'email': 'person@example.com', 'planType': 'pro',
                                   'workspaceName': 'Home'}})
        status = codex.CodexRuntime.auth_status(self.app)
        self.assertEqual(status, {'provider': 'codex', 'state': 'signed_in', 'account': 'ChatGPT (pro)',
                                  'detail': 'Codex is signed in with your ChatGPT account.'})
        self.assertNotIn('example.com', json.dumps(status))
        self.assertNotIn('user-secret', json.dumps(status))

    def test_runs_on_the_app_owned_home_with_pinned_credential_store(self):
        codex.CodexRuntime.auth_status(self.app)
        launch = self.launches()[0]
        self.assertEqual(launch['codex_home'], str(self.home))
        self.assertTrue(self.home.is_dir())
        argv = launch['argv']
        self.assertEqual(argv[0], 'app-server')
        overrides = dict(argv[i + 1].split('=', 1) for i in range(1, len(argv), 2) if argv[i] == '-c')
        self.assertEqual(overrides['cli_auth_credentials_store'], '"file"')
        self.assertEqual(overrides['forced_login_method'], '"chatgpt"')
        self.assertNotIn('SECRET_TOKEN', launch['env'])
        self.assertEqual(self.sent('account/read')[0]['params'], {'refreshToken': False})
        self.assertEqual(self.sent('initialize')[0]['params']['clientInfo']['name'], 'interspace')

    def test_signed_out_and_ignores_unrelated_notifications(self):
        self.scenario({'account': None, 'after_initialize': [
            {'method': 'remoteControl/status/changed', 'params': {'status': 'disabled'}}]})
        status = codex.CodexRuntime.auth_status(self.app)
        self.assertEqual((status['state'], status['account']), ('signed_out', None))

    def test_unknown_plan_text_is_not_shown(self):
        self.scenario({'account': {'type': 'chatgpt', 'planType': 'pro <script>'}})
        self.assertEqual(codex.CodexRuntime.auth_status(self.app)['account'], 'ChatGPT')

    def test_missing_cli(self):
        with mock.patch.object(codex, 'find_binary', lambda: None):
            status = codex.CodexRuntime.auth_status(self.app)
        self.assertEqual(status['state'], 'missing_cli')
        self.assertEqual(self.launches(), [])

    def test_broken_server_is_an_error(self):
        self.scenario({'exit_on': 'initialize'})
        status = codex.CodexRuntime.auth_status(self.app)
        self.assertEqual(status['state'], 'error')
        self.assertIsNone(status['account'])


class SignInTests(CodexAuthCase):
    def test_device_sign_in_then_status(self):
        self.scenario({'account': None, 'login': {'complete_after': 1.0}})
        started = codex.CodexRuntime.begin_sign_in(self.app)
        self.assertEqual(started['provider'], 'codex')
        self.assertEqual(started['kind'], 'device')
        self.assertEqual(started['url'], 'https://auth.openai.com/codex/device')
        self.assertEqual(started['code'], 'ABCD-12345')
        self.assertIsInstance(started['detail'], str)
        self.assertEqual(self.sent('account/login/start')[0]['params'], {'type': 'chatgptDeviceCode'})
        self.assertTrue(codex_auth.pending(self.home))
        # While the sign-in is pending, status is read through the same app-server.
        waiting = codex.CodexRuntime.auth_status(self.app)
        self.assertEqual(waiting['state'], 'signed_out')
        self.assertIn('Waiting', waiting['detail'])
        self.assertEqual(len(self.launches()), 1)
        self.assertTrue(self.wait_until(
            lambda: codex.CodexRuntime.auth_status(self.app)['state'] == 'signed_in'))
        self.assertEqual(codex.CodexRuntime.auth_status(self.app)['account'], 'ChatGPT (pro)')
        self.assertTrue(self.wait_until(lambda: not codex_auth.pending(self.home)))

    def test_on_finish_is_called_once_with_the_outcome(self):
        for scenario, outcome in (({'complete_after': 0.1}, 'success'),
                                  ({'complete_after': 0.1, 'success': False}, 'failed')):
            self.scenario({'account': None, 'login': scenario})
            seen = []
            codex.CodexRuntime.begin_sign_in(self.app, on_finish=seen.append)
            self.assertTrue(self.wait_until(lambda: seen))
            # Called after the attempt is over, so a status read then sees the outcome.
            self.assertFalse(codex_auth.pending(self.home))
            time.sleep(0.1)
            self.assertEqual(seen, [outcome])
            (self.home / 'fake-account.json').unlink(missing_ok=True)

    def test_on_finish_is_not_called_for_a_replaced_or_cancelled_sign_in(self):
        self.scenario({'account': None, 'login': {'complete_after': None}})
        first, second = [], []
        codex.CodexRuntime.begin_sign_in(self.app, on_finish=first.append)
        codex.CodexRuntime.begin_sign_in(self.app, on_finish=second.append)
        codex_auth.cancel_all()
        time.sleep(0.2)
        self.assertEqual((first, second), ([], []))

    def test_failed_sign_in_reports_in_status_and_stops_the_server(self):
        self.scenario({'account': None, 'login': {'complete_after': 0.1, 'success': False}})
        codex.CodexRuntime.begin_sign_in(self.app)
        self.assertTrue(self.wait_until(lambda: not codex_auth.pending(self.home)))
        status = codex.CodexRuntime.auth_status(self.app)
        self.assertEqual(status['state'], 'signed_out')
        self.assertIn('did not complete', status['detail'])

    def test_a_new_sign_in_cancels_the_pending_one(self):
        self.scenario({'account': None, 'login': {'complete_after': None}})
        codex.CodexRuntime.begin_sign_in(self.app)
        codex.CodexRuntime.begin_sign_in(self.app)
        self.assertTrue(self.wait_until(lambda: len(self.sent('account/login/cancel')) == 1))
        self.assertEqual(self.sent('account/login/cancel')[0]['params'], {'loginId': 'login-1'})
        self.assertEqual(len(self.launches()), 2)

    def test_refused_or_malformed_start_raises_a_safe_error(self):
        for login in ({'error': True}, {'result': {'verificationUrl': 'http://evil.example/x'}},
                      {'result': {'userCode': 'x' * 80}}, {'result': {'type': 'apiKey'}}):
            self.scenario({'account': None, 'login': login})
            with self.subTest(login=login), self.assertRaises(ValueError):
                codex.CodexRuntime.begin_sign_in(self.app)
            self.assertFalse(codex_auth.pending(self.home))

    def test_missing_cli_raises(self):
        with mock.patch.object(codex, 'find_binary', lambda: None):
            with self.assertRaisesRegex(ValueError, 'Install Codex'):
                codex.CodexRuntime.begin_sign_in(self.app)

    def test_sign_out(self):
        self.scenario({'account': {'type': 'chatgpt', 'planType': 'plus'}})
        self.assertEqual(codex.CodexRuntime.auth_status(self.app)['state'], 'signed_in')
        status = codex.CodexRuntime.sign_out(self.app)
        self.assertEqual(status['state'], 'signed_out')
        self.assertEqual(len(self.sent('account/logout')), 1)
        self.assertEqual(codex.CodexRuntime.auth_status(self.app)['state'], 'signed_out')
        for launch in self.launches():
            self.assertEqual(launch['codex_home'], str(self.home))

    def test_errors_are_value_errors(self):
        self.assertTrue(issubclass(codex_auth.AuthError, ValueError))


class ModelListTests(CodexAuthCase):
    MODELS = [
        {'id': 'gpt-a', 'isDefault': True, 'defaultReasoningEffort': 'medium',
         'supportedReasoningEfforts': [{'reasoningEffort': 'low', 'description': 'Fast'},
                                       {'reasoningEffort': 'medium', 'description': 'Balanced'}, 'high',
                                       {'reasoningEffort': 'Not Valid!'}]},
        {'id': 'gpt-b', 'isDefault': False, 'defaultReasoningEffort': 'low', 'supportedReasoningEfforts': ['low']},
        {'id': 'bad id with spaces', 'isDefault': False, 'supportedReasoningEfforts': []},
    ]
    EXPECTED = [{'id': 'gpt-a', 'is_default': True, 'default_effort': 'medium', 'efforts': ['low', 'medium', 'high']},
                {'id': 'gpt-b', 'is_default': False, 'default_effort': 'low', 'efforts': ['low']}]

    def list_models(self):
        return codex.CodexRuntime.models(self.app)

    def test_signed_in_lists_models_with_plain_efforts(self):
        self.scenario({'models': self.MODELS})
        self.assertEqual(self.list_models(), self.EXPECTED)
        self.assertEqual(len(self.sent('account/read')), 1)
        self.assertEqual(len(self.sent('model/list')), 1)

    def test_models_key_and_pages_are_followed(self):
        self.scenario({'models': self.MODELS, 'models_key': 'models', 'models_page': 1})
        self.assertEqual(self.list_models(), self.EXPECTED)
        self.assertEqual(len(self.sent('model/list')), 3)

    def test_signed_out_is_refused_before_model_list(self):
        self.scenario({'models': self.MODELS, 'account': None})
        with self.assertRaisesRegex(codex_auth.AuthError, 'Sign in to Codex to see its models.'):
            self.list_models()
        self.assertEqual(self.sent('model/list'), [])

    def test_hung_model_list_times_out_and_the_process_is_gone(self):
        self.scenario({'models_hang': True})
        started = time.monotonic()
        with self.assertRaises(codex_auth.AuthError):
            self.list_models()
        self.assertLess(time.monotonic() - started, 11)
        pid = self.launches()[0]['pid']
        self.assertTrue(self.wait_until(lambda: not _alive(pid)))


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class LegacyCodexAuthTests(CodexAuthCase):
    def test_legacy_status_uses_the_given_home(self):
        log = self.root / 'cli.log'
        script = self.root / 'bin' / 'codex-cli'
        script.write_text('#!/bin/sh\necho "$CODEX_HOME $*" >> %s\necho "Not logged in"\nexit 1\n' % shlex.quote(str(log)))
        script.chmod(0o755)
        auth = codex_auth.CodexAuth(str(script), codex_home=self.home)
        self.assertFalse(auth.status()['ready'])
        line = log.read_text().strip()
        self.assertTrue(line.startswith(str(self.home) + ' '))
        self.assertIn('-c cli_auth_credentials_store="file" -c forced_login_method="chatgpt" login status', line)


if __name__ == '__main__':
    unittest.main()
