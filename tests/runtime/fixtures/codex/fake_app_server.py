"""A scripted stand-in for `codex app-server` (stdio JSON-RPC, no "jsonrpc" field), for runtime tests.

Usage: fake_app_server.py <scenario.json> <log.jsonl> app-server [-c key=value ...]

The first log line records argv, cwd and the environment's keys; every line received after that is logged as
{"in": message}, and every server-request reply as well. Message shapes follow the 0B spike's live transcript
(docs/research/codex-app-server-runtime.md). Strings "$thread" and "$turn" in scenario steps are replaced.

Scenario keys:
  account       the `account/read` result's `account` (default {"type": "chatgpt"}); null = signed out
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
        return value.replace('$thread', THREAD).replace('$turn', turn_id)
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
    elif method == 'account/read':
        account = scenario.get('account', {'type': 'chatgpt'})
        send({'id': request_id, 'result': {'account': account, 'requiresOpenaiAuth': account is None}})
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
