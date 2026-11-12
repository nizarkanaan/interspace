import json
import threading
import unittest
from pathlib import Path

from . import fakehttp
from spaces import base
import spaces
from spaces import github

API = 'https://api.github.com'
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'github'
TOKEN = 'github_pat_canary_' + '0' * 70
NOW = base.parse_time('2026-11-11T10:00:30.000Z')
AUTH = {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': github.API_VERSION}
NEXT = {'Link': '<https://api.github.com/next?page=2>; rel="next", <https://api.github.com/last?page=9>; rel="last"'}
LAST = {'Link': '<https://api.github.com/first?page=1>; rel="first", <https://api.github.com/prev?page=1>; rel="prev"'}
REPO = 'github:repo:octo/notes'
ISSUE = 'github:issue:octo/notes#41'
PULL = 'github:pull:octo/notes#42'
BRANCH = 'github:branch:octo/notes@main'


def load(name):
    return json.loads((FIXTURES / (name + '.json')).read_text(encoding='utf-8'))


class GitHubTestCase(unittest.TestCase):
    signed_in = True

    def setUp(self):
        self.http = fakehttp.FakeHttp()
        self.credentials = fakehttp.MemoryCredentials({'kind': 'token', 'access_token': TOKEN} if self.signed_in else None)
        self.journal = fakehttp.MemoryJournal()
        self.connector = github.Connector(http=self.http, credentials=self.credentials, journal=self.journal,
                                          clock=lambda: NOW)

    def tearDown(self):
        self.http.assert_done()

    def assertNoSecret(self, value):
        text = json.dumps(value, default=str)
        self.assertNotIn('canary', text)
        self.assertNotIn('secret detail', text)


class RegistryTests(GitHubTestCase):
    def test_registry_builds_the_github_connector(self):
        made = spaces.connector('github', self.http, self.credentials, self.journal)
        self.assertIsInstance(made, github.Connector)
        self.assertEqual((made.app, made.kinds), ('github', ('repo', 'issue', 'pull', 'file', 'branch')))


class StatusTests(GitHubTestCase):
    def test_signed_in(self):
        self.http.expect('GET', API + '/user', json=load('user'), match_headers=AUTH)
        self.assertEqual(self.connector.status(), {
            'v': 1, 'app': 'github', 'state': 'signed_in', 'account': {'label': 'octocat', 'id': '583231'},
            'granted': ['repo:read', 'contents:read', 'issues:write', 'pulls:write'],
            'detail': '', 'checked_at': '2026-11-11T10:00:30.000Z'})

    def test_signed_out_makes_no_request(self):
        self.credentials.delete()
        status = self.connector.status()
        self.assertEqual((status['state'], status['account'], status['granted']), ('signed_out', None, []))

    def test_expired(self):
        self.http.expect('GET', API + '/user', status=401, json=load('error'))
        status = self.connector.status()
        self.assertEqual(status['state'], 'expired')
        self.assertIn('Sign in', status['detail'])
        self.assertNoSecret(status)

    def test_unreachable_and_keychain_unavailable(self):
        self.http.expect('GET', API + '/user', raises='connection')
        self.assertEqual(self.connector.status()['state'], 'unavailable')

        class Broken:
            def get(self):
                raise base.CredentialStoreUnavailable('The Keychain did not answer. Try again.')
        connector = github.Connector(http=self.http, credentials=Broken(), journal=self.journal, clock=lambda: NOW)
        status = connector.status()
        self.assertEqual(status['state'], 'unavailable')
        self.assertIn('Keychain', status['detail'])


class SignInTests(GitHubTestCase):
    signed_in = False

    def test_token_entry_step(self):
        step = self.connector.begin_sign_in({})
        self.assertEqual(step['kind'], 'token_entry')
        self.assertEqual(set(step), {'v', 'app', 'kind', 'label', 'help_url', 'pattern'})
        self.assertTrue(step['help_url'].startswith('https://docs.github.com/'))
        self.assertRegex(TOKEN, step['pattern'])
        self.assertNotRegex('ghp_' + 'a' * 36, step['pattern'])   # classic tokens carry broad scopes

    def test_complete_validates_then_stores(self):
        self.http.expect('GET', API + '/user', json=load('user'), match_headers=AUTH)
        status = self.connector.complete_sign_in({'token': TOKEN}, threading.Event())
        self.assertEqual((status['state'], status['account']['label']), ('signed_in', 'octocat'))
        self.assertEqual(self.credentials.get(), {'kind': 'token', 'access_token': TOKEN, 'account_id': '583231'})
        self.assertNoSecret(status)

    def test_cancelled_before_and_after_the_check(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(base.SignInCancelled):
            self.connector.complete_sign_in({'token': TOKEN}, cancel)

        class CancelDuringCheck:
            calls = 0

            def is_set(self):
                self.calls += 1
                return self.calls > 1
        self.http.expect('GET', API + '/user', json=load('user'))
        with self.assertRaises(base.SignInCancelled):
            self.connector.complete_sign_in({'token': TOKEN}, CancelDuringCheck())
        self.assertIsNone(self.credentials.get())

    def test_rejected_and_malformed_tokens_store_nothing(self):
        self.http.expect('GET', API + '/user', status=401, json=load('error'))
        with self.assertRaises(base.InvalidRequest) as caught:
            self.connector.complete_sign_in({'token': TOKEN}, None)
        self.assertNoSecret(str(caught.exception))
        for params in ({}, {'token': 'short'}, {'token': 'ghp_' + 'a' * 36}, {'token': 'github_pat_ has spaces in it ok'},
                       {'token': TOKEN, 'x': 1}, {'token': 5}):
            with self.subTest(params=params), self.assertRaises(base.InvalidRequest):
                self.connector.complete_sign_in(params, None)
        self.assertIsNone(self.credentials.get())

    def test_reads_and_writes_need_sign_in(self):
        with self.assertRaises(base.NotSignedIn):
            self.connector.browse()
        with self.assertRaises(base.NotSignedIn):
            self.connector.write('github.issue.comment', ISSUE, {'body': 'hi'}, 'k1')
        self.assertEqual(self.journal.records, {})


class SignOutTests(GitHubTestCase):
    def test_sign_out_deletes_the_secret_without_a_request(self):
        status = self.connector.sign_out()
        self.assertEqual(status['state'], 'signed_out')
        self.assertIsNone(self.credentials.get())


class BrowseTests(GitHubTestCase):
    def test_repositories_over_two_pages(self):
        self.http.expect('GET', API + '/user/repos', json=load('repos_page1'), headers=NEXT, match_headers=AUTH,
                         match_params={'per_page': '2', 'page': '1', 'sort': 'updated'})
        first = self.connector.browse(limit=2)
        self.assertEqual(first['v'], 1)
        self.assertEqual(first['items'][0], {
            'ref': REPO, 'kind': 'repo', 'title': 'octo/notes', 'parent': None, 'url': 'https://github.com/octo/notes',
            'updated_at': '2026-11-10T18:02:11.000Z', 'has_children': True,
            'meta': {'private': True, 'description': 'Reading notes and drafts.', 'language': 'Python',
                     'open_issues': 3, 'default_branch': 'main', 'archived': False}})
        self.assertEqual(first['items'][1]['meta'], {'private': False, 'open_issues': 0, 'default_branch': 'main', 'archived': False})
        self.assertTrue(first['next_cursor'])
        self.http.expect('GET', API + '/user/repos', json=load('repos_page2'), headers=LAST,
                         match_params={'per_page': '2', 'page': '2'})
        second = self.connector.browse(cursor=first['next_cursor'], limit=2)
        self.assertEqual([i['ref'] for i in second['items']], ['github:repo:octo-lab/papers'])
        self.assertIsNone(second['next_cursor'])

    def test_repository_lists_default_branch_then_issues_and_pulls(self):
        self.http.expect('GET', API + '/repos/octo/notes', json=load('repo'))
        self.http.expect('GET', API + '/repos/octo/notes/issues', json=load('issues_page1'), headers=NEXT,
                         match_params={'state': 'open', 'sort': 'updated', 'direction': 'desc', 'per_page': '2', 'page': '1'})
        first = self.connector.browse(REPO, limit=3)
        self.assertEqual(first['items'][0], {
            'ref': BRANCH, 'kind': 'branch', 'title': 'main', 'parent': REPO,
            'url': 'https://github.com/octo/notes/tree/main', 'updated_at': None, 'has_children': True,
            'meta': {'default': True}})
        self.assertEqual(first['items'][1], {
            'ref': ISSUE, 'kind': 'issue', 'title': 'Track reading list', 'parent': REPO,
            'url': 'https://github.com/octo/notes/issues/41', 'updated_at': '2026-11-10T17:00:00.000Z', 'has_children': False,
            'meta': {'number': 41, 'state': 'open', 'author': 'octocat', 'comments': 2, 'labels': 'reading, todo'}})
        self.assertEqual((first['items'][2]['ref'], first['items'][2]['kind']), (PULL, 'pull'))
        self.http.expect('GET', API + '/repos/octo/notes/issues', json=load('issues_page2'),
                         match_params={'per_page': '2', 'page': '2'})
        second = self.connector.browse(REPO, cursor=first['next_cursor'], limit=3)
        self.assertEqual([i['ref'] for i in second['items']], ['github:issue:octo/notes#7'])
        self.assertIsNone(second['next_cursor'])

    def test_repository_with_limit_one_still_reaches_issues(self):
        self.http.expect('GET', API + '/repos/octo/notes', json=load('repo'))
        first = self.connector.browse(REPO, limit=1)
        self.assertEqual([i['ref'] for i in first['items']], [BRANCH])
        self.http.expect('GET', API + '/repos/octo/notes/issues', json=load('issues_page2'),
                         match_params={'per_page': '1', 'page': '1'})
        second = self.connector.browse(REPO, cursor=first['next_cursor'], limit=1)
        self.assertEqual([i['ref'] for i in second['items']], ['github:issue:octo/notes#7'])

    def test_branch_and_folder_contents(self):
        self.http.expect('GET', API + '/repos/octo/notes/contents', json=load('contents_root'), match_params={'ref': 'main'})
        first = self.connector.browse(BRANCH, limit=2)
        self.assertEqual(first['items'][0], {
            'ref': 'github:file:octo/notes@main:docs', 'kind': 'file', 'title': 'docs', 'parent': BRANCH,
            'url': 'https://github.com/octo/notes/tree/main/docs', 'updated_at': None, 'has_children': True,
            'meta': {'type': 'dir'}})
        self.assertEqual(first['items'][1]['meta'], {'type': 'file', 'size': 40})
        self.http.expect('GET', API + '/repos/octo/notes/contents', json=load('contents_root'))
        second = self.connector.browse(BRANCH, cursor=first['next_cursor'], limit=2)
        self.assertEqual([i['title'] for i in second['items']], ['notes.txt'])
        self.assertIsNone(second['next_cursor'])
        self.http.expect('GET', API + '/repos/octo/notes/contents/docs', json=load('contents_docs'), match_params={'ref': 'main'})
        docs = self.connector.browse('github:file:octo/notes@main:docs')
        self.assertEqual([(i['ref'], i['parent']) for i in docs['items']],
                         [('github:file:octo/notes@main:docs/guide.md', 'github:file:octo/notes@main:docs')])

    def test_paths_and_branches_are_encoded(self):
        self.http.expect('GET', API + '/repos/octo/notes/contents/my%20docs/a%23b', json=[],
                         match_params={'ref': 'feature/x'})
        self.connector.browse('github:file:octo/notes@feature/x:my docs/a#b')

    def test_a_file_has_no_children(self):
        self.http.expect('GET', API + '/repos/octo/notes/contents/docs/guide.md', json=load('file'))
        with self.assertRaises(base.InvalidRequest):
            self.connector.browse('github:file:octo/notes@main:docs/guide.md')

    def test_cursor_and_refs_are_checked(self):
        self.http.expect('GET', API + '/user/repos', json=load('repos_page1'), headers=NEXT)
        cursor = self.connector.browse(limit=2)['next_cursor']
        for call in (lambda: self.connector.browse(REPO, cursor=cursor),
                     lambda: self.connector.browse(limit=3, cursor=cursor),
                     lambda: self.connector.search('x', cursor=cursor),
                     lambda: self.connector.browse(cursor='garbage'),
                     lambda: self.connector.browse(limit=0),
                     lambda: self.connector.browse(limit=101),
                     lambda: self.connector.browse(ISSUE),
                     lambda: self.connector.browse(PULL),
                     lambda: self.connector.browse('notion:page:x'),
                     lambda: self.connector.browse('github:repo:octo'),
                     lambda: self.connector.browse('github:repo:octo/..'),
                     lambda: self.connector.browse('github:repo:../x'),
                     lambda: self.connector.browse('github:repo:octo/notes/extra'),
                     lambda: self.connector.read('github:issue:octo/notes#x'),
                     lambda: self.connector.read('github:issue:octo/notes#0'),
                     lambda: self.connector.read('github:branch:octo/notes@a..b'),
                     lambda: self.connector.read('github:branch:octo/notes@'),
                     lambda: self.connector.read('github:file:octo/notes@main:../secret'),
                     lambda: self.connector.read('github:file:octo/notes@main:/abs'),
                     lambda: self.connector.read('github:file:octo/notes@main'),
                     lambda: self.connector.read('github:commit:octo/notes@abc')):
            with self.assertRaises(base.InvalidRequest):
                call()


class SearchTests(GitHubTestCase):
    def test_issue_search_adds_the_type_qualifier(self):
        self.http.expect('GET', API + '/search/issues', json=load('search_issues'), headers=NEXT,
                         match_params={'q': 'reading is:issue', 'per_page': '25', 'page': '1'})
        page = self.connector.search('reading', kinds=['issue'])
        self.assertEqual([i['ref'] for i in page['items']], [ISSUE])
        self.http.expect('GET', API + '/search/issues', json={'total_count': 1, 'incomplete_results': False, 'items': []},
                         match_params={'q': 'reading is:issue', 'page': '2'})
        self.assertEqual(self.connector.search('reading', kinds=['issue'], cursor=page['next_cursor'])['items'], [])

    def test_all_kinds_share_the_limit_across_three_searches(self):
        self.http.expect('GET', API + '/search/repositories', json=load('search_repos'),
                         match_params={'q': 'notes', 'per_page': '4', 'page': '1'})
        self.http.expect('GET', API + '/search/issues', json=load('search_issues'), headers=NEXT,
                         match_params={'q': 'notes is:issue', 'per_page': '3', 'page': '1'})
        self.http.expect('GET', API + '/search/issues', json=load('search_pulls'),
                         match_params={'q': 'notes is:pr', 'per_page': '3', 'page': '1'})
        first = self.connector.search('notes', limit=10)
        self.assertEqual([i['ref'] for i in first['items']], [REPO, ISSUE, PULL])
        # Only the issue search has more; the next page asks it alone.
        self.http.expect('GET', API + '/search/issues', json=load('search_issues'),
                         match_params={'q': 'notes is:issue', 'per_page': '3', 'page': '2'})
        second = self.connector.search('notes', limit=10, cursor=first['next_cursor'])
        self.assertEqual(len(second['items']), 1)
        self.assertIsNone(second['next_cursor'])

    def test_files_and_branches_are_not_searchable_and_queries_are_checked(self):
        self.assertEqual(self.connector.search('x', kinds=['file', 'branch']), {'v': 1, 'items': [], 'next_cursor': None})
        for args in (('',), ('x' * 501,), ('x', ['page']), ('x', []), (5,)):
            with self.subTest(args=args), self.assertRaises(base.InvalidRequest):
                self.connector.search(*args)


class ReadTests(GitHubTestCase):
    ISSUE_TEXT = ('# Track reading list (#41)\n\nOpen issue by @octocat · Labels: reading, todo\n\n'
                  'Keep a list of **papers**.\n\n- one\n- two\n'
                  '\n---\n\n**@octocat** commented on 2026-11-02:\n\nStarted the list.\n'
                  '\n---\n\n**@hubot** commented on 2026-11-03:\n\nAdded two papers.\n')

    def expect_issue(self):
        self.http.expect('GET', API + '/repos/octo/notes/issues/41', json=load('issue'), match_headers=AUTH)
        self.http.expect('GET', API + '/repos/octo/notes/issues/41/comments', json=load('issue_comments'),
                         match_params={'per_page': '100', 'page': '1'})

    def test_read_issue_with_comments(self):
        self.expect_issue()
        content = self.connector.read(ISSUE)
        self.assertEqual(content, {
            'v': 1, 'ref': ISSUE, 'title': 'Track reading list', 'format': 'markdown', 'text': self.ISSUE_TEXT,
            'truncated': False, 'next_cursor': None, 'version': '2026-11-10T17:00:00.000Z',
            'url': 'https://github.com/octo/notes/issues/41', 'parent': REPO,
            'meta': {'number': 41, 'state': 'open', 'author': 'octocat', 'comments': 2, 'labels': 'reading, todo'}})

    def test_read_with_truncation_joins_to_the_full_text(self):
        self.connector.max_read_chars = 60
        parts, cursor = [], None
        while True:
            self.expect_issue()
            content = self.connector.read(ISSUE, cursor=cursor)
            self.assertLessEqual(len(content['text']), 60)
            parts.append(content['text'])
            cursor = content['next_cursor']
            self.assertEqual(content['truncated'], cursor is not None)
            if cursor is None:
                break
        self.assertGreater(len(parts), 3)
        self.assertEqual(''.join(parts), self.ISSUE_TEXT)

    def test_continuation_fails_when_the_issue_changed(self):
        self.connector.max_read_chars = 60
        self.expect_issue()
        cursor = self.connector.read(ISSUE)['next_cursor']
        changed = load('issue')
        changed['updated_at'] = '2026-11-11T00:00:00Z'
        self.http.expect('GET', API + '/repos/octo/notes/issues/41', json=changed)
        with self.assertRaises(base.InvalidRequest):
            self.connector.read(ISSUE, cursor=cursor)
        with self.assertRaises(base.InvalidRequest):
            self.connector.read('github:issue:octo/notes#7', cursor=cursor)

    def test_read_pull_without_comments(self):
        self.http.expect('GET', API + '/repos/octo/notes/pulls/42', json=load('pull'))
        content = self.connector.read(PULL)
        self.assertEqual(content['text'], '# Add chapter outline (#42)\n\nOpen pull request by @octocat · outline into main\n\n'
                                          'Outline for chapter 1.\n')
        self.assertEqual(content['meta'], {'number': 42, 'state': 'open', 'author': 'octocat', 'comments': 0,
                                           'head': 'outline', 'base': 'main', 'draft': False, 'merged': False})
        self.assertEqual(content['url'], 'https://github.com/octo/notes/pull/42')

    def test_read_repository_with_readme(self):
        self.http.expect('GET', API + '/repos/octo/notes', json=load('repo'))
        self.http.expect('GET', API + '/repos/octo/notes/readme', json=load('readme'))
        content = self.connector.read(REPO)
        self.assertEqual(content['text'], '# octo/notes\n\nReading notes and drafts.\n\n'
                                          'Default branch: main · 3 open issues and pull requests\n\n---\n\n'
                                          '# Notes\n\nInvented README for tests.\n')
        self.assertEqual((content['format'], content['version'], content['parent']), ('markdown', '2026-11-10T18:02:11.000Z', None))

    def test_read_repository_without_readme(self):
        self.http.expect('GET', API + '/repos/octo/notes', json=load('repo'))
        self.http.expect('GET', API + '/repos/octo/notes/readme', status=404, json=load('error'))
        self.assertTrue(self.connector.read(REPO)['text'].endswith('pull requests\n'))

    def test_read_text_file(self):
        self.http.expect('GET', API + '/repos/octo/notes/contents/docs/guide.md', json=load('file'), match_params={'ref': 'main'})
        content = self.connector.read('github:file:octo/notes@main:docs/guide.md')
        self.assertEqual((content['format'], content['text'], content['version'], content['parent'], content['title']),
                         ('text', '# Guide\n\nLine one.\nLine two.\n', 'f' * 40, 'github:file:octo/notes@main:docs', 'guide.md'))
        self.assertEqual(content['url'], 'https://github.com/octo/notes/blob/main/docs/guide.md')

    def test_root_file_parent_is_the_branch(self):
        self.http.expect('GET', API + '/repos/octo/notes/contents/notes.txt', json=dict(load('file'), path='notes.txt', name='notes.txt'))
        self.assertEqual(self.connector.read('github:file:octo/notes@main:notes.txt')['parent'], BRANCH)

    def test_binary_and_large_files_are_unavailable(self):
        for name in ('file_binary', 'file_large'):
            self.http.expect('GET', API + '/repos/octo/notes/contents/x', json=load(name))
            content = self.connector.read('github:file:octo/notes@main:x')
            with self.subTest(name=name):
                self.assertEqual((content['format'], content['text']), ('unavailable', ''))
                self.assertTrue(content['meta']['reason'])

    def test_read_folder_lists_names(self):
        self.http.expect('GET', API + '/repos/octo/notes/contents/docs', json=load('contents_root'))
        content = self.connector.read('github:file:octo/notes@main:docs')
        self.assertEqual((content['format'], content['text']), ('text', 'docs/\nREADME.md\nnotes.txt\n'))

    def test_read_branch(self):
        self.http.expect('GET', API + '/repos/octo/notes/branches/main', json=load('branch'))
        content = self.connector.read(BRANCH)
        self.assertEqual(content['format'], 'json')
        self.assertEqual(json.loads(content['text']), {'name': 'main', 'commit': 'c' * 40, 'protected': True})
        self.assertEqual((content['version'], content['parent']), ('c' * 40, REPO))

    def test_remote_shape_is_validated(self):
        broken = load('issue')
        broken['updated_at'] = 7
        self.http.expect('GET', API + '/repos/octo/notes/issues/41', json=broken)
        with self.assertRaises(base.InvalidResponse):
            self.connector.read(ISSUE)
        self.http.expect('GET', API + '/repos/octo/notes/issues/41', body=b'<html>')
        with self.assertRaises(base.InvalidResponse):
            self.connector.read(ISSUE)
        self.http.expect('GET', API + '/user/repos', json={'items': []})
        with self.assertRaises(base.InvalidResponse):
            self.connector.browse()
        bad_name = load('repos_page1')
        bad_name[0]['full_name'] = 'octo/../x'
        self.http.expect('GET', API + '/user/repos', json=bad_name)
        with self.assertRaises(base.InvalidResponse):
            self.connector.browse()


class ActionTests(GitHubTestCase):
    def test_action_specs_and_tools(self):
        specs = {spec['name']: spec for spec in self.connector.actions()}
        self.assertEqual({name: spec['effect'] for name, spec in specs.items()}, {
            'github.repo.create_issue': 'create', 'github.issue.comment': 'create', 'github.issue.update': 'update',
            'github.issue.close': 'destructive', 'github.pull.comment': 'create', 'github.repo.create_pull': 'create'})
        self.assertTrue(specs['github.issue.update']['requires_version'])
        for spec in specs.values():
            self.assertFalse(spec['params_schema']['additionalProperties'])
            self.assertEqual(spec['target_kind'], spec['name'].split('.')[1])
        names = [tool['name'] for tool in base.tools(self.connector)]
        self.assertEqual(names, ['github_search', 'github_browse', 'github_read', 'github_repo_create_issue',
                                 'github_issue_comment', 'github_issue_update', 'github_issue_close',
                                 'github_pull_comment', 'github_repo_create_pull'])

    def test_create_issue(self):
        self.http.expect('POST', API + '/repos/octo/notes/issues', status=201, json=load('created_issue'), match_headers=AUTH,
                         match_json={'title': 'New issue', 'body': 'Details.', 'labels': ['todo']})
        result = self.connector.write('github.repo.create_issue', REPO,
                                      {'title': 'New issue', 'body': 'Details.', 'labels': ['todo']}, 'ui-1')
        self.assertEqual(result, {
            'v': 1, 'ok': True, 'action': 'github.repo.create_issue', 'ref': REPO,
            'result_ref': 'github:issue:octo/notes#43', 'url': 'https://github.com/octo/notes/issues/43',
            'version': '2026-11-11T09:31:02.000Z', 'replayed': False, 'summary': 'Created issue #43 "New issue".'})
        self.assertEqual(self.http.calls[-1]['json'], {'title': 'New issue', 'body': 'Details.', 'labels': ['todo']})

    def test_comment_on_issue_and_pull(self):
        self.http.expect('POST', API + '/repos/octo/notes/issues/41/comments', status=201, json=load('comment'),
                         match_json={'body': 'Looks good'})
        result = self.connector.write('github.issue.comment', ISSUE, {'body': 'Looks good'}, 'ui-2')
        self.assertEqual((result['result_ref'], result['url'], result['summary']),
                         (ISSUE, load('comment')['html_url'], 'Commented on issue #41.'))
        self.http.expect('POST', API + '/repos/octo/notes/issues/42/comments', status=201, json=load('comment'))
        result = self.connector.write('github.pull.comment', PULL, {'body': 'Nice'}, 'ui-3')
        self.assertEqual((result['result_ref'], result['summary']), (PULL, 'Commented on pull request #42.'))

    def test_update_issue_checks_the_version_first(self):
        self.http.expect('GET', API + '/repos/octo/notes/issues/41', json=load('issue'))
        self.http.expect('PATCH', API + '/repos/octo/notes/issues/41', json=load('updated_issue'))
        result = self.connector.write('github.issue.update', ISSUE, {
            'title': 'Renamed', 'labels': ['done'], 'base_version': '2026-11-10T17:00:00.000Z'}, 'ui-4')
        self.assertEqual(self.http.calls[-1]['json'], {'title': 'Renamed', 'labels': ['done']})
        self.assertEqual((result['version'], result['summary']), ('2026-11-11T09:33:00.000Z', 'Updated issue #41.'))

    def test_update_issue_conflict(self):
        self.http.expect('GET', API + '/repos/octo/notes/issues/41', json=load('issue'))
        with self.assertRaises(base.Conflict):
            self.connector.write('github.issue.update', ISSUE, {'body': 'x', 'base_version': '2026-11-01T00:00:00.000Z'}, 'ui-5')
        self.assertEqual(self.journal.records['ui-5']['status'], 'failed')
        self.http.expect('GET', API + '/repos/octo/notes/issues/41', json=load('issue'))
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('github.issue.update', ISSUE, {'body': 'x', 'base_version': 'yesterday'}, 'ui-6')

    def test_close_issue(self):
        self.http.expect('PATCH', API + '/repos/octo/notes/issues/41', json=load('closed_issue'),
                         match_json={'state': 'closed', 'state_reason': 'not_planned'})
        result = self.connector.write('github.issue.close', ISSUE, {'reason': 'not_planned'}, 'ui-7')
        self.assertEqual(result['summary'], 'Closed issue #41.')
        self.http.expect('PATCH', API + '/repos/octo/notes/issues/41', json=load('closed_issue'))
        self.connector.write('github.issue.close', ISSUE, {}, 'ui-8')
        self.assertEqual(self.http.calls[-1]['json'], {'state': 'closed', 'state_reason': 'completed'})

    def test_create_pull_from_a_pushed_branch(self):
        self.http.expect('POST', API + '/repos/octo/notes/pulls', status=201, json=load('created_pull'),
                         match_json={'title': 'Draft chapter', 'head': 'chapter', 'base': 'main', 'draft': True})
        result = self.connector.write('github.repo.create_pull', REPO,
                                      {'title': 'Draft chapter', 'head': 'chapter', 'base': 'main', 'draft': True}, 'ui-9')
        self.assertEqual((result['result_ref'], result['url'], result['summary']),
                         ('github:pull:octo/notes#44', 'https://github.com/octo/notes/pull/44',
                          'Opened pull request #44 "Draft chapter".'))
        self.http.expect('POST', API + '/repos/octo/notes/pulls', status=422, json=load('error'))
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('github.repo.create_pull', REPO, {'title': 't', 'head': 'missing', 'base': 'main'}, 'ui-10')

    def test_journal_replay_makes_no_second_request(self):
        self.http.expect('POST', API + '/repos/octo/notes/issues/41/comments', status=201, json=load('comment'))
        first = self.connector.write('github.issue.comment', ISSUE, {'body': 'Looks good'}, 'ui-11')
        again = self.connector.write('github.issue.comment', ISSUE, {'body': 'Looks good'}, 'ui-11')
        self.assertEqual(dict(first, replayed=True), again)
        self.assertEqual(len(self.http.calls), 1)
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('github.issue.comment', ISSUE, {'body': 'Other'}, 'ui-11')

    def test_timeout_after_send_is_outcome_unknown_and_never_resent(self):
        self.http.expect('POST', API + '/repos/octo/notes/issues', raises='timeout_after_send')
        for _ in range(2):
            with self.assertRaises(base.OutcomeUnknown):
                self.connector.write('github.repo.create_issue', REPO, {'title': 'x'}, 'ui-12')
        self.assertEqual(self.journal.records['ui-12']['status'], 'outcome_unknown')

    def test_read_step_timeout_before_an_update_is_not_unknown(self):
        self.http.expect('GET', API + '/repos/octo/notes/issues/41', raises='timeout_after_send')
        with self.assertRaises(base.Unavailable):
            self.connector.write('github.issue.update', ISSUE, {'body': 'x', 'base_version': '2026-11-10T17:00:00.000Z'}, 'ui-13')
        self.assertEqual(self.journal.records['ui-13']['status'], 'failed')

    def test_write_validation(self):
        bad = [('github.issue.delete', ISSUE, {}),
               ('github.issue.comment', PULL, {'body': 'x'}),
               ('github.pull.comment', ISSUE, {'body': 'x'}),
               ('github.issue.comment', ISSUE, {'body': ''}),
               ('github.issue.comment', ISSUE, {'body': 'x' * 65537}),
               ('github.issue.comment', ISSUE, {'body': 'x', 'extra': 1}),
               ('github.repo.create_issue', REPO, {'body': 'no title'}),
               ('github.repo.create_issue', REPO, {'title': 'x', 'labels': 'todo'}),
               ('github.repo.create_issue', REPO, {'title': 'x', 'labels': ['']}),
               ('github.repo.create_issue', REPO, {'title': 'x', 'labels': ['a'] * 21}),
               ('github.issue.update', ISSUE, {'base_version': '2026-11-10T17:00:00.000Z'}),
               ('github.issue.update', ISSUE, {'title': 'x'}),
               ('github.issue.close', ISSUE, {'reason': 'spam'}),
               ('github.repo.create_pull', REPO, {'title': 'x', 'head': 'a'}),
               ('github.repo.create_pull', REPO, {'title': 'x', 'head': 'a', 'base': 'main', 'draft': 'yes'}),
               ('github.repo.create_issue', ISSUE, {'title': 'x'})]
        for action, ref, params in bad:
            with self.subTest(action=action, params=params), self.assertRaises(base.InvalidRequest):
                self.connector.write(action, ref, params, 'k1')
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('github.issue.comment', ISSUE, {'body': 'x'}, 'bad key')
        self.assertEqual(self.journal.records, {})


class ErrorMappingTests(GitHubTestCase):
    def read_with(self, status, headers=None):
        self.http.expect('GET', API + '/repos/octo/notes/branches/main', status=status, json=load('error'), headers=headers)
        return self.connector.read(BRANCH)

    def test_read_status_mapping(self):
        cases = {400: base.InvalidRequest, 401: base.AuthExpired, 403: base.Forbidden, 404: base.NotFound,
                 409: base.Conflict, 410: base.NotFound, 412: base.Conflict, 422: base.InvalidRequest,
                 429: base.RateLimited, 500: base.Unavailable, 502: base.Unavailable, 503: base.Unavailable,
                 302: base.InvalidResponse}
        for status, error in cases.items():
            with self.subTest(status=status), self.assertRaises(error) as caught:
                self.read_with(status)
            self.assertNoSecret(str(caught.exception))

    def test_rate_limit_403s(self):
        with self.assertRaises(base.RateLimited) as caught:
            self.read_with(403, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(int(NOW) + 120)})
        self.assertEqual(caught.exception.retry_after_s, 120)
        with self.assertRaises(base.RateLimited) as caught:
            self.read_with(403, {'Retry-After': '60', 'X-RateLimit-Remaining': '4000'})
        self.assertEqual(caught.exception.retry_after_s, 60)
        with self.assertRaises(base.RateLimited) as caught:
            self.read_with(429, {'Retry-After': '17'})
        self.assertEqual(caught.exception.retry_after_s, 17)

    def test_connection_error_is_unavailable(self):
        self.http.expect('GET', API + '/repos/octo/notes/branches/main', raises='connection')
        with self.assertRaises(base.Unavailable):
            self.connector.read(BRANCH)

    def test_write_server_error_is_outcome_unknown(self):
        self.http.expect('POST', API + '/repos/octo/notes/issues/41/comments', status=502)
        with self.assertRaises(base.OutcomeUnknown):
            self.connector.write('github.issue.comment', ISSUE, {'body': 'hi'}, 'k-502')
        self.assertEqual(self.journal.records['k-502']['status'], 'outcome_unknown')

    def test_write_client_errors_are_definite(self):
        for status, error in ((404, base.NotFound), (403, base.Forbidden), (429, base.RateLimited),
                              (422, base.InvalidRequest), (410, base.NotFound)):
            self.http.expect('POST', API + '/repos/octo/notes/issues/41/comments', status=status, json=load('error'))
            with self.subTest(status=status), self.assertRaises(error):
                self.connector.write('github.issue.comment', ISSUE, {'body': 'hi'}, 'k-%d' % status)
            self.assertEqual(self.journal.records['k-%d' % status]['status'], 'failed')


class ChangesTests(GitHubTestCase):
    def test_baseline_then_batches(self):
        baseline = self.connector.changes()
        self.assertEqual((baseline['v'], baseline['items'], baseline['complete']), (1, [], True))
        self.assertEqual(self.http.calls, [])

        self.http.expect('GET', API + '/issues', json=load('changes_1'), headers=NEXT, match_params={
            'filter': 'all', 'state': 'all', 'sort': 'updated', 'direction': 'desc',
            'since': '2026-11-11T10:00:30Z', 'per_page': '2', 'page': '1'})
        first = self.connector.changes(baseline['cursor'], limit=2)
        self.assertEqual(first['items'], [
            {'ref': ISSUE, 'change': 'updated', 'at': '2026-11-11T10:05:00.000Z', 'title': 'Track reading list'},
            {'ref': 'github:pull:octo-lab/papers#3', 'change': 'created', 'at': '2026-11-11T10:03:00.000Z', 'title': 'Fresh idea'}])
        self.assertFalse(first['complete'])

        self.http.expect('GET', API + '/issues', json=load('changes_2'),
                         match_params={'since': '2026-11-11T10:00:30Z', 'page': '2'})
        second = self.connector.changes(first['cursor'], limit=2)
        self.assertEqual(second['items'], [
            {'ref': 'github:issue:octo/site#9', 'change': 'updated', 'at': '2026-11-11T10:01:00.000Z', 'title': 'Fix footer'}])
        self.assertTrue(second['complete'])

        # The next sweep starts at the newest update seen and skips what was already reported.
        self.http.expect('GET', API + '/issues', json=load('changes_1'),
                         match_params={'since': '2026-11-11T10:05:00Z', 'page': '1'})
        third = self.connector.changes(second['cursor'], limit=2)
        self.assertEqual((third['items'], third['complete']), ([], True))

    def test_bad_cursor(self):
        with self.assertRaises(base.InvalidRequest):
            self.connector.changes('not-a-cursor')
        self.http.expect('GET', API + '/user/repos', json=load('repos_page1'), headers=NEXT)
        browse_cursor = self.connector.browse(limit=2)['next_cursor']
        with self.assertRaises(base.InvalidRequest):
            self.connector.changes(browse_cursor)


if __name__ == '__main__':
    unittest.main()
