"""Codex CLI adapter: no shell, no credential-file access, no arbitrary tools."""
import json
import os
from pathlib import Path
import shutil
import signal
import selectors
import subprocess
import tempfile
import threading
import time


class ProviderError(RuntimeError):
    def __init__(self, message, usage=None):
        super().__init__(message)
        self.usage = usage


def search_event(item):
    """Only provider-observed URL fields establish provenance; final model text never does."""
    urls = []
    def visit(value, depth=0):
        if depth > 12:
            raise ProviderError('Search provenance exceeds the supported nesting limit.')
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'url':
                    if not isinstance(child, str) or len(child) > 2000:
                        raise ProviderError('Malformed search provenance URL.')
                    urls.append(child)
                elif key == 'urls':
                    if not isinstance(child, list) or any(not isinstance(u,str) or len(u)>2000 for u in child):
                        raise ProviderError('Malformed search provenance URLs.')
                    urls.extend(child)
                elif isinstance(child, (dict,list)):
                    visit(child,depth+1)
        elif isinstance(value,list):
            for child in value: visit(child,depth+1)
    visit(item)
    if len(urls)>200:
        raise ProviderError('Search provenance exceeds the supported URL limit.')
    query = item.get('query', '')
    action = item.get('action', {})
    if not isinstance(action,dict) or not isinstance(query,str):
        raise ProviderError('Malformed search activity.')
    if not query:
        query = action.get('query','')
    if not isinstance(query,str) or len(query)>2000:
        raise ProviderError('Malformed search query.')
    return {'query':query,'urls':list(dict.fromkeys(urls)),'action':str(action.get('type','search'))[:80]}


def find_codex():
    candidates = [shutil.which('codex'),
                  '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex',
                  '/Applications/Codex.app/Contents/Resources/codex']
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


class CodexProvider:
    def __init__(self, binary=None, timeout=240):
        self.binary = str(binary) if binary else find_codex()
        self.timeout = timeout

    def status(self):
        if not self.binary:
            return {'ready': False, 'message': 'Install Codex CLI or the ChatGPT Mac app to connect OpenAI.'}
        try:
            result = subprocess.run([self.binary, 'login', 'status'], capture_output=True, timeout=10)
            return {'ready': result.returncode == 0,
                    'message': 'Codex signed in' if result.returncode == 0 else 'Sign in to Codex with your ChatGPT account.'}
        except (OSError, subprocess.TimeoutExpired):
            return {'ready': False, 'message': 'Codex could not be started. Check its installation.'}

    def sign_in(self, cancel, emit):
        if not self.binary:
            raise ProviderError('Install Codex CLI or the ChatGPT Mac app before signing in.')
        process = subprocess.Popen([self.binary, 'login', '--device-auth'], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        messages = []
        def read():
            import re
            for line in process.stdout:
                clean = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', line).strip()
                if clean:
                    messages.append(clean)
                    emit('\n'.join(messages)[-4000:])
        worker = threading.Thread(target=read, daemon=True)
        worker.start()
        deadline = time.monotonic() + 180
        try:
            while process.poll() is None:
                if cancel.wait(.1):
                    raise ProviderError('Sign-in cancelled.')
                if time.monotonic() >= deadline:
                    raise ProviderError('Sign-in deadline reached. Start sign-in again when ready.')
            if process.returncode != 0:
                raise ProviderError('Codex sign-in did not complete. Check the device authorization instructions.')
        finally:
            self.stop(process)
            worker.join(timeout=2)

    @staticmethod
    def stop(process):
        # The session group may outlive its leader. Always address the owned group.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                process.terminate()
        time.sleep(.15)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS restricted hosts can deny a signal to an already-empty group.
            # Still ensure the direct child has exited; owned-group TERM was attempted above.
            if process.poll() is None:
                process.kill()
        process.wait(timeout=2)

    def run(self, prompt, schema, cwd, cancel):
        return self._run(prompt,schema,cwd,cancel)

    def search(self, prompt, schema, cwd, cancel, on_event):
        return self._run(prompt,schema,cwd,cancel,on_event)

    def _run(self, prompt, schema, cwd, cancel, on_search=None):
        if cancel.is_set():
            raise ProviderError('Run cancelled before dispatch.')
        if not self.binary:
            raise ProviderError('Codex is missing. Install Codex CLI or the ChatGPT Mac app.')
        cwd = Path(cwd).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='response-schema-', dir=cwd) as temporary:
            schema_path = Path(temporary) / 'schema.json'
            schema_path.write_text(json.dumps(schema))
            command = [self.binary, '-a', 'never', 'exec', '--ignore-user-config', '--sandbox', 'read-only',
                       '--ephemeral', '--json', '--skip-git-repo-check', '-C', str(cwd),
                       '-c', 'features.shell_tool=false', '-c', 'features.multi_agent=false',
                       '-c', 'web_search="live"' if on_search is not None else 'web_search="disabled"',
                       '-c', 'model_reasoning_effort="low"',
                       '--output-schema', str(schema_path), '-']
            try:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, start_new_session=True)
            except OSError as error:
                raise ProviderError('Codex could not be launched. Check its executable and permissions.') from error
            def write_input():
                try:
                    process.stdin.write(prompt)
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            writer = threading.Thread(target=write_input, daemon=True)
            writer.start()
            selector = selectors.DefaultSelector()
            for stream, name in ((process.stdout,'stdout'),(process.stderr,'stderr')):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            deadline = time.monotonic() + min(self.timeout,240)
            buffer, stderr, total = b'', b'', 0
            messages, usage, completed, search_count = [], {}, False, 0
            def consume(line):
                nonlocal usage, completed, search_count
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    return
                item = event.get('item', {})
                if item.get('type') == 'web_search' and on_search is not None:
                    search_count += 1
                    if search_count > 100:
                        raise ProviderError('Search activity exceeded the supported event limit.')
                    on_search(search_event(item))
                elif item.get('type') in ('command_execution','file_change','mcp_tool_call','web_search','collab_tool_call'):
                    raise ProviderError('Unexpected tool activity: this workflow accepts text-only results.')
                if event.get('type') in ('turn.failed','error'):
                    raise ProviderError('Codex reported a failed stage.')
                if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                    messages.append(item.get('text',''))
                if event.get('type') == 'turn.completed':
                    completed = True
                    usage = {k:v for k,v in event.get('usage',{}).items() if type(v) is int and v >= 0}
            try:
                while selector.get_map():
                    if cancel.is_set():
                        raise ProviderError('Run cancelled; active Codex process stopped.')
                    if time.monotonic() >= deadline:
                        raise ProviderError('Stage deadline reached; Codex process stopped. No automatic retry.')
                    for key, _ in selector.select(.05):
                        chunk = os.read(key.fileobj.fileno(),65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > 2_000_000:
                            raise ProviderError('Codex output exceeded the stage limit.')
                        if key.data == 'stderr':
                            stderr = (stderr + chunk)[-8192:]
                        else:
                            buffer += chunk
                            while b'\n' in buffer:
                                line, buffer = buffer.split(b'\n',1)
                                consume(line)
                if buffer:
                    consume(buffer)
                if cancel.is_set():
                    raise ProviderError('Run cancelled before accepting its result.')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderError('Stage deadline reached; Codex process stopped.')
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired as error:
                    raise ProviderError('Stage deadline reached; Codex process stopped.') from error
                if process.returncode != 0:
                    if b'Operation not permitted' in stderr:
                        raise ProviderError('macOS blocked Codex startup. Launch Interspace normally from Finder; this restricted execution environment cannot start it.')
                    raise ProviderError('Codex did not complete. Check sign-in, account limits and network access, then try again.')
                if not completed or not messages:
                    raise ProviderError('Codex returned no completed response.')
                try:
                    result = json.loads(messages[-1])
                except (ValueError, TypeError) as error:
                    raise ProviderError('Codex response was not valid JSON.') from error
                if not isinstance(result,dict):
                    raise ProviderError('Codex JSON response must be an object.')
                return result, usage
            except ProviderError as error:
                error.usage = usage if completed else None
                raise
            finally:
                selector.close()
                self.stop(process)
                writer.join(timeout=2)
                for stream in (process.stdout,process.stderr):
                    stream.close()
