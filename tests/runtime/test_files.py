"""Interspace's own file-change tools for Claude sessions: every path step opened without following links."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'app' / 'backend') not in sys.path:
    sys.path.append(str(ROOT / 'app' / 'backend'))

from runtime import files  # noqa: E402


class FilesCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.ws = self.root / 'ws'
        self.other = self.root / 'other'
        self.outside = self.root / 'outside'
        for path in (self.ws, self.other, self.outside):
            path.mkdir()
        (self.outside / 'secret').write_text('keep\n')
        self.workspaces = {'p1': str(self.ws), 'p2': str(self.other)}

    def target(self, path):
        found = files.locate(path, self.workspaces, str(self.ws))
        self.assertIsNotNone(found, path)
        return found

    def assert_outside_untouched(self):
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ['secret'])
        self.assertEqual((self.outside / 'secret').read_text(), 'keep\n')


class LocateTests(FilesCase):
    def test_paths_inside_a_workspace(self):
        self.assertEqual(files.locate('src/a.py', self.workspaces, str(self.ws)), ('p1', str(self.ws), ('src', 'a.py')))
        self.assertEqual(files.locate(str(self.other / 'b.txt'), self.workspaces, str(self.ws)),
                         ('p2', str(self.other), ('b.txt',)))
        self.assertEqual(files.locate('./src//a.py', self.workspaces, str(self.ws))[2], ('src', 'a.py'))

    def test_a_workspace_named_through_a_link_still_matches(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.ws, target_is_directory=True)
        found = files.locate(str(self.ws / 'a.py'), {'p1': str(alias)}, str(alias))
        self.assertEqual(found, ('p1', str(self.ws), ('a.py',)))

    def test_refused_paths(self):
        for path in ('', '../outside/secret', 'src/../../x', str(self.outside / 'secret'), '.git/config',
                     'sub/.GIT/hooks/x', '.Git', str(self.ws), 'a\x00b', 7, None, 'x' * 5000):
            with self.subTest(path=path):
                self.assertIsNone(files.locate(path, self.workspaces, str(self.ws)))


class WriteTests(FilesCase):
    def test_new_file_and_folders_are_created(self):
        old, new = files.write_file(self.target('src/pkg/a.py'), 'print(1)\n')
        self.assertIsNone(old)
        self.assertEqual(new, 'print(1)\n')
        self.assertEqual((self.ws / 'src/pkg/a.py').read_text(), 'print(1)\n')
        self.assertEqual(stat.S_IMODE(os.stat(str(self.ws / 'src/pkg/a.py')).st_mode), 0o644)
        self.assertEqual([p.name for p in (self.ws / 'src/pkg').iterdir()], ['a.py'])  # No temp file left.

    def test_existing_file_keeps_its_mode(self):
        path = self.ws / 'run.sh'
        path.write_text('old\n')
        path.chmod(0o755)
        old, new = files.write_file(self.target('run.sh'), 'new\n')
        self.assertEqual((old, new), ('old\n', 'new\n'))
        self.assertEqual(path.read_text(), 'new\n')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)

    def test_a_hard_linked_file_is_replaced_not_written_through(self):
        inside = self.ws / 'linked'
        os.link(str(self.outside / 'secret'), str(inside))
        files.write_file(self.target('linked'), 'changed\n')
        self.assertEqual(inside.read_text(), 'changed\n')
        self.assert_outside_untouched()

    def test_links_and_odd_files_are_refused(self):
        (self.ws / 'to-secret').symlink_to(self.outside / 'secret')
        (self.ws / 'to-outside').symlink_to(self.outside, target_is_directory=True)
        (self.ws / 'dir').mkdir()
        os.mkfifo(str(self.ws / 'fifo'))
        for path in ('to-secret', 'to-outside/new.txt', 'to-outside/secret', 'dir', 'fifo'):
            with self.subTest(path=path):
                with self.assertRaises(files.FileToolError):
                    files.write_file(self.target(path), 'x')
                with self.assertRaises(files.FileToolError):
                    files.edit_file(self.target(path), 'keep', 'gone')
        self.assert_outside_untouched()
        self.assertTrue((self.ws / 'to-secret').is_symlink())

    def test_content_must_be_text_of_a_bounded_size(self):
        for content in (None, 5, 'x' * (files.MAX_FILE_BYTES + 1)):
            with self.subTest(size=len(content) if isinstance(content, str) else content):
                with self.assertRaises(files.FileToolError):
                    files.write_file(self.target('a.txt'), content)
        self.assertFalse((self.ws / 'a.txt').exists())


class EditTests(FilesCase):
    def setUp(self):
        super().setUp()
        (self.ws / 'a.py').write_text('x = 1\ny = 1\n')

    def test_replaces_one_occurrence(self):
        old, new = files.edit_file(self.target('a.py'), 'x = 1', 'x = 2')
        self.assertEqual((old, new), ('x = 1\ny = 1\n', 'x = 2\ny = 1\n'))
        self.assertEqual((self.ws / 'a.py').read_text(), 'x = 2\ny = 1\n')

    def test_ambiguous_missing_or_empty_edits_fail(self):
        for args in (('= 1', 'z'), ('nope', 'z'), ('', 'z'), ('x = 1', 'x = 1')):
            with self.subTest(args=args):
                with self.assertRaises(files.FileToolError):
                    files.edit_file(self.target('a.py'), *args)
        with self.assertRaises(files.FileToolError):
            files.edit_file(self.target('missing.py'), 'a', 'b')
        self.assertEqual((self.ws / 'a.py').read_text(), 'x = 1\ny = 1\n')

    def test_replace_all(self):
        files.edit_file(self.target('a.py'), '= 1', '= 3', replace_all=True)
        self.assertEqual((self.ws / 'a.py').read_text(), 'x = 3\ny = 3\n')


class NotebookTests(FilesCase):
    def setUp(self):
        super().setUp()
        self.notebook = {'cells': [{'id': 'c1', 'cell_type': 'code', 'source': 'print(1)', 'metadata': {},
                                    'outputs': [], 'execution_count': 1},
                                   {'id': 'c2', 'cell_type': 'markdown', 'source': '# Title', 'metadata': {}}],
                         'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}
        (self.ws / 'n.ipynb').write_text(json.dumps(self.notebook))

    def cells(self):
        return json.loads((self.ws / 'n.ipynb').read_text())['cells']

    def test_replace_insert_and_delete(self):
        files.edit_notebook(self.target('n.ipynb'), 'print(2)', cell_id='c1')
        cell = self.cells()[0]
        self.assertEqual((cell['source'], cell['outputs'], cell['execution_count']), ('print(2)', [], None))
        files.edit_notebook(self.target('n.ipynb'), 'Notes', cell_id='c1', cell_type='markdown', edit_mode='insert')
        self.assertEqual([c['source'] for c in self.cells()], ['print(2)', 'Notes', '# Title'])
        files.edit_notebook(self.target('n.ipynb'), '', cell_id='c2', edit_mode='delete')
        self.assertEqual([c['source'] for c in self.cells()], ['print(2)', 'Notes'])
        files.edit_notebook(self.target('n.ipynb'), 'first', cell_type='code', edit_mode='insert')
        self.assertEqual(self.cells()[0]['source'], 'first')

    def test_bad_notebook_edits_fail(self):
        for kwargs in ({'cell_id': 'nope'}, {'cell_id': 'c1', 'edit_mode': 'rename'},
                       {'cell_id': 'c1', 'edit_mode': 'insert'}, {'edit_mode': 'replace'}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(files.FileToolError):
                    files.edit_notebook(self.target('n.ipynb'), 'x', **kwargs)
        (self.ws / 'bad.ipynb').write_text('not json')
        with self.assertRaises(files.FileToolError):
            files.edit_notebook(self.target('bad.ipynb'), 'x', cell_id='c1')
        self.assertEqual(json.loads((self.ws / 'n.ipynb').read_text()), self.notebook)


if __name__ == '__main__':
    unittest.main()
