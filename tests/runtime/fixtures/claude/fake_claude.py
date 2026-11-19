"""A fake `claude` CLI that replays a JSON scenario over the stream-json control protocol.

Usage (through a generated wrapper): fake_claude.py <scenario.json> <log.jsonl> <claude args...>

It never contacts a network or reads credentials. Every launch, every stdin line and every
answer it gets is appended to the log so tests can assert what the adapter sent.

Scenario keys:
  auth: {"exit": 0, "stdout": "<text>"}         answer to `claude auth status`
  turns: [[step, ...], ...]                      steps replayed for each user message
  by_prompt: [{"contains": "<text>", "turns": [...]}, ...]
                                                 the first entry whose text is in --system-prompt replaces
                                                 `turns` (one scenario file for several sessions)
Steps:
  {"emit": <object>}       write one JSON line (the string "$MODEL" is replaced by --model)
  {"raw": "<text>"}        write a raw line
  {"init": {...}}          write system/init built from the launch flags, with overrides
  {"ask": {"tool_name", "input", "tool_use_id", "result": "<text>", "request_input": {...}}}
                           emit the assistant tool_use, send can_use_tool, wait for the answer,
                           then emit a tool_result (ok on allow, is_error on deny). `request_input`, when
                           given, is the input in can_use_tool (the real CLI normalises the model's input
                           before asking, spike-0b.md gotcha 1); the tool_use block keeps `input`.
  {"mcp_call": {"name", "arguments", "tool_use_id"}}
                           call the bridge socket named in the --mcp-config file (with its token), then emit a
                           tool_result. A server with FAKE_TOOLS in its env is the tests' fake bridge (one JSON
                           line each way); otherwise it is the real Interspace bridge, spoken to as MCP.
                           "$team_id" in arguments is replaced by the last team_id a call returned.
  {"ask": {..., "apply": {"path", "text"}}}  on allow, also write that file (relative to the working folder),
                           as the real CLI's Edit/Write would
  {"ask": {..., "mcp": true}}  an Interspace bridge tool (tool_name mcp__interspace__<name>): on allow, call it
                           on the bridge with the allowed input, as the real CLI does, and emit its result
  {"spawn": [argv...]}     start a background child process (a command left running)
  {"kill_spawned": true}   stop the children started with spawn
  {"touch": "<path>"}      create that file
  {"wait_file": "<path>"}  wait (up to 20 s, else exit 3) until that file exists
  {"control": <request>}   send a control_request and wait for its control_response
  {"wait_interrupt": true} wait for an interrupt control_request, answer it, emit an interrupted result
  {"ignore_interrupt": true} like wait_interrupt but never answers and never ends
  {"hang": true}           sleep until killed
  {"exit": <code>}         exit now
  {"spam": <bytes>}        write that many bytes of valid assistant lines
"""
import json
import os
import socket
import subprocess
import sys
import time

scenario_path, log_path = sys.argv[1], sys.argv[2]
args = sys.argv[3:]
with open(scenario_path) as handle:
    scenario = json.load(handle)


def log(entry):
    with open(log_path, 'a') as handle:
        handle.write(json.dumps(entry) + '\n')


log({'launch': args, 'env': dict(os.environ), 'cwd': os.getcwd(), 'pid': os.getpid(), 'pgid': os.getpgid(0)})

if args[:2] == ['auth', 'status']:
    auth = scenario.get('auth', {'exit': 0, 'stdout': json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})})
    sys.stdout.write(auth.get('stdout', ''))
    sys.stdout.flush()
    sys.exit(auth.get('exit', 0))


def flag(name):
    return args[args.index(name) + 1] if name in args else None


MODEL = flag('--model')
counter = [0]
saved = {}


def out(obj):
    text = json.dumps(obj).replace('$MODEL', MODEL or '')
    sys.stdout.write(text + '\n')
    sys.stdout.flush()


def read():
    line = sys.stdin.readline()
    if not line:
        log({'eof': True})
        sys.exit(0)
    message = json.loads(line)
    log({'stdin': message})
    return message


def control(request):
    counter[0] += 1
    request_id = 'cli_%d' % counter[0]
    out({'type': 'control_request', 'request_id': request_id, 'request': request})
    while True:
        message = read()
        if message.get('type') == 'control_response' and message['response'].get('request_id') == request_id:
            return message['response']


def tool_result(tool_use_id, text, is_error):
    out({'type': 'user', 'parent_tool_use_id': None, 'session_id': 's1',
         'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tool_use_id,
                                                   'content': text, 'is_error': is_error}]}})


def mcp_servers():
    config = flag('--mcp-config')
    if not config:
        return {}
    with open(config) as handle:  # A file path: the bridge token never sits in argv.
        loaded = json.load(handle)
    log({'mcp_config': loaded, 'mode': oct(os.stat(config).st_mode & 0o777)})
    return loaded['mcpServers']


def mcp_rpc(server, requests):
    """Speak MCP to the real Interspace bridge: hello with the token, then each request; returns the results."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(server['env']['INTERSPACE_MCP_SOCKET'])
    reader = client.makefile('rb')

    def send(message):
        client.sendall((json.dumps(message) + '\n').encode())
    send({'token': server['env']['INTERSPACE_MCP_TOKEN']})
    send({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}})
    send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    results = {}
    for index, (method, params) in enumerate(requests, 1):
        send({'jsonrpc': '2.0', 'id': index, 'method': method, 'params': params})
    while len(results) < len(requests):
        line = reader.readline()
        if not line:
            break
        message = json.loads(line)
        if message.get('id'):
            results[message['id']] = message.get('result')
    client.close()
    return [results.get(i) for i in range(1, len(requests) + 1)]


def init(overrides):
    tools = [t for t in (flag('--tools') or '').split(',') if t]
    servers = []
    for name, server in mcp_servers().items():
        servers.append({'name': name, 'status': 'connected'})
        if 'FAKE_TOOLS' in server['env']:
            names = server['env']['FAKE_TOOLS'].split(',')
        else:
            names = [t['name'] for t in mcp_rpc(server, [('tools/list', {})])[0]['tools']]
        tools += ['mcp__%s__%s' % (name, tool) for tool in names]
    message = {'type': 'system', 'subtype': 'init', 'session_id': 's1', 'cwd': os.getcwd(), 'tools': tools,
               # Like Claude Code 2.1.322: `--permission-mode manual` is reported as "default".
               'mcp_servers': servers, 'model': MODEL,
               'permissionMode': 'default' if flag('--permission-mode') == 'manual' else flag('--permission-mode'),
               'apiKeySource': 'none'}
    message.update(overrides)
    out(message)


def interrupted_result():
    out({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'session_id': 's1',
         'num_turns': 1, 'permission_denials': [],
         'usage': {'input_tokens': 5, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 1},
         'modelUsage': {MODEL: {'inputTokens': 5, 'outputTokens': 1, 'cacheReadInputTokens': 0,
                                'cacheCreationInputTokens': 0, 'costUSD': 0.01}}})


def substitute(value):
    if isinstance(value, str):
        return saved.get(value[1:], value) if value.startswith('$') else value
    if isinstance(value, list):
        return [substitute(v) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v) for k, v in value.items()}
    return value


def mcp_call(step, literal=False):
    server = next(iter(mcp_servers().values()))
    arguments = step['arguments'] if literal else substitute(step['arguments'])
    if 'FAKE_TOOLS' not in server['env']:
        result = mcp_rpc(server, [('tools/call', {'name': step['name'], 'arguments': arguments})])[0]
        log({'mcp_reply': result})
        text = result['content'][0]['text']
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get('team_id'), str):
            saved['team_id'] = parsed['team_id']
        tool_result(step['tool_use_id'], text, bool(result.get('isError')))
        return
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(server['env']['INTERSPACE_MCP_SOCKET'])
    client.sendall((json.dumps({'token': server['env']['INTERSPACE_MCP_TOKEN'], 'name': step['name'],
                                'arguments': step['arguments']}) + '\n').encode())
    data = b''
    while not data.endswith(b'\n'):
        chunk = client.recv(65536)
        if not chunk:
            break
        data += chunk
    client.close()
    log({'mcp_reply': json.loads(data)})
    tool_result(step['tool_use_id'], data.decode().strip(), False)


def run_step(step):
    if 'emit' in step:
        out(step['emit'])
    elif 'raw' in step:
        sys.stdout.write(step['raw'] + '\n')
        sys.stdout.flush()
    elif 'init' in step:
        init(step['init'])
    elif 'ask' in step:
        ask = step['ask']
        out({'type': 'assistant', 'parent_tool_use_id': None, 'session_id': 's1',
             'message': {'id': 'msg_t', 'role': 'assistant', 'model': MODEL,
                         'content': [{'type': 'tool_use', 'id': ask['tool_use_id'], 'name': ask['tool_name'],
                                      'input': ask['input']}]}})
        response = control({'subtype': 'can_use_tool', 'tool_name': ask['tool_name'],
                            'input': ask.get('request_input', ask['input']),
                            'tool_use_id': ask['tool_use_id'], 'permission_suggestions': []})
        answer = response.get('response', {})
        log({'answer': answer})
        if answer.get('behavior') == 'allow' and ask.get('apply'):
            with open(ask['apply']['path'], 'w') as handle:
                handle.write(ask['apply']['text'])
        if ask.get('mcp') and answer.get('behavior') == 'allow':
            mcp_call({'name': ask['tool_name'].split('__', 2)[2], 'arguments': answer['updatedInput'],
                      'tool_use_id': ask['tool_use_id']}, literal=True)
        elif not ask.get('no_result'):
            if answer.get('behavior') == 'allow':
                tool_result(ask['tool_use_id'], ask.get('result', 'ok'), False)
            else:
                tool_result(ask['tool_use_id'], answer.get('message', 'denied'), True)
    elif 'mcp_call' in step:
        mcp_call(step['mcp_call'])
    elif 'control' in step:
        log({'control_answer': control(step['control'])})
    elif 'wait_interrupt' in step or 'ignore_interrupt' in step:
        while True:
            message = read()
            if message.get('type') == 'control_request' and message['request'].get('subtype') == 'interrupt':
                break
        if 'ignore_interrupt' in step:
            while True:
                time.sleep(1)
        out({'type': 'control_response', 'response': {'subtype': 'success', 'request_id': message['request_id']}})
        interrupted_result()
    elif 'spawn' in step:
        spawned.append(subprocess.Popen(step['spawn']))
    elif 'kill_spawned' in step:
        for child in spawned:
            child.kill()
            child.wait()
        del spawned[:]
    elif 'touch' in step:
        open(step['touch'], 'a').close()
    elif 'wait_file' in step:
        deadline = time.monotonic() + 20
        while not os.path.exists(step['wait_file']):
            if time.monotonic() > deadline:
                log({'timeout': step['wait_file']})
                sys.exit(3)
            time.sleep(0.02)
    elif 'hang' in step:
        while True:
            time.sleep(1)
    elif 'exit' in step:
        sys.exit(step['exit'])
    elif 'spam' in step:
        line = json.dumps({'type': 'assistant', 'parent_tool_use_id': None, 'session_id': 's1',
                           'message': {'id': 'msg_s', 'role': 'assistant', 'model': MODEL,
                                       'content': [{'type': 'text', 'text': 'x' * 1000}]}}) + '\n'
        for _ in range(step['spam'] // len(line) + 1):
            sys.stdout.write(line)
        sys.stdout.flush()


spawned = []
turns = scenario.get('turns', [])
for choice in scenario.get('by_prompt', []):
    if choice['contains'] in (flag('--system-prompt') or ''):
        turns = choice['turns']
        break
turn = 0
while True:
    message = read()
    kind = message.get('type')
    if kind == 'control_request':
        subtype = message['request'].get('subtype')
        if subtype == 'initialize':
            if scenario.get('init_fail'):
                out({'type': 'control_response', 'response': {'subtype': 'error', 'request_id': message['request_id'],
                                                                'error': 'nope'}})
            else:
                out({'type': 'control_response', 'response': {'subtype': 'success', 'request_id': message['request_id'],
                                                                'response': {'commands': [], 'models': []}}})
        else:
            out({'type': 'control_response', 'response': {'subtype': 'success', 'request_id': message['request_id']}})
        continue
    if kind != 'user':
        continue
    steps = turns[turn] if turn < len(turns) else []
    turn += 1
    for step in steps:
        run_step(step)
