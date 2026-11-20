"""research/cache.py: keys, TTL, entry and total size limits, LRU pruning."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from research import cache  # noqa: E402

from . import fakes  # noqa: E402


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'research-cache'
        self.clock = fakes.FakeClock(1_800_000_000.0)

    def make(self, **options):
        return cache.Cache(self.root, clock=self.clock, **options)

    def test_round_trip_and_canonical_args(self):
        store = self.make()
        self.assertEqual(store.get('crossref', 'paper', {'doi': '10.1/x', 'a': 1}), (False, None))
        store.put('crossref', 'paper', {'a': 1, 'doi': '10.1/x'}, {'title': 'X'})
        self.assertEqual(store.get('crossref', 'paper', {'doi': '10.1/x', 'a': 1}), (True, {'title': 'X'}))
        self.assertEqual(store.get('openalex', 'paper', {'doi': '10.1/x', 'a': 1}), (False, None))
        self.assertEqual(store.hits, {'crossref': 1})

    def test_none_is_a_cached_answer(self):
        store = self.make()
        store.put('crossref', 'paper', ['10.1/x'], None)
        self.assertEqual(store.get('crossref', 'paper', ['10.1/x']), (True, None))

    def test_entries_expire_after_seven_days(self):
        store = self.make()
        store.put('arxiv', 'paper', ['1706.03762'], {'t': 1})
        self.clock.now += 7 * 86400 - 1
        self.assertTrue(store.get('arxiv', 'paper', ['1706.03762'])[0])
        self.clock.now += 2
        self.assertEqual(store.get('arxiv', 'paper', ['1706.03762']), (False, None))
        self.assertEqual(list(self.root.glob('*.json')), [])

    def test_large_entries_are_not_stored(self):
        store = self.make(max_entry_bytes=1000)
        store.put('arxiv', 'search', ['q'], {'text': 'x' * 2000})
        self.assertEqual(store.get('arxiv', 'search', ['q']), (False, None))
        self.assertEqual(cache.MAX_ENTRY_BYTES, 2 * 1024 * 1024)
        self.assertEqual(cache.MAX_TOTAL_BYTES, 200 * 1024 * 1024)
        self.assertEqual(cache.TTL_S, 7 * 86400)

    def test_total_is_pruned_least_recently_used_first(self):
        store = self.make(max_total_bytes=1500)
        for name in ('a', 'b', 'c'):
            store.put('arxiv', 'paper', [name], {'text': name * 400})
            self.clock.now += 10
        store.get('arxiv', 'paper', ['a'])          # a is now the most recently used
        self.clock.now += 10
        store.put('arxiv', 'paper', ['d'], {'text': 'd' * 400})
        present = {n for n in 'abcd' if store.get('arxiv', 'paper', [n])[0]}
        self.assertEqual(present, {'a', 'c', 'd'})

    def test_corrupt_entry_is_a_miss(self):
        store = self.make()
        store.put('arxiv', 'paper', ['x'], {'t': 1})
        for path in self.root.glob('*.json'):
            path.write_text('{nope', encoding='utf-8')
        self.assertEqual(store.get('arxiv', 'paper', ['x']), (False, None))

    def test_file_holds_only_source_method_args_and_value(self):
        store = self.make()
        store.put('unpaywall', 'fulltext', ['10.1/x'], {'oa_url': None})
        [path] = self.root.glob('*.json')
        entry = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(set(entry), {'v', 'key', 'at', 'value'})
        self.assertEqual(entry['key'], ['unpaywall', 'fulltext', ['10.1/x']])
        if os.name == 'posix':
            self.assertEqual(path.stat().st_mode & 0o077, 0)


if __name__ == '__main__':
    unittest.main()
