"""Opt-in live smoke test of the Codex runtime against the real `codex app-server`.

Not part of the routine suite: unittest discovery never imports this file (it is not named test*.py), and it
refuses to run unless INTERSPACE_LIVE_CODEX=1. Run it only with the user's explicit approval at the time:

    INTERSPACE_LIVE_CODEX=1 INTERSPACE_CODEX_HOME=<app-owned home, signed in> \
        python3 tests/runtime/fixtures/codex/live_smoke.py [--handshake-only]

`--handshake-only` starts the session (initialize, account/read, thread/start with the Interspace sandbox
profile) and stops: no model call. Without it, one short model turn runs in a throwaway git repository and
asks for one command; every event is printed. Nothing else is touched.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'app' / 'backend'))

from runtime import codex  # noqa: E402


class PrintingContext:
    def __init__(self, workspace):
        self.task_id, self.turn_id = 'live', 'u1'
        self.project_ids = ['p1']
        self.workspaces = {'p1': workspace}
        self.primary_workspace = workspace
        self.scope = {'web_search': 'deny'}
        self.model = os.environ.get('INTERSPACE_CODEX_MODEL') or None
        self.cancel = threading.Event()

    def tools(self):
        return []

    def authorize(self, request, call_id):
        allowed = request.get('category') == 'command' and request.get('sandbox') == 'workspace' and not request.get('network')
        print('authorize', call_id, json.dumps(request), '->', 'allow' if allowed else 'deny')
        return {'decision': 'allow' if allowed else 'deny', 'rule': 'live.smoke', 'scope_version': 1}

    def observed(self, request, call_id):
        print('observed', call_id, json.dumps(request))
        return {'decision': 'allow', 'rule': 'provider.sandbox', 'scope_version': 1}

    def emit(self, kind, data, *, turn_id=None, item_id=None):
        print('event', kind, item_id, json.dumps(data)[:300])

    def app_tool(self, name, arguments, call_id):
        return {'ok': False, 'error': {'code': 'denied', 'message': 'No apps in the smoke test.'}}

    def report_usage(self, usage):
        print('usage', json.dumps(usage))


def main():
    if os.environ.get('INTERSPACE_LIVE_CODEX') != '1':
        print('Refusing to run: set INTERSPACE_LIVE_CODEX=1 (only with the user\'s approval).')
        return 2
    home = os.environ.get('INTERSPACE_CODEX_HOME')
    if not home:
        print('Set INTERSPACE_CODEX_HOME to the app-owned, signed-in Codex home.')
        return 2
    with tempfile.TemporaryDirectory(prefix='interspace-live-') as temporary:
        data = Path(os.path.realpath(temporary))
        repo = data / 'workspaces' / 'live' / 'p1'
        repo.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        (repo / 'README.md').write_text('smoke\n')
        ctx = PrintingContext(str(repo))
        runtime = codex.CodexRuntime(codex_home=home, app_data=data)
        session = runtime.open(ctx)
        print('session started; thread', session.thread_id)
        try:
            if '--handshake-only' not in sys.argv:
                result = session.run_turn('Run `ls` once, then reply with the single word OK.', ctx)
                print('turn result', json.dumps(result))
        finally:
            session.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
