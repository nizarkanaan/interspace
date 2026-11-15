"""Task scopes for agentic tasks: schema, digest binding, edits and the pure `decide` policy.

The contract is docs/superpowers/specs/agentic-spaces/scope.md. `decide` performs no I/O except
`os.path.realpath` and reads no clock except the `now` it is given. Rule matching on commands is a
guard against accidents and obvious escapes; the sandbox is the containment boundary.
"""
import copy
import hashlib
import json
import os
import posixpath
import re
import shlex

import budget

from timeutil import iso_time


VERSION = 1
MAX_PROJECTS = 8
MAX_PATTERNS = 64
MAX_PATTERN_CHARS = 256
MAX_PREFIX_ARGS = 8
MAX_HOSTS = 64
MAX_ID_CHARS = 128
MAX_REQUEST_PATHS = 1000
MAX_ARG_CHARS = 100000
MIN_TIME_LIMIT_S = 60
MAX_TIME_LIMIT_S = 86400
DEFAULT_TIME_LIMIT_S = 3600

ACCESS = ('read', 'write')
TRISTATE = ('allow', 'ask', 'deny')
SANDBOXES = ('workspace', 'escalated')
ANSWER_DECISIONS = ('allow_once', 'add_to_scope', 'deny', 'text', 'cancelled')
TOP_LEVEL_KEYS = ('v', 'task_id', 'version', 'projects', 'commands', 'network', 'apps', 'web_search', 'limits')

# Always-deny rule IDs (scope.md). Additions need the coordinator; removals need the user.
DENY_CREDENTIALS = 'always_deny.credentials'
DENY_KEYCHAIN = 'always_deny.keychain'
DENY_BYPASS = 'always_deny.bypass'
DENY_PRIVILEGE = 'always_deny.privilege'
DENY_OUTSIDE_WRITE = 'always_deny.outside_write'
DENY_APP_DATA = 'always_deny.app_data'
DENY_SHARING = 'always_deny.sharing'
DENY_SCOPE_SELF_EDIT = 'always_deny.scope_self_edit'
ASK_DESTRUCTIVE = 'always_ask.destructive'
ASK_ESCALATION = 'always_ask.escalation'
ASK_MCP = 'always_ask.mcp'
ASK_OUTSIDE_READ = 'always_ask.outside_read'
RULE_UNAPPROVED = 'approval.scope_unapproved'
RULE_DEFAULT_DENY = 'scope.default_deny'
RULE_INVALID = 'policy.invalid_request'
RULE_FAILED = 'policy.failed'
RULE_OUTSIDE = 'outside_scope'

CREDENTIAL_NAMES = frozenset(('id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', 'credentials', 'credentials.json',
                              'secrets.json'))
CREDENTIAL_SUFFIXES = ('.key', '.pem', '.p12', '.pfx')
# Relative to the user's home. Entries ending in '/' are directories.
CREDENTIAL_HOME_PATHS = ('.ssh/', '.aws/', '.config/gh/', '.codex/auth.json', '.claude/.credentials.json', '.netrc',
                         '.git-credentials', 'Library/Keychains/')
APP_DATA_RELATIVE = 'Library/Application Support/Interspace'
BYPASS_MARKERS = ('--dangerously-bypass-approvals-and-sandbox', '--yolo', 'danger-full-access',
                  '--dangerously-skip-permissions', 'bypassPermissions', 'approval_policy=never',
                  'approval-policy=never', 'sandbox_mode=', '--ask-for-approval=never')
BYPASS_FLAG_PAIRS = (('-a', 'never'), ('--ask-for-approval', 'never'))
PRIVILEGE_PREFIXES = (('sudo',), ('su',), ('doas',), ('osascript',), ('launchctl',), ('csrutil',), ('spctl',),
                      ('tccutil',), ('systemsetup',), ('dscl',), ('defaults', 'write'))
KEYCHAIN_COMMANDS = ('security',)
SHARING_WORDS = frozenset(('share', 'shares', 'sharing', 'unshare', 'permission', 'permissions', 'invite', 'invites',
                           'invitation', 'collaborator', 'collaborators', 'member', 'members', 'membership', 'owner',
                           'ownership', 'impersonate', 'impersonation'))
SELF_EDIT_WORDS = frozenset(('scope', 'scopes', 'approval', 'approve', 'budget', 'limit', 'limits'))
OWN_SERVER = 'interspace'

SHELL_OPERATORS = (';', '&&', '||', '|', '&', '`', '$(', '<', '>', '\n')
SHELLS = frozenset(('sh', 'bash', 'zsh', 'dash', 'fish'))
INTERPRETER = re.compile(r'^(python[0-9.]*|node|ruby|perl|php)$')
SIMPLE_WRAPPERS = frozenset(('command', 'builtin', 'exec', 'nohup'))
GIT_GLOBAL_WITH_VALUE = ('-C', '-c')
GIT_GLOBAL_FLAGS = ('--no-pager', '-P')
GIT_GLOBAL_PREFIXES = ('--git-dir=', '--work-tree=', '--exec-path=')

HOST = re.compile(r'^(\*\.)?[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$')
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
REDACT_FLAGS = ('--token', '--password', '--key', '-p')
REDACT_NAME = re.compile(r'TOKEN|SECRET|KEY|PASSWORD', re.I)
REDACTED = '[redacted]'

ON_OFF_NETWORK_TITLE = 'Allow network to any host for this one command?'


# ---------------------------------------------------------------- provisional seams

def network_per_host():
    """PROVISIONAL(0B-5): whether the sandbox can enforce command network per host.

    Until the runtime spike is reconciled the sandbox has on/off network only, so every command
    network request asks for "any host, this one command" and the host lists are not used.
    """
    return False


# ---------------------------------------------------------------- canonical JSON and digests

def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def sha256_digest(value):
    return 'sha256:' + hashlib.sha256(canonical_json(value)).hexdigest()


def digest(document):
    """Digest of the whole scope document, version included."""
    return sha256_digest(document)


def request_digest(request):
    return sha256_digest(request)


# ---------------------------------------------------------------- validation

def _fail(message):
    raise ValueError(message)


def _is_int(value):
    return type(value) is int


def _check_id(value, what):
    if not isinstance(value, str) or not value or len(value) > MAX_ID_CHARS:
        _fail('%s must be a non-empty identifier.' % what)


def _check_keys(value, keys, what):
    if not isinstance(value, dict) or set(value) != set(keys):
        _fail('%s must have exactly the fields %s.' % (what, ', '.join(keys)))


def validate_pattern(pattern):
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS:
        _fail('Path patterns must be 1 to %d characters.' % MAX_PATTERN_CHARS)
    if pattern.startswith('/') or '\\' in pattern or '\x00' in pattern or '..' in pattern.split('/'):
        _fail('Path patterns must be relative to the workspace, use "/", and never contain "..".')
    return pattern


def _check_list(values, what, limit, check):
    if not isinstance(values, list) or len(values) > limit:
        _fail('%s must be a list of at most %d entries.' % (what, limit))
    for value in values:
        check(value)


def _check_prefix(prefix):
    if (not isinstance(prefix, list) or not 1 <= len(prefix) <= MAX_PREFIX_ARGS
            or not all(isinstance(a, str) and a and '\x00' not in a for a in prefix)):
        _fail('Command rules must be lists of 1 to %d non-empty strings.' % MAX_PREFIX_ARGS)


def _check_host(host):
    if not isinstance(host, str) or len(host) > 253 or not HOST.match(host):
        _fail('Hosts must be lowercase names without scheme or port, optionally starting with "*.".')


def _check_project(entry, project_ids):
    _check_keys(entry, ('project_id', 'access', 'read', 'write', 'deny'), 'Each project')
    _check_id(entry['project_id'], 'Project ID')
    if project_ids is not None and entry['project_id'] not in project_ids:
        _fail('The scope names a project that is not registered.')
    if entry['access'] not in ACCESS:
        _fail('Project access must be read or write.')
    for field in ('read', 'write', 'deny'):
        _check_list(entry[field], 'Project %s patterns' % field, MAX_PATTERNS, validate_pattern)
    if entry['write'] and entry['access'] != 'write':
        _fail('Write patterns need write access to the project.')


def validate(document, *, project_ids=None):
    """Validate a whole scope document; raises ValueError with one sentence. Returns the document."""
    _check_keys(document, TOP_LEVEL_KEYS, 'The scope')
    if document['v'] != VERSION or not _is_int(document['v']):
        _fail('The scope format version is not supported.')
    _check_id(document['task_id'], 'Task ID')
    if not _is_int(document['version']) or document['version'] < 1:
        _fail('The scope version must be a positive whole number.')
    projects = document['projects']
    _check_list(projects, 'Projects', MAX_PROJECTS, lambda entry: _check_project(entry, project_ids))
    if len({entry['project_id'] for entry in projects}) != len(projects):
        _fail('A project is listed twice in the scope.')
    commands = document['commands']
    _check_keys(commands, ('workspace', 'allow', 'deny'), 'Commands')
    if commands['workspace'] not in TRISTATE:
        _fail('Workspace commands must be allow, ask or deny.')
    _check_list(commands['allow'], 'Allowed commands', MAX_PATTERNS, _check_prefix)
    _check_list(commands['deny'], 'Denied commands', MAX_PATTERNS, _check_prefix)
    network = document['network']
    _check_keys(network, ('default', 'allow_hosts', 'deny_hosts'), 'Network')
    if network['default'] not in ('ask', 'deny'):
        _fail('Network must be ask or deny.')
    _check_list(network['allow_hosts'], 'Allowed hosts', MAX_HOSTS, _check_host)
    _check_list(network['deny_hosts'], 'Denied hosts', MAX_HOSTS, _check_host)
    # Connected apps were removed (2026-11-15). The key stays, always empty, so saved scopes keep their digests.
    if document['apps'] != []:
        _fail('Connected apps are no longer supported; remove them from the scope.')
    if document['web_search'] not in TRISTATE:
        _fail('Web search must be allow, ask or deny.')
    limits = document['limits']
    _check_keys(limits, ('token_budget', 'time_limit_s'), 'Limits')
    budget.validate(limits['token_budget'])
    if not _is_int(limits['time_limit_s']) or not MIN_TIME_LIMIT_S <= limits['time_limit_s'] <= MAX_TIME_LIMIT_S:
        _fail('The time limit must be between %d and %d seconds.' % (MIN_TIME_LIMIT_S, MAX_TIME_LIMIT_S))
    return document


def default(task, project_ids, *, access='write'):
    """The starting scope the scope editor shows for a new agent task."""
    if access not in ACCESS:
        _fail('Project access must be read or write.')
    projects = [{'project_id': pid, 'access': access, 'read': ['**'],
                 'write': ['**'] if access == 'write' else [], 'deny': []} for pid in project_ids]
    any_write = any(entry['access'] == 'write' for entry in projects)
    document = {
        'v': VERSION, 'task_id': task['id'], 'version': 1, 'projects': projects,
        'commands': {'workspace': 'allow' if any_write else 'ask', 'allow': [], 'deny': []},
        'network': {'default': 'ask', 'allow_hosts': [], 'deny_hosts': []},
        'apps': [], 'web_search': 'ask',
        'limits': {'token_budget': task.get('token_budget'), 'time_limit_s': DEFAULT_TIME_LIMIT_S},
    }
    return validate(document)


DRAFT_TASK_ID = 'draft'  # Placeholder until agent_create assigns the real task ID.


def project_default(project_id, *, token_budget=None, project_ids=None):
    """`scope_default {project_id}`: the scope the new agent task form starts from.

    The project's workspace is readable and writable and workspace commands run without asking.
    No command network and no web search: the user widens the scope in the editor.
    `token_budget` is the project's budget, or budget.DEFAULT_BUDGET when it has none.
    """
    _check_id(project_id, 'Project ID')
    document = {
        'v': VERSION, 'task_id': DRAFT_TASK_ID, 'version': 1,
        'projects': [{'project_id': project_id, 'access': 'write', 'read': ['**'], 'write': ['**'], 'deny': []}],
        'commands': {'workspace': 'allow', 'allow': [], 'deny': []},
        'network': {'default': 'deny', 'allow_hosts': [], 'deny_hosts': []},
        'apps': [], 'web_search': 'deny',
        'limits': {'token_budget': budget.DEFAULT_BUDGET if token_budget is None else token_budget,
                   'time_limit_s': DEFAULT_TIME_LIMIT_S},
    }
    return validate(document, project_ids=project_ids)


# ---------------------------------------------------------------- approval and edits

def is_approved(document, approval):
    return (isinstance(approval, dict) and approval.get('v') == VERSION
            and approval.get('scope_version') == document.get('version')
            and approval.get('scope_digest') == digest(document))


def approve(document, scope_version, scope_digest, *, now):
    """`scope_approve`: succeeds only when the version and digest are the ones the user saw."""
    if scope_version != document['version'] or scope_digest != digest(document):
        _fail('The scope changed since it was shown; review it again before approving.')
    return {'v': VERSION, 'scope_version': document['version'], 'scope_digest': digest(document),
            'approved_at': iso_time(now), 'by': 'user'}


def edit(current, base_version, new_document, *, project_ids=None):
    """`scope_update`: returns the edited scope at base_version + 1. The caller clears the approval."""
    if base_version != current['version']:
        _fail('The scope changed since you opened it; reload it and edit again.')
    if not isinstance(new_document, dict):
        _fail('The scope must be an object.')
    document = copy.deepcopy(new_document)
    if document.get('task_id') != current['task_id']:
        _fail('A scope edit cannot move the scope to another task.')
    document['version'] = base_version + 1
    return validate(document, project_ids=project_ids)


PATCH_PROJECT_FIELDS = ('project_id', 'access', 'read', 'write', 'deny')


def merge_patch(document, patch):
    """Apply a scope patch: lists append missing entries, read may become write, nothing is removed.

    The version is unchanged; callers increment it. Raises ValueError for a patch outside the
    patchable fields or a result that is not a valid scope.
    """
    if not isinstance(patch, dict) or not set(patch) <= {'projects', 'commands', 'network'}:
        _fail('A scope patch may only widen projects, commands or network hosts.')
    merged = copy.deepcopy(document)
    for entry in patch.get('projects', []):
        if not isinstance(entry, dict) or not set(entry) <= set(PATCH_PROJECT_FIELDS) or 'project_id' not in entry:
            _fail('A project patch names a project and its widened fields.')
        target = next((p for p in merged['projects'] if p['project_id'] == entry['project_id']), None)
        if target is None:
            target = {'project_id': entry['project_id'], 'access': 'read', 'read': [], 'write': [], 'deny': []}
            merged['projects'].append(target)
        if entry.get('access') == 'write':
            target['access'] = 'write'
        for field in ('read', 'write', 'deny'):
            _append_missing(target[field], entry.get(field, []))
    commands = patch.get('commands', {})
    if not isinstance(commands, dict) or not set(commands) <= {'allow'}:
        _fail('A command patch may only add allowed command prefixes.')
    _append_missing(merged['commands']['allow'], commands.get('allow', []))
    network = patch.get('network', {})
    if not isinstance(network, dict) or not set(network) <= {'allow_hosts'}:
        _fail('A network patch may only add allowed hosts.')
    _append_missing(merged['network']['allow_hosts'], network.get('allow_hosts', []))
    return validate(merged)


def _append_missing(target, additions):
    if not isinstance(additions, list):
        _fail('Patch lists must be lists.')
    for item in additions:
        if item not in target:
            target.append(copy.deepcopy(item))


def patched(document, patch):
    """The scope after `add_to_scope`: patch merged and version incremented."""
    merged = merge_patch(document, patch)
    merged['version'] = document['version'] + 1
    return merged


def apply_answer(document, approval, ask, answer, *, now):
    """Bind the user's answer to the exact ask, and apply `add_to_scope`.

    Returns {"scope", "approval", "run", "change"}: `run` says whether the asked request may now run
    (exactly as submitted), and `change` is "amended" when the scope was widened and re-approved.
    """
    if not isinstance(answer, dict) or not isinstance(ask, dict):
        _fail('The answer does not match an open question.')
    if 'ask_id' in ask and answer.get('ask_id') != ask['ask_id']:
        _fail('The answer does not match the open question.')
    if answer.get('request_digest') != ask.get('request_digest'):
        _fail('The answer does not match the request that was shown.')
    decision = answer.get('decision')
    if decision == 'cancelled' or decision == 'deny':
        return {'scope': document, 'approval': approval, 'run': False, 'change': None}
    if decision not in ask.get('options', ()):
        _fail('That answer was not offered for this question.')
    if decision == 'text':
        return {'scope': document, 'approval': approval, 'run': False, 'change': None}
    if decision == 'allow_once':
        if not is_approved(document, approval):
            _fail('The task scope changed; approve it again before answering.')
        return {'scope': document, 'approval': approval, 'run': True, 'change': None}
    # add_to_scope: only when the scope is unchanged since the ask and the UI echoes the shown digest.
    if not ask.get('scope_patch') or not ask.get('patched_scope_digest'):
        _fail('This question cannot add to the scope.')
    if answer.get('scope_digest') != ask['patched_scope_digest']:
        _fail('The scope change does not match the one that was shown.')
    amended = patched(document, ask['scope_patch'])
    if digest(amended) != ask['patched_scope_digest']:
        _fail('The task scope changed since the question was asked; review it again.')
    new_approval = {'v': VERSION, 'scope_version': amended['version'], 'scope_digest': digest(amended),
                    'approved_at': iso_time(now), 'by': 'user'}
    return {'scope': amended, 'approval': new_approval, 'run': True, 'change': 'amended'}


# ---------------------------------------------------------------- glob and paths

_GLOB_CACHE = {}


def glob_match(pattern, path):
    """Case-sensitive match: `*` within a segment, `**` any number of segments, `?` one character."""
    regex = _GLOB_CACHE.get(pattern)
    if regex is None:
        regex = _GLOB_CACHE[pattern] = re.compile(_glob_regex(pattern), re.S)
    return regex.match(path) is not None


def _glob_regex(pattern):
    parts, i = [], 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            parts.append('(?:.*/)?')
            i += 3
        elif pattern.startswith('/**', i) and i + 3 == len(pattern):
            parts.append('(?:/.*)?')
            i += 3
        elif pattern.startswith('**', i):
            parts.append('.*')
            i += 2
        elif pattern[i] == '*':
            parts.append('[^/]*')
            i += 1
        elif pattern[i] == '?':
            parts.append('[^/]')
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return '^' + ''.join(parts) + '$'


def _inside(path, root):
    return path == root or path.startswith(root.rstrip('/') + '/')


class _Paths:
    """Resolved locations one `decide` call checks against."""

    def __init__(self, workspace_roots, home, app_data, temp_roots):
        self.roots = {pid: os.path.realpath(root) for pid, root in dict(workspace_roots).items()}
        self.home = os.path.realpath(home if home is not None else os.path.expanduser('~'))
        raw_app_data = app_data if app_data is not None else posixpath.join(self.home, APP_DATA_RELATIVE)
        self.app_data = os.path.realpath(raw_app_data)
        self.temp_roots = [os.path.realpath(root) for root in temp_roots]
        self.credential_dirs = [posixpath.join(self.home, p) for p in CREDENTIAL_HOME_PATHS]

    def expand(self, path):
        if path == '~' or path.startswith('~/'):
            return self.home + path[1:]
        return path

    def resolve(self, path, base):
        path = self.expand(path)
        if not posixpath.isabs(path):
            if base is None:
                return None
            path = posixpath.join(base, path)
        return os.path.realpath(path)

    def project_of(self, resolved):
        """(project_id, workspace-relative path) for a resolved path, or (None, None) outside."""
        best = None
        for pid, root in self.roots.items():
            if _inside(resolved, root) and (best is None or len(root) > len(self.roots[best])):
                best = pid
        if best is None:
            return None, None
        return best, posixpath.relpath(resolved, self.roots[best])

    def is_credential(self, given, resolved):
        for candidate in (given, resolved):
            if candidate is None:
                continue
            leaf = posixpath.basename(candidate.rstrip('/'))
            if leaf.startswith('.env') or leaf.endswith(CREDENTIAL_SUFFIXES) or leaf in CREDENTIAL_NAMES:
                return True
        if resolved is None:
            return False
        for entry in self.credential_dirs:
            if entry.endswith('/') and _inside(resolved, entry.rstrip('/')):
                return True
            if resolved == entry:
                return True
        return False

    def is_app_data(self, resolved):
        if resolved is None or not _inside(resolved, self.app_data):
            return False
        return not any(_inside(resolved, root) for root in self.roots.values())


# ---------------------------------------------------------------- command normalization

def _basename(arg):
    return posixpath.basename(arg) if '/' in arg else arg


def _opaque_string(text):
    return any(op in text for op in SHELL_OPERATORS)


def shell_tokens(text):
    """Tokens of a shell string with operators split out, for deny checks only."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return text.split()


def _skip_env(args):
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--':
            return args[i + 1:]
        if arg in ('-u', '-P', '-S', '-C'):
            i += 2
        elif arg.startswith('-') or ('=' in arg and not arg.startswith('=')):
            i += 1
        else:
            break
    return args[i:]


def _skip_nice(args):
    if args[:1] == ['-n']:
        return args[2:]
    if args and re.match(r'^-n?-?\d+$', args[0]):
        return args[1:]
    return args


def _skip_timeout(args):
    i = 0
    while i < len(args) and args[i].startswith('-'):
        i += 2 if args[i] in ('-s', '-k', '--signal', '--kill-after') else 1
    return args[i + 1:]  # the duration


def _skip_flags(args, with_value=()):
    i = 0
    while i < len(args) and args[i].startswith('-'):
        i += 2 if args[i] in with_value else 1
    return args[i:]


WRAPPER_SKIPPERS = {
    'env': _skip_env,
    'nice': _skip_nice,
    'timeout': _skip_timeout,
    'time': lambda args: _skip_flags(args),
    'caffeinate': lambda args: _skip_flags(args, ('-t', '-w')),
    'xcrun': lambda args: _skip_flags(args, ('--sdk', '-sdk', '--toolchain', '-toolchain')),
}


def _inline_code(argv):
    """The inline code a shell or interpreter is given, or None. `argv[0]` is already a basename."""
    name, args = argv[0], argv[1:]
    if name in SHELLS:
        for i, arg in enumerate(args):
            if arg.startswith('-') and not arg.startswith('--') and 'c' in arg[1:]:
                return ' '.join(args[i + 1:i + 2])
        return None
    if INTERPRETER.match(name):
        for i, arg in enumerate(args):
            if arg.startswith('-') and not arg.startswith('--') and arg[-1:] in ('c', 'e', 'E'):
                return ' '.join(args[i + 1:i + 2])
        return None
    if name == 'eval':
        return ' '.join(args)
    if name == 'xargs':
        return shlex.join(_skip_flags(args, ('-I', '-n', '-P', '-L', '-s', '-E', '-d')))
    if name == 'find' and ('-exec' in args or '-execdir' in args or '-ok' in args):
        start = min(args.index(f) for f in ('-exec', '-execdir', '-ok') if f in args)
        return shlex.join(args[start + 1:])
    return None


def normalize_argv(argv=None, command=None):
    """The argv rules see (scope.md steps 1-5).

    Returns {"argv", "opaque", "inner", "git_config"}. `inner` holds tokens of inline code given
    to a shell or interpreter (normalized once, as a shell string) for the deny checks.
    """
    opaque = False
    if argv is None:
        text = command or ''
        if _opaque_string(text):
            return {'argv': shell_tokens(text), 'opaque': True, 'inner': [], 'git_config': []}
        try:
            argv = shlex.split(text)
        except ValueError:
            return {'argv': text.split(), 'opaque': True, 'inner': [], 'git_config': []}
    argv = list(argv)
    if not argv:
        return {'argv': [], 'opaque': True, 'inner': [], 'git_config': []}
    argv[0] = _basename(argv[0])
    while argv:
        name = argv[0]
        if name in SIMPLE_WRAPPERS:
            rest = argv[1:]
        elif name in WRAPPER_SKIPPERS:
            rest = WRAPPER_SKIPPERS[name](argv[1:])
        else:
            break
        if not rest:
            break
        argv = [_basename(rest[0])] + rest[1:]
    git_config = []
    if argv and argv[0] == 'git':
        i, args = 0, argv[1:]
        while i < len(args):
            arg = args[i]
            if arg in GIT_GLOBAL_WITH_VALUE:
                if arg == '-c' and i + 1 < len(args):
                    git_config.append(args[i + 1])
                i += 2
            elif arg in GIT_GLOBAL_FLAGS or arg.startswith(GIT_GLOBAL_PREFIXES):
                i += 1
            else:
                break
        argv = ['git'] + args[i:]
    inner = []
    code = _inline_code(argv) if argv else None
    if code is not None:
        opaque = True
        inner = shell_tokens(code)
        if inner:
            inner[0] = _basename(inner[0])
    return {'argv': argv, 'opaque': opaque, 'inner': inner, 'git_config': git_config}


def _prefix_at(tokens, prefix):
    """Index where `prefix` matches `tokens` (first token compared by basename), or -1."""
    size = len(prefix)
    for start in range(len(tokens) - size + 1):
        if _basename(tokens[start]) == prefix[0] and list(tokens[start + 1:start + size]) == list(prefix[1:]):
            return start
    return -1


def redact_argv(argv):
    """Redact secret-looking values (scope.md audit rules), keeping argument positions."""
    out, hide_next = [], False
    for arg in argv:
        if hide_next:
            out.append(REDACTED)
            hide_next = False
            continue
        if arg in REDACT_FLAGS:
            out.append(arg)
            hide_next = True
            continue
        name, sep, _value = arg.partition('=')
        if sep and (name in REDACT_FLAGS or REDACT_NAME.search(name)):
            out.append(name + '=' + REDACTED)
            continue
        out.append(arg)
    return out


# ---------------------------------------------------------------- request validation

class _Invalid(Exception):
    pass


def _need(condition):
    if not condition:
        raise _Invalid()


def _text(value, limit=MAX_ARG_CHARS, allow_empty=False):
    return isinstance(value, str) and (allow_empty or value) and len(value) <= limit and '\x00' not in value


def _check_request(request):
    _need(isinstance(request, dict))
    category = request.get('category')
    if category == 'file_read':
        _need(_text(request.get('path')) and _text(request.get('project_id'), MAX_ID_CHARS))
    elif category == 'file_write':
        paths = request.get('paths')
        _need(isinstance(paths, list) and 1 <= len(paths) <= MAX_REQUEST_PATHS and all(_text(p) for p in paths))
        _need(_text(request.get('project_id'), MAX_ID_CHARS))
    elif category == 'command':
        argv, text = request.get('argv'), request.get('command')
        if argv is not None:
            _need(isinstance(argv, list) and argv and all(_text(a, allow_empty=True) for a in argv) and _text(argv[0]))
        else:
            _need(_text(text) and text.strip())
        _need(_text(request.get('cwd')))
        _need(request.get('sandbox') in SANDBOXES and type(request.get('network')) is bool)
        _need(request.get('project_id') is None or _text(request.get('project_id'), MAX_ID_CHARS))
    elif category == 'network':
        host = request.get('host')
        _need(host is None or (_text(host, 253) and HOST.match(host) and not host.startswith('*.')))
        _need(request.get('port') is None or (_is_int(request['port']) and 0 < request['port'] < 65536))
        _need(_text(request.get('via'), 32))
    elif category == 'web_search':
        _need(_text(request.get('query'), 2000))
    elif category == 'mcp':
        _need(_text(request.get('server'), 128) and _text(request.get('tool'), 128))
    else:
        raise _Invalid()


# ---------------------------------------------------------------- decisions

def _result(document, decision, rule, reason, ask=None):
    return {'decision': decision, 'rule': rule, 'reason': reason,
            'scope_version': document.get('version') if isinstance(document, dict) else None,
            'scope_digest': digest(document) if isinstance(document, dict) else None,
            'ask': ask}


def _allow(document, rule):
    return _result(document, 'allow', rule, 'Inside the task scope.')


def _deny(document, rule, reason):
    return _result(document, 'deny', rule, reason)


def _ask(document, request, rule, reason, title, detail, patch=None, per_host=True):
    options = ['allow_once']
    patched_digest = None
    if patch is not None:
        try:
            patched_digest = digest(patched(document, patch))
        except ValueError:  # the widening would break a schema limit; offer no patch
            patch = None
    if patch is not None and per_host:
        options.append('add_to_scope')
    elif patch is not None:
        patch, patched_digest = None, None
    options.append('deny')
    if reason in ('scope_unapproved',):
        options = []
    ask = {'reason': reason, 'title': _clip(title, 200), 'detail': detail, 'options': options,
           'scope_patch': patch, 'patched_scope_digest': patched_digest,
           'request_digest': request_digest(request)}
    return _result(document, 'ask', rule, 'Outside the task scope.' if reason != 'scope_unapproved'
                   else 'The task scope is not approved.', ask)


def _clip(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _show_argv(argv):
    return _clip(' '.join(redact_argv(argv)), 120)


def decide(scope, approval, request, *, workspace_roots, now, home=None, app_data=None, temp_roots=()):
    """Allow, ask or deny one agent request (scope.md evaluation order). Pure apart from realpath.

    `scope` and `approval` must be the live ones from the task record. `workspace_roots` maps the
    task's project IDs to their workspace clones. `home`, `app_data` and `temp_roots` default to
    the user's home, Interspace's Application Support folder and none.
    """
    document = scope
    paths = _Paths(workspace_roots, home, app_data, temp_roots)
    try:
        _check_request(request)
    except _Invalid:
        return _deny(document, RULE_INVALID, 'The request is malformed.')
    # 1. Approval binding.
    if not is_approved(document, approval):
        return _ask(document, request, RULE_UNAPPROVED, 'scope_unapproved', 'Approve the task scope?',
                    'The task scope changed or is not approved yet.')
    category = request['category']
    handler = {'file_read': _decide_read, 'file_write': _decide_write, 'command': _decide_command,
               'network': _decide_network, 'web_search': _decide_web_search, 'mcp': _decide_mcp}[category]
    return handler(document, request, paths)


def safe_decide(scope, approval, request, **kwargs):
    """`decide`, failing closed: any exception becomes `deny` with rule `policy.failed`."""
    try:
        return decide(scope, approval, request, **kwargs)
    except Exception:  # noqa: BLE001 - the policy must never fail open
        try:
            version, scope_digest = scope['version'], digest(scope)
        except Exception:  # noqa: BLE001
            version, scope_digest = None, None
        return {'decision': 'deny', 'rule': RULE_FAILED, 'reason': 'The policy check failed.',
                'scope_version': version, 'scope_digest': scope_digest, 'ask': None}


def _project_entry(document, project_id):
    for index, entry in enumerate(document['projects']):
        if entry['project_id'] == project_id:
            return index, entry
    return None, None


def _resolve_file(paths, request, given):
    base = paths.roots.get(request['project_id'])
    resolved = paths.resolve(given, base)
    lexical = None
    if not posixpath.isabs(paths.expand(given)):
        lexical = posixpath.normpath(given)
    return resolved, lexical


def _deny_listed(entry, relative, lexical):
    for pattern in entry['deny']:
        if glob_match(pattern, relative) or (lexical is not None and glob_match(pattern, lexical)):
            return True
    return False


def _patchable(relative):
    try:
        validate_pattern(relative)
    except ValueError:
        return False
    return '*' not in relative and '?' not in relative


def _decide_read(document, request, paths):
    resolved, lexical = _resolve_file(paths, request, request['path'])
    # 2. Always deny.
    if paths.is_credential(request['path'], resolved):
        return _deny(document, DENY_CREDENTIALS, 'Credential files are never available to agents.')
    if paths.is_app_data(resolved):
        return _deny(document, DENY_APP_DATA, "Interspace's own data is never available to agents.")
    project_id, relative = paths.project_of(resolved) if resolved else (None, None)
    index, entry = _project_entry(document, project_id)
    if entry is None:
        # 4. Always ask: reads outside every workspace are never in scope in v1.
        return _ask(document, request, ASK_OUTSIDE_READ, 'outside_scope', 'Read a file outside the workspace?',
                    'Reads outside the task workspace always ask.')
    base = 'projects[%d]' % index
    # 3. Scope deny.
    if _deny_listed(entry, relative, lexical):
        return _deny(document, base + '.deny', 'The task scope denies this path.')
    # 5. Scope allow.
    if any(glob_match(p, relative) for p in entry['read']):
        return _allow(document, base + '.read')
    # 6. Otherwise ask.
    patch = {'projects': [{'project_id': project_id, 'read': [relative]}]} if _patchable(relative) else None
    return _ask(document, request, base + '.read', 'outside_scope', 'Read %s?' % _clip(relative, 160),
                'The task scope does not cover reading this path.', patch)


def _decide_write(document, request, paths):
    targets = []
    for given in request['paths']:
        resolved, lexical = _resolve_file(paths, request, given)
        if paths.is_credential(given, resolved):
            return _deny(document, DENY_CREDENTIALS, 'Credential files are never available to agents.')
        targets.append((given, resolved, lexical))
    outside_temp = []
    for given, resolved, lexical in targets:
        project_id = paths.project_of(resolved)[0] if resolved else None
        if project_id is not None:
            continue
        if resolved is not None and any(_inside(resolved, root) for root in paths.temp_roots):
            outside_temp.append(given)
            continue
        return _deny(document, DENY_OUTSIDE_WRITE, 'Agents write only inside their own task workspace.')
    for given, resolved, lexical in targets:
        if paths.is_app_data(resolved):
            return _deny(document, DENY_APP_DATA, "Interspace's own data is never available to agents.")
    # 3. Scope deny, for every path first.
    located = []
    for given, resolved, lexical in targets:
        if given in outside_temp:
            continue
        project_id, relative = paths.project_of(resolved)
        index, entry = _project_entry(document, project_id)
        if entry is not None and _deny_listed(entry, relative, lexical):
            return _deny(document, 'projects[%d].deny' % index, 'The task scope denies this path.')
        located.append((project_id, relative, index, entry))
    if outside_temp:
        return _ask(document, request, RULE_OUTSIDE, 'outside_scope', 'Write temporary files?',
                    'The task scope does not cover these files.')
    # 5. Scope allow: every path matches its project's write list.
    uncovered = {}
    rules = []
    for project_id, relative, index, entry in located:
        if entry is None:
            uncovered.setdefault(project_id, []).append(relative)
            continue
        rules.append('projects[%d].write' % index)
        if entry['access'] != 'write' or not any(glob_match(p, relative) for p in entry['write']):
            uncovered.setdefault(project_id, []).append(relative)
    if not uncovered:
        return _allow(document, rules[0])
    # 6. Otherwise ask, with a patch adding exactly the uncovered paths.
    patch_entries = []
    for project_id, relatives in uncovered.items():
        index, entry = _project_entry(document, project_id)
        if entry is None or not all(_patchable(r) for r in relatives):
            patch_entries = None
            break
        widened = {'project_id': project_id}
        if entry['access'] != 'write':
            widened['access'] = 'write'
        widened['write'] = list(dict.fromkeys(relatives))
        patch_entries.append(widened)
    first_project = next(iter(uncovered))
    index, _entry = _project_entry(document, first_project)
    rule = 'projects[%d].write' % index if index is not None else RULE_OUTSIDE
    relatives = [r for rs in uncovered.values() for r in rs]
    title = 'Write %s?' % _clip(relatives[0], 160) if len(relatives) == 1 else 'Write %d files?' % len(relatives)
    return _ask(document, request, rule, 'outside_scope', title, 'The task scope does not cover writing these paths.',
                {'projects': patch_entries} if patch_entries else None)


def _always_deny_command(document, request, normalized, paths, cwd):
    """Always-deny checks over the normalized argv, every original argument and inline code."""
    original = list(request['argv']) if request['argv'] is not None else shell_tokens(request['command'])
    sequences = [normalized['argv'], original, normalized['inner']]
    every_arg = [a for sequence in sequences for a in sequence] + normalized['git_config']
    for sequence in sequences:
        if any(_prefix_at(sequence, (name,)) >= 0 for name in KEYCHAIN_COMMANDS):
            return _deny(document, DENY_KEYCHAIN, 'Agents never use the Keychain.')
    for arg in every_arg:
        if any(marker in arg for marker in BYPASS_MARKERS):
            return _deny(document, DENY_BYPASS, 'Agents never run with the sandbox or approvals bypassed.')
    for sequence in sequences:
        if any(_prefix_at(sequence, pair) >= 0 for pair in BYPASS_FLAG_PAIRS):
            return _deny(document, DENY_BYPASS, 'Agents never run with the sandbox or approvals bypassed.')
    for sequence in sequences:
        if any(_prefix_at(sequence, prefix) >= 0 for prefix in PRIVILEGE_PREFIXES):
            return _deny(document, DENY_PRIVILEGE, 'Agents never raise their privileges.')
    for arg in every_arg:
        for candidate in _path_like(arg):
            resolved = paths.resolve(candidate, cwd)
            if paths.is_credential(candidate, resolved):
                return _deny(document, DENY_CREDENTIALS, 'Credential files are never available to agents.')
            if paths.is_app_data(resolved):
                return _deny(document, DENY_APP_DATA, "Interspace's own data is never available to agents.")
    return None


def _path_like(arg):
    """Arguments (or `--flag=value` values) that name a file, for the visible-argv credential checks."""
    candidates = [arg]
    if arg.startswith('-') and '=' in arg:
        candidates = [arg.split('=', 1)[1]]
    return [c for c in candidates if c and ('/' in c or c.startswith(('~', '.')) or _credential_name(c))]


def _credential_name(name):
    return name.startswith('.env') or name.endswith(CREDENTIAL_SUFFIXES) or name in CREDENTIAL_NAMES


def _decide_command(document, request, paths):
    normalized = normalize_argv(request['argv'], request['command'])
    base = paths.roots.get(request.get('project_id')) if request.get('project_id') else None
    if base is None and len(paths.roots) == 1:
        base = next(iter(paths.roots.values()))
    cwd = paths.resolve(request['cwd'], base)
    # 2. Always deny.
    denied = _always_deny_command(document, request, normalized, paths, cwd)
    if denied:
        return denied
    # 3. Scope deny.
    for index, prefix in enumerate(document['commands']['deny']):
        if any(_prefix_at(seq, prefix) >= 0 for seq in (normalized['argv'], normalized['inner'])):
            return _deny(document, 'commands.deny[%d]' % index, 'The task scope denies this command.')
    shown = _show_argv(normalized['argv'])
    # 4. Always ask.
    if request['sandbox'] == 'escalated':
        return _ask(document, request, ASK_ESCALATION, 'escalation', 'Run `%s` outside the sandbox?' % shown,
                    'Commands that leave the sandbox always ask.')
    # 5. Scope allow.
    in_workspace = cwd is not None and paths.project_of(cwd)[0] is not None
    allowed_rule = None
    if in_workspace and not normalized['opaque']:
        for index, prefix in enumerate(document['commands']['allow']):
            if normalized['argv'][:len(prefix)] == list(prefix):
                allowed_rule = 'commands.allow[%d]' % index
                break
        if allowed_rule is None and document['commands']['workspace'] == 'allow':
            allowed_rule = 'commands.workspace'
    if allowed_rule is not None:
        if request['network']:
            return _network_decision(document, dict(request), None)
        return _allow(document, allowed_rule)
    # 6. Otherwise ask (or deny when the setting is deny).
    if document['commands']['workspace'] == 'deny':
        return _deny(document, RULE_DEFAULT_DENY, 'The task scope does not allow commands.')
    patch = None
    if in_workspace and not normalized['opaque'] and len(normalized['argv']) <= MAX_PREFIX_ARGS:
        patch = {'commands': {'allow': [normalized['argv']]}}
    return _ask(document, request, 'commands.workspace', 'outside_scope', 'Run `%s`?' % shown,
                'The task scope does not cover this command.', patch)


def _host_matches(pattern, host):
    if pattern.startswith('*.'):
        return host.endswith(pattern[1:])
    return host == pattern


def _network_decision(document, request, host):
    network = document['network']
    per_host = network_per_host() and host is not None
    if per_host:
        for index, pattern in enumerate(network['deny_hosts']):
            if _host_matches(pattern, host):
                return _deny(document, 'network.deny_hosts[%d]' % index, 'The task scope denies this host.')
        for index, pattern in enumerate(network['allow_hosts']):
            if _host_matches(pattern, host):
                return _allow(document, 'network.allow_hosts[%d]' % index)
    if network['default'] == 'deny':
        return _deny(document, RULE_DEFAULT_DENY, 'The task scope does not allow network access.')
    if not per_host:
        return _ask(document, request, 'network.default', 'network_host', ON_OFF_NETWORK_TITLE,
                    'The sandbox can only turn network on for every host while this one command runs.',
                    None, per_host=False)
    return _ask(document, request, 'network.default', 'network_host', 'Allow network access to %s?' % host,
                'The task scope does not cover this host.', {'network': {'allow_hosts': [host]}})


def _decide_network(document, request, paths):
    return _network_decision(document, request, request['host'])


def _decide_web_search(document, request, paths):
    setting = document['web_search']
    if setting == 'allow':
        return _allow(document, 'web_search')
    if setting == 'deny':
        return _deny(document, RULE_DEFAULT_DENY, 'The task scope does not allow web search.')
    return _ask(document, request, 'web_search', 'outside_scope', 'Search the web?',
                'The task scope asks before each web search.')


def _words(name):
    return set(w for w in re.split(r'[^a-z0-9]+', name.lower()) if w)


def _changes_sharing(name):
    return bool(_words(name) & SHARING_WORDS)


def _decide_mcp(document, request, paths):
    server, tool = request['server'], request['tool']
    if server == OWN_SERVER:
        if _words(tool) & SELF_EDIT_WORDS:
            return _deny(document, DENY_SCOPE_SELF_EDIT, 'Agents never change their own scope or limits.')
        return _deny(document, RULE_INVALID, "Interspace's own tools are not MCP requests.")
    if _changes_sharing(tool):
        return _deny(document, DENY_SHARING, 'Agents never change sharing, permissions or ownership.')
    return _ask(document, request, ASK_MCP, 'mcp_tool', 'Run MCP tool %s/%s?' % (_clip(server, 60), _clip(tool, 60)),
                'Tools from other MCP servers always ask.')
