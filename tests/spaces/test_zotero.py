import hashlib
import json
import threading
import unittest
from pathlib import Path

from . import fakehttp
from spaces import base
import spaces
from spaces import zotero

LOCAL = 'http://127.0.0.1:23119/api'
WEB = 'https://api.zotero.org'
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'zotero'
KEY = 'canary000000000000000001'   # an invented web API key; must never leak
NOW = base.parse_time('2026-11-11T10:00:30.000Z')
SECRET = {'kind': 'zotero', 'write_key': KEY, 'user_id': '123456', 'username': 'example-user'}
WEB_AUTH = {'Zotero-API-Key': KEY, 'Zotero-API-Version': '3'}
ITEM = 'zotero:item:users/0/items/ITEM2222'
BOOK = 'zotero:item:users/0/items/ITEM3333'
COLLECTION = 'zotero:collection:users/0/collections/CL222222'
LIBRARY = 'zotero:library:users/0'


def load(name):
    return json.loads((FIXTURES / (name + '.json')).read_text(encoding='utf-8'))


def total(n):
    return {'Total-Results': str(n)}


def write_token(key):
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]


class ZoteroTestCase(unittest.TestCase):
    secret = SECRET

    def setUp(self):
        self.http = fakehttp.FakeHttp()
        self.credentials = fakehttp.MemoryCredentials(self.secret)
        self.journal = fakehttp.MemoryJournal()
        self.connector = zotero.Connector(http=self.http, credentials=self.credentials, journal=self.journal,
                                          clock=lambda: NOW)

    def tearDown(self):
        self.http.assert_done()

    def assertNoSecret(self, value):
        self.assertNotIn('canary', json.dumps(value, default=str))

    def expect_local(self, path, **kwargs):
        self.http.expect('GET', LOCAL + path, **kwargs)


class RegistryTests(ZoteroTestCase):
    def test_registry_builds_the_zotero_connector(self):
        made = spaces.connector('zotero', self.http, self.credentials, self.journal)
        self.assertIsInstance(made, zotero.Connector)
        self.assertEqual((made.app, made.kinds), ('zotero', ('library', 'collection', 'item', 'attachment')))


class StatusTests(ZoteroTestCase):
    def test_signed_in_with_write_key(self):
        self.expect_local('/users/0/items/top', json=[load('item')], headers=total(5),
                          match_params={'limit': '1'}, match_headers={'Zotero-API-Version': '3'})
        status = self.connector.status()
        self.assertEqual(status, {
            'v': 1, 'app': 'zotero', 'state': 'signed_in', 'account': {'label': 'example-user', 'id': '123456'},
            'granted': ['library:read', 'library:write'], 'detail': '', 'checked_at': '2026-11-11T10:00:30.000Z'})
        self.assertNotIn('Zotero-API-Key', self.http.calls[0]['headers'])   # local reads carry no key
        self.assertNoSecret(status)

    def test_signed_in_read_only(self):
        self.credentials.set({'kind': 'zotero'})
        self.expect_local('/users/0/items/top', json=[])
        status = self.connector.status()
        self.assertEqual((status['state'], status['account'], status['granted']),
                         ('signed_in', {'label': 'My Library', 'id': 'local'}, ['library:read']))

    def test_signed_out_makes_no_request(self):
        self.credentials.delete()
        status = self.connector.status()
        self.assertEqual((status['state'], status['account'], status['granted']), ('signed_out', None, []))

    def test_local_api_off_is_unavailable_with_instructions(self):
        self.expect_local('/users/0/items/top', status=403, body=b'Local API is not enabled')
        status = self.connector.status()
        self.assertEqual(status['state'], 'unavailable')
        self.assertIn('Allow other applications', status['detail'])
        self.assertEqual(status['granted'], [])

    def test_zotero_closed_is_unavailable(self):
        self.expect_local('/users/0/items/top', raises='connection')
        status = self.connector.status()
        self.assertEqual(status['state'], 'unavailable')
        self.assertIn('Open Zotero', status['detail'])

    def test_keychain_unavailable(self):
        class Broken:
            def get(self):
                raise base.CredentialStoreUnavailable('The Keychain did not answer. Try again.')
        connector = zotero.Connector(http=self.http, credentials=Broken(), journal=self.journal, clock=lambda: NOW)
        status = connector.status()
        self.assertEqual(status['state'], 'unavailable')
        self.assertIn('Keychain', status['detail'])

    def test_odd_local_reply_is_unavailable(self):
        self.expect_local('/users/0/items/top', json={'not': 'a list'})
        self.assertEqual(self.connector.status()['state'], 'unavailable')


class SignInTests(ZoteroTestCase):
    secret = None

    def test_local_check_step(self):
        step = self.connector.begin_sign_in({})
        self.assertEqual(set(step), {'v', 'app', 'kind', 'detail'})
        self.assertEqual((step['app'], step['kind']), ('zotero', 'local_check'))
        self.assertIn('Allow other applications', step['detail'])
        self.assertEqual(self.http.calls, [])

    def test_complete_without_write_key(self):
        self.expect_local('/users/0/items/top', json=[])
        status = self.connector.complete_sign_in({}, threading.Event())
        self.assertEqual((status['state'], status['granted']), ('signed_in', ['library:read']))
        self.assertEqual(self.credentials.get(), {'kind': 'zotero'})

    def test_complete_with_write_key_verifies_it_then_stores(self):
        self.expect_local('/users/0/items/top', json=[])
        self.http.expect('GET', WEB + '/keys/current', json=load('key_current'), match_headers=WEB_AUTH)
        status = self.connector.complete_sign_in({'write_key': KEY}, threading.Event())
        self.assertEqual((status['state'], status['account'], status['granted']),
                         ('signed_in', {'label': 'example-user', 'id': '123456'}, ['library:read', 'library:write']))
        self.assertEqual(self.credentials.get(), SECRET)
        self.assertNoSecret(status)

    def test_reconnect_without_key_keeps_the_saved_key(self):
        self.credentials.set(SECRET)
        self.expect_local('/users/0/items/top', json=[])
        status = self.connector.complete_sign_in({'write_key': None}, None)
        self.assertEqual(status['granted'], ['library:read', 'library:write'])
        self.assertEqual(self.credentials.get(), SECRET)

    def test_key_without_write_access_is_refused(self):
        reply = load('key_current')
        reply['access']['user']['write'] = False
        self.expect_local('/users/0/items/top', json=[])
        self.http.expect('GET', WEB + '/keys/current', json=reply)
        with self.assertRaises(base.InvalidRequest) as caught:
            self.connector.complete_sign_in({'write_key': KEY}, None)
        self.assertIn('write access', str(caught.exception))
        self.assertIsNone(self.credentials.get())

    def test_rejected_and_malformed_keys_store_nothing(self):
        for status in (403, 404):
            self.expect_local('/users/0/items/top', json=[])
            self.http.expect('GET', WEB + '/keys/current', status=status, body=b'Invalid key')
            with self.subTest(status=status), self.assertRaises(base.InvalidRequest) as caught:
                self.connector.complete_sign_in({'write_key': KEY}, None)
            self.assertNoSecret(str(caught.exception))
        for params in ({'write_key': 'short'}, {'write_key': KEY + '!'}, {'token': KEY}, {'write_key': KEY, 'x': 1}, []):
            with self.subTest(params=params), self.assertRaises(base.InvalidRequest):
                self.connector.complete_sign_in(params, None)
        self.assertIsNone(self.credentials.get())

    def test_zotero_closed_during_sign_in(self):
        self.expect_local('/users/0/items/top', raises='connection')
        with self.assertRaises(base.Unavailable) as caught:
            self.connector.complete_sign_in({}, None)
        self.assertIn('Open Zotero', str(caught.exception))
        self.expect_local('/users/0/items/top', status=403)
        with self.assertRaises(base.Unavailable) as caught:
            self.connector.complete_sign_in({}, None)
        self.assertIn('Allow other applications', str(caught.exception))
        self.assertIsNone(self.credentials.get())

    def test_cancelled_before_and_after_the_check(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(base.SignInCancelled):
            self.connector.complete_sign_in({}, cancel)

        class CancelDuringCheck:
            calls = 0

            def is_set(self):
                self.calls += 1
                return self.calls > 1
        self.expect_local('/users/0/items/top', json=[])
        self.http.expect('GET', WEB + '/keys/current', json=load('key_current'))
        with self.assertRaises(base.SignInCancelled):
            self.connector.complete_sign_in({'write_key': KEY}, CancelDuringCheck())
        self.assertIsNone(self.credentials.get())

    def test_reads_need_sign_in(self):
        with self.assertRaises(base.NotSignedIn):
            self.connector.browse()
        with self.assertRaises(base.NotSignedIn):
            self.connector.read(ITEM)
        with self.assertRaises(base.NotSignedIn):
            self.connector.write('zotero.item.add_tags', ITEM, {'tags': ['x']}, 'k1')
        self.assertEqual(self.journal.records, {})


class SignOutTests(ZoteroTestCase):
    def test_sign_out_deletes_the_secret(self):
        status = self.connector.sign_out()
        self.assertEqual(status['state'], 'signed_out')
        self.assertIsNone(self.credentials.get())


class BrowseTests(ZoteroTestCase):
    def test_roots_over_two_pages(self):
        groups = load('groups')
        self.expect_local('/users/0/groups', json=groups[:1], headers=total(2), match_params={'start': '0', 'limit': '1'})
        first = self.connector.browse(limit=2)
        self.assertEqual(first['items'], [
            {'ref': LIBRARY, 'kind': 'library', 'title': 'My Library', 'parent': None, 'url': None,
             'updated_at': None, 'has_children': True, 'meta': {'type': 'user'}},
            {'ref': 'zotero:library:groups/456', 'kind': 'library', 'title': 'Lab Reading Group', 'parent': None,
             'url': None, 'updated_at': '2026-11-08T07:00:00.000Z', 'has_children': True,
             'meta': {'type': 'group', 'items': 40}}])
        self.assertTrue(first['next_cursor'])
        self.expect_local('/users/0/groups', json=groups[1:], headers=total(2), match_params={'start': '1', 'limit': '2'})
        second = self.connector.browse(cursor=first['next_cursor'], limit=2)
        self.assertEqual([i['title'] for i in second['items']], ['Thesis'])
        self.assertIsNone(second['next_cursor'])

    def test_library_lists_collections_then_items_across_pages(self):
        self.expect_local('/users/0/collections/top', json=[load('collection')], headers=total(1),
                          match_params={'start': '0', 'limit': '2'})
        self.expect_local('/users/0/items/top', json=[load('item')], headers=total(2),
                          match_params={'start': '0', 'limit': '1', 'sort': 'dateModified', 'direction': 'desc'})
        first = self.connector.browse(LIBRARY, limit=2)
        self.assertEqual(first['items'][0], {
            'ref': COLLECTION, 'kind': 'collection', 'title': 'Reading', 'parent': LIBRARY,
            'url': 'https://www.zotero.org/example-user/collections/CL222222', 'updated_at': None,
            'has_children': True, 'meta': {'items': 3, 'subcollections': 1}})
        self.assertEqual(first['items'][1], {
            'ref': ITEM, 'kind': 'item', 'title': 'Attention Is All You Need', 'parent': LIBRARY,
            'url': 'https://www.zotero.org/example-user/items/ITEM2222', 'updated_at': '2026-11-10T18:02:11.000Z',
            'has_children': True, 'meta': {'type': 'journalArticle', 'creators': 'Vaswani et al.',
                                           'date': '2017-06-12', 'children': 2}})
        self.expect_local('/users/0/items/top', json=[load('book')], headers=total(2), match_params={'start': '1', 'limit': '2'})
        second = self.connector.browse(LIBRARY, cursor=first['next_cursor'], limit=2)
        self.assertEqual([(i['ref'], i['has_children']) for i in second['items']], [(BOOK, False)])
        self.assertIsNone(second['next_cursor'])

    def test_collection_children(self):
        self.expect_local('/users/0/collections/CL222222/collections', json=[load('subcollection')], headers=total(1))
        self.expect_local('/users/0/collections/CL222222/items/top', json=[load('item')], headers=total(1))
        page = self.connector.browse(COLLECTION)
        self.assertEqual([(i['ref'], i['parent']) for i in page['items']], [
            ('zotero:collection:users/0/collections/CL333333', COLLECTION), (ITEM, COLLECTION)])
        self.assertIsNone(page['next_cursor'])

    def test_item_children_are_notes_and_attachments(self):
        self.expect_local('/users/0/items/ITEM2222/children', json=[load('note'), load('attachment')], headers=total(2))
        page = self.connector.browse(ITEM)
        self.assertEqual([(i['ref'], i['kind'], i['title'], i['parent']) for i in page['items']], [
            ('zotero:item:users/0/items/NTE22222', 'item', 'Reading notes', ITEM),
            ('zotero:attachment:users/0/items/ATT22222', 'attachment', 'Full Text PDF', ITEM)])

    def test_group_library_and_attachment(self):
        self.expect_local('/groups/456/collections/top', json=[], headers=total(0))
        self.expect_local('/groups/456/items/top', json=[], headers=total(0))
        self.assertEqual(self.connector.browse('zotero:library:groups/456'), {'v': 1, 'items': [], 'next_cursor': None})
        self.assertEqual(self.connector.browse('zotero:attachment:users/0/items/ATT22222')['items'], [])

    def test_missing_total_header_pages_by_count(self):
        self.expect_local('/users/0/items/ITEM2222/children', json=[load('note')], match_params={'limit': '1'})
        page = self.connector.browse(ITEM, limit=1)
        self.assertTrue(page['next_cursor'])

    def test_bad_refs_cursors_and_limits(self):
        self.expect_local('/users/0/groups', json=load('groups')[:1], headers=total(2))
        cursor = self.connector.browse(limit=2)['next_cursor']
        for call in (lambda: self.connector.browse(LIBRARY, cursor=cursor),
                     lambda: self.connector.search('x', cursor=cursor),
                     lambda: self.connector.browse(cursor='garbage'),
                     lambda: self.connector.browse(limit=0),
                     lambda: self.connector.browse(limit=101),
                     lambda: self.connector.browse('zotero:library:users/123'),
                     lambda: self.connector.browse('zotero:library:groups/0'),
                     lambda: self.connector.browse('zotero:item:users/0/items/ITEM000O'),
                     lambda: self.connector.browse('zotero:item:users/0/collections/CL222222'),
                     lambda: self.connector.browse('zotero:collection:users/0/items/ITEM2222'),
                     lambda: self.connector.browse('zotero:item:users/0/items/../../keys'),
                     lambda: self.connector.browse('zotero:note:users/0/items/ITEM2222'),
                     lambda: self.connector.browse('notion:page:abc')):
            with self.assertRaises(base.InvalidRequest):
                call()

    def test_remote_shape_is_validated(self):
        self.expect_local('/users/0/collections/top', json=[load('collection')], headers=total(1))
        self.expect_local('/users/0/items/top', json=[load('item')], headers=total(2))
        cursor = self.connector.browse(LIBRARY, limit=2)['next_cursor']   # now in the items phase
        broken = load('item')
        broken['key'] = '../x'
        self.expect_local('/users/0/items/top', json=[broken], headers=total(2), match_params={'start': '1'})
        with self.assertRaises(base.InvalidResponse):
            self.connector.browse(LIBRARY, cursor=cursor, limit=2)
        self.expect_local('/users/0/collections/top', body=b'<html>')
        with self.assertRaises(base.InvalidResponse):
            self.connector.browse(LIBRARY)


class SearchTests(ZoteroTestCase):
    def test_search_over_two_pages_and_kind_filter(self):
        self.expect_local('/users/0/items', json=[load('item')], headers=total(2), match_params={
            'q': 'attention', 'qmode': 'titleCreatorYear', 'itemType': '-attachment', 'start': '0', 'limit': '1'})
        first = self.connector.search('attention', kinds=['item'], limit=1)
        self.assertEqual([i['ref'] for i in first['items']], [ITEM])
        self.assertEqual(first['items'][0]['parent'], COLLECTION)
        self.expect_local('/users/0/items', json=[load('book')], headers=total(2), match_params={'start': '1'})
        second = self.connector.search('attention', kinds=['item'], cursor=first['next_cursor'], limit=1)
        self.assertEqual(([i['ref'] for i in second['items']], second['next_cursor']), ([BOOK], None))

        self.expect_local('/users/0/items', json=[load('attachment')], headers=total(1), match_params={'itemType': 'attachment'})
        page = self.connector.search('pdf', kinds=['attachment'])
        self.assertEqual([(i['kind'], i['parent']) for i in page['items']], [('attachment', ITEM)])
        self.expect_local('/users/0/items', json=[], headers=total(0))
        self.connector.search('pdf')
        self.assertNotIn('itemType', self.http.calls[-1]['params'])

    def test_collection_only_search_and_bad_queries(self):
        self.assertEqual(self.connector.search('x', kinds=['collection', 'library']), {'v': 1, 'items': [], 'next_cursor': None})
        for args in (('',), ('x' * 501,), ('x', ['page']), ('x', []), (5,)):
            with self.subTest(args=args), self.assertRaises(base.InvalidRequest):
                self.connector.search(*args)


class ReadTests(ZoteroTestCase):
    def test_read_item_as_json(self):
        self.expect_local('/users/0/items/ITEM2222', json=load('item'))
        content = self.connector.read(ITEM)
        self.assertEqual((content['format'], content['truncated'], content['next_cursor']), ('json', False, None))
        record = json.loads(content['text'])
        self.assertEqual(record['title'], 'Attention Is All You Need')
        self.assertEqual(record['creators'][0], {'creatorType': 'author', 'firstName': 'Ashish', 'lastName': 'Vaswani'})
        self.assertNotIn('relations', record)
        self.assertNotIn('key', record)
        self.assertEqual((content['ref'], content['title'], content['version']), (ITEM, 'Attention Is All You Need', '1203'))
        self.assertEqual(content['url'], 'https://www.zotero.org/example-user/items/ITEM2222')
        self.assertEqual(content['parent'], COLLECTION)
        self.assertEqual(content['meta'], {'type': 'journalArticle', 'creators': 'Vaswani et al.', 'date': '2017-06-12', 'children': 2})

    def test_read_note_as_text(self):
        self.expect_local('/users/0/items/NTE22222', json=load('note'))
        content = self.connector.read('zotero:item:users/0/items/NTE22222')
        self.assertEqual(content['format'], 'text')
        self.assertEqual(content['text'], 'Reading notes\n\nKey claim & method\n\n- one\n- two')
        self.assertEqual((content['title'], content['parent']), ('Reading notes', ITEM))

    def test_read_attachment_full_text(self):
        self.expect_local('/users/0/items/ATT22222', json=load('attachment'))
        self.expect_local('/users/0/items/ATT22222/fulltext', json=load('fulltext'))
        content = self.connector.read('zotero:attachment:users/0/items/ATT22222')
        self.assertEqual((content['format'], content['text']), ('text', load('fulltext')['content']))
        self.assertEqual(content['meta'], {'type': 'attachment', 'content_type': 'application/pdf',
                                           'filename': 'vaswani-2017.pdf'})

    def test_attachment_without_indexed_text_is_unavailable(self):
        self.expect_local('/users/0/items/ATT22222', json=load('attachment'))
        self.expect_local('/users/0/items/ATT22222/fulltext', status=404, body=b'Not found')
        content = self.connector.read('zotero:attachment:users/0/items/ATT22222')
        self.assertEqual((content['format'], content['text']), ('unavailable', ''))
        self.assertIn('indexed', content['meta']['reason'])

    def test_read_collection_and_library(self):
        self.expect_local('/users/0/collections/CL333333', json=load('subcollection'))
        content = self.connector.read('zotero:collection:users/0/collections/CL333333')
        self.assertEqual(json.loads(content['text']), {'name': 'Transformers', 'items': 1, 'subcollections': 0})
        self.assertEqual((content['format'], content['version'], content['parent']), ('json', '901', COLLECTION))
        library = self.connector.read(LIBRARY)
        self.assertEqual((json.loads(library['text']), library['parent']), ({'name': 'My Library', 'type': 'user'}, None))
        self.expect_local('/users/0/groups', json=load('groups'), match_params={'limit': '100'})
        group = self.connector.read('zotero:library:groups/789')
        self.assertEqual(json.loads(group['text']), {'name': 'Thesis', 'type': 'group', 'items': 2})
        self.expect_local('/users/0/groups', json=load('groups'))
        with self.assertRaises(base.NotFound):
            self.connector.read('zotero:library:groups/999')

    def test_read_with_truncation_and_continuation(self):
        self.connector.max_read_chars = 30
        full = load('fulltext')['content']
        parts, cursor = [], None
        while True:
            self.expect_local('/users/0/items/ATT22222', json=load('attachment'))
            self.expect_local('/users/0/items/ATT22222/fulltext', json=load('fulltext'))
            content = self.connector.read('zotero:attachment:users/0/items/ATT22222', cursor=cursor)
            self.assertLessEqual(len(content['text']), 30)
            parts.append(content['text'])
            cursor = content['next_cursor']
            self.assertEqual(content['truncated'], cursor is not None)
            if cursor is None:
                break
        self.assertEqual(''.join(parts), full)
        self.assertEqual(len(parts), 3)

    def test_continuation_after_a_change_starts_over(self):
        self.connector.max_read_chars = 30
        self.expect_local('/users/0/items/ATT22222', json=load('attachment'))
        self.expect_local('/users/0/items/ATT22222/fulltext', json=load('fulltext'))
        cursor = self.connector.read('zotero:attachment:users/0/items/ATT22222')['next_cursor']
        changed = load('attachment')
        changed['version'] = changed['data']['version'] = 1300
        self.expect_local('/users/0/items/ATT22222', json=changed)
        with self.assertRaises(base.InvalidRequest):
            self.connector.read('zotero:attachment:users/0/items/ATT22222', cursor=cursor)
        with self.assertRaises(base.InvalidRequest):
            self.connector.read(ITEM, cursor=cursor)

    def test_remote_shape_is_validated(self):
        broken = load('item')
        broken['data']['dateModified'] = 7
        self.expect_local('/users/0/items/ITEM2222', json=broken)
        with self.assertRaises(base.InvalidResponse):
            self.connector.read(ITEM)
        self.expect_local('/users/0/items/ITEM2222', json=[load('item')])
        with self.assertRaises(base.InvalidResponse):
            self.connector.read(ITEM)


class ActionTests(ZoteroTestCase):
    def test_action_specs_and_tools(self):
        specs = {spec['name']: spec for spec in self.connector.actions()}
        self.assertEqual({name: spec['effect'] for name, spec in specs.items()}, {
            'zotero.library.create_item': 'create', 'zotero.item.add_note': 'create',
            'zotero.item.add_tags': 'update', 'zotero.collection.add_item': 'update',
            'zotero.item.trash': 'destructive'})
        for spec in specs.values():
            self.assertFalse(spec['params_schema']['additionalProperties'])
            self.assertEqual(spec['target_kind'], spec['name'].split('.')[1])
            self.assertFalse(spec['requires_version'])
        names = [tool['name'] for tool in base.tools(self.connector)]
        self.assertEqual(names, ['zotero_search', 'zotero_browse', 'zotero_read', 'zotero_library_create_item',
                                 'zotero_item_add_note', 'zotero_item_add_tags', 'zotero_collection_add_item',
                                 'zotero_item_trash'])

    def test_create_item(self):
        self.http.expect('POST', WEB + '/users/123456/items', json=load('created_item'),
                         match_headers=dict(WEB_AUTH, **{'Zotero-Write-Token': write_token('ui-1')}),
                         match_json=[{'itemType': 'book', 'title': 'New paper',
                                      'creators': [{'creatorType': 'author', 'lastName': 'Vaswani', 'firstName': 'Ashish'},
                                                   {'creatorType': 'author', 'name': 'Example Lab'}],
                                      'date': '2026', 'url': 'https://example.org/new', 'abstractNote': 'About it.',
                                      'tags': [{'tag': 'ml'}], 'collections': [], 'relations': {}}])
        result = self.connector.write('zotero.library.create_item', LIBRARY, {
            'item_type': 'book', 'title': 'New paper', 'creators': ['Vaswani, Ashish', 'Example Lab'], 'date': '2026',
            'url': 'https://example.org/new', 'abstract': 'About it.', 'tags': ['ml']}, 'ui-1')
        self.assertEqual(result, {
            'v': 1, 'ok': True, 'action': 'zotero.library.create_item', 'ref': LIBRARY,
            'result_ref': 'zotero:item:users/0/items/ITEM4444',
            'url': 'https://www.zotero.org/example-user/items/ITEM4444', 'version': '1300', 'replayed': False,
            'summary': 'Created "New paper" in Zotero. It appears in the Zotero app after Zotero syncs.'})
        self.assertNoSecret(result)

    def test_create_item_in_group(self):
        self.http.expect('POST', WEB + '/groups/456/items', json=load('created_item'))
        result = self.connector.write('zotero.library.create_item', 'zotero:library:groups/456',
                                      {'item_type': 'webpage', 'title': 'Site'}, 'ui-1g')
        self.assertEqual(result['result_ref'], 'zotero:item:groups/456/items/ITEM4444')
        self.assertEqual(self.http.calls[-1]['json'], [{'itemType': 'webpage', 'title': 'Site', 'creators': [],
                                                        'tags': [], 'collections': [], 'relations': {}}])

    def test_add_note_escapes_text(self):
        self.http.expect('POST', WEB + '/users/123456/items', json=load('created_note'), match_json=[{
            'itemType': 'note', 'parentItem': 'ITEM2222',
            'note': '<p>Looks &lt;good&gt; &amp; fine<br>second line</p><p>Next</p>',
            'tags': [], 'collections': [], 'relations': {}}])
        result = self.connector.write('zotero.item.add_note', ITEM,
                                      {'text': 'Looks <good> & fine\nsecond line\n\nNext'}, 'ui-2')
        self.assertEqual((result['result_ref'], result['summary']),
                         ('zotero:item:users/0/items/NTE33333', 'Added a note to the item.'))

    def test_add_tags_reads_then_patches_with_version(self):
        self.http.expect('GET', WEB + '/users/123456/items/ITEM2222', json=load('item'), match_headers=WEB_AUTH)
        self.http.expect('PATCH', WEB + '/users/123456/items/ITEM2222', status=204, headers={'Last-Modified-Version': '1301'},
                         match_headers={'If-Unmodified-Since-Version': '1203'},
                         match_json={'tags': [{'tag': 'ml'}, {'tag': 'nlp'}]})
        result = self.connector.write('zotero.item.add_tags', ITEM, {'tags': ['ml', 'nlp']}, 'ui-3')
        self.assertEqual((result['version'], result['summary'], result['result_ref']), ('1301', 'Added 1 tag.', ITEM))

    def test_add_tags_already_present_makes_no_change(self):
        self.http.expect('GET', WEB + '/users/123456/items/ITEM2222', json=load('item'))
        result = self.connector.write('zotero.item.add_tags', ITEM, {'tags': ['ml']}, 'ui-3b')
        self.assertEqual((result['summary'], result['version']), ('The item already has these tags.', '1203'))

    def test_add_item_to_collection(self):
        self.http.expect('GET', WEB + '/users/123456/items/ITEM3333', json=load('book'))
        self.http.expect('PATCH', WEB + '/users/123456/items/ITEM3333', status=204, headers={'Last-Modified-Version': '1302'},
                         match_headers={'If-Unmodified-Since-Version': '1100'}, match_json={'collections': ['CL222222']})
        result = self.connector.write('zotero.collection.add_item', COLLECTION, {'item': BOOK}, 'ui-4')
        self.assertEqual((result['result_ref'], result['summary']), (BOOK, 'Added "Deep Learning Basics" to the collection.'))
        for item in ('zotero:item:groups/456/items/ITEM3333', 'zotero:attachment:users/0/items/ATT22222', 'nope'):
            with self.subTest(item=item), self.assertRaises(base.InvalidRequest):
                self.connector.write('zotero.collection.add_item', COLLECTION, {'item': item}, 'ui-4x')

    def test_trash(self):
        self.http.expect('GET', WEB + '/users/123456/items/ITEM2222', json=load('item'))
        self.http.expect('PATCH', WEB + '/users/123456/items/ITEM2222', status=204, headers={'Last-Modified-Version': '1303'},
                         match_headers={'If-Unmodified-Since-Version': '1203'}, match_json={'deleted': 1})
        result = self.connector.write('zotero.item.trash', ITEM, {}, 'ui-5')
        self.assertEqual(result['summary'], 'Moved "Attention Is All You Need" to the Zotero trash.')

    def test_changed_meanwhile_is_conflict(self):
        for action, params in (('zotero.item.add_tags', {'tags': ['new']}), ('zotero.item.trash', {})):
            self.http.expect('GET', WEB + '/users/123456/items/ITEM2222', json=load('item'))
            self.http.expect('PATCH', WEB + '/users/123456/items/ITEM2222', status=412, body=b'Item has been modified')
            key = 'c-' + action.split('.')[-1]
            with self.subTest(action=action), self.assertRaises(base.Conflict):
                self.connector.write(action, ITEM, params, key)
            self.assertEqual(self.journal.records[key]['status'], 'failed')

    def test_failed_object_in_a_create_reply_is_definite(self):
        self.http.expect('POST', WEB + '/users/123456/items', json={
            'successful': {}, 'success': {}, 'unchanged': {}, 'failed': {'0': {'key': 'X', 'code': 400, 'message': 'Invalid field'}}})
        with self.assertRaises(base.InvalidRequest) as caught:
            self.connector.write('zotero.item.add_note', ITEM, {'text': 'hi'}, 'ui-6')
        self.assertNotIn('Invalid field', str(caught.exception))
        self.assertEqual(self.journal.records['ui-6']['status'], 'failed')

    def test_journal_replay_makes_no_second_request(self):
        self.http.expect('POST', WEB + '/users/123456/items', json=load('created_note'))
        first = self.connector.write('zotero.item.add_note', ITEM, {'text': 'Looks good'}, 'ui-7')
        again = self.connector.write('zotero.item.add_note', ITEM, {'text': 'Looks good'}, 'ui-7')
        self.assertEqual(dict(first, replayed=True), again)
        self.assertEqual(len(self.http.calls), 1)
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('zotero.item.add_note', ITEM, {'text': 'Other'}, 'ui-7')

    def test_timeout_after_send_is_outcome_unknown_and_never_resent(self):
        self.http.expect('POST', WEB + '/users/123456/items', raises='timeout_after_send')
        for _ in range(2):
            with self.assertRaises(base.OutcomeUnknown):
                self.connector.write('zotero.item.add_note', ITEM, {'text': 'hi'}, 'ui-8')
        self.assertEqual(self.journal.records['ui-8']['status'], 'outcome_unknown')

    def test_read_step_timeout_before_a_write_is_not_unknown(self):
        self.http.expect('GET', WEB + '/users/123456/items/ITEM2222', raises='timeout_after_send')
        with self.assertRaises(base.Unavailable):
            self.connector.write('zotero.item.trash', ITEM, {}, 'ui-9')
        self.assertEqual(self.journal.records['ui-9']['status'], 'failed')

    def test_writes_need_a_web_key(self):
        self.credentials.set({'kind': 'zotero'})
        with self.assertRaises(base.Unsupported) as caught:
            self.connector.write('zotero.item.add_note', ITEM, {'text': 'hi'}, 'ui-10')
        self.assertIn('web API key', str(caught.exception))
        self.assertEqual(self.journal.records, {})

    def test_write_validation(self):
        bad = [('zotero.item.delete', ITEM, {}),
               ('zotero.item.add_note', COLLECTION, {'text': 'x'}),
               ('zotero.item.add_note', 'zotero:attachment:users/0/items/ATT22222', {'text': 'x'}),
               ('zotero.item.add_note', ITEM, {'text': ''}),
               ('zotero.item.add_note', ITEM, {'text': 'x', 'extra': 1}),
               ('zotero.item.add_note', ITEM, ['x']),
               ('zotero.item.add_tags', ITEM, {'tags': []}),
               ('zotero.item.add_tags', ITEM, {'tags': ['']}),
               ('zotero.item.add_tags', ITEM, {'tags': 'ml'}),
               ('zotero.item.add_tags', ITEM, {'tags': ['x' * 256]}),
               ('zotero.item.trash', ITEM, {'why': 'x'}),
               ('zotero.library.create_item', LIBRARY, {'title': 'x'}),
               ('zotero.library.create_item', LIBRARY, {'item_type': 'note', 'title': 'x'}),
               ('zotero.library.create_item', LIBRARY, {'item_type': 'book', 'title': 'x', 'creators': [5]}),
               ('zotero.library.create_item', LIBRARY, {'item_type': 'book', 'title': 'x', 'url': 'javascript:alert(1)'}),
               ('zotero.collection.add_item', COLLECTION, {})]
        for action, ref, params in bad:
            with self.subTest(action=action, params=params), self.assertRaises(base.InvalidRequest):
                self.connector.write(action, ref, params, 'k1')
        with self.assertRaises(base.InvalidRequest):
            self.connector.write('zotero.item.add_note', ITEM, {'text': 'x'}, 'bad key')
        self.assertEqual(self.journal.records, {})


class ErrorMappingTests(ZoteroTestCase):
    def test_local_read_status_mapping(self):
        cases = {400: base.InvalidRequest, 403: base.Unavailable, 404: base.NotFound, 409: base.Conflict,
                 412: base.Conflict, 429: base.RateLimited, 500: base.Unavailable, 501: base.Unsupported,
                 503: base.Unavailable, 302: base.InvalidResponse}
        for status, error in cases.items():
            self.expect_local('/users/0/items/ITEM2222', status=status, body=b'Secret item text')
            with self.subTest(status=status), self.assertRaises(error) as caught:
                self.connector.read(ITEM)
            self.assertNotIn('Secret item text', str(caught.exception))

    def test_retry_after(self):
        self.expect_local('/users/0/items/ITEM2222', status=429, headers={'Retry-After': '17'})
        with self.assertRaises(base.RateLimited) as caught:
            self.connector.read(ITEM)
        self.assertEqual(caught.exception.retry_after_s, 17)

    def test_web_write_status_mapping(self):
        cases = {400: base.InvalidRequest, 401: base.AuthExpired, 403: base.Forbidden, 404: base.NotFound,
                 409: base.Conflict, 412: base.Conflict, 413: base.InvalidRequest, 429: base.RateLimited}
        for status, error in cases.items():
            self.http.expect('POST', WEB + '/users/123456/items', status=status, body=b'Secret')
            key = 'w-%d' % status
            with self.subTest(status=status), self.assertRaises(error) as caught:
                self.connector.write('zotero.item.add_note', ITEM, {'text': 'hi'}, key)
            self.assertNoSecret(str(caught.exception))
            self.assertEqual(self.journal.records[key]['status'], 'failed')

    def test_write_server_error_is_outcome_unknown(self):
        self.http.expect('POST', WEB + '/users/123456/items', status=503)
        with self.assertRaises(base.OutcomeUnknown):
            self.connector.write('zotero.item.add_note', ITEM, {'text': 'hi'}, 'k-503')
        self.assertEqual(self.journal.records['k-503']['status'], 'outcome_unknown')

    def test_connection_error_is_unavailable(self):
        self.expect_local('/users/0/items/ITEM2222', raises='connection')
        with self.assertRaises(base.Unavailable) as caught:
            self.connector.read(ITEM)
        self.assertIn('Open Zotero', str(caught.exception))


class ChangesTests(ZoteroTestCase):
    def test_baseline_then_batches(self):
        self.expect_local('/users/0/items', json={'ITEM2222': 1203}, headers={'Last-Modified-Version': '1250'},
                          match_params={'format': 'versions', 'limit': '1'})
        baseline = self.connector.changes()
        self.assertEqual((baseline['v'], baseline['items'], baseline['complete']), (1, [], True))

        changed = load('changes')
        self.expect_local('/users/0/items', json=changed[:2], headers=dict(total(3), **{'Last-Modified-Version': '1260'}),
                          match_params={'since': '1250', 'includeTrashed': '1', 'start': '0', 'limit': '2'})
        first = self.connector.changes(baseline['cursor'], limit=2)
        self.assertEqual(first['items'], [
            {'ref': ITEM, 'change': 'updated', 'at': '2026-11-11T10:04:00.000Z', 'title': 'Attention Is All You Need'},
            {'ref': 'zotero:item:users/0/items/ITEM4444', 'change': 'created', 'at': '2026-11-11T10:05:00.000Z',
             'title': 'Fresh paper'}])
        self.assertFalse(first['complete'])

        self.expect_local('/users/0/items', json=changed[2:], headers=dict(total(3), **{'Last-Modified-Version': '1261'}),
                          match_params={'since': '1250', 'start': '2'})
        second = self.connector.changes(first['cursor'], limit=2)
        self.assertEqual(second['items'], [{'ref': 'zotero:item:users/0/items/ITEM5555', 'change': 'deleted',
                                            'at': '2026-11-11T10:06:00.000Z', 'title': 'Old draft'}])
        self.assertTrue(second['complete'])

        # The next sweep starts at the library version seen on the first page.
        self.expect_local('/users/0/items', json=[], headers=dict(total(0), **{'Last-Modified-Version': '1261'}),
                          match_params={'since': '1260', 'start': '0'})
        third = self.connector.changes(second['cursor'])
        self.assertEqual((third['items'], third['complete']), ([], True))

    def test_bad_cursor_and_missing_version(self):
        with self.assertRaises(base.InvalidRequest):
            self.connector.changes('not-a-cursor')
        self.expect_local('/users/0/items', json={})
        with self.assertRaises(base.InvalidResponse):
            self.connector.changes()


if __name__ == '__main__':
    unittest.main()
