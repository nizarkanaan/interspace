"""Codex connection check and sign-in, and the app shell around them. Disposable fake `codex` executables only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))

from codex_auth import AuthError, CodexAuth
from service import Application

WARM_ENV = 'INTERSPACE_FAKE_WARM_UP'


def fake_header():
    """First lines of a fake `codex`: with WARM_ENV set it exits at once (see `warm_up`)."""
    return ('#!' + sys.executable + '\nimport json,os,sys,time\nif os.environ.get(%r):\n sys.exit(0)\n' % WARM_ENV)


def warm_up(path):
    """Run a freshly written fake once before a test times anything.

    macOS checks every new executable on its first run, one at a time across the machine: with eight processes
    writing fresh scripts, a first run took a median 0.9 s and up to 1.9 s, a second run 0.02 s. Under a parallel
    full-suite load that wait alone overran this file's deadlines (the pidfile wait below). Running each fake once
    here moves the check out of the timed part of the test.
    """
    subprocess.run([str(path)], env=dict(os.environ, **{WARM_ENV: '1'}), check=True, timeout=120,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def executable(self, body):
        path = self.root / 'fake-codex'
        path.write_text(fake_header() + body)
        path.chmod(0o755)
        warm_up(path)
        return path

    def test_status_reports_signed_in_signed_out_and_missing(self):
        signed_in = self.executable("assert sys.argv[1:] == ['login', 'status']\nsys.exit(0)\n")
        self.assertEqual(CodexAuth(signed_in).status(), {'ready': True, 'message': 'Codex signed in'})
        signed_out = self.executable('sys.exit(1)\n')
        self.assertFalse(CodexAuth(signed_out).status()['ready'])
        missing = CodexAuth()
        missing.binary = None
        self.assertIn('Install Codex', missing.status()['message'])
        with self.assertRaisesRegex(AuthError, 'Install'):
            missing.sign_in(threading.Event(), lambda text: None)

    def test_device_sign_in_relays_instructions_and_reports_failure(self):
        ok = self.executable("assert sys.argv[1:] == ['login', '--device-auth']\nprint('\\x1b[1mOpen https://example.invalid/device\\x1b[0m', flush=True)\nprint('Code: ABCD-1234', flush=True)\n")
        shown = []
        CodexAuth(ok).sign_in(threading.Event(), shown.append)
        self.assertEqual(shown[-1], 'Open https://example.invalid/device\nCode: ABCD-1234')
        failed = self.executable('sys.exit(3)\n')
        with self.assertRaisesRegex(AuthError, 'did not complete'):
            CodexAuth(failed).sign_in(threading.Event(), shown.append)

    def test_cancel_stops_the_sign_in_process_group(self):
        marker = self.root / 'child-effect'
        binary = self.executable("import os\nif os.fork()==0:\n time.sleep(1)\n open(" + repr(str(marker)) + ",'w').write('bad')\n os._exit(0)\ntime.sleep(20)\n")
        cancel = threading.Event()
        threading.Timer(.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaisesRegex(AuthError, 'cancelled'):
            CodexAuth(binary).sign_in(cancel, lambda text: None)
        self.assertLess(time.monotonic() - started, 3)
        time.sleep(1.2)
        self.assertFalse(marker.exists())

    def test_backend_quit_with_closed_output_stops_active_provider(self):
        marker = self.root / 'orphan-effect'
        pidfile = self.root / 'provider-pid'
        binary = self.root / 'codex'
        body = ('import os\n'
                "if '--device-auth' not in sys.argv:\n print('Logged in using ChatGPT')\n sys.exit(0)\n"
                + 'open(' + repr(str(pidfile)) + ",'w').write(str(os.getpid()))\n"
                + 'time.sleep(2)\nopen(' + repr(str(marker)) + ",'w').write('bad')\n")
        binary.write_text(fake_header() + body)
        binary.chmod(0o755)
        warm_up(binary)
        env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ.get('PATH', ''))
        process = subprocess.Popen([sys.executable, str(ROOT / 'app/backend/service.py'), '--data-root', str(self.root / 'quit-data')],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            process.stdin.write(json.dumps({'id': 'sign-in', 'method': 'sign_in', 'params': {}}) + '\n')
            process.stdin.flush()
            deadline = time.monotonic() + 5
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(pidfile.exists())
            process.stdin.write(json.dumps({'id': 'status', 'method': 'connection', 'params': {}}) + '\n')
            process.stdin.flush()
            process.stdout.close()
            process.stdin.close()
            process.wait(timeout=5)
            diagnostic = process.stderr.read()
            self.assertEqual(process.returncode, 0, diagnostic)
            time.sleep(2.1)
            self.assertFalse(marker.exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if pidfile.exists():
                try:
                    os.killpg(int(pidfile.read_text()), 9)
                except (OSError, ValueError):
                    pass  # Gone already, or the fake had not written its pid yet.
            process.stderr.close()


class FakeAuth:
    def __init__(self):
        self.entered = threading.Event()
        self.result = None

    def status(self):
        return {'ready': True, 'message': 'Test connection'}

    def sign_in(self, cancel, emit):
        emit('Open the device page')
        self.entered.set()
        if self.result == 'fail':
            raise AuthError('Codex sign-in did not complete.')
        cancel.wait(5)
        if cancel.is_set():
            raise AuthError('Sign-in cancelled.')


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.messages = []
        self.auth = FakeAuth()
        self.app = Application(Path(self.tmp.name) / 'data', provider=self.auth, emit=self.messages.append)
        self.addCleanup(self.app.scheduler.shutdown, 5)

    def test_connection_and_sign_in_report_through_state(self):
        self.assertEqual(self.app.handle('connection', {})['connection'], {'ready': True, 'message': 'Test connection'})
        self.assertEqual(self.app.handle('sign_in', {}), {'started': True})
        self.assertTrue(self.auth.entered.wait(2))
        self.assertEqual(self.app.public()['active'], 'Signing in')
        self.assertIn({'type': 'auth', 'text': 'Open the device page'}, self.messages)
        with self.assertRaisesRegex(ValueError, 'already running'):
            self.app.handle('sign_in', {})
        self.assertTrue(self.app.handle('cancel', {})['cancellation_requested'])
        self.app.wait()
        self.assertIsNone(self.app.public()['active'])
        self.assertEqual(self.app.public()['error'], 'Sign-in cancelled.')
        self.auth.result = 'fail'
        self.app.handle('sign_in', {})
        self.app.wait()
        self.assertEqual(self.app.public()['error'], 'Codex sign-in did not complete.')

    def test_unknown_methods_and_bad_params_are_refused(self):
        for method in ('chat', 'start_review', 'delete_project', None):
            with self.assertRaisesRegex(ValueError, 'Unknown method'):
                self.app.handle(method, {})
        with self.assertRaisesRegex(ValueError, 'params'):
            self.app.handle('state', [])

    def test_sign_in_does_not_take_an_agent_run_slot(self):
        self.app.handle('sign_in', {})
        self.assertTrue(self.auth.entered.wait(2))
        snapshot = self.app.public()['scheduler']
        self.assertEqual(snapshot['running'], [])
        self.assertNotIn('legacy_active', snapshot)
        self.app.handle('cancel', {})
        self.app.wait()


if __name__ == '__main__':
    unittest.main()
