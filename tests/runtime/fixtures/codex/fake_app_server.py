"""A scripted stand-in for `codex app-server` (stdio JSON-RPC, no "jsonrpc" field), for runtime tests.

Usage: fake_app_server.py <scenario.json> <log.jsonl> app-server [-c key=value ...]

The first log line records argv, cwd and the environment's keys; every line received after that is logged as
{"in": message}, and every server-request reply as well. Message shapes follow the 0B spike's live transcript
(docs/research/codex-app-server-runtime.md). Strings "$thread" and "$turn" in scenario steps are replaced.

Scenario keys:
  account       the `account/read` result's `account` (default {"type": "chatgpt"}); null = signed out.
                A sign-in or sign-out saves the account in `$CODEX_HOME/fake-account.json`, which then wins,
                so later processes on the same home see it (like the real `auth.json`).
  after_initialize  notifications sent right after the `initialize` reply
  login         `account/login/start` behaviour: {"result": {...} (merged into the reply), "error": true,
                "complete_after": seconds (default 0.2; null = never), "success": true,
                "account": {...} (saved on success)}
  thread_start  fields merged into the `thread/start` result (to break the sandbox echo, for example)
  exit_on       a request method after which the process exits at once
  turns         a list, one entry per `turn/start`, each a list of steps:
    {"notify": method, "params": {...}}      send a notification
    {"request": method, "params": {...}}     send a server request and wait for its reply
    {"wait_interrupt": true}                 wait until the client sends turn/interrupt
    {"complete": status, "error": {...}}     send turn/completed for this turn
    {"raw": text}                            write one raw line
    {"exit": code}                           exit the process
    {"sleep": seconds}
    {"touch": path}                          create that file
    {"wait_file": path}                      wait (up to 20 s, else exit 3) until that file exists
"$cwd" in any step is replaced by the server's working folder.
"""
import json
import os
import sys
import threading
import time

scenario = json.load(open(sys.argv[1]))
log = open(sys.argv[2], 'a')
log_lock = threading.Lock()
write_lock = threading.Lock()
THREAD = 'thr-0001'
replies = {}
reply_cond = threading.Condition()
interrupted = threading.Event()
turn_count = [0]


def record(entry):
    with log_lock:
        log.write(json.dumps(entry) + '\n')
        log.flush()


def send(message):
    with write_lock:
        sys.stdout.write(json.dumps(message) + '\n')
        sys.stdout.flush()


def fill(value, turn_id):
    if isinstance(value, str):
        return value.replace('$thread', THREAD).replace('$turn', turn_id).replace('$cwd', os.getcwd())
    if isinstance(value, list):
        return [fill(v, turn_id) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, turn_id) for k, v in value.items()}
    return value


def play(steps, turn_id):
    next_id = [100]
    for step in steps:
        step = fill(step, turn_id)
        if 'notify' in step:
            send({'method': step['notify'], 'params': step.get('params', {})})
        elif 'request' in step:
            request_id = next_id[0]
            next_id[0] += 1
            send({'id': request_id, 'method': step['request'], 'params': step.get('params', {})})
            with reply_cond:
                if not reply_cond.wait_for(lambda: request_id in replies, 10):
                    record({'timeout': request_id})
                    os._exit(3)
        elif 'wait_interrupt' in step:
            if not interrupted.wait(10):
                record({'timeout': 'interrupt'})
                os._exit(3)
        elif 'complete' in step:
            send({'method': 'turn/completed', 'params': {'threadId': THREAD, 'turn': {
                'id': turn_id, 'items': [], 'status': step['complete'], 'error': step.get('error'),
                'durationMs': 5}}})
        elif 'raw' in step:
            with write_lock:
                sys.stdout.write(step['raw'] + '\n')
                sys.stdout.flush()
        elif 'exit' in step:
            os._exit(step['exit'])
        elif 'sleep' in step:
            time.sleep(step['sleep'])
        elif 'touch' in step:
            open(step['touch'], 'a').close()
        elif 'wait_file' in step:
            deadline = time.monotonic() + 20
            while not os.path.exists(step['wait_file']):
                if time.monotonic() > deadline:
                    record({'timeout': step['wait_file']})
                    os._exit(3)
                time.sleep(0.02)


def account_path():
    home = os.environ.get('CODEX_HOME')
    return os.path.join(home, 'fake-account.json') if home else None


def saved_account():
    path = account_path()
    if path and os.path.exists(path):
        with open(path) as handle:
            return json.load(handle)
    return scenario.get('account', {'type': 'chatgpt'})


def save_account(account):
    path = account_path()
    if path:
        with open(path, 'w') as handle:
            json.dump(account, handle)


def finish_login(login_id, login, delay):
    time.sleep(delay)
    success = login.get('success', True)
    if success:
        save_account(login.get('account', {'type': 'chatgpt', 'email': 'person@example.com', 'planType': 'pro'}))
    send({'method': 'account/login/completed', 'params': {'loginId': login_id, 'success': success,
                                                           'error': None if success else 'denied'}})
    if success:
        send({'method': 'account/updated', 'params': {'authMode': 'chatgpt', 'planType': 'pro'}})


def handle(message):
    method, request_id, params = message.get('method'), message.get('id'), message.get('params') or {}
    if method is None:
        with reply_cond:
            replies[request_id] = message
            reply_cond.notify_all()
        return
    if request_id is None:
        return
    if method == 'initialize':
        send({'id': request_id, 'result': {'userAgent': 'fake/0.167.0', 'codexHome': os.environ.get('CODEX_HOME'),
                                           'platformFamily': 'unix', 'platformOs': 'macos'}})
        for note in scenario.get('after_initialize', []):
            send(note)
    elif method == 'account/read':
        account = saved_account()
        send({'id': request_id, 'result': {'account': account, 'requiresOpenaiAuth': account is None,
                                           'userId': 'user-secret' if account else None}})
    elif method == 'account/login/start':
        login = scenario.get('login', {})
        if login.get('error'):
            send({'id': request_id, 'error': {'code': -32600, 'message': 'login refused'}})
        else:
            result = {'type': 'chatgptDeviceCode', 'loginId': 'login-1',
                      'verificationUrl': 'https://auth.openai.com/codex/device', 'userCode': 'ABCD-12345'}
            result.update(login.get('result', {}))
            send({'id': request_id, 'result': result})
            delay = login.get('complete_after', 0.2)
            if delay is not None:
                threading.Thread(target=finish_login, args=(result.get('loginId'), login, delay), daemon=True).start()
    elif method == 'account/login/cancel':
        send({'id': request_id, 'result': {}})
    elif method == 'account/logout':
        save_account(None)
        send({'id': request_id, 'result': {}})
        send({'method': 'account/updated', 'params': {'authMode': None, 'planType': None}})
    elif method == 'thread/start':
        result = {'thread': {'id': THREAD, 'ephemeral': True, 'status': {'type': 'idle'}},
                  'model': params.get('model') or 'gpt-test', 'modelProvider': 'openai', 'cwd': params.get('cwd'),
                  'instructionSources': [], 'approvalPolicy': params.get('approvalPolicy'),
                  'approvalsReviewer': params.get('approvalsReviewer'),
                  'sandbox': {'type': 'workspaceWrite', 'writableRoots': [params.get('cwd')], 'networkAccess': False},
                  'activePermissionProfile': {'id': params.get('permissions'), 'extends': ':workspace'}}
        result.update(scenario.get('thread_start', {}))
        send({'id': request_id, 'result': result})
    elif method == 'turn/start':
        index = turn_count[0]
        turn_count[0] += 1
        turn_id = 'turn-%d' % (index + 1)
        interrupted.clear()
        send({'id': request_id, 'result': {'turn': {'id': turn_id, 'status': 'inProgress', 'items': []}}})
        send({'method': 'turn/started', 'params': {'threadId': THREAD, 'turn': {'id': turn_id, 'status': 'inProgress'}}})
        turns = scenario.get('turns', [])
        steps = turns[index] if index < len(turns) else [{'complete': 'completed'}]
        threading.Thread(target=play, args=(steps, turn_id), daemon=True).start()
    elif method == 'turn/interrupt':
        send({'id': request_id, 'result': {}})
        interrupted.set()
    else:
        send({'id': request_id, 'error': {'code': -32601, 'message': 'unknown method ' + method}})
    if scenario.get('exit_on') == method:
        os._exit(0)


record({'argv': sys.argv[3:], 'cwd': os.getcwd(), 'env': sorted(os.environ), 'codex_home': os.environ.get('CODEX_HOME'),
        'pid': os.getpid(), 'pgid': os.getpgid(0)})
for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        record({'bad': line})
        continue
    record({'in': message})
    handle(message)
