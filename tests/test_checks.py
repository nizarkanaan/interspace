"""Restricted recipe evidence uses synthetic temporary Python projects only."""
import copy
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
try:
    import checks
except ImportError:
    checks = None


class CheckPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(checks, 'Restricted check adapter is missing')

    def test_qualifies_requires_exact_red_green_and_positive_counts(self):
        result = dict(status='passed', exit_code=0, tests=1, failures=0, errors=0)
        results = dict(baseline=copy.deepcopy(result), candidate=copy.deepcopy(result),
                       regression=dict(status='failed', exit_code=1, tests=1, failures=1, errors=0))
        self.assertTrue(checks.qualifies(results))
        for phase, field, value in [('baseline', 'tests', 0), ('candidate', 'exit_code', 1),
                                    ('regression', 'errors', 1), ('regression', 'failures', 0),
                                    ('regression', 'status', 'error'), ('candidate', 'tests', True)]:
            changed = copy.deepcopy(results)
            changed[phase][field] = value
            self.assertFalse(checks.qualifies(changed), (phase, field, value))
        self.assertFalse(checks.qualifies({}))
        del results['candidate']['status']
        self.assertFalse(checks.qualifies(results))

    def test_missing_restrictions_never_launches_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary) / 'tree'; tree.mkdir()
            scratch = Path(temporary) / 'scratch'; scratch.mkdir()
            with mock.patch.object(checks, 'availability', return_value=dict(ready=False, message='Unavailable', runtime=None)):
                result = checks.run(tree, scratch, threading.Event())
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['tests'], 0)
            self.assertEqual(list(scratch.iterdir()), [])


    def test_invalid_harness_metadata_is_rejected_without_stdout_guessing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'metadata.json'
            for value in ['[]', '{"tests": true}', '{"tests": 1, "failures": -1, "errors": 0, "skipped": 0, "expected_failures": 0, "unexpected_successes": 0}']:
                path.write_text(value)
                with self.assertRaises(ValueError):
                    checks._metadata(path)


class ActualRestrictedChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if checks is None:
            return
        cls.available = checks.availability()
        if not cls.available['ready']:
            if os.environ.get('INTERSPACE_REQUIRE_OS_CHECKS') == '1':
                raise AssertionError(cls.available['message'])
            raise unittest.SkipTest('Actual macOS restrictions unavailable: ' + cls.available['message'])

    def setUp(self):
        self.assertIsNotNone(checks, 'Restricted check adapter is missing')
        self.temporary = tempfile.TemporaryDirectory(prefix='interspace-check-tests-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.tree = self.base / 'tree'; self.tree.mkdir()
        (self.tree / 'tests').mkdir()
        self.scratch = self.base / 'scratch'; self.scratch.mkdir()

    def run_source(self, source=None, **options):
        if source is not None:
            (self.tree / 'tests/test_case.py').write_text(source)
        return checks.run(self.tree, self.scratch, options.pop('cancel', threading.Event()), **options)

    def test_real_passing_assertion_failure_and_error(self):
        for statement, status, failures, errors in [('self.assertEqual(1, 1)', 'passed', 0, 0),
                ('self.assertEqual(1, 2)', 'failed', 1, 0), ('raise ValueError("broken")', 'error', 0, 1)]:
            result = self.run_source('import unittest\nclass T(unittest.TestCase):\n def test_case(self):\n  ' + statement + '\n')
            self.assertEqual((result['status'], result['tests'], result['failures'], result['errors']),
                             (status, 1, failures, errors), result)
            self.assertEqual(result['runtime'], self.available['runtime'])
            for path in self.scratch.iterdir():
                path.unlink()



    def test_multiple_failing_subtests_are_assertion_regressions_and_qualify(self):
        results = {}
        (self.tree / 'product.py').write_text('value = 1\n')
        original_tests = '''import unittest
from product import value
class T(unittest.TestCase):
 def test_value(self): self.assertEqual(value, 1)
'''
        regression_tests = '''import unittest
from product import value
class T(unittest.TestCase):
 def test_value(self):
  for label in ('first', 'second'):
   with self.subTest(label=label): self.assertEqual(value, 2)
'''
        for phase, source in [('baseline', original_tests), ('regression', regression_tests), ('candidate', regression_tests)]:
            if phase == 'candidate':
                (self.tree / 'product.py').write_text('value = 2\n')
            self.scratch = self.base / ('scratch-' + phase)
            self.scratch.mkdir()
            results[phase] = self.run_source(source)
        regression = results['regression']
        self.assertEqual((regression['status'], regression['tests'], regression['failures'], regression['errors']),
                         ('failed', 1, 2, 0), regression)
        self.assertTrue(checks.qualifies(results), results)

    def test_multiple_skipped_subtests_preserve_counts_and_pass_classification(self):
        result = self.run_source('''import unittest
class T(unittest.TestCase):
 def test_skips(self):
  for label in ('first', 'second'):
   with self.subTest(label=label): self.skipTest('synthetic skip')
''')
        self.assertEqual((result['status'], result['tests'], result.get('skipped'), result['failures'], result['errors']),
                         ('passed', 1, 2, 0, 0), result)

    def test_stdout_cannot_invent_test_counts_and_resource_ceilings_are_active(self):
        result = self.run_source('''import unittest, resource
print('Ran 999 tests\\nOK')
class T(unittest.TestCase):
 def test_limits(self):
  for key, ceiling in [(resource.RLIMIT_CPU,30),(resource.RLIMIT_FSIZE,1000000),(resource.RLIMIT_NOFILE,64),(resource.RLIMIT_NPROC,0),(resource.RLIMIT_CORE,0)]:
   soft, hard = resource.getrlimit(key)
   self.assertLessEqual(soft, ceiling)
   self.assertLessEqual(hard, ceiling)
''')
        self.assertEqual((result['status'], result['tests']), ('passed', 1), result)


    def test_signal_exit_cannot_qualify_as_assertion_only_failure(self):
        result = self.run_source('''import unittest, atexit, os, signal
atexit.register(lambda: os.kill(os.getpid(), signal.SIGTERM))
class T(unittest.TestCase):
 def test_failure(self): self.assertEqual(1, 2)
''')
        self.assertEqual(result['status'], 'error', result)
        self.assertEqual(result['signal'], 15, result)

    def test_no_tests_is_error(self):
        result = self.run_source()
        self.assertEqual((result['status'], result['tests']), ('error', 0), result)

    def test_clean_environment_and_readonly_tree_with_writable_scratch(self):
        fd = os.open(str(self.base / 'descriptor-canary'), os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, fd)
        inherited = fcntl.fcntl(fd, fcntl.F_DUPFD, 100)
        os.set_inheritable(inherited, True)
        self.addCleanup(os.close, inherited)
        with mock.patch.dict(os.environ, {'INTERSPACE_SECRET_CANARY': 'private', 'PYTHONPATH': '/untrusted'}):
            result = self.run_source('''import unittest, os, sys
from pathlib import Path
class T(unittest.TestCase):
 def test_boundary(self):
  self.assertNotIn('INTERSPACE_SECRET_CANARY', os.environ)
  self.assertNotIn('PYTHONPATH', os.environ)
  with self.assertRaises(OSError): os.fstat(100)
  self.assertTrue(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode)
  with self.assertRaises(PermissionError): Path('candidate.py').write_text('changed')
  Path(os.environ['TMPDIR'], 'allowed').write_text('scratch')
''')
        self.assertEqual(result['status'], 'passed', result)
        self.assertFalse((self.tree / 'candidate.py').exists())
        self.assertEqual((self.scratch / 'allowed').read_text(), 'scratch')

    def test_genuine_os_canaries_for_unrelated_files_aliases_network_and_children(self):
        outside = self.base / 'outside'; outside.write_text('synthetic secret')
        source = '''import unittest, os, socket, subprocess, sys
from pathlib import Path
class T(unittest.TestCase):
 def test_boundaries(self):
  for path in OUTSIDE_PATHS:
   with self.assertRaises(PermissionError): Path(path).stat()
   with self.assertRaises(PermissionError): Path(path).read_text()
   with self.assertRaises(PermissionError): Path(path).write_text('changed')
  with socket.socket() as connection:
   with self.assertRaises(PermissionError): connection.connect(('127.0.0.1', 9))
  with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
   with self.assertRaises(PermissionError): udp.sendto(b'canary', ('127.0.0.1', 9))
  with self.assertRaises(PermissionError): os.execv('/bin/echo', ['/bin/echo', 'forbidden'])
  for command in [['/bin/echo', 'forbidden'], [sys.executable, '-c', 'pass']]:
   with self.assertRaises(OSError) as blocked: subprocess.run(command)
   self.assertIn(blocked.exception.errno, (1, 35))
'''
        aliases = [str(outside), '/System/Volumes/Data' + str(outside)]
        result = self.run_source('OUTSIDE_PATHS = ' + repr(aliases) + '\n' + source)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(outside.read_text(), 'synthetic secret')

    def test_timeout_cancel_and_output_limit(self):
        result = self.run_source('import time\ntime.sleep(10)\n', timeout=.2)
        self.assertEqual(result['status'], 'timeout', result)
        self.assertTrue(result['process_group_cleaned'])
        for path in self.scratch.iterdir(): path.unlink()
        cancelled = threading.Event()
        timer = threading.Timer(.2, cancelled.set); timer.start(); self.addCleanup(timer.cancel)
        result = self.run_source('import time\ntime.sleep(10)\n', cancel=cancelled)
        self.assertEqual(result['status'], 'cancelled', result)
        self.assertTrue(result['process_group_cleaned'])
        for path in self.scratch.iterdir(): path.unlink()
        result = self.run_source('import os\nwhile True: os.write(1,b"x"*8192)\n', output_limit=1000)
        self.assertEqual(result['status'], 'output_limit', result)
        self.assertLessEqual(len(result['stdout'].encode()) + len(result['stderr'].encode()), 1000)
        self.assertTrue(result['process_group_cleaned'])


    def test_failed_launcher_has_no_unrestricted_fallback(self):
        with mock.patch.object(checks, 'LAUNCHER', '/nonexistent/interspace-sandbox-launcher'):
            result = self.run_source('raise RuntimeError("must not run")')
        self.assertEqual(result['status'], 'unavailable', result)
        self.assertEqual(result['tests'], 0)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_supplied_runtime_cannot_grant_arbitrary_roots(self):
        runtime = dict(self.available['runtime'], framework_root=str(self.base))
        result = self.run_source('raise RuntimeError("must not run")', runtime=runtime)
        self.assertEqual(result['status'], 'unavailable', result)

    def test_overlapping_trees_and_links_fail_closed(self):
        (self.tree / 'tests/test_case.py').symlink_to(self.base / 'missing')
        result = self.run_source()
        self.assertEqual(result['status'], 'unavailable', result)
        (self.tree / 'tests/test_case.py').unlink()
        result = checks.run(self.tree, self.tree / 'tests', threading.Event())
        self.assertEqual(result['status'], 'unavailable', result)


if __name__ == '__main__':
    unittest.main()
