"""Durable audit log (scope.md)."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

import audit  # noqa: E402

NOV = 1794393000.0          # 2026-11-11T10:30:00Z
TASK = 'a' * 32
DIGEST = 'sha256:' + '1' * 64


def decision_record(**extra):
    record = {'actor': 'agent', 'kind': 'decision', 'task_id': TASK, 'project_id': 'p1', 'turn_id': 't-3',
              'call_id': 'call_11',
              'request': {'category': 'file_write', 'project_id': 'p1', 'paths': ['src/notes.md']},
              'decision': 'allow', 'rule': 'projects[0].write', 'scope_version': 3, 'scope_digest': DIGEST}
    record.update(extra)
    return record


class Clock:
    def __init__(self, t=NOV):
        self.t = t

    def __call__(self):
        self.t += 0.001
        return self.t


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name) / 'audit'
        self.clock = Clock()
        self.log = audit.AuditLog(self.dir, clock=self.clock)

    def lines(self, name='2026-11.jsonl'):
        return (self.dir / name).read_bytes().split(b'\n')

    def test_append_writes_full_record_format_with_hash_chain(self):
        first = self.log.append(decision_record())
        second = self.log.append(decision_record(decision='ask', rule='always_ask.destructive'))
        self.assertEqual(set(first), {'v', 'id', 'at', 'prev', 'actor', 'kind', 'task_id', 'project_id', 'turn_id',
                                      'call_id', 'request', 'decision', 'rule', 'scope_version', 'scope_digest',
                                      'outcome', 'idempotency_key', 'detail'})
        self.assertEqual((first['v'], first['prev'], first['outcome'], first['detail']), (1, None, None, None))
        self.assertRegex(first['id'], '^[0-9a-f]{32}$')
        self.assertRegex(first['at'], r'^2026-11-11T10:30:00\.\d{3}Z$')
        raw = self.lines()
        self.assertEqual(raw[-1], b'')
        self.assertEqual(json.loads(raw[0]), first)
        self.assertEqual(second['prev'], 'sha256:' + hashlib.sha256(raw[0]).hexdigest())
        self.assertEqual(self.log.verify(), [])

    def test_append_fsyncs_before_returning(self):
        with mock.patch.object(audit.os, 'fsync', wraps=os.fsync) as fsync:
            self.log.append(decision_record())
        self.assertGreaterEqual(fsync.call_count, 1)

    def test_write_failure_raises_audit_failed(self):
        with mock.patch.object(audit.os, 'fsync', side_effect=OSError('disk full')):
            with self.assertRaises(audit.AuditFailed) as failure:
                self.log.append(decision_record())
        self.assertIsInstance(failure.exception, ValueError)
        self.assertEqual(failure.exception.code, 'audit_failed')
        self.assertNotIn('disk full', str(failure.exception))
        blocked = Path(self.dir.parent / 'file-not-dir')
        blocked.write_text('x')
        with self.assertRaises(audit.AuditFailed):
            audit.AuditLog(blocked / 'audit').append(decision_record())

    def test_monthly_files_and_chain_restart(self):
        self.log.append(decision_record())
        self.clock.t = 1796083200.0  # 2026-12-01T00:00:00Z
        december = self.log.append(decision_record())
        self.assertIsNone(december['prev'])
        self.assertTrue((self.dir / '2026-12.jsonl').exists())
        self.assertEqual([r['at'][:7] for r in self.log.read()], ['2026-12', '2026-11'])

    def test_restart_continues_chain_and_never_rewrites(self):
        self.log.append(decision_record())
        before = (self.dir / '2026-11.jsonl').read_bytes()
        reopened = audit.AuditLog(self.dir, clock=self.clock)
        record = reopened.append(decision_record())
        after = (self.dir / '2026-11.jsonl').read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual(record['prev'], 'sha256:' + hashlib.sha256(before.rstrip(b'\n')).hexdigest())
        self.assertEqual(reopened.verify(), [])

    def test_torn_last_line_after_crash_is_skipped_and_chained(self):
        self.log.append(decision_record())
        with open(self.dir / '2026-11.jsonl', 'ab') as handle:
            handle.write(b'{"v": 1, "id": "torn')
        reopened = audit.AuditLog(self.dir, clock=self.clock)
        self.assertEqual(len(reopened.read()), 1)
        record = reopened.append(decision_record(call_id='after'))
        raw = self.lines()
        self.assertEqual(raw[1], b'{"v": 1, "id": "torn')
        self.assertEqual(json.loads(raw[2])['call_id'], 'after')
        self.assertEqual(record['prev'], 'sha256:' + hashlib.sha256(raw[1]).hexdigest())
        self.assertEqual([r['call_id'] for r in reopened.read()], ['after', 'call_11'])
        problems = reopened.verify()
        self.assertEqual([(p['line'], p['problem']) for p in problems], [(2, 'malformed')])

    def test_tampered_line_breaks_chain(self):
        for n in range(3):
            self.log.append(decision_record(call_id='c%d' % n))
        path = self.dir / '2026-11.jsonl'
        path.write_bytes(path.read_bytes().replace(b'"c1"', b'"cX"'))
        self.assertEqual([(p['line'], p['problem']) for p in self.log.verify()], [(3, 'prev_mismatch')])

    def test_read_filters_newest_first_and_skips_malformed_and_unknown_versions(self):
        other = 'b' * 32
        self.log.append(decision_record(call_id='1'))
        self.log.append(decision_record(task_id=other, call_id='2'))
        mid = self.log.append(decision_record(call_id='3'))
        with open(self.dir / '2026-11.jsonl', 'ab') as handle:
            handle.write(b'not json\n[1,2]\n{"v": 2, "id": "x", "at": "2026-11-12T10:00:00.000Z", "task_id": "%s"}\n' % TASK.encode())
        self.log.append(decision_record(call_id='4'))
        self.assertEqual([r['call_id'] for r in self.log.read()], ['4', '3', '2', '1'])
        self.assertEqual([r['call_id'] for r in self.log.read(task_id=TASK)], ['4', '3', '1'])
        self.assertEqual([r['call_id'] for r in self.log.read(since=mid['at'])], ['4', '3'])
        self.assertEqual([r['call_id'] for r in self.log.read(limit=2)], ['4', '3'])
        self.assertEqual(self.log.read(task_id='none'), [])

    def test_record_kinds_and_validation(self):
        self.log.append({'actor': 'user', 'kind': 'answer', 'task_id': TASK, 'decision': 'allow_once',
                         'detail': {'ask_id': 'a1', 'request_digest': DIGEST}})
        self.log.append({'actor': 'user', 'kind': 'scope', 'task_id': TASK, 'request': None,
                         'detail': {'from_version': 3, 'to_version': 4, 'from_digest': DIGEST, 'to_digest': DIGEST}})
        self.log.append({'actor': 'agent', 'kind': 'action', 'task_id': TASK, 'outcome': 'outcome_unknown',
                         'idempotency_key': TASK + ':' + 'f' * 32,
                         'request': {'category': 'network', 'host': 'pypi.org', 'port': 443, 'via': 'command'}})
        bad = [
            dict(decision_record(), v=2),
            dict(decision_record(), actor='robot'),
            dict(decision_record(), kind='gossip'),
            dict(decision_record(), decision='maybe'),
            dict(decision_record(), request=None),
            dict(decision_record(), surprise=1),
            {'actor': 'agent', 'kind': 'action', 'task_id': TASK, 'outcome': 'great', 'request': {'category': 'web_search'}},
            {'actor': 'user', 'kind': 'answer', 'task_id': TASK, 'decision': 'allow', 'detail': {'ask_id': 'a', 'request_digest': DIGEST}},
            {'actor': 'user', 'kind': 'answer', 'task_id': TASK, 'decision': 'text', 'detail': {'ask_id': 'a', 'text': 'secret'}},
            {'actor': 'user', 'kind': 'auth', 'detail': {'app': 'x', 'state': 'signed_in'}},
            {'actor': 'user', 'kind': 'user_write', 'outcome': 'succeeded', 'request': {'category': 'web_search'}},
            dict(decision_record(), request={'category': 'app', 'app': 'x', 'op': 'read', 'action': 'x.read', 'ref': 'x:p:1'}),
            {'actor': 'user', 'kind': 'scope', 'request': {'category': 'web_search'}, 'detail': {}},
        ]
        for record in bad:
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.log.append(record)
        self.assertEqual(len(self.log.read()), 3)

    def test_private_content_is_redacted_or_dropped(self):
        long = 'x' * 500
        stored = self.log.append(decision_record(request={
            'category': 'command', 'argv': ['curl', '--token', 'tok123', '-p', 'pw', 'ACCESS_TOKEN=abc', 'API_KEY=zz',
                                            '--password=hunter2', 'mode=fast', long] + ['y' * 150] * 20,
            'command': None, 'cwd': '.', 'sandbox': 'workspace', 'network': False, 'project_id': 'p1',
            'env': {'SECRET': 'v'}, 'stdin': 'content'}))
        argv = stored['request']['argv']
        self.assertEqual(argv[:9], ['curl', '--token', '[redacted]', '-p', '[redacted]', 'ACCESS_TOKEN=[redacted]',
                                    'API_KEY=[redacted]', '--password=[redacted]', 'mode=fast'])
        self.assertEqual(len(argv[9]), 200)
        self.assertLessEqual(sum(len(a) for a in argv), 2000)
        self.assertNotIn('env', stored['request'])
        self.assertNotIn('stdin', stored['request'])
        text = (self.dir / '2026-11.jsonl').read_text()
        for secret in ('tok123', 'hunter2', 'ACCESS_TOKEN=abc', 'API_KEY=zz', '"content"', '"pw"'):
            self.assertNotIn(secret, text)
        shell = self.log.append(decision_record(request={'category': 'command', 'argv': None,
                                                         'command': 'deploy --token s3cr3t', 'cwd': '.',
                                                         'sandbox': 'workspace', 'network': False}))
        self.assertNotIn('s3cr3t', json.dumps(shell))
        search = self.log.append(decision_record(request={'category': 'web_search', 'query': 'my private question'}))
        self.assertEqual(search['request'], {'category': 'web_search'})
        read = self.log.append(decision_record(request={'category': 'file_read', 'project_id': 'p1',
                                                        'path': 'README.md', 'body': 'page text'}))
        self.assertNotIn('body', read['request'])
        self.assertNotIn('page text', (self.dir / '2026-11.jsonl').read_text())

    def test_concurrent_appends_keep_one_valid_chain(self):
        def worker(n):
            for i in range(20):
                self.log.append(decision_record(call_id='%d-%d' % (n, i)))
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.log.read(limit=1000)), 80)
        self.assertEqual(self.log.verify(), [])


if __name__ == '__main__':
    unittest.main()
