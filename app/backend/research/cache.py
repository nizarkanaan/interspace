"""The research response cache (research/tools.md "Cache").

Entries are keyed by (source, method, canonical args) and hold normalized results, never raw responses,
keys or emails. Each entry lives 7 days and is at most 2 MiB; the folder is pruned least recently used
first to 200 MiB. A read refreshes the entry's file time, which is the LRU order.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from . import http

TTL_S = 7 * 86400
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024


def _canonical(source, method, args):
    return json.dumps([source, method, args], sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class Cache:
    def __init__(self, root, *, clock=time.time, ttl_s=TTL_S, max_entry_bytes=MAX_ENTRY_BYTES,
                 max_total_bytes=MAX_TOTAL_BYTES):
        self.root = Path(root)
        self._clock = clock
        self._ttl_s = ttl_s
        self._max_entry = max_entry_bytes
        self._max_total = max_total_bytes
        self._lock = threading.Lock()
        self.hits = {}   # answers served from the cache per source, for research_usage

    def _path(self, source, method, args):
        digest = hashlib.sha256(_canonical(source, method, args).encode('utf-8')).hexdigest()
        return self.root / (digest + '.json')

    def get(self, source, method, args):
        """(True, value) for a fresh entry, else (False, None)."""
        path = self._path(source, method, args)
        key = json.loads(_canonical(source, method, args))
        with self._lock:
            try:
                entry = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return False, None
            now = self._clock()
            if not isinstance(entry, dict) or entry.get('key') != key or not isinstance(entry.get('at'), (int, float)) \
                    or now - entry['at'] > self._ttl_s:
                self._remove(path)
                return False, None
            try:
                os.utime(path, (now, now))
            except OSError:
                pass
            self.hits[source] = self.hits.get(source, 0) + 1
        http.note('cached', source)
        return True, entry.get('value')

    def put(self, source, method, args, value):
        entry = {'v': 1, 'key': json.loads(_canonical(source, method, args)), 'at': self._clock(), 'value': value}
        data = json.dumps(entry, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(data) > self._max_entry:
            return
        path = self._path(source, method, args)
        with self._lock:
            try:
                self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                handle, temp = tempfile.mkstemp(dir=str(self.root), prefix='.tmp-')
                try:
                    with os.fdopen(handle, 'wb') as out:
                        out.write(data)
                    now = self._clock()
                    os.utime(temp, (now, now))
                    os.replace(temp, str(path))
                except BaseException:
                    self._remove(Path(temp))
                    raise
            except OSError:
                return   # a cache that cannot write is only slower
            self._prune()

    def _prune(self):
        files = []
        for path in self.root.glob('*.json'):
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append((stat.st_mtime, stat.st_size, path))
        total = sum(size for _, size, _ in files)
        for _, size, path in sorted(files, key=lambda f: f[0]):
            if total <= self._max_total:
                break
            self._remove(path)
            total -= size

    @staticmethod
    def _remove(path):
        try:
            path.unlink()
        except OSError:
            pass
