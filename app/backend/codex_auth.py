"""Codex connection check and device sign-in: no shell, no credential-file access."""
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time


class AuthError(RuntimeError):
    """A sign-in failure whose message is safe to show."""


def find_codex():
    candidates = [shutil.which('codex'),
                  '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex',
                  '/Applications/Codex.app/Contents/Resources/codex']
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


class CodexAuth:
    def __init__(self, binary=None):
        self.binary = str(binary) if binary else find_codex()

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
            raise AuthError('Install Codex CLI or the ChatGPT Mac app before signing in.')
        try:
            process = subprocess.Popen([self.binary, 'login', '--device-auth'], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       start_new_session=True)
        except OSError as error:
            raise AuthError('Codex could not be started. Check its installation.') from error
        messages = []

        def read():
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
                    raise AuthError('Sign-in cancelled.')
                if time.monotonic() >= deadline:
                    raise AuthError('Sign-in deadline reached. Start sign-in again when ready.')
            if process.returncode != 0:
                raise AuthError('Codex sign-in did not complete. Check the device authorization instructions.')
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
