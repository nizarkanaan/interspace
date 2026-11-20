"""Full text for the claim check (docs/superpowers/specs/2026-11-20-claim-fulltext-design.md)."""
from pathlib import Path
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))

from research import claims, fulltext  # noqa: E402

BODY = ('Introduction. Mobile networks fail during storms.\n\n'
        'Methods. We measured emergency call fallback to a second operator in 40 outages across three countries.\n\n'
        'Results. Fallback succeeded in 31 of 40 outages, and the median time to answer was 41 seconds.\n\n'
        'Discussion. Roaming callers were not measured, so their outcomes remain unknown.')


def resolver(*addresses):
    def resolve(host, port, type=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, port)) for a in addresses]
    return resolve


class FakeReply:
    def __init__(self, status, headers, body=b''):
        self.status, self._headers, self._body = status, headers, [body, b'']

    def getheader(self, name):
        return self._headers.get(name)

    def read(self, n):
        return self._body.pop(0) if self._body else b''


def connection_for(replies, seen):
    class Conn:
        def __init__(self, host, address, family):
            seen.append((host, address))

        def request(self, method, path, headers=None):
            self.path = path

        def getresponse(self):
            return replies.pop(0)

        def close(self):
            pass
    return Conn


class DownloadTests(unittest.TestCase):
    def test_private_and_local_addresses_are_refused(self):
        for address in ('127.0.0.1', '10.0.0.5', '192.168.1.2', '169.254.169.254', '::1'):
            with self.assertRaisesRegex(fulltext.FullTextError, 'local or private'):
                fulltext.fetch_public('https://example.org/a.pdf', resolve=resolver(address),
                                      connection=connection_for([], []))

    def test_only_https_links_and_redirects_are_rechecked(self):
        with self.assertRaisesRegex(fulltext.FullTextError, 'Only https'):
            fulltext.fetch_public('http://example.org/a.pdf', resolve=resolver('93.184.216.34'))
        seen = []
        replies = [FakeReply(302, {'Location': 'https://cdn.example.net/a.pdf'}),
                   FakeReply(200, {'Content-Type': 'application/pdf'}, b'%PDF-1.7 body')]
        body, kind = fulltext.fetch_public('https://example.org/a', resolve=resolver('93.184.216.34'),
                                           connection=connection_for(replies, seen))
        self.assertEqual((body, kind), (b'%PDF-1.7 body', 'application/pdf'))
        self.assertEqual([h for h, _ in seen], ['example.org', 'cdn.example.net'])
        replies = [FakeReply(302, {'Location': 'https://intranet.local/x'})]
        def mixed(host, port, type=None):
            return resolver('10.1.1.1' if host == 'intranet.local' else '93.184.216.34')(host, port)
        with self.assertRaisesRegex(fulltext.FullTextError, 'local or private'):
            fulltext.fetch_public('https://example.org/a', resolve=mixed, connection=connection_for(replies, []))

    def test_wrong_types_and_errors_are_refused(self):
        replies = [FakeReply(200, {'Content-Type': 'application/zip'}, b'PK')]
        with self.assertRaisesRegex(fulltext.FullTextError, 'not a PDF or a web page'):
            fulltext.fetch_public('https://example.org/a', resolve=resolver('93.184.216.34'),
                                  connection=connection_for(replies, []))
        replies = [FakeReply(404, {})]
        with self.assertRaisesRegex(fulltext.FullTextError, 'HTTP 404'):
            fulltext.fetch_public('https://example.org/a', resolve=resolver('93.184.216.34'),
                                  connection=connection_for(replies, []))


class TextTests(unittest.TestCase):
    def test_html_text_drops_scripts_and_navigation(self):
        page = b'<html><nav>Menu</nav><script>evil()</script><p>Fallback succeeded.</p><p>Second para.</p></html>'
        self.assertEqual(fulltext.html_text(page), 'Fallback succeeded.\n\nSecond para.')

    def test_passages_pick_the_best_matching_text_in_order(self):
        found = fulltext.passages(BODY, 'Fallback succeeded in most outages, with a median time to answer.', k=2,
                                  size=120)
        self.assertEqual(len(found), 2)
        self.assertTrue(any('31 of 40 outages' in p for p in found))
        self.assertEqual(fulltext.passages(BODY, 'the of and'), [])


class FakeCall:
    tool = 'claims_pending'

    def __init__(self, decisions):
        self.decisions, self.asked, self.noted = decisions, [], []

    def authorize(self, request):
        self.asked.append(request['source'])
        return {'decision': self.decisions.get(request['source'], 'deny')}

    def note_call(self, source):
        self.noted.append(source)


class App:
    http = None
    bridge = None


class TextForTests(unittest.TestCase):
    def test_open_access_text_needs_the_fulltext_permission_and_is_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'fulltext'
            paper = {'doi': '10.5555/x', 'oa_url': 'https://example.org/a.html'}
            text, error = fulltext.text_for(App(), FakeCall({}), paper, folder, fetch=lambda url: (b'', 'text/html'))
            self.assertEqual((text, error), (None, "Open-access full text is not allowed by this task's scope."))
            call = FakeCall({'fulltext': 'allow'})
            page = ('<p>' + BODY.replace('\n\n', '</p><p>') + '</p>').encode()
            text, error = fulltext.text_for(App(), call, paper, folder, fetch=lambda url: (page, 'text/html'))
            self.assertIsNone(error)
            self.assertIn('31 of 40 outages', text)
            self.assertEqual((call.asked, call.noted), (['fulltext'], ['fulltext']))
            again = FakeCall({})
            self.assertEqual(fulltext.text_for(App(), again, paper, folder, fetch=None)[0], text)
            self.assertEqual(again.asked, [])  # Cached: no new download, no new ask.


class ClaimAttachTests(unittest.TestCase):
    def test_claims_wait_for_full_text_and_take_passages(self):
        report = ('# R\n\nFallback succeeded in most outages with a short time to answer [1].\n\n## References\n\n'
                  '1. Example (2020). Fallback study. https://example.org/a.pdf\n')
        corpus = {'papers': [{'paper': {'title': 'Fallback study across operators', 'oa_url': 'https://example.org/a.pdf',
                                        'doi': None}}]}
        value = claims.start(report.replace('Fallback study.', 'Fallback study across operators.'), corpus, 't0')
        [claim] = value['claims']
        self.assertEqual((claim['status'], claim['source']), ('pending', None))
        claims.attach(claim, BODY, None, 't1')
        self.assertEqual((claim['status'], claim['source_kind']), ('pending', 'full text'))
        self.assertIn('31 of 40 outages', claim['source'])
        out = claims.record(value, report.replace('Fallback study.', 'Fallback study across operators.'),
                            [{'id': claim['id'], 'verdict': 'supported', 'reason': 'Results section.',
                              'quote': 'Fallback succeeded in 31 of 40 outages'}], 'codex', 't2')
        self.assertEqual(out['recorded'], 1)
        other = dict(claim, status='pending', source=None, abstract=None, fulltext_tried=False)
        claims.attach(other, None, 'No open-access full text was found.', 't3')
        self.assertEqual((other['verdict'], other['reason']), ('cannot_tell', 'No open-access full text was found.'))


if __name__ == '__main__':
    unittest.main()
