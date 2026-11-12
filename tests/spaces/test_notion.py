import json
import threading
import unittest
from pathlib import Path

from . import fakehttp
from spaces import base
import spaces
from spaces import notion

API = 'https://api.notion.com/v1'
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'notion'
TOKEN = 'ntn_canary000000000000000000000000000000000001'
NOW = base.parse_time('2026-11-11T10:00:30.000Z')
AUTH = {'Authorization': 'Bearer ' + TOKEN, 'Notion-Version': notion.NOTION_VERSION}


def U(n):
    return '11111111-2222-4333-8444-%012d' % n


def load(name):
    return json.loads((FIXTURES / (name + '.json')).read_text(encoding='utf-8'))


class NotionTestCase(unittest.TestCase):
    signed_in = True

    def setUp(self):
        self.http = fakehttp.FakeHttp()
        self.credentials = fakehttp.MemoryCredentials({'kind': 'token', 'access_token': TOKEN} if self.signed_in else None)
        self.journal = fakehttp.MemoryJournal()
        self.connector = notion.Connector(http=self.http, credentials=self.credentials, journal=self.journal,
                                          clock=lambda: NOW)

    def tearDown(self):
        self.http.assert_done()

    def assertNoSecret(self, value):
        self.assertNotIn('canary', json.dumps(value, default=str))


class RegistryTests(NotionTestCase):
    def test_registry_builds_the_notion_connector(self):
        made = spaces.connector('notion', self.http, self.credentials, self.journal)
        self.assertIsInstance(made, notion.Connector)
        self.assertEqual((made.app, made.kinds), ('notion', ('page', 'database', 'block')))


class StatusTests(NotionTestCase):
    def test_signed_in(self):
        self.http.expect('GET', API + '/users/me', json=load('users_me'), match_headers=AUTH)
        status = self.connector.status()
        self.assertEqual(status, {
            'v': 1, 'app': 'notion', 'state': 'signed_in',
            'account': {'label': 'Example Workspace', 'id': U(900)},
            'granted': ['content:read', 'content:write', 'comments:write'],
            'detail': '', 'checked_at': '2026-11-11T10:00:30.000Z'})

    def test_signed_out_makes_no_request(self):
        self.credentials.delete()
        status = self.connector.status()
        self.assertEqual((status['state'], status['account'], status['granted']), ('signed_out', None, []))

    def test_expired(self):
        self.http.expect('GET', API + '/users/me', status=401, json={'object': 'error', 'status': 401})
        status = self.connector.status()
        self.assertEqual(status['state'], 'expired')
        self.assertIn('Sign in', status['detail'])
        self.assertNoSecret(status)

    def test_unreachable_and_keychain_unavailable(self):
        self.http.expect('GET', API + '/users/me', raises='connection')
        self.assertEqual(self.connector.status()['state'], 'unavailable')

        class Broken:
            def get(self):
                raise base.CredentialStoreUnavailable('The Keychain did not answer. Try again.')
        connector = notion.Connector(http=self.http, credentials=Broken(), journal=self.journal, clock=lambda: NOW)
        status = connector.status()
        self.assertEqual(status['state'], 'unavailable')
        self.assertIn('Keychain', status['detail'])


class SignInTests(NotionTestCase):
    signed_in = False

    def test_token_entry_step(self):
        step = self.connector.begin_sign_in({})
        self.assertEqual(step['kind'], 'token_entry')
        self.assertEqual(set(step), {'v', 'app', 'kind', 'label', 'help_url', 'pattern'})
        self.assertTrue(step['help_url'].startswith('https://developers.notion.com/'))
        self.assertRegex(TOKEN, step['pattern'])

    def test_complete_validates_then_stores(self):
        self.http.expect('GET', API + '/users/me', json=load('users_me'), match_headers=AUTH)
        status = self.connector.complete_sign_in({'token': TOKEN}, threading.Event())
        self.assertEqual(status['state'], 'signed_in')
        self.assertEqual(status['checked_at'], '2026-11-11T10:00:30.000Z')
        self.assertEqual(self.credentials.get(), {'kind': 'token', 'access_token': TOKEN, 'account_id': U(900)})
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
        self.http.expect('GET', API + '/users/me', json=load('users_me'))
        with self.assertRaises(base.SignInCancelled):
            self.connector.complete_sign_in({'token': TOKEN}, CancelDuringCheck())
        self.assertIsNone(self.credentials.get())

    def test_rejected_and_malformed_tokens_store_nothing(self):
        self.http.expect('GET', API + '/users/me', status=401, json={'object': 'error'})
        with self.assertRaises(base.InvalidRequest) as caught:
            self.connector.complete_sign_in({'token': TOKEN}, None)
        self.assertNoSecret(str(caught.exception))
        for params in ({}, {'token': 'short'}, {'token': 'has spaces in it but long enough'}, {'token': TOKEN, 'x': 1}):
            with self.subTest(params=params), self.assertRaises(base.InvalidRequest):
                self.connector.complete_sign_in(params, None)
        self.assertIsNone(self.credentials.get())

    def test_reads_need_sign_in(self):
        with self.assertRaises(base.NotSignedIn):
            self.connector.browse()
        with self.assertRaises(base.NotSignedIn):
            self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'hi'}, 'k1')
        self.assertEqual(self.journal.records, {})


class SignOutTests(NotionTestCase):
    def test_sign_out_deletes_the_secret(self):
        status = self.connector.sign_out()
        self.assertEqual(status['state'], 'signed_out')
        self.assertIsNone(self.credentials.get())


class BrowseTests(NotionTestCase):
    def test_roots_over_two_pages(self):
        self.http.expect('POST', API + '/search', json=load('search_page1'), match_headers=AUTH,
                         match_json={'page_size': 2, 'sort': {'timestamp': 'last_edited_time', 'direction': 'descending'}})
        first = self.connector.browse(limit=2)
        self.assertEqual(first['v'], 1)
        self.assertEqual(first['items'][0], {
            'ref': 'notion:page:' + U(1), 'kind': 'page', 'title': 'Reading notes', 'parent': None,
            'url': load('page')['url'], 'updated_at': '2026-11-10T18:02:00.000Z', 'has_children': True, 'meta': {}})
        database = first['items'][1]
        self.assertEqual((database['ref'], database['kind'], database['title'], database['parent']),
                         ('notion:database:' + U(10), 'database', 'Papers', 'notion:page:' + U(2)))
        self.assertTrue(first['next_cursor'])
        self.http.expect('POST', API + '/search', json=load('search_page2'),
                         match_json={'page_size': 2, 'start_cursor': 'cursor-search-2'})
        second = self.connector.browse(cursor=first['next_cursor'], limit=2)
        self.assertEqual([item['title'] for item in second['items']], ['Projects', 'Week 45'])
        self.assertEqual(second['items'][1]['parent'], 'notion:page:' + U(1))
        self.assertIsNone(second['next_cursor'])

    def test_page_children_over_two_pages(self):
        self.http.expect('GET', API + '/blocks/%s/children' % U(1), json=load('page_children'),
                         match_params={'page_size': '50'})
        first = self.connector.browse('notion:page:' + U(1))
        self.assertEqual([(i['ref'], i['title']) for i in first['items']],
                         [('notion:page:' + U(32), 'Week 45'), ('notion:database:' + U(33), 'Papers')])
        self.assertEqual(first['items'][0]['parent'], 'notion:page:' + U(1))
        self.http.expect('GET', API + '/blocks/%s/children' % U(1), json=load('page_children_2'),
                         match_params={'start_cursor': 'cursor-children-2'})
        second = self.connector.browse('notion:page:' + U(1), cursor=first['next_cursor'])
        self.assertEqual([i['title'] for i in second['items']], ['Week 46'])
        self.assertIsNone(second['next_cursor'])

    def test_database_rows(self):
        self.http.expect('GET', API + '/databases/' + U(10), json=load('database'))
        self.http.expect('POST', API + '/data_sources/%s/query' % U(11), json=load('query_rows'),
                         match_json={'page_size': 50})
        page = self.connector.browse('notion:database:' + U(10))
        self.assertEqual(page['items'][0]['meta'], {'Status': 'Draft', 'Pages': 15, 'Tags': 'ml'})
        self.assertEqual(page['items'][0]['parent'], 'notion:database:' + U(10))
        self.assertIsNone(page['next_cursor'])

    def test_cursor_must_match_the_call(self):
        self.http.expect('POST', API + '/search', json=load('search_page1'))
        cursor = self.connector.browse(limit=2)['next_cursor']
        for call in (lambda: self.connector.browse('notion:page:' + U(1), cursor=cursor),
                     lambda: self.connector.search('x', cursor=cursor),
                     lambda: self.connector.browse(cursor='garbage'),
                     lambda: self.connector.browse(limit=0),
                     lambda: self.connector.browse(limit=101),
                     lambda: self.connector.browse('notion:block:' + U(1)),
                     lambda: self.connector.browse('github:repo:o/n'),
                     lambda: self.connector.browse('notion:page:../users')):
            with self.assertRaises(base.InvalidRequest):
                call()


class SearchTests(NotionTestCase):
    def test_search_with_kind_filter(self):
        self.http.expect('POST', API + '/search', json=load('search_results'),
                         match_json={'query': 'attention', 'page_size': 25,
                                     'filter': {'property': 'object', 'value': 'data_source'}})
        page = self.connector.search('attention', kinds=['database'])
        self.assertEqual([i['kind'] for i in page['items']], ['database'])
        self.http.expect('POST', API + '/search', json=load('search_results'), match_json={'query': 'attention'})
        page = self.connector.search('attention')
        self.assertEqual([i['ref'] for i in page['items']], ['notion:database:' + U(10), 'notion:page:' + U(21)])
        self.assertNotIn('filter', self.http.calls[-1]['json'])

    def test_block_only_search_and_bad_queries(self):
        self.assertEqual(self.connector.search('x', kinds=['block']), {'v': 1, 'items': [], 'next_cursor': None})
        for args in (('',), ('x' * 501,), ('x', ['repo']), ('x', [])):
            with self.subTest(args=args), self.assertRaises(base.InvalidRequest):
                self.connector.search(*args)


class ReadTests(NotionTestCase):
    def expect_page(self):
        self.http.expect('GET', API + '/pages/' + U(1), json=load('page'))

    def test_read_page_as_markdown(self):
        self.expect_page()
        self.http.expect('GET', API + '/blocks/%s/children' % U(1), json=load('blocks_1'), match_params={'page_size': '100'})
        self.http.expect('GET', API + '/blocks/%s/children' % U(1), json=load('blocks_2'),
                         match_params={'start_cursor': 'cursor-blocks-2'})
        content = self.connector.read('notion:page:' + U(1))
        self.assertEqual(content['text'],
                         '# Reading notes\n\n# Summary\n\nPlain **bold** and [a link](https://example.org/a)\n\n'
                         '- first point\n- [x] check figures\n\n```python\nprint(\'hi\')\n```\n\n---\n\n'
                         '[Unsupported Notion block: synced_block]\n\n')
        self.assertEqual((content['format'], content['truncated'], content['next_cursor']), ('markdown', False, None))
        self.assertEqual(content['version'], '2026-11-10T18:02:00.000Z')
        self.assertEqual((content['ref'], content['title'], content['url']), ('notion:page:' + U(1), 'Reading notes', load('page')['url']))
        self.assertIsNone(content['parent'])   # a workspace-level page

    def test_read_with_truncation_and_continuation(self):
        self.connector.max_read_chars = 60
        self.expect_page()
        self.http.expect('GET', API + '/blocks/%s/children' % U(1), json=load('blocks_1'))
        first = self.connector.read('notion:page:' + U(1))
        self.assertTrue(first['truncated'])
        self.assertEqual(first['text'], '# Reading notes\n\n# Summary\n\n')
        self.expect_page()
        self.http.expect('GET', API + '/blocks/%s/children' % U(1), json=load('blocks_1'), match_params={'page_size': '100'})
        second = self.connector.read('notion:page:' + U(1), cursor=first['next_cursor'])
        self.assertEqual(second['text'], 'Plain **bold** and [a link](https://example.org/a)\n\n')
        self.assertTrue(second['truncated'])
        self.expect_page()
        self.http.expect('GET', API + '/blocks/%s/children' % U(1), json=load('blocks_1'))
        self.http.expect('GET', API + '/blocks/%s/children' % U(1), json=load('blocks_2'),
                         match_params={'start_cursor': 'cursor-blocks-2'})
        third = self.connector.read('notion:page:' + U(1), cursor=second['next_cursor'])
        self.assertEqual(third['text'], '- first point\n- [x] check figures\n')
        self.assertTrue(third['truncated'])
        with self.assertRaises(base.InvalidRequest):
            self.connector.read('notion:page:' + U(2), cursor=second['next_cursor'])

    def test_parts_join_to_the_full_text(self):
        class RoutedHttp:
            """Answers by URL, so any number of continuation reads can be made."""
            def request(self, method, url, *, params=None, **kwargs):
                if url == API + '/pages/' + U(1):
                    name = 'page'
                else:
                    name = 'blocks_2' if (params or {}).get('start_cursor') == 'cursor-blocks-2' else 'blocks_1'
                return base.Response(200, {}, json.dumps(load(name)).encode())
        connector = notion.Connector(http=RoutedHttp(), credentials=self.credentials, journal=self.journal)

        def read_all(max_chars):
            connector.max_read_chars = max_chars
            parts, cursor = [], None
            for _ in range(200):
                content = connector.read('notion:page:' + U(1), cursor=cursor)
                self.assertLessEqual(len(content['text']), max_chars)
                parts.append(content['text'])
                cursor = content['next_cursor']
                if cursor is None:
                    return ''.join(parts)
            self.fail('read never finished')
        full = read_all(200000)
        for size in (20, 33, 60):
            with self.subTest(size=size):
                self.assertEqual(read_all(size), full)

    def test_read_database_schema_as_json(self):
        self.http.expect('GET', API + '/databases/' + U(10), json=load('database'))
        self.http.expect('GET', API + '/data_sources/' + U(11), json=load('data_source'))
        content = self.connector.read('notion:database:' + U(10))
        self.assertEqual(content['format'], 'json')
        self.assertEqual(json.loads(content['text']), {
            'title': 'Papers', 'data_sources': [{'id': U(11), 'name': 'Papers'}],
            'properties': {'Name': {'type': 'title'}, 'Pages': {'type': 'number'},
                           'Status': {'type': 'status', 'options': ['Draft', 'Done']},
                           'Tags': {'type': 'multi_select', 'options': ['ml']}}})
        self.assertEqual(content['version'], '2026-11-09T12:00:00.000Z')
        self.assertEqual(content['parent'], 'notion:page:' + U(2))

    def test_read_database_row_has_property_meta(self):
        self.http.expect('GET', API + '/pages/' + U(21), json=load('row_page'))
        self.http.expect('GET', API + '/blocks/%s/children' % U(21), json={'object': 'list', 'results': [], 'next_cursor': None, 'has_more': False})
        content = self.connector.read('notion:page:' + U(21))
        self.assertEqual(content['meta'], {'Status': 'Draft', 'Pages': 15, 'Tags': 'ml'})
        self.assertEqual(content['parent'], 'notion:database:' + U(10))
        self.assertEqual(content['text'], '# Attention is all you need\n\n')

    def test_read_block(self):
        self.http.expect('GET', API + '/blocks/' + U(41), json=load('block'))
        content = self.connector.read('notion:block:' + U(41))
        self.assertEqual(content['text'], '# Summary\n\n')
        self.assertEqual(content['parent'], 'notion:page:' + U(1))

    def test_remote_shape_is_validated(self):
        broken = load('page')
        broken['last_edited_time'] = 7
        self.http.expect('GET', API + '/pages/' + U(1), json=broken)
        with self.assertRaises(base.InvalidResponse):
            self.connector.read('notion:page:' + U(1))
        self.http.expect('GET', API + '/pages/' + U(1), body=b'<html>')
        with self.assertRaises(base.InvalidResponse):
            self.connector.read('notion:page:' + U(1))


class ActionTests(NotionTestCase):
    def test_action_specs_and_tools(self):
        specs = {spec['name']: spec for spec in self.connector.actions()}
        self.assertEqual({name: spec['effect'] for name, spec in specs.items()}, {
            'notion.database.create_page': 'create', 'notion.page.append': 'update',
            'notion.page.update_properties': 'update', 'notion.page.comment': 'create',
            'notion.page.archive': 'destructive'})
        self.assertTrue(specs['notion.page.update_properties']['requires_version'])
        for spec in specs.values():
            self.assertFalse(spec['params_schema']['additionalProperties'])
            self.assertEqual(spec['target_kind'], spec['name'].split('.')[1])
        names = [tool['name'] for tool in base.tools(self.connector)]
        self.assertEqual(names, ['notion_search', 'notion_browse', 'notion_read', 'notion_database_create_page',
                                 'notion_page_append', 'notion_page_update_properties', 'notion_page_comment',
                                 'notion_page_archive'])

    def test_create_page_in_database(self):
        self.http.expect('GET', API + '/databases/' + U(10), json=load('database'))
        self.http.expect('POST', API + '/pages', json=load('created_page'), match_json={
            'parent': {'type': 'data_source_id', 'data_source_id': U(11)},
            'properties': {'title': {'title': [{'type': 'text', 'text': {'content': 'New paper'}}]}},
            'children': [{'object': 'block', 'type': 'paragraph',
                          'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': 'Abstract here.'}}]}}]})
        result = self.connector.write('notion.database.create_page', 'notion:database:' + U(10),
                                      {'title': 'New paper', 'markdown': 'Abstract here.'}, 'ui-1')
        self.assertEqual(result, {
            'v': 1, 'ok': True, 'action': 'notion.database.create_page', 'ref': 'notion:database:' + U(10),
            'result_ref': 'notion:page:' + U(60), 'url': load('created_page')['url'],
            'version': '2026-11-11T09:31:00.000Z', 'replayed': False, 'summary': 'Created page "New paper".'})

    def test_append_markdown(self):
        self.http.expect('PATCH', API + '/blocks/%s/children' % U(1), json=load('append_result'), match_json={'children': [
            {'object': 'block', 'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': 'Notes'}}]}},
            {'object': 'block', 'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': 'one'}}]}},
            {'object': 'block', 'type': 'to_do', 'to_do': {'rich_text': [{'type': 'text', 'text': {'content': 'two'}}], 'checked': True}},
            {'object': 'block', 'type': 'numbered_list_item', 'numbered_list_item': {'rich_text': [{'type': 'text', 'text': {'content': 'three'}}]}},
            {'object': 'block', 'type': 'quote', 'quote': {'rich_text': [{'type': 'text', 'text': {'content': 'cited'}}]}},
            {'object': 'block', 'type': 'divider', 'divider': {}},
            {'object': 'block', 'type': 'code', 'code': {'rich_text': [{'type': 'text', 'text': {'content': 'x = 1\ny = 2'}}], 'language': 'python'}},
            {'object': 'block', 'type': 'paragraph', 'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': 'Line a\nline b'}}]}},
        ]})
        markdown = '## Notes\n- one\n- [x] two\n1. three\n> cited\n---\n```python\nx = 1\ny = 2\n```\n\nLine a\nline b\n'
        result = self.connector.write('notion.page.append', 'notion:page:' + U(1), {'markdown': markdown}, 'ui-2')
        self.assertEqual((result['result_ref'], result['summary']), ('notion:page:' + U(1), 'Appended 8 blocks to the page.'))

    def test_append_splits_long_text_and_limits_blocks(self):
        self.http.expect('PATCH', API + '/blocks/%s/children' % U(1), json=load('append_result'))
        self.connector.write('notion.page.append', 'notion:page:' + U(1), {'markdown': 'x' * 4500}, 'ui-3')
        rich = self.http.calls[-1]['json']['children'][0]['paragraph']['rich_text']
        self.assertEqual([len(r['text']['content']) for r in rich], [2000, 2000, 500])
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('notion.page.append', 'notion:page:' + U(1), {'markdown': '\n\n'.join(['p'] * 101)}, 'ui-4')
        self.assertNotIn('ui-4', self.journal.records)

    def test_update_properties_with_version(self):
        self.http.expect('GET', API + '/pages/' + U(21), json=load('row_page'))
        self.http.expect('PATCH', API + '/pages/' + U(21), json=load('updated_row'), match_json={'properties': {
            'Status': {'status': {'name': 'Done'}}, 'Pages': {'number': 16}, 'Tags': {'multi_select': [{'name': 'ml'}, {'name': 'nlp'}]},
            'Name': {'title': [{'type': 'text', 'text': {'content': 'Renamed'}}]}}})
        result = self.connector.write('notion.page.update_properties', 'notion:page:' + U(21), {
            'properties': {'Status': 'Done', 'Pages': 16, 'Tags': ['ml', 'nlp'], 'Name': 'Renamed'},
            'base_version': '2026-11-10T09:00:00.000Z'}, 'ui-5')
        self.assertEqual(result['version'], '2026-11-11T09:32:00.000Z')
        self.assertEqual(result['summary'], 'Updated 4 properties.')

    def test_update_properties_conflict(self):
        self.http.expect('GET', API + '/pages/' + U(21), json=load('row_page'))
        with self.assertRaises(base.Conflict):
            self.connector.write('notion.page.update_properties', 'notion:page:' + U(21), {
                'properties': {'Status': 'Done'}, 'base_version': '2026-11-01T00:00:00.000Z'}, 'ui-6')
        self.assertEqual(self.journal.records['ui-6']['status'], 'failed')

    def test_update_properties_rejects_unknown_or_unsupported(self):
        for properties in ({'Missing': 'x'}, {'Pages': 'not a number'}, {'Status': 5}):
            self.http.expect('GET', API + '/pages/' + U(21), json=load('row_page'))
            with self.subTest(properties=properties), self.assertRaises(base.InvalidRequest):
                self.connector.write('notion.page.update_properties', 'notion:page:' + U(21), {
                    'properties': properties, 'base_version': '2026-11-10T09:00:00.000Z'}, 'k-%d' % len(self.http.calls))
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('notion.page.update_properties', 'notion:page:' + U(21), {'properties': {'a': 1}}, 'k-x')

    def test_comment(self):
        self.http.expect('POST', API + '/comments', json=load('comment'), match_json={
            'parent': {'page_id': U(1)}, 'rich_text': [{'type': 'text', 'text': {'content': 'Looks good'}}]})
        result = self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'Looks good'}, 'ui-7')
        self.assertEqual((result['result_ref'], result['summary']), ('notion:page:' + U(1), 'Added a comment.'))

    def test_archive_moves_to_trash(self):
        self.http.expect('PATCH', API + '/pages/' + U(1), json=load('trashed_page'), match_json={'in_trash': True})
        result = self.connector.write('notion.page.archive', 'notion:page:' + U(1), {}, 'ui-8')
        self.assertEqual(result['summary'], 'Moved "Reading notes" to the Notion trash.')

    def test_journal_replay_makes_no_second_request(self):
        self.http.expect('POST', API + '/comments', json=load('comment'))
        first = self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'Looks good'}, 'ui-9')
        again = self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'Looks good'}, 'ui-9')
        self.assertEqual(dict(first, replayed=True), again)
        self.assertEqual(len(self.http.calls), 1)
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'Other'}, 'ui-9')

    def test_timeout_after_send_is_outcome_unknown_and_never_resent(self):
        self.http.expect('POST', API + '/comments', raises='timeout_after_send')
        with self.assertRaises(base.OutcomeUnknown):
            self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'hi'}, 'ui-10')
        with self.assertRaises(base.OutcomeUnknown):
            self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'hi'}, 'ui-10')
        self.assertEqual(self.journal.records['ui-10']['status'], 'outcome_unknown')

    def test_read_step_timeout_before_a_write_is_not_unknown(self):
        self.http.expect('GET', API + '/databases/' + U(10), raises='timeout_after_send')
        with self.assertRaises(base.Unavailable):
            self.connector.write('notion.database.create_page', 'notion:database:' + U(10), {'title': 'x'}, 'ui-11')
        self.assertEqual(self.journal.records['ui-11']['status'], 'failed')

    def test_write_validation(self):
        bad = [('notion.page.delete', 'notion:page:' + U(1), {}),
               ('notion.page.comment', 'notion:database:' + U(1), {'text': 'x'}),
               ('notion.page.comment', 'notion:page:' + U(1), {'text': ''}),
               ('notion.page.comment', 'notion:page:' + U(1), {'text': 'x' * 2001}),
               ('notion.page.comment', 'notion:page:' + U(1), {'text': 'x', 'extra': 1}),
               ('notion.page.archive', 'notion:page:' + U(1), {'why': 'x'}),
               ('notion.database.create_page', 'notion:database:' + U(10), {'markdown': 'x'})]
        for action, ref, params in bad:
            with self.subTest(action=action, params=params), self.assertRaises(base.InvalidRequest):
                self.connector.write(action, ref, params, 'k1')
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'x'}, 'bad key')
        self.assertEqual(self.journal.records, {})


class ErrorMappingTests(NotionTestCase):
    def read_with(self, status, headers=None):
        self.http.expect('GET', API + '/pages/' + U(99), status=status, json=load('error_404'), headers=headers)
        return self.connector.read('notion:page:' + U(99))

    def test_read_status_mapping(self):
        cases = {400: base.InvalidRequest, 401: base.AuthExpired, 403: base.Forbidden, 404: base.NotFound,
                 409: base.Conflict, 412: base.Conflict, 422: base.InvalidRequest, 429: base.RateLimited,
                 500: base.Unavailable, 502: base.Unavailable, 503: base.Unavailable, 529: base.RateLimited,
                 302: base.InvalidResponse}
        for status, error in cases.items():
            with self.subTest(status=status), self.assertRaises(error) as caught:
                self.read_with(status)
            message = str(caught.exception)
            self.assertNotIn('Could not find page', message)
            self.assertNoSecret(message)

    def test_retry_after(self):
        with self.assertRaises(base.RateLimited) as caught:
            self.read_with(429, {'Retry-After': '17'})
        self.assertEqual(caught.exception.retry_after_s, 17)

    def test_connection_error_is_unavailable(self):
        self.http.expect('GET', API + '/pages/' + U(1), raises='connection')
        with self.assertRaises(base.Unavailable):
            self.connector.read('notion:page:' + U(1))

    def test_write_server_error_is_outcome_unknown(self):
        self.http.expect('POST', API + '/comments', status=502)
        with self.assertRaises(base.OutcomeUnknown):
            self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'hi'}, 'k-502')

    def test_write_client_errors_are_definite(self):
        for status, error in ((404, base.NotFound), (403, base.Forbidden), (429, base.RateLimited), (400, base.InvalidRequest)):
            self.http.expect('POST', API + '/comments', status=status, json=load('error_404'))
            with self.subTest(status=status), self.assertRaises(error):
                self.connector.write('notion.page.comment', 'notion:page:' + U(1), {'text': 'hi'}, 'k-%d' % status)
            self.assertEqual(self.journal.records['k-%d' % status]['status'], 'failed')


class ChangesTests(NotionTestCase):
    def test_baseline_then_batches(self):
        baseline = self.connector.changes()
        self.assertEqual((baseline['v'], baseline['items'], baseline['complete']), (1, [], True))
        self.assertEqual(self.http.calls, [])

        self.http.expect('POST', API + '/search', json=load('changes_1'), match_json={
            'page_size': 2, 'sort': {'timestamp': 'last_edited_time', 'direction': 'descending'}})
        first = self.connector.changes(baseline['cursor'], limit=2)
        self.assertEqual(first['items'], [
            {'ref': 'notion:page:' + U(1), 'change': 'updated', 'at': '2026-11-11T10:05:00.000Z', 'title': 'Reading notes'},
            {'ref': 'notion:page:' + U(80), 'change': 'created', 'at': '2026-11-11T10:03:00.000Z', 'title': 'Fresh idea'}])
        self.assertFalse(first['complete'])

        self.http.expect('POST', API + '/search', json=load('changes_2'), match_json={'start_cursor': 'cursor-changes-2'})
        second = self.connector.changes(first['cursor'], limit=2)
        self.assertEqual([i['ref'] for i in second['items']], ['notion:page:' + U(2)])
        self.assertTrue(second['complete'])

        # The next sweep starts at the newest edit seen and skips what was already reported.
        self.http.expect('POST', API + '/search', json=load('changes_1'))
        third = self.connector.changes(second['cursor'], limit=2)
        self.assertEqual((third['items'], third['complete']), ([], True))

    def test_bad_cursor(self):
        with self.assertRaises(base.InvalidRequest):
            self.connector.changes('not-a-cursor')
        self.http.expect('POST', API + '/search', json=load('search_page1'))
        browse_cursor = self.connector.browse(limit=2)['next_cursor']
        with self.assertRaises(base.InvalidRequest):
            self.connector.changes(browse_cursor)


if __name__ == '__main__':
    unittest.main()
