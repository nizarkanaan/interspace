"""Scope schema, digest binding and the pure decide policy (scope.md)."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

import scope  # noqa: E402

NOW = 1794393000.0
TASK = '8c1d' * 8
PID = 'f03a' * 8
OTHER_PID = 'b0b0' * 8


def base_scope():
    return {
        'v': 1, 'task_id': TASK, 'version': 3,
        'projects': [{'project_id': PID, 'access': 'write',
                      'read': ['**'], 'write': ['src/**', 'tests/**'], 'deny': ['secrets/**']}],
        'commands': {'workspace': 'allow', 'allow': [['git', 'status']], 'deny': [['git', 'push']]},
        'network': {'default': 'ask', 'allow_hosts': ['pypi.org'], 'deny_hosts': []},
        'apps': [],
        'web_search': 'allow',
        'limits': {'token_budget': 250000, 'time_limit_s': 3600},
    }


def approval_for(document):
    return scope.approve(document, document['version'], scope.digest(document), now=NOW)


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(os.path.realpath(temp.name))
        self.home = self.base / 'home'
        self.app_data = self.home / 'Library/Application Support/Interspace'
        self.root = self.app_data / 'workspaces' / TASK / PID
        self.other_task_root = self.app_data / 'workspaces' / ('9' * 32) / PID
        self.tmp = self.base / 'runtime-tmp'
        for folder in (self.root / 'src', self.root / 'tests', self.root / 'secrets', self.root / 'docs',
                       self.other_task_root, self.tmp, self.home / '.ssh', self.base / 'outside'):
            folder.mkdir(parents=True, exist_ok=True)
        self.scope = base_scope()
        self.approval = approval_for(self.scope)

    def decide(self, request, document=None, approval='same'):
        document = self.scope if document is None else document
        approval = approval_for(document) if approval == 'same' else approval
        return scope.decide(document, approval, request, workspace_roots={PID: str(self.root)}, now=NOW,
                            home=str(self.home), app_data=str(self.app_data), temp_roots=(str(self.tmp),))

    def assertDecision(self, result, decision, rule):
        self.assertEqual((result['decision'], result['rule']), (decision, rule), result)
        self.assertEqual(result['scope_version'], 3 if result['rule'] != 'approval.scope_unapproved' else result['scope_version'])
        if decision == 'ask':
            self.assertEqual(set(result['ask']), {'reason', 'title', 'detail', 'options', 'scope_patch',
                                                  'patched_scope_digest', 'request_digest'})
        else:
            self.assertIsNone(result['ask'])


def read(path, project=PID):
    return {'category': 'file_read', 'project_id': project, 'path': path}


def write(*paths):
    return {'category': 'file_write', 'project_id': PID, 'paths': list(paths)}


def command(argv=None, text=None, cwd='.', sandbox='workspace', network=False):
    return {'category': 'command', 'argv': argv, 'command': text, 'cwd': cwd,
            'sandbox': sandbox, 'network': network, 'project_id': PID}


class ValidationTests(unittest.TestCase):
    def test_example_scope_is_valid_and_round_trips(self):
        document = base_scope()
        self.assertEqual(scope.validate(document), document)
        self.assertEqual(scope.validate(document, project_ids={PID}), document)

    def test_invalid_documents_raise_value_error(self):
        def mutate(change):
            document = base_scope()
            change(document)
            return document
        cases = {
            'unknown v': lambda d: d.update(v=2),
            'unknown key': lambda d: d.update(extra=1),
            'missing key': lambda d: d.pop('apps'),
            'version zero': lambda d: d.update(version=0),
            'version bool': lambda d: d.update(version=True),
            'duplicate project': lambda d: d['projects'].append(copy.deepcopy(d['projects'][0])),
            'nine projects': lambda d: d.update(projects=[dict(d['projects'][0], project_id=str(i)) for i in range(9)]),
            'write on read access': lambda d: d['projects'][0].update(access='read'),
            'dotdot pattern': lambda d: d['projects'][0].update(read=['src/../x']),
            'absolute pattern': lambda d: d['projects'][0].update(read=['/etc/**']),
            'backslash pattern': lambda d: d['projects'][0].update(read=['src\\x']),
            'long pattern': lambda d: d['projects'][0].update(read=['a' * 257]),
            'too many patterns': lambda d: d['projects'][0].update(read=['a'] * 65),
            'bad workspace': lambda d: d['commands'].update(workspace='yes'),
            'empty prefix': lambda d: d['commands'].update(allow=[[]]),
            'long prefix': lambda d: d['commands'].update(allow=[['x'] * 9]),
            'network allow default': lambda d: d['network'].update(default='allow'),
            'host with port': lambda d: d['network'].update(allow_hosts=['pypi.org:443']),
            'host uppercase': lambda d: d['network'].update(allow_hosts=['PyPI.org']),
            'host scheme': lambda d: d['network'].update(allow_hosts=['https://pypi.org']),
            'any app': lambda d: d.update(apps=[{'app': 'a', 'access': 'read', 'resources': 'all'}]),
            'apps not a list': lambda d: d.update(apps=None),
            'bad web search': lambda d: d.update(web_search='maybe'),
            'short time limit': lambda d: d['limits'].update(time_limit_s=59),
            'long time limit': lambda d: d['limits'].update(time_limit_s=86401),
            'bad budget': lambda d: d['limits'].update(token_budget=0),
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                scope.validate(mutate(change))
        with self.assertRaises(ValueError):
            scope.validate(base_scope(), project_ids={OTHER_PID})
        with self.assertRaises(ValueError):
            scope.validate('not a dict')

    def test_default_scope(self):
        task = {'id': TASK, 'token_budget': 100000}
        document = scope.default(task, [PID])
        scope.validate(document)
        self.assertEqual(document['version'], 1)
        self.assertEqual(document['projects'], [{'project_id': PID, 'access': 'write', 'read': ['**'], 'write': ['**'], 'deny': []}])
        self.assertEqual(document['commands']['workspace'], 'allow')
        self.assertEqual(document['network'], {'default': 'ask', 'allow_hosts': [], 'deny_hosts': []})
        self.assertEqual((document['web_search'], document['limits']), ('ask', {'token_budget': 100000, 'time_limit_s': 3600}))
        read_only = scope.default(task, [PID], access='read')
        self.assertEqual(read_only['projects'][0]['write'], [])
        self.assertEqual(read_only['commands']['workspace'], 'ask')
        self.assertEqual(scope.default(task, [])['commands']['workspace'], 'ask')


class DigestAndEditTests(Fixture):
    def test_digest_is_canonical_and_covers_version(self):
        document = base_scope()
        reordered = dict(reversed(list(copy.deepcopy(document).items())))
        self.assertEqual(scope.digest(document), scope.digest(reordered))
        self.assertTrue(scope.digest(document).startswith('sha256:'))
        self.assertEqual(len(scope.digest(document)), 71)
        bumped = dict(document, version=4)
        self.assertNotEqual(scope.digest(document), scope.digest(bumped))
        self.assertEqual(scope.request_digest({'b': 1, 'a': 'é'}), scope.request_digest({'a': 'é', 'b': 1}))

    def test_approve_binds_exact_version_and_digest(self):
        approval = scope.approve(self.scope, 3, scope.digest(self.scope), now=NOW)
        self.assertEqual(approval, {'v': 1, 'scope_version': 3, 'scope_digest': scope.digest(self.scope),
                                    'approved_at': '2026-11-11T10:30:00.000Z', 'by': 'user'})
        self.assertTrue(scope.is_approved(self.scope, approval))
        with self.assertRaises(ValueError):
            scope.approve(self.scope, 2, scope.digest(self.scope), now=NOW)
        with self.assertRaises(ValueError):
            scope.approve(self.scope, 3, 'sha256:' + '0' * 64, now=NOW)

    def test_missing_or_stale_approval_pauses_whole_scope(self):
        for approval in (None, {}, dict(self.approval, scope_digest='sha256:' + '0' * 64),
                         dict(self.approval, scope_version=2), dict(self.approval, v=2)):
            with self.subTest(approval=approval):
                result = self.decide(read('src/a.py'), approval=approval)
                self.assertEqual((result['decision'], result['rule']), ('ask', 'approval.scope_unapproved'))
                self.assertEqual(result['ask']['reason'], 'scope_unapproved')
                self.assertEqual(result['ask']['options'], [])

    def test_edit_increments_version_and_invalidates_approval(self):
        new = copy.deepcopy(self.scope)
        new['version'] = 99  # the UI never sets it; the backend replaces it
        new['web_search'] = 'deny'
        edited = scope.edit(self.scope, 3, new)
        self.assertEqual(edited['version'], 4)
        self.assertEqual(self.scope['version'], 3)
        result = self.decide(read('src/a.py'), document=edited, approval=self.approval)
        self.assertEqual(result['rule'], 'approval.scope_unapproved')
        self.assertEqual(result['scope_version'], 4)
        self.assertEqual(result['scope_digest'], scope.digest(edited))
        self.assertTrue(scope.is_approved(edited, scope.approve(edited, 4, scope.digest(edited), now=NOW)))

    def test_edit_rejects_stale_base_and_task_change(self):
        with self.assertRaises(ValueError):
            scope.edit(self.scope, 2, copy.deepcopy(self.scope))
        with self.assertRaises(ValueError):
            scope.edit(self.scope, 3, dict(copy.deepcopy(self.scope), task_id='other'))
        narrowed = copy.deepcopy(self.scope)
        narrowed['limits']['time_limit_s'] = 120
        self.assertEqual(scope.edit(self.scope, 3, narrowed)['version'], 4)


class FileDecisionTests(Fixture):
    def test_reads_and_writes_inside_scope_are_allowed(self):
        self.assertDecision(self.decide(read('src/a.py')), 'allow', 'projects[0].read')
        self.assertDecision(self.decide(read(str(self.root / 'docs/x.md'))), 'allow', 'projects[0].read')
        self.assertDecision(self.decide(write('src/a.py', 'tests/b/c.py')), 'allow', 'projects[0].write')
        result = self.decide(write('src/a.py'))
        self.assertEqual((result['scope_version'], result['scope_digest']), (3, scope.digest(self.scope)))

    def test_scope_deny_beats_allow(self):
        self.assertDecision(self.decide(read('secrets/token.txt')), 'deny', 'projects[0].deny')
        self.assertDecision(self.decide(write('src/a.py', 'secrets/x')), 'deny', 'projects[0].deny')

    def test_write_outside_write_list_asks_with_narrow_patch(self):
        result = self.decide(write('src/a.py', 'docs/guide.md'))
        self.assertDecision(result, 'ask', 'projects[0].write')
        ask = result['ask']
        self.assertEqual(ask['reason'], 'outside_scope')
        self.assertEqual(ask['options'], ['allow_once', 'add_to_scope', 'deny'])
        self.assertEqual(ask['scope_patch'], {'projects': [{'project_id': PID, 'write': ['docs/guide.md']}]})
        patched = scope.merge_patch(self.scope, ask['scope_patch'])
        patched['version'] = 4
        self.assertEqual(ask['patched_scope_digest'], scope.digest(patched))
        self.assertEqual(ask['request_digest'], scope.request_digest(write('src/a.py', 'docs/guide.md')))

    def test_write_with_read_access_patch_upgrades_access(self):
        document = copy.deepcopy(self.scope)
        document['projects'][0].update(access='read', write=[])
        result = self.decide(write('src/a.py'), document=document)
        self.assertEqual(result['ask']['scope_patch'],
                         {'projects': [{'project_id': PID, 'access': 'write', 'write': ['src/a.py']}]})

    def test_glob_patterns(self):
        cases = [('**', 'a/b/c.py', True), ('src/*', 'src/a.py', True), ('src/*', 'src/a/b.py', False),
                 ('src/**', 'src/a/b.py', True), ('src/**', 'src', True), ('**/*.py', 'x.py', True),
                 ('**/*.py', 'a/b/x.py', True), ('?.md', 'a.md', True), ('?.md', 'ab.md', False),
                 ('src/**/test_*.py', 'src/test_a.py', True), ('Src/**', 'src/a', False), ('a.b', 'aXb', False)]
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertIs(scope.glob_match(pattern, path), expected)

    def test_path_traversal_is_resolved_never_trimmed(self):
        self.assertDecision(self.decide(read('src/../../../../../outside/x')), 'ask', 'always_ask.outside_read')
        self.assertEqual(self.decide(read('src/../secrets/k'))['rule'], 'projects[0].deny')
        self.assertDecision(self.decide(write('src/../../escape.py')), 'deny', 'always_deny.outside_write')
        self.assertDecision(self.decide(write(str(self.base / 'outside/x.py'))), 'deny', 'always_deny.outside_write')
        self.assertDecision(self.decide(read(str(self.base / 'outside/x'))), 'ask', 'always_ask.outside_read')
        ask = self.decide(read(str(self.base / 'outside/x')))['ask']
        self.assertEqual((ask['options'], ask['scope_patch']), (['allow_once', 'deny'], None))

    def test_symlinks_are_resolved(self):
        (self.root / 'src/out').symlink_to(self.base / 'outside')
        (self.root / 'src/hidden').symlink_to(self.root / 'secrets')
        (self.root / 'secrets/alias').symlink_to(self.root / 'src')
        (self.root / 'src/key').symlink_to(self.home / '.ssh/id_ed25519')
        self.assertDecision(self.decide(write('src/out/x.py')), 'deny', 'always_deny.outside_write')
        self.assertDecision(self.decide(read('src/out/x.py')), 'ask', 'always_ask.outside_read')
        self.assertDecision(self.decide(read('src/hidden/token')), 'deny', 'projects[0].deny')
        # The given name is checked against deny lists too, not only the resolved target.
        self.assertDecision(self.decide(write('secrets/alias/a.py')), 'deny', 'projects[0].deny')
        self.assertDecision(self.decide(read('src/key')), 'deny', 'always_deny.credentials')

    def test_symlinked_workspace_root_is_resolved(self):
        link = self.base / 'root-link'
        link.symlink_to(self.root)
        result = scope.decide(self.scope, self.approval, read(str(self.root / 'src/a.py')),
                              workspace_roots={PID: str(link)}, now=NOW, home=str(self.home),
                              app_data=str(self.app_data))
        self.assertEqual(result['decision'], 'allow')

    def test_other_task_workspace_and_app_data_are_denied(self):
        self.assertDecision(self.decide(read(str(self.other_task_root / 'src/a.py'))), 'deny', 'always_deny.app_data')
        self.assertDecision(self.decide(read(str(self.app_data / 'state.json'))), 'deny', 'always_deny.app_data')
        self.assertDecision(self.decide(read(str(self.app_data / 'audit/2026-11.jsonl'))), 'deny', 'always_deny.app_data')
        self.assertDecision(self.decide(write(str(self.app_data / 'state.json'))), 'deny', 'always_deny.outside_write')
        self.assertDecision(self.decide(write(str(self.other_task_root / 'a'))), 'deny', 'always_deny.outside_write')

    def test_credentials_are_denied_everywhere(self):
        for name in ('.env', '.env.local', 'server.key', 'cert.pem', 'a.p12', 'a.pfx', 'id_rsa', 'id_dsa',
                     'id_ecdsa', 'id_ed25519', 'credentials', 'credentials.json', 'secrets.json'):
            with self.subTest(name=name):
                self.assertDecision(self.decide(read('src/' + name)), 'deny', 'always_deny.credentials')
                self.assertDecision(self.decide(write('src/' + name)), 'deny', 'always_deny.credentials')
        for relative in ('.ssh/config', '.aws/credentials', '.aws/config', '.config/gh/hosts.yml', '.codex/auth.json',
                         '.claude/.credentials.json', '.netrc', '.git-credentials', 'Library/Keychains/login.keychain-db'):
            with self.subTest(relative=relative):
                self.assertDecision(self.decide(read(str(self.home / relative))), 'deny', 'always_deny.credentials')
        self.assertEqual(self.decide(read(str(self.home / '.codex/config.toml')))['rule'], 'always_ask.outside_read')

    def test_temp_writes_are_not_outside_write_but_still_ask(self):
        result = self.decide(write(str(self.tmp / 'scratch.txt')))
        self.assertDecision(result, 'ask', 'outside_scope')
        self.assertIsNone(result['ask']['scope_patch'])

    def test_read_of_project_not_in_scope_asks_outside(self):
        result = self.decide(read('src/a.py', project=OTHER_PID))
        self.assertEqual(result['decision'], 'ask')


class CommandDecisionTests(Fixture):
    def test_normalize_argv(self):
        cases = [
            (['/usr/bin/git', 'status'], ['git', 'status']),
            (['env', '-i', 'A=1', 'B=2', 'nice', '-n', '5', 'timeout', '30', 'python3', '-V'], ['python3', '-V']),
            (['command', 'exec', 'nohup', 'time', 'caffeinate', 'xcrun', 'swift'], ['swift']),
            (['git', '-C', 'sub', '-c', 'core.pager=cat', '--no-pager', '-P', '--git-dir=.git', '--work-tree=.',
              '--exec-path=/x', 'log'], ['git', 'log']),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                normalized = scope.normalize_argv(argv)
                self.assertEqual(normalized['argv'], expected)
                self.assertFalse(normalized['opaque'])
        self.assertEqual(scope.normalize_argv(['git', '-c', 'a=b', 'status'])['git_config'], ['a=b'])
        self.assertEqual(scope.normalize_argv(None, 'git status --short')['argv'], ['git', 'status', '--short'])
        for text in ('ls; rm x', 'a && b', 'a || b', 'a | b', 'a &', 'echo `id`', 'echo $(id)', 'a < b', 'a > b',
                     'a\nb', 'echo "unterminated'):
            with self.subTest(text=text):
                self.assertTrue(scope.normalize_argv(None, text)['opaque'])
        for argv in (['bash', '-c', 'ls'], ['sh', '-c', 'ls'], ['zsh', '-c', 'x'], ['python3', '-c', 'print(1)'],
                     ['node', '-e', '1'], ['perl', '-E', '1'], ['eval', 'ls'], ['xargs', 'rm'],
                     ['find', '.', '-exec', 'rm', '{}', ';'], ['/bin/bash', '-lc', 'ls']):
            with self.subTest(argv=argv):
                self.assertTrue(scope.normalize_argv(argv)['opaque'])
        self.assertEqual(scope.normalize_argv(['bash', '-c', 'sudo rm -rf /'])['inner'][:2], ['sudo', 'rm'])

    def test_workspace_commands(self):
        self.assertDecision(self.decide(command(['python3', '-m', 'unittest'])), 'allow', 'commands.workspace')
        self.assertDecision(self.decide(command(['ls'], cwd='src')), 'allow', 'commands.workspace')
        document = copy.deepcopy(self.scope)
        document['commands']['workspace'] = 'ask'
        self.assertDecision(self.decide(command(['git', 'status', '--short']), document=document), 'allow', 'commands.allow[0]')
        result = self.decide(command(['make', 'test']), document=document)
        self.assertDecision(result, 'ask', 'commands.workspace')
        self.assertEqual(result['ask']['scope_patch'], {'commands': {'allow': [['make', 'test']]}})
        self.assertIsNone(self.decide(command(['a'] * 9), document=document)['ask']['scope_patch'])
        document['commands']['workspace'] = 'deny'
        self.assertDecision(self.decide(command(['make']), document=document), 'deny', 'scope.default_deny')
        self.assertDecision(self.decide(command(['git', 'status']), document=document), 'allow', 'commands.allow[0]')

    def test_opaque_commands_never_match_allow(self):
        result = self.decide(command(None, 'ls | wc -l'))
        self.assertDecision(result, 'ask', 'commands.workspace')
        self.assertIsNone(result['ask']['scope_patch'])
        self.assertEqual(self.decide(command(['bash', '-c', 'git status']))['decision'], 'ask')

    def test_cwd_outside_workspace_asks(self):
        for cwd in (str(self.base / 'outside'), '../..', str(self.other_task_root)):
            with self.subTest(cwd=cwd):
                result = self.decide(command(['git', 'status'], cwd=cwd))
                self.assertDecision(result, 'ask', 'commands.workspace')
                self.assertIsNone(result['ask']['scope_patch'])

    def test_scope_deny_matches_anywhere(self):
        for argv in (['git', 'push'], ['/usr/bin/git', '-C', 'x', 'push', 'origin'], ['env', 'A=1', 'git', 'push'],
                     ['bash', '-c', 'cd x && git push']):
            with self.subTest(argv=argv):
                self.assertDecision(self.decide(command(argv)), 'deny', 'commands.deny[0]')
        self.assertDecision(self.decide(command(None, 'make && git push')), 'deny', 'commands.deny[0]')

    def test_always_deny_commands(self):
        cases = {
            'always_deny.keychain': [['security', 'find-generic-password'], ['/usr/bin/security', 'x'],
                                     ['env', 'security', 'dump-keychain'], ['bash', '-c', 'security list'],
                                     ['xargs', 'security']],
            'always_deny.privilege': [['sudo', 'ls'], ['su'], ['doas', 'x'], ['osascript', '-e', 'x'], ['launchctl', 'load'],
                                      ['csrutil', 'status'], ['spctl', '--status'], ['tccutil', 'reset'],
                                      ['systemsetup', '-x'], ['dscl', '.'], ['defaults', 'write', 'x', 'y', 'z'],
                                      ['nice', '-n', '1', 'sudo', 'ls'], ['sh', '-c', 'echo; sudo ls']],
            'always_deny.bypass': [['codex', '--dangerously-bypass-approvals-and-sandbox'], ['codex', '--yolo'],
                                   ['codex', '-s', 'danger-full-access'], ['claude', '--dangerously-skip-permissions'],
                                   ['claude', '--permission-mode', 'bypassPermissions'], ['codex', '-c', 'approval_policy=never'],
                                   ['codex', '--config', 'sandbox_mode=x'], ['codex', '-a', 'never'],
                                   ['codex', '--ask-for-approval', 'never'], ['codex', '--ask-for-approval=never'],
                                   ['git', '-c', 'x.y=approval-policy=never', 'status']],
            'always_deny.credentials': [['cat', '~/.ssh/id_rsa'], ['cat', 'src/.env'], ['cp', '{home}/.aws/credentials', 'x'],
                                        ['curl', '--netrc-file={home}/.netrc']],
            'always_deny.app_data': [['cat', '{app_data}/state.json']],
        }
        for rule, argvs in cases.items():
            for argv in argvs:
                argv = [a.replace('{home}', str(self.home)).replace('{app_data}', str(self.app_data)) for a in argv]
                with self.subTest(rule=rule, argv=argv):
                    self.assertDecision(self.decide(command(argv)), 'deny', rule)
                    self.assertEqual(self.decide(command(argv, sandbox='escalated'))['decision'], 'deny')
        self.assertDecision(self.decide(command(None, 'sudo ls')), 'deny', 'always_deny.privilege')
        self.assertDecision(self.decide(command(['defaults', 'read', 'x'])), 'allow', 'commands.workspace')

    def test_escalated_commands_always_ask(self):
        result = self.decide(command(['git', 'status'], sandbox='escalated'))
        self.assertDecision(result, 'ask', 'always_ask.escalation')
        self.assertEqual((result['ask']['reason'], result['ask']['options'], result['ask']['scope_patch']),
                         ('escalation', ['allow_once', 'deny'], None))

    def test_command_needing_network_asks_for_network(self):
        result = self.decide(command(['pip', 'install', 'x'], network=True))
        self.assertDecision(result, 'ask', 'network.default')
        self.assertEqual(result['ask']['reason'], 'network_host')
        self.assertEqual(result['ask']['options'], ['allow_once', 'deny'])
        self.assertEqual(result['ask']['title'], 'Allow network to any host for this one command?')


class NetworkAndSearchTests(Fixture):
    def request(self, host='pypi.org'):
        return {'category': 'network', 'host': host, 'port': 443, 'via': 'command'}

    def test_on_off_network_asks_for_every_host(self):
        # PROVISIONAL(0B-5): the sandbox has on/off network only, so host lists do not apply to commands.
        for host in ('pypi.org', 'evil.example', None):
            with self.subTest(host=host):
                result = self.decide(self.request(host))
                self.assertDecision(result, 'ask', 'network.default')
                self.assertEqual(result['ask']['options'], ['allow_once', 'deny'])
                self.assertIsNone(result['ask']['scope_patch'])
        document = copy.deepcopy(self.scope)
        document['network']['default'] = 'deny'
        self.assertDecision(self.decide(self.request(None), document=document), 'deny', 'scope.default_deny')

    def test_per_host_rules_when_sandbox_supports_them(self):
        document = copy.deepcopy(self.scope)
        document['network'].update(allow_hosts=['pypi.org', '*.pythonhosted.org'], deny_hosts=['*.evil.test'])
        original = scope.network_per_host
        scope.network_per_host = lambda: True
        self.addCleanup(setattr, scope, 'network_per_host', original)
        self.assertDecision(self.decide(self.request('pypi.org'), document=document), 'allow', 'network.allow_hosts[0]')
        self.assertDecision(self.decide(self.request('files.pythonhosted.org'), document=document), 'allow', 'network.allow_hosts[1]')
        self.assertEqual(self.decide(self.request('pythonhosted.org'), document=document)['decision'], 'ask')
        self.assertDecision(self.decide(self.request('a.evil.test'), document=document), 'deny', 'network.deny_hosts[0]')
        result = self.decide(self.request('example.com'), document=document)
        self.assertDecision(result, 'ask', 'network.default')
        self.assertEqual(result['ask']['options'], ['allow_once', 'add_to_scope', 'deny'])
        self.assertEqual(result['ask']['scope_patch'], {'network': {'allow_hosts': ['example.com']}})

    def test_web_search_settings(self):
        request = {'category': 'web_search', 'query': 'python'}
        self.assertDecision(self.decide(request), 'allow', 'web_search')
        for setting, expected in (('ask', 'ask'), ('deny', 'deny')):
            document = dict(copy.deepcopy(self.scope), web_search=setting)
            result = self.decide(request, document=document)
            self.assertEqual(result['decision'], expected)
        self.assertEqual(self.decide(request, document=dict(copy.deepcopy(self.scope), web_search='deny'))['rule'],
                         'scope.default_deny')


class McpDecisionTests(Fixture):
    def test_own_server_and_sharing_tools_are_denied(self):
        self.assertDecision(self.decide({'category': 'mcp', 'server': 'interspace', 'tool': 'scope_update'}),
                            'deny', 'always_deny.scope_self_edit')
        self.assertDecision(self.decide({'category': 'mcp', 'server': 'interspace', 'tool': 'read_page'}),
                            'deny', 'policy.invalid_request')
        self.assertDecision(self.decide({'category': 'mcp', 'server': 'other', 'tool': 'share_doc'}),
                            'deny', 'always_deny.sharing')

    def test_other_mcp_tools_always_ask(self):
        result = self.decide({'category': 'mcp', 'server': 'files', 'tool': 'read_file'})
        self.assertDecision(result, 'ask', 'always_ask.mcp')
        self.assertEqual((result['ask']['reason'], result['ask']['options']), ('mcp_tool', ['allow_once', 'deny']))


class MalformedRequestTests(Fixture):
    def test_malformed_requests_fail_closed_without_raising(self):
        for request in (None, {}, {'category': 'teleport'}, read(''), read(None), write(), {'category': 'file_write', 'project_id': PID, 'paths': 'src/a'},
                        command(None, None), command([]), command(['ls', 5]), command(['ls'], sandbox='nope'),
                        {'category': 'app', 'app': 'x', 'op': 'read', 'action': 'x.read', 'ref': 'x:page:1'},
                        {'category': 'network', 'host': 'a b', 'port': 1, 'via': 'command'},
                        {'category': 'web_search', 'query': 5}, {'category': 'mcp', 'server': '', 'tool': 'x'},
                        read('src/a\x00b')):
            with self.subTest(request=request):
                result = self.decide(request)
                self.assertDecision(result, 'deny', 'policy.invalid_request')

    def test_safe_decide_turns_exceptions_into_policy_failed(self):
        result = scope.safe_decide(self.scope, self.approval, read('src/a.py'), workspace_roots=None, now=NOW)
        self.assertEqual((result['decision'], result['rule']), ('deny', 'policy.failed'))


class AnswerTests(Fixture):
    def ask_for_docs(self):
        result = self.decide(write('docs/guide.md'))
        return dict(result['ask'], ask_id='a1', request=write('docs/guide.md'))

    def test_add_to_scope_amends_and_reapproves(self):
        ask = self.ask_for_docs()
        answer = {'ask_id': 'a1', 'decision': 'add_to_scope', 'request_digest': ask['request_digest'],
                  'scope_digest': ask['patched_scope_digest']}
        outcome = scope.apply_answer(self.scope, self.approval, ask, answer, now=NOW)
        self.assertEqual(outcome['change'], 'amended')
        self.assertTrue(outcome['run'])
        self.assertEqual(outcome['scope']['version'], 4)
        self.assertEqual(scope.digest(outcome['scope']), ask['patched_scope_digest'])
        self.assertTrue(scope.is_approved(outcome['scope'], outcome['approval']))
        self.assertEqual(outcome['scope']['projects'][0]['write'], ['src/**', 'tests/**', 'docs/guide.md'])
        self.assertEqual(self.scope['version'], 3)
        again = scope.decide(outcome['scope'], outcome['approval'], write('docs/guide.md'),
                             workspace_roots={PID: str(self.root)}, now=NOW)
        self.assertEqual(again['decision'], 'allow')

    def test_add_to_scope_rejects_changed_scope_or_digest(self):
        ask = self.ask_for_docs()
        answer = {'ask_id': 'a1', 'decision': 'add_to_scope', 'request_digest': ask['request_digest'],
                  'scope_digest': ask['patched_scope_digest']}
        edited = scope.edit(self.scope, 3, dict(copy.deepcopy(self.scope), web_search='ask'))
        with self.assertRaises(ValueError):
            scope.apply_answer(edited, approval_for(edited), ask, answer, now=NOW)
        with self.assertRaises(ValueError):
            scope.apply_answer(self.scope, self.approval, ask, dict(answer, scope_digest='sha256:' + 'f' * 64), now=NOW)
        with self.assertRaises(ValueError):
            scope.apply_answer(self.scope, self.approval, ask, dict(answer, scope_digest=None), now=NOW)

    def test_answers_bind_request_digest_and_offered_options(self):
        ask = self.ask_for_docs()
        good = {'ask_id': 'a1', 'decision': 'allow_once', 'request_digest': ask['request_digest']}
        outcome = scope.apply_answer(self.scope, self.approval, ask, good, now=NOW)
        self.assertEqual((outcome['run'], outcome['change'], outcome['scope'], outcome['approval']),
                         (True, None, self.scope, self.approval))
        denied = scope.apply_answer(self.scope, self.approval, ask, dict(good, decision='deny'), now=NOW)
        self.assertFalse(denied['run'])
        for bad in (dict(good, request_digest='sha256:' + '0' * 64), dict(good, ask_id='a2'),
                    dict(good, decision='text'), dict(good, decision='cancel')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                scope.apply_answer(self.scope, self.approval, ask, bad, now=NOW)
        escalated = self.decide(command(['ls'], sandbox='escalated'))['ask']
        escalated = dict(escalated, ask_id='a1')
        with self.assertRaises(ValueError):
            scope.apply_answer(self.scope, self.approval, escalated,
                               {'ask_id': 'a1', 'decision': 'add_to_scope', 'request_digest': escalated['request_digest'],
                                'scope_digest': None}, now=NOW)

    def test_allow_once_needs_live_approval(self):
        ask = self.ask_for_docs()
        edited = scope.edit(self.scope, 3, dict(copy.deepcopy(self.scope), web_search='ask'))
        with self.assertRaises(ValueError):
            scope.apply_answer(edited, None, ask, {'ask_id': 'a1', 'decision': 'allow_once',
                                                  'request_digest': ask['request_digest']}, now=NOW)

    def test_merge_patch_only_widens(self):
        merged = scope.merge_patch(self.scope, {
            'projects': [{'project_id': PID, 'access': 'read', 'read': ['**', 'x'], 'deny': []}],
            'commands': {'allow': [['git', 'status'], ['make']]},
            'network': {'allow_hosts': ['example.com']},
        })
        self.assertEqual(merged['projects'][0]['access'], 'write')
        self.assertEqual(merged['projects'][0]['read'], ['**', 'x'])
        self.assertEqual(merged['projects'][0]['deny'], ['secrets/**'])
        self.assertEqual(merged['commands']['allow'], [['git', 'status'], ['make']])
        self.assertEqual(merged['network']['allow_hosts'], ['pypi.org', 'example.com'])
        self.assertEqual(merged['apps'], [])
        self.assertEqual(merged['version'], 3)
        with self.assertRaises(ValueError):
            scope.merge_patch(self.scope, {'version': 9})
        with self.assertRaises(ValueError):
            scope.merge_patch(self.scope, {'limits': {'token_budget': 1}})
        with self.assertRaises(ValueError):
            scope.merge_patch(self.scope, {'apps': [{'app': 'a', 'access': 'read', 'resources': 'all'}]})


if __name__ == '__main__':
    unittest.main()
