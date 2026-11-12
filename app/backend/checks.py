"""Fixed, deny-default Apple Python unittest recipe. No unrestricted fallback.

Unittest metadata is emitted by the application harness, separately from test output.
Project code shares that interpreter: metadata does not certify honest test code.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid

RECIPE = 'python_unittest_v1'
PRESET = 'macos-deny-default-v1'
LAUNCHER = '/usr/bin/sandbox-exec'
FRAMEWORKS = (
    '/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework',
    '/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework',
)

# No broad /System grant (Data is mounted there), service lookup or child processes.
PROFILE = '''(version 1)
(deny default)
(allow process-exec (literal (param "PYTHON")))
(allow file-read* file-test-existence file-map-executable
 (subpath "/usr/lib") (subpath "/System/Library")
 (subpath "/System/Cryptexes/OS") (subpath "/System/Volumes/Preboot/Cryptexes/OS")
 (subpath "/private/var/db/dyld") (subpath (param "FRAMEWORK")))
(allow file-read* file-test-existence (literal "/") (literal "/dev/null")
 (literal "/dev/urandom") (subpath (param "TREE")) (subpath (param "SCRATCH")))
(allow file-write* (subpath (param "SCRATCH")))
(allow sysctl-read (sysctl-name "hw.activecpu") (sysctl-name "hw.ncpu")
 (sysctl-name "hw.pagesize") (sysctl-name "kern.osrelease")
 (sysctl-name "kern.ostype") (sysctl-name "kern.osversion"))
(allow signal (target self))
(allow system-mac-syscall (require-all (mac-policy-name "Sandbox") (mac-syscall-number 67)))
'''

# Runs before importing any project module. The -I/-S/-B flags are also fixed.
HARNESS = r'''
import os, sys, json, resource, unittest
for key, value in ((resource.RLIMIT_CPU, 30), (resource.RLIMIT_FSIZE, 1000000),
                   (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_NPROC, 0),
                   (resource.RLIMIT_CORE, 0)):
    resource.setrlimit(key, (value, value))
tree, metadata = sys.argv[1:]
sys.path.insert(0, tree)
_dump, _open, _write, _close = json.dumps, os.open, os.write, os.close
_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
try:
    suite = unittest.defaultTestLoader.discover(os.path.join(tree, 'tests'), pattern='test*.py', top_level_dir=None)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    record = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
                  unexpected_successes=len(result.unexpectedSuccesses))
    code = 0 if result.wasSuccessful() and result.testsRun > 0 else 1
except BaseException:
    import traceback
    traceback.print_exc()
    record = dict(tests=0, failures=0, errors=1, skipped=0, expected_failures=0, unexpected_successes=0)
    code = 1
fd = _open(metadata, _flags, 0o600)
try:
    _write(fd, _dump(record).encode('ascii'))
finally:
    _close(fd)
raise SystemExit(code)
'''


def availability():
    """Freshly verify an installed Apple runtime, returning only app-owned roots."""
    unavailable = dict(ready=False, message='Signed Apple Python and macOS restrictions are required.', runtime=None)
    if sys.platform != 'darwin' or not os.path.isfile(LAUNCHER):
        return unavailable
    for framework in FRAMEWORKS:
        root = Path(framework)
        version = root / 'Versions/Current'
        if not version.exists():
            continue
        version = version.resolve()
        executable = version / 'Resources/Python.app/Contents/MacOS/Python'
        try:
            if not executable.is_file() or not executable.resolve().is_relative_to(root.resolve()):
                continue
            # Apple anchor, not merely an ad-hoc signature. Never bypass failed trust lookup.
            verified = subprocess.run(['/usr/bin/codesign', '--verify', '--strict', '-R', '=anchor apple', str(executable)],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      env={'PATH': '/usr/bin:/bin'}, close_fds=True, timeout=10)
            if verified.returncode:
                continue
            runtime = dict(executable=str(executable.resolve()), sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                           framework_root=str(root.resolve()), version=version.name, recipe=RECIPE, preset=PRESET)
            return dict(ready=True, message='Restricted Apple Python checks are available.', runtime=runtime)
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return unavailable


def qualifies(results):
    if not isinstance(results, dict):
        return False
    for phase in ('baseline', 'regression', 'candidate'):
        item = results.get(phase)
        if not isinstance(item, dict):
            return False
        if any(type(item.get(key)) is not int for key in ('tests', 'failures', 'errors', 'exit_code')):
            return False
        if item['tests'] < 1 or item['errors'] != 0:
            return False
        if phase == 'regression':
            if item.get('status') != 'failed' or item['exit_code'] == 0 or item['failures'] < 1:
                return False
        elif item.get('status') != 'passed' or item['exit_code'] != 0 or item['failures'] != 0:
            return False
    return True


def _paths(tree, scratch):
    tree, scratch = Path(tree), Path(scratch)
    if tree.is_symlink() or scratch.is_symlink():
        raise ValueError('Check directories cannot be symlinks.')
    tree, scratch = tree.resolve(strict=True), scratch.resolve(strict=True)
    if not tree.is_dir() or not scratch.is_dir() or tree == scratch or tree in scratch.parents or scratch in tree.parents:
        raise ValueError('Read-only tree and writable scratch must be separate directories.')
    if any(scratch.iterdir()):
        raise ValueError('Each check requires fresh empty scratch.')
    for current, directories, files in os.walk(str(tree), followlinks=False):
        for name in directories + files:
            info = os.lstat(os.path.join(current, name))
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError('Check tree must contain only regular files and directories.')
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise ValueError('Check tree cannot contain hardlinks.')
    return tree, scratch


def _stop(process):
    # Always signal the owned group, including after its leader has exited.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                process.send_signal(sig)
        if sig == signal.SIGTERM:
            time.sleep(.05)
    process.wait(timeout=2)
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _metadata(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
            raise ValueError('Invalid harness metadata.')
        record = json.loads(os.read(fd, 4097).decode('ascii'))
    finally:
        os.close(fd)
    if not isinstance(record, dict):
        raise ValueError('Invalid harness metadata object.')
    for key in ('tests', 'failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes'):
        if type(record.get(key)) is not int or record[key] < 0:
            raise ValueError('Invalid harness test counts.')
    # testsRun counts methods; each failed/skipped subTest can add a result entry.
    # These event counts therefore need not sum to at most the method count.
    return record


def run(tree, scratch, cancel, *, runtime=None, timeout=30, output_limit=100000):
    """Execute one fixed recipe; caller durably reserves the three-workflow ceiling."""
    started = time.monotonic()
    result = dict(status='unavailable', exit_code=None, stdout='', stderr='', tests=0, failures=0, errors=0,
                  duration=0.0, runtime=runtime, timed_out=False, cancelled=False, output_limited=False,
                  process_group_cleaned=False, signal=None, metadata_source='trusted-unittest-harness-v1')
    available = availability()
    if not available['ready'] or (runtime is not None and runtime != available['runtime']):
        result['message'] = available['message'] if not available['ready'] else 'Approved runtime no longer matches.'
        return result
    runtime = available['runtime']; result['runtime'] = runtime
    try:
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError('Check deadline must be positive and at most 30 seconds.')
        if type(output_limit) is not int or not 0 < output_limit <= 100000:
            raise ValueError('Check output must be bounded by 100000 bytes.')
        tree, scratch = _paths(tree, scratch)
    except (OSError, ValueError) as error:
        result['message'] = str(error)
        return result
    if cancel.is_set():
        result.update(status='cancelled', cancelled=True)
        return result
    metadata = scratch / ('result-' + uuid.uuid4().hex + '.json')
    command = [LAUNCHER, '-D', 'PYTHON=' + runtime['executable'], '-D', 'FRAMEWORK=' + runtime['framework_root'],
               '-D', 'TREE=' + str(tree), '-D', 'SCRATCH=' + str(scratch), '-p', PROFILE,
               runtime['executable'], '-I', '-S', '-B', '-c', HARNESS, str(tree), str(metadata)]
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(scratch), 'TMPDIR': str(scratch), 'LANG': 'C', 'LC_ALL': 'C'}
    process = None
    streams = { 'stdout': bytearray(), 'stderr': bytearray() }
    total = 0
    reason = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(command, cwd=str(tree), env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, start_new_session=True)
        for name in streams:
            pipe = getattr(process, name)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        deadline = time.monotonic() + timeout
        while selector.get_map():
            if cancel.is_set():
                reason = 'cancelled'; break
            if time.monotonic() >= deadline:
                reason = 'timeout'; break
            for key, _ in selector.select(min(.05, max(0, deadline - time.monotonic()))):
                data = os.read(key.fileobj.fileno(), 8192)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                remaining = output_limit - total
                streams[key.data].extend(data[:remaining]); total += min(len(data), remaining)
                if len(data) > remaining:
                    reason = 'output_limit'; break
            if reason:
                break
        if reason is None:
            while process.poll() is None:
                if cancel.is_set(): reason = 'cancelled'; break
                if time.monotonic() >= deadline: reason = 'timeout'; break
                time.sleep(.01)
    except OSError as error:
        result['message'] = 'Restriction launch failed: ' + str(error)
    finally:
        selector.close()
        if process is not None:
            result['process_group_cleaned'] = _stop(process)
            result['exit_code'] = process.returncode
            result['signal'] = -process.returncode if process.returncode < 0 else None
            for name in streams:
                getattr(process, name).close()
        # Ignore undecodable fragments rather than inflate encoded output with replacement characters.
        for name in streams:
            result[name] = streams[name].decode('utf-8', errors='ignore')
        result['duration'] = time.monotonic() - started
    if process is None:
        return result
    if not result['process_group_cleaned']:
        result['status'] = 'error'
        result['message'] = 'Could not confirm owned process-group cleanup.'
        return result
    if reason:
        result['status'] = reason
        result['timed_out'] = reason == 'timeout'
        result['cancelled'] = reason == 'cancelled'
        result['output_limited'] = reason == 'output_limit'
        return result
    try:
        counts = _metadata(metadata)
        result.update(counts)
        if result['signal'] is not None or counts['tests'] == 0 or counts['errors'] or counts['unexpected_successes']:
            result['status'] = 'error'
        elif counts['failures']:
            result['status'] = 'failed' if result['exit_code'] != 0 else 'error'
        elif result['exit_code'] == 0:
            result['status'] = 'passed'
        else:
            result['status'] = 'error'
    except (OSError, ValueError, TypeError, UnicodeError):
        result['status'] = 'error'
        result['message'] = 'No valid harness metadata; execution or restrictions failed.'
    return result
