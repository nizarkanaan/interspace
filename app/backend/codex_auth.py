"""Codex connection check, device sign-in and sign-out: no shell, no credential-file access.

The provider methods (`account_status`, `begin_device_sign_in`, `sign_out`) work on the app-owned CODEX_HOME
through `codex app-server` account RPCs (docs/superpowers/specs/multi-provider/spike-0b.md):
`account/read`, `account/login/start` with `{type: 'chatgptDeviceCode'}`, `account/login/cancel` and
`account/logout`. Every command on that home pins `cli_auth_credentials_store="file"` (so the token never
goes to the shared macOS keychain) and `forced_login_method="chatgpt"` (no API-key login there).

Of the account only `type` and `planType` are kept; the email, user and account ids are never stored, shown
or logged. `status` and `sign_in` are the older CLI forms the app's legacy `connection` and `sign_in` methods use.
"""
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import threading
import time


class AuthError(ValueError):
    """A sign-in failure whose message is safe to show."""


CREDENTIAL_OVERRIDES = (('cli_auth_credentials_store', 'file'), ('forced_login_method', 'chatgpt'))
CLIENT_INFO = {'name': 'interspace', 'title': 'Interspace', 'version': '1'}
REQUEST_TIMEOUT_S = 15
MODELS_TIMEOUT_S = 10  # Total deadline for `list_models`, all pages and the account check included.
MAX_MODEL_PAGES = 10
SIGN_IN_TIMEOUT_S = 900  # Device codes expire well within this; the server is stopped after it.
MAX_LINE_BYTES = 1024 * 1024
URL_RE = re.compile(r'https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~/%-]*)?\Z')
CODE_RE = re.compile(r'[A-Za-z0-9]{2,16}(-[A-Za-z0-9]{2,16}){0,3}\Z')
PLAN_RE = re.compile(r'[A-Za-z0-9_-]{1,32}\Z')
ID_RE = re.compile(r'[A-Za-z0-9._:-]{1,128}\Z')
ACCOUNT_TITLES = {'chatgpt': 'ChatGPT', 'apiKey': 'API key'}


def find_codex():
    candidates = [shutil.which('codex'),
                  '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex',
                  '/Applications/Codex.app/Contents/Resources/codex']
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


def config_args():
    """`-c key="value"` pins for every command on the app-owned home."""
    args = []
    for key, value in CREDENTIAL_OVERRIDES:
        args += ['-c', key + '=' + json.dumps(value)]
    return args


def account_name(account):
    """'ChatGPT (pro)' from an `account/read` account; nothing else from it is kept."""
    kind = account.get('type')
    name = ACCOUNT_TITLES.get(kind, 'Codex') if isinstance(kind, str) else 'Codex'
    plan = account.get('planType')
    return name + ' (' + plan + ')' if isinstance(plan, str) and PLAN_RE.match(plan) else name


def _stop_process(process):
    # The session group may outlive its leader. Always address the owned group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        if process.poll() is None:
            process.terminate()
    time.sleep(.15)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS restricted hosts can deny a signal to an already-empty group.
        # Still ensure the direct child has exited; owned-group TERM was attempted above.
        if process.poll() is None:
            process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


class AppServer:
    """A minimal `codex app-server` JSON-RPC client for the account methods. Server requests are refused."""

    def __init__(self, argv, env, cwd):
        try:
            self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            raise AuthError('Codex could not be started. Check its installation.') from None
        self.notifications = queue.Queue()
        self._replies = {}
        self._cond = threading.Condition()
        self._write = threading.Lock()
        self._next_id = 0
        self._dead = False
        self._closed = False
        threading.Thread(target=self._read, daemon=True, name='codex-auth-reader').start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_LINE_BYTES + 1)
                if not line or len(line) > MAX_LINE_BYTES:
                    break
                try:
                    message = json.loads(line.decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(message, dict):
                    continue
                if 'method' not in message and 'id' in message:
                    with self._cond:
                        self._replies[message['id']] = message
                        self._cond.notify_all()
                elif isinstance(message.get('method'), str):
                    if 'id' in message:
                        self._send({'id': message['id'], 'error': {'code': -32601, 'message': 'Not supported.'}})
                    else:
                        self.notifications.put(message)
        except (OSError, ValueError):
            pass
        finally:
            with self._cond:
                self._dead = True
                self._cond.notify_all()
            self.notifications.put(None)

    def _send(self, message):
        data = (json.dumps(message, separators=(',', ':')) + '\n').encode('utf-8')
        with self._write:
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass  # The reader sees the end of output.

    def request(self, method, params=None, timeout=REQUEST_TIMEOUT_S):
        with self._cond:
            self._next_id += 1
            request_id = self._next_id
        message = {'id': request_id, 'method': method}
        if params is not None:
            message['params'] = params
        self._send(message)
        deadline = time.monotonic() + timeout
        with self._cond:
            while request_id not in self._replies:
                left = deadline - time.monotonic()
                if self._dead or left <= 0:
                    raise AuthError('Codex stopped answering. Check its installation and try again.')
                self._cond.wait(min(left, 0.1))
            reply = self._replies.pop(request_id)
        if 'error' in reply or not isinstance(reply.get('result'), dict):
            raise AuthError('Codex refused the request.')
        return reply['result']

    def notify(self, method, params=None):
        message = {'method': method}
        if params is not None:
            message['params'] = params
        self._send(message)

    def initialize(self):
        self.request('initialize', {'clientInfo': CLIENT_INFO,
                                    'capabilities': {'experimentalApi': True, 'requestAttestation': False}})
        self.notify('initialized')

    def wait_for(self, method, match, deadline, stop):
        """The params of the first `method` notification that `match` accepts, or None at deadline, stop or exit."""
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                message = self.notifications.get(timeout=0.1)
            except queue.Empty:
                continue
            if message is None:
                return None
            params = message.get('params')
            if message['method'] == method and isinstance(params, dict) and match(params):
                return params
        return None

    @property
    def alive(self):
        return not self._dead and not self._closed and self.process.poll() is None

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        _stop_process(self.process)
        try:
            self.process.stdout.close()
        except (OSError, ValueError):
            pass


class _DeviceSignIn:
    """One pending device sign-in: its app-server stays up until the login completes, fails or expires."""

    def __init__(self, server, login_id, on_finish=None):
        self.server = server
        self.login_id = login_id
        self.on_finish = on_finish  # Called with the outcome when this attempt ends on its own (not replaced).
        self.stop = threading.Event()
        self.done = threading.Event()
        self.outcome = None  # 'success' | 'failed' | 'expired' | 'cancelled'

    def run(self, home):
        try:
            params = self.server.wait_for('account/login/completed', lambda p: p.get('loginId') == self.login_id,
                                          time.monotonic() + SIGN_IN_TIMEOUT_S, self.stop)
            if self.stop.is_set():
                self.outcome = 'cancelled'
            elif params is None:
                self.outcome = 'expired'
            else:
                self.outcome = 'success' if params.get('success') is True else 'failed'
        finally:
            with _lock:
                current = _active.get(home) is self
                if current:
                    del _active[home]
                    _outcomes[home] = self.outcome
            self.server.close()
            self.done.set()
        # A replaced or cancelled attempt reports nothing: the user started another one, or the app is closing.
        if current and self.outcome != 'cancelled' and self.on_finish is not None:
            try:
                self.on_finish(self.outcome)
            except Exception:
                pass  # The caller's report failing must not break sign-in; the next status read still answers.

    def cancel(self):
        try:
            if self.server.alive:
                self.server.request('account/login/cancel', {'loginId': self.login_id}, timeout=3)
        except AuthError:
            pass
        self.stop.set()
        self.done.wait(5)


_lock = threading.Lock()
_active = {}    # str(codex_home) -> _DeviceSignIn
_outcomes = {}  # str(codex_home) -> outcome of the last finished sign-in


def pending(codex_home):
    with _lock:
        return str(codex_home) in _active


def cancel_all():
    """Stop every pending sign-in (app shutdown, tests)."""
    with _lock:
        attempts = list(_active.values())
    for attempt in attempts:
        attempt.cancel()


OUTCOME_DETAILS = {
    'failed': 'Codex sign-in did not complete. Start it again when ready.',
    'expired': 'The Codex sign-in code expired. Start it again when ready.',
    'cancelled': 'Codex sign-in was cancelled.',
}


def _model(item):
    """One `model/list` entry cut to the contract, or None when it is not a usable model."""
    from runtime import registry
    if not isinstance(item, dict) or not isinstance(item.get('id'), str):
        return None
    try:
        model = registry.check_model('codex', item['id'])
    except ValueError:
        return None
    efforts = []
    for entry in item.get('supportedReasoningEfforts') or []:
        effort = entry.get('reasoningEffort') if isinstance(entry, dict) else entry
        try:
            ok = isinstance(effort, str) and registry.check_effort('codex', effort)
        except ValueError:
            continue
        if ok and effort not in efforts:
            efforts.append(effort)
    default = item.get('defaultReasoningEffort')
    try:
        default = registry.check_effort('codex', default) if isinstance(default, str) else None
    except ValueError:
        default = None
    return {'id': model, 'is_default': item.get('isDefault') is True, 'default_effort': default, 'efforts': efforts}


class CodexAuth:
    """Codex sign-in helper. `command` is the codex argv prefix; `codex_home` and `environ` select the home."""

    def __init__(self, binary=None, *, command=None, codex_home=None, environ=None):
        if command is not None:
            self.command = list(command) or None  # An empty command means no Codex is installed.
        else:
            binary = str(binary) if binary else find_codex()
            self.command = [binary] if binary else None
        self.codex_home = Path(codex_home) if codex_home else None
        self.environ = dict(environ) if environ is not None else None

    @property
    def binary(self):
        return self.command[0] if self.command else None

    @binary.setter
    def binary(self, value):
        self.command = [str(value)] if value else None

    # -- the app-owned home: app-server account RPCs ---------------------------------------------------

    def _env(self):
        env = dict(self.environ if self.environ is not None else os.environ)
        if self.codex_home is not None:
            env['CODEX_HOME'] = str(self.codex_home)
        return env

    def _server(self):
        if self.codex_home is None:
            raise AuthError('Interspace has no data folder for Codex.')
        self.codex_home.mkdir(parents=True, exist_ok=True)
        server = AppServer(self.command + ['app-server'] + config_args(), self._env(), str(self.codex_home))
        try:
            server.initialize()
        except AuthError:
            server.close()
            raise AuthError('Codex did not start. Check its installation and try again.') from None
        return server

    def _read_account(self, server):
        result = server.request('account/read', {'refreshToken': False})
        account = result.get('account')
        if account is None:
            return None
        if not isinstance(account, dict):
            raise AuthError('Codex sent an account Interspace does not understand.')
        return account_name(account)

    def account_status(self):
        """{'state', 'account', 'detail'} for the app-owned home."""
        if not self.command:
            return {'state': 'missing_cli', 'account': None,
                    'detail': 'Install Codex CLI or the ChatGPT Mac app to use Codex.'}
        home = str(self.codex_home)
        with _lock:
            attempt = _active.get(home)
            outcome = _outcomes.get(home)
        try:
            if attempt is not None and attempt.server.alive:
                name = self._read_account(attempt.server)
            else:
                attempt = None
                server = self._server()
                try:
                    name = self._read_account(server)
                finally:
                    server.close()
        except AuthError as error:
            return {'state': 'error', 'account': None, 'detail': str(error)}
        if name is not None:
            return {'state': 'signed_in', 'account': name, 'detail': 'Codex is signed in with your ChatGPT account.'}
        if attempt is not None:
            detail = 'Waiting for you to finish signing in to Codex in the browser.'
        else:
            detail = OUTCOME_DETAILS.get(outcome, 'Sign in to Codex with your ChatGPT account.')
        return {'state': 'signed_out', 'account': None, 'detail': detail}

    def list_models(self):
        """The signed-in account's models: [{'id', 'is_default', 'default_effort', 'efforts'}], else AuthError.

        Reads `account/read` first, since a signed-out account also answers `model/list` with another list.
        """
        if not self.command:
            raise AuthError('Install Codex CLI or the ChatGPT Mac app to see its models.')
        deadline = time.monotonic() + MODELS_TIMEOUT_S

        def left():
            return max(deadline - time.monotonic(), 0.1)
        server = self._server()
        try:
            if self._read_account_within(server, left()) is None:
                raise AuthError('Sign in to Codex to see its models.')
            found, cursor = [], None
            for _ in range(MAX_MODEL_PAGES):
                if time.monotonic() >= deadline:
                    raise AuthError('Codex took too long to list its models.')
                result = server.request('model/list', {'cursor': cursor} if cursor else {}, left())
                page = result.get('data', result.get('models'))
                if not isinstance(page, list):
                    raise AuthError('Codex sent a model list Interspace does not understand.')
                found += [m for m in map(_model, page) if m]
                cursor = result.get('nextCursor')
                if not isinstance(cursor, str) or not cursor:
                    break
            return found
        except AuthError as error:
            if str(error).startswith('Codex stopped answering'):
                raise AuthError('Codex did not list its models in time. Try again.') from None
            raise
        finally:
            server.close()

    def _read_account_within(self, server, timeout):
        result = server.request('account/read', {'refreshToken': False}, timeout)
        account = result.get('account')
        if account is not None and not isinstance(account, dict):
            raise AuthError('Codex sent an account Interspace does not understand.')
        return account

    def begin_device_sign_in(self, on_finish=None):
        """Start a device sign-in; returns {'kind': 'device', 'url', 'code', 'detail'} and keeps waiting.

        `on_finish(outcome)` runs on the waiting thread once the sign-in succeeds, fails or expires
        ('success' | 'failed' | 'expired'), after the attempt is over. It is not called when the attempt is
        replaced by a new sign-in, signed out or cancelled.
        """
        if not self.command:
            raise AuthError('Install Codex CLI or the ChatGPT Mac app before signing in.')
        home = str(self.codex_home)
        with _lock:
            previous = _active.pop(home, None)
            _outcomes.pop(home, None)
        if previous is not None:
            previous.cancel()
        server = self._server()
        try:
            started = server.request('account/login/start', {'type': 'chatgptDeviceCode'})
            url, code, login_id = started.get('verificationUrl'), started.get('userCode'), started.get('loginId')
            if started.get('type') != 'chatgptDeviceCode' or not isinstance(url, str) or not URL_RE.match(url) \
                    or len(url) > 300 or not isinstance(code, str) or not CODE_RE.match(code) \
                    or not isinstance(login_id, str) or not ID_RE.match(login_id):
                raise AuthError('Codex sent a sign-in code Interspace does not understand.')
        except AuthError:
            server.close()
            raise
        attempt = _DeviceSignIn(server, login_id, on_finish)
        with _lock:
            _active[home] = attempt
        threading.Thread(target=attempt.run, args=(home,), daemon=True, name='codex-device-sign-in').start()
        return {'kind': 'device', 'url': url, 'code': code,
                'detail': 'Open the link, sign in with your ChatGPT account and enter the code.'}

    def sign_out(self):
        """Sign the app-owned home out (idempotent); returns the new status."""
        if not self.command:
            return self.account_status()
        home = str(self.codex_home)
        with _lock:
            previous = _active.pop(home, None)
            _outcomes.pop(home, None)
        if previous is not None:
            previous.cancel()
        server = self._server()
        try:
            server.request('account/logout')
        finally:
            server.close()
        return self.account_status()

    # -- legacy CLI forms ------------------------------------------------------------------------------

    def _cli(self, args):
        prefix = config_args() if self.codex_home is not None else []
        return self.command + prefix + list(args)

    def _cli_env(self):
        return self._env() if self.codex_home is not None or self.environ is not None else None

    def status(self):
        if not self.command:
            return {'ready': False, 'message': 'Install Codex CLI or the ChatGPT Mac app to connect OpenAI.'}
        try:
            result = subprocess.run(self._cli(['login', 'status']), capture_output=True, timeout=10,
                                    env=self._cli_env())
            return {'ready': result.returncode == 0,
                    'message': 'Codex signed in' if result.returncode == 0 else 'Sign in to Codex with your ChatGPT account.'}
        except (OSError, subprocess.TimeoutExpired):
            return {'ready': False, 'message': 'Codex could not be started. Check its installation.'}

    def sign_in(self, cancel, emit):
        if not self.command:
            raise AuthError('Install Codex CLI or the ChatGPT Mac app before signing in.')
        try:
            process = subprocess.Popen(self._cli(['login', '--device-auth']), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       start_new_session=True, env=self._cli_env())
        except OSError as error:
            raise AuthError('Codex could not be started. Check its installation.') from error
        messages = []

        def read():
            for line in process.stdout:
                clean = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', line).strip()
                if clean:
                    messages.append(clean)
                    emit('\n'.join(messages)[-4000:])
        worker = threading.Thread(target=read, daemon=True)
        worker.start()
        deadline = time.monotonic() + 180
        try:
            while process.poll() is None:
                if cancel.wait(.1):
                    raise AuthError('Sign-in cancelled.')
                if time.monotonic() >= deadline:
                    raise AuthError('Sign-in deadline reached. Start sign-in again when ready.')
            if process.returncode != 0:
                raise AuthError('Codex sign-in did not complete. Check the device authorization instructions.')
        finally:
            self.stop(process)
            worker.join(timeout=2)
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass

    @staticmethod
    def stop(process):
        _stop_process(process)
