#!/usr/bin/env python3
"""Spike 0B: real `claude` CLI, fake model. Records the stdio permission protocol for Edit/Write/Bash.

A local HTTP server plays the Anthropic Messages API (SSE) and scripts tool_use steps. The CLI runs with
ANTHROPIC_BASE_URL pointing at it and a dummy API key in a scratch CLAUDE_CONFIG_DIR/HOME, so no account,
keychain entry or real model is touched. The driver answers every can_use_tool control_request from SCRIPT.

Usage: claude_permission_probe.py SCRATCH_DIR   (creates SCRATCH_DIR/repo as a git repo; writes transcript.jsonl)
"""
import http.server, json, os, shutil, subprocess, sys, threading, time

SCRATCH = os.path.abspath(sys.argv[1])
REPO = os.path.join(SCRATCH, 'repo')
# Outside the CLI's cwd and not under TMPDIR (the Bash sandbox allows writes to temp folders).
OUTSIDE = os.environ.get('SPIKE_OUTSIDE') or os.path.join(SCRATCH, 'outside')
CLAUDE = shutil.which('claude') or os.path.expanduser('~/.local/bin/claude')

# (tool name, input, host answer). Answers: 'allow' echoes the exact input as updatedInput; 'deny' refuses.
SCRIPT = [
    ('Write', {'file_path': os.path.join(REPO, 'hello.txt'), 'content': 'hello\n'}, 'allow'),
    ('Edit', {'file_path': os.path.join(REPO, 'hello.txt'), 'old_string': 'hello', 'new_string': 'DENIED'}, 'deny'),
    ('Edit', {'file_path': os.path.join(REPO, 'hello.txt'), 'old_string': 'hello', 'new_string': 'hello world'}, 'allow'),
    ('Bash', {'command': 'echo from-bash > bash.txt', 'description': 'write bash.txt'}, 'allow'),
    ('Write', {'file_path': os.path.join(OUTSIDE, 'escaped.txt'), 'content': 'outside\n'}, 'allow'),
    ('Bash', {'command': 'echo esc > ' + os.path.join(OUTSIDE, 'bash-escaped.txt'), 'description': 'write outside'}, 'allow'),
    ('Write', {'file_path': os.path.join(REPO, 'relative-check.txt'), 'content': 'x\n'}, 'allow-modified'),
]

os.makedirs(SCRATCH, exist_ok=True)
transcript = open(os.path.join(SCRATCH, 'transcript.jsonl'), 'w')
def rec(direction, obj):
    transcript.write(json.dumps({'dir': direction, 'msg': obj}) + '\n'); transcript.flush()


def sse(events):
    return ''.join('event: %s\ndata: %s\n\n' % (e['type'], json.dumps(e)) for e in events).encode()


def reply_events(model, step):
    usage = {'input_tokens': 10, 'output_tokens': 5, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}
    start = {'type': 'message_start', 'message': {'id': 'msg_%d' % step, 'type': 'message', 'role': 'assistant',
             'model': model, 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': usage}}
    if step < len(SCRIPT):
        name, inp, _ = SCRIPT[step]
        block = {'type': 'tool_use', 'id': 'toolu_%02d' % step, 'name': name, 'input': {}}
        delta = {'type': 'input_json_delta', 'partial_json': json.dumps(inp)}
        stop = 'tool_use'
    else:
        block, delta, stop = {'type': 'text', 'text': ''}, {'type': 'text_delta', 'text': 'done'}, 'end_turn'
    return [start, {'type': 'content_block_start', 'index': 0, 'content_block': block},
            {'type': 'content_block_delta', 'index': 0, 'delta': delta},
            {'type': 'content_block_stop', 'index': 0},
            {'type': 'message_delta', 'delta': {'stop_reason': stop, 'stop_sequence': None}, 'usage': {'output_tokens': 5}},
            {'type': 'message_stop'}]


class Api(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('content-length', 0))) or b'{}')
        path = self.path.split('?')[0]
        rec('api', {'path': path, 'model': body.get('model'), 'tools': [t.get('name') for t in body.get('tools') or []],
                    'n_messages': len(body.get('messages') or [])})
        if path.endswith('/count_tokens'):
            out = json.dumps({'input_tokens': 10}).encode()
            self.send_response(200); self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(out))); self.end_headers(); self.wfile.write(out); return
        msgs = body.get('messages') or []
        main = bool(body.get('tools'))
        # Step = number of tool_result blocks so far (main loop only); helper calls just get text.
        step = sum(1 for m in msgs if m.get('role') == 'user' and isinstance(m.get('content'), list)
                   for b in m['content'] if isinstance(b, dict) and b.get('type') == 'tool_result') if main else len(SCRIPT)
        if main:
            last = msgs[-1] if msgs else {}
            for b in last.get('content') if isinstance(last.get('content'), list) else []:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    rec('tool_result_to_model', b)
        data = sse(reply_events(body.get('model') or 'x', step)) if body.get('stream') else None
        if data is None:  # non-streaming helper call
            data = json.dumps({'id': 'msg_h', 'type': 'message', 'role': 'assistant', 'model': body.get('model'),
                               'content': [{'type': 'text', 'text': 'ok'}], 'stop_reason': 'end_turn',
                               'usage': {'input_tokens': 1, 'output_tokens': 1}}).encode()
            ctype = 'application/json'
        else:
            ctype = 'text/event-stream'
        self.send_response(200); self.send_header('content-type', ctype)
        self.send_header('content-length', str(len(data))); self.end_headers(); self.wfile.write(data)


def main():
    for d in (REPO, OUTSIDE, os.path.join(SCRATCH, 'home'), os.path.join(SCRATCH, 'cfg')):
        os.makedirs(d, exist_ok=True)
    subprocess.run(['git', 'init', '-q', REPO], check=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {'PATH': os.environ['PATH'], 'HOME': os.path.join(SCRATCH, 'home'), 'TMPDIR': os.environ.get('TMPDIR', '/tmp'),
           'LANG': 'en_US.UTF-8', 'USER': os.environ.get('USER', 'u'),
           'CLAUDE_CONFIG_DIR': os.path.join(SCRATCH, 'cfg'),
           'ANTHROPIC_BASE_URL': 'http://127.0.0.1:%d' % server.server_port,
           'ANTHROPIC_API_KEY': 'sk-ant-spike-dummy-not-a-key',
           'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1', 'DISABLE_AUTOUPDATER': '1'}
    tools = ['Read', 'Grep', 'Glob', 'Bash', 'Edit', 'Write']
    settings = {'permissions': {'allow': [], 'deny': [], 'ask': tools}, 'disableAllHooks': True,
                'sandbox': {'enabled': os.environ.get('SPIKE_SANDBOX', '1') == '1', 'autoAllowBashIfSandboxed': False,
                            'allowUnsandboxedCommands': False}}
    argv = [CLAUDE, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
            '--model', 'claude-sonnet-5-5', '--tools', ','.join(tools), '--permission-mode',
            os.environ.get('SPIKE_MODE', 'manual'), '--permission-prompt-tool', 'stdio', '--permission-prompts', 'host',
            '--setting-sources', '', '--settings', json.dumps(settings), '--strict-mcp-config',
            '--disable-slash-commands', '--no-session-persistence', '--max-turns', '20']
    p = subprocess.Popen(argv, cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    threading.Thread(target=lambda: [rec('stderr', l.rstrip()) for l in p.stderr], daemon=True).start()
    def send(obj):
        rec('host', obj); p.stdin.write(json.dumps(obj) + '\n'); p.stdin.flush()
    send({'type': 'control_request', 'request_id': 'req_init', 'request': {'subtype': 'initialize', 'hooks': None}})
    send({'type': 'user', 'message': {'role': 'user', 'content': 'run the script'}, 'parent_tool_use_id': None,
          'session_id': ''})
    deadline = time.time() + 120
    turns_left = int(os.environ.get('SPIKE_TURNS', '1'))
    for line in p.stdout:
        msg = json.loads(line)
        rec('cli', msg)
        if msg.get('type') == 'control_request' and msg['request'].get('subtype') == 'can_use_tool':
            req = msg['request']
            # Match by tool_use_id: the CLI normalises input (Edit gains replace_all=false), so input != script.
            tid = req.get('tool_use_id') or ''
            idx = int(tid[6:]) if tid.startswith('toolu_') and tid[6:].isdigit() else None
            answer = SCRIPT[idx][2] if idx is not None and idx < len(SCRIPT) else 'deny'
            if answer == 'allow':
                resp = {'behavior': 'allow', 'updatedInput': req['input']}
            elif answer == 'allow-modified':  # host rewrites input: does the CLI honour updatedInput?
                resp = {'behavior': 'allow', 'updatedInput': dict(req['input'], content='rewritten-by-host\n')}
            else:
                resp = {'behavior': 'deny', 'message': 'Denied by spike host.'}
            send({'type': 'control_response', 'response': {'subtype': 'success', 'request_id': msg['request_id'],
                                                           'response': resp}})
        if msg.get('type') == 'result':
            turns_left -= 1
            if turns_left > 0:  # SPIKE_TURNS=2: second user message in the same process (usage per turn?)
                send({'type': 'user', 'message': {'role': 'user', 'content': 'again'}, 'parent_tool_use_id': None,
                      'session_id': ''})
                continue
            break
        if time.time() > deadline:
            break
    p.stdin.close()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()
    server.shutdown()
    for root in (REPO, OUTSIDE):
        for name in sorted(os.listdir(root)):
            if os.path.isfile(os.path.join(root, name)):
                print('%s/%s: %r' % (os.path.basename(root), name, open(os.path.join(root, name)).read()))


if __name__ == '__main__':
    main()
