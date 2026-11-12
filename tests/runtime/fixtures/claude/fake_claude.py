"""A fake `claude` CLI that replays a JSON scenario over the stream-json control protocol.

Usage (through a generated wrapper): fake_claude.py <scenario.json> <log.jsonl> <claude args...>

It never contacts a network or reads credentials. Every launch, every stdin line and every
answer it gets is appended to the log so tests can assert what the adapter sent.

Scenario keys:
  auth: {"exit": 0, "stdout": "<text>"}         answer to `claude auth status`
  turns: [[step, ...], ...]                      steps replayed for each user message
Steps:
  {"emit": <object>}       write one JSON line (the string "$MODEL" is replaced by --model)
  {"raw": "<text>"}        write a raw line
  {"init": {...}}          write system/init built from the launch flags, with overrides
  {"ask": {"tool_name", "input", "tool_use_id", "result": "<text>"}}
                           emit the assistant tool_use, send can_use_tool, wait for the answer,
                           then emit a tool_result (ok on allow, is_error on deny)
  {"mcp_call": {"name", "arguments", "tool_use_id"}}
                           call the fake bridge socket named in the --mcp-config file (with its token),
                           then emit a tool_result
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


def init(overrides):
    tools = [t for t in (flag('--tools') or '').split(',') if t]
    servers = []
    for name, server in mcp_servers().items():
        servers.append({'name': name, 'status': 'connected'})
        tools += ['mcp__%s__%s' % (name, tool) for tool in server['env']['FAKE_TOOLS'].split(',')]
    message = {'type': 'system', 'subtype': 'init', 'session_id': 's1', 'cwd': os.getcwd(), 'tools': tools,
               'mcp_servers': servers, 'model': MODEL, 'permissionMode': flag('--permission-mode'),
               'apiKeySource': 'none'}
    message.update(overrides)
    out(message)


def interrupted_result():
    out({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'session_id': 's1',
         'num_turns': 1, 'permission_denials': [],
         'usage': {'input_tokens': 5, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 1},
         'modelUsage': {MODEL: {'inputTokens': 5, 'outputTokens': 1, 'cacheReadInputTokens': 0,
                                'cacheCreationInputTokens': 0, 'costUSD': 0.01}}})


def mcp_call(step):
    server = next(iter(mcp_servers().values()))
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
        response = control({'subtype': 'can_use_tool', 'tool_name': ask['tool_name'], 'input': ask['input'],
                            'tool_use_id': ask['tool_use_id'], 'permission_suggestions': []})
        answer = response.get('response', {})
        log({'answer': answer})
        if not ask.get('no_result'):
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


turns = scenario.get('turns', [])
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
