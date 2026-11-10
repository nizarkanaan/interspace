import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
sys.path.insert(0, str(ROOT / 'tests'))
import test_pilot

try:
    from provider import CodexProvider, ProviderError
    from service import Application
except ImportError:
    CodexProvider = Application = None
    ProviderError = RuntimeError


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def executable(self, body):
        path = self.root / 'fake-codex'
        path.write_text('#!' + sys.executable + '\nimport sys,json,time\nsys.stdin.read()\n' + body)
        path.chmod(0o755)
        return path

    def test_real_process_events_return_json_and_usage(self):
        binary = self.executable("print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{\"reply\":\"Hello\"}'}}))\nprint(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':5}}))\n")
        result, usage = CodexProvider(binary, timeout=3).run('test', {}, self.root, threading.Event())
        self.assertEqual(result, {'reply': 'Hello'})
        self.assertEqual(usage['output_tokens'], 5)

    def test_failed_or_tool_executing_process_is_not_success(self):
        binary = self.executable("print(json.dumps({'type':'item.started','item':{'type':'command_execution'}}))\n")
        with self.assertRaisesRegex(ProviderError, 'tool'):
            CodexProvider(binary, timeout=3).run('test', {}, self.root, threading.Event())
        binary = self.executable("print('failed',file=sys.stderr)\nsys.exit(1)\n")
        with self.assertRaises(ProviderError):
            CodexProvider(binary, timeout=3).run('test', {}, self.root, threading.Event())

    def test_timeout_and_cancel_stop_process(self):
        binary = self.executable('time.sleep(20)\n')
        started = time.monotonic()
        with self.assertRaisesRegex(ProviderError, 'deadline'):
            CodexProvider(binary, timeout=.15).run('test', {}, self.root, threading.Event())
        self.assertLess(time.monotonic()-started, 3)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(ProviderError, 'cancel'):
            CodexProvider(binary).run('test', {}, self.root, cancel)

    def test_forbidden_tool_event_stops_before_later_side_effect(self):
        marker = self.root / 'tool-effect'
        binary = self.executable("print(json.dumps({'type':'item.started','item':{'type':'command_execution'}}),flush=True)\ntime.sleep(.7)\nopen("+repr(str(marker))+",'w').write('bad')\n")
        with self.assertRaisesRegex(ProviderError,'tool'):
            CodexProvider(binary, timeout=8).run('test',{},self.root,threading.Event())
        time.sleep(.8)
        self.assertFalse(marker.exists())

    def test_deadline_kills_child_after_leader_exits(self):
        marker = self.root / 'child-effect'
        binary = self.executable("import os\nif os.fork()==0:\n time.sleep(.7)\n open("+repr(str(marker))+",'w').write('bad')\n os._exit(0)\nos._exit(0)\n")
        with self.assertRaisesRegex(ProviderError,'deadline'):
            CodexProvider(binary,timeout=.15).run('test',{},self.root,threading.Event())
        time.sleep(.8)
        self.assertFalse(marker.exists())

    def test_backend_quit_with_closed_output_stops_active_provider(self):
        import subprocess
        marker = self.root / 'orphan-effect'
        pidfile = self.root / 'provider-pid'
        binary = self.root / 'codex'
        body = ('import os\n'
                "if 'login' in sys.argv:\n time.sleep(.2)\n print('Logged in using ChatGPT')\n sys.exit(0)\n"
                + 'open('+repr(str(pidfile))+",'w').write(str(os.getpid()))\n"
                + 'sys.stdin.read()\ntime.sleep(2)\nopen('+repr(str(marker))+",'w').write('bad')\n")
        binary.write_text('#!'+sys.executable+'\nimport sys,time\n'+body)
        binary.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root)+os.pathsep+os.environ.get('PATH',''))
        process = subprocess.Popen([sys.executable,str(ROOT/'app/backend/service.py'),'--data-root',str(self.root/'quit-data')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        try:
            process.stdin.write(json.dumps({'id':'chat','method':'chat','params':{'scope':'workspace','text':'hello'}})+'\n')
            process.stdin.flush()
            deadline=time.monotonic()+3
            while not pidfile.exists() and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue(pidfile.exists())
            process.stdin.write(json.dumps({'id':'status','method':'connection','params':{}})+'\n')
            process.stdin.flush()
            process.stdout.close()
            process.stdin.close()
            process.wait(timeout=5)
            diagnostic=process.stderr.read()
            self.assertEqual(process.returncode,0,diagnostic)
            time.sleep(2.1)
            self.assertFalse(marker.exists())
        finally:
            if process.poll() is None: process.kill();process.wait()
            if pidfile.exists():
                try: os.killpg(int(pidfile.read_text()),9)
                except OSError: pass
            process.stderr.close()

    def test_malformed_json_is_rejected(self):
        binary = self.executable("print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'not JSON'}}))\nprint(json.dumps({'type':'turn.completed'}))\n")
        with self.assertRaisesRegex(ProviderError, 'JSON'):
            CodexProvider(binary).run('test', {}, self.root, threading.Event())


class AppTests(unittest.TestCase):
    setUp = test_pilot.PilotTests.setUp
    git = test_pilot.PilotTests.git
    def app(self, provider=None):
        if provider is None:
            class Fake:
                binary = '/fake'
                def status(self):
                    return {'ready': True, 'message': 'Test provider'}
                def run(self, prompt, schema, cwd, cancel):
                    if 'Role: Orchestrator' in prompt:
                        return {'reply': 'I can review the selected project.', 'action': 'propose_review'}, {'input_tokens': 1}
                    result = {'summary':'Reviewed snapshot','findings':[{'claim':'Context exists','evidence':[{'source':'README.md','start':1,'end':1}]}], 'proposal':'Not executed; propose a bounded check.'}
                    if 'Role: Reviewer' in prompt:
                        result['verdict'] = 'accept'
                    return result, {'input_tokens': 1, 'output_tokens': 1}
            provider = Fake()
        return Application(self.base / 'app-data', provider=provider)

    def test_chat_plan_and_two_workers_persist_without_source_changes(self):
        app = self.app()
        app.handle('select_project', {'path': str(self.source)})
        baseline = self.git('status', '--porcelain')
        app.handle('chat', {'scope':'project', 'text':'Review the evidence'})
        app.wait()
        plan = app.public()['pending']
        self.assertIsNotNone(plan)
        app.handle('start_review', {'plan_id':plan['id']})
        app.wait()
        state = app.public()
        self.assertEqual(state['run']['stage'], 'completed')
        self.assertTrue(state['run']['verification']['unchanged'])
        self.assertEqual(baseline, self.git('status', '--porcelain'))
        restored = self.app()
        self.assertEqual(restored.public()['threads'], state['threads'])
        self.assertEqual(len(state['usage']), 3)

    def test_stale_plan_and_unknown_actions_rejected(self):
        app = self.app()
        app.handle('select_project', {'path':str(self.source)})
        with self.assertRaisesRegex(ValueError, 'plan'):
            app.handle('start_review', {'plan_id':'stale'})
        with self.assertRaisesRegex(ValueError, 'method'):
            app.handle('delete_project', {})
        app.handle('chat', {'scope':'workspace','text':'Help'})
        app.wait()
        self.assertIsNone(app.public()['pending'])

    def test_plan_is_rejected_after_project_commit_changes(self):
        app = self.app()
        app.handle('select_project', {'path':str(self.source)})
        app.handle('chat', {'scope':'project','text':'Review'})
        app.wait()
        plan = app.public()['pending']
        (self.source/'README.md').write_text('Changed committed evidence\n')
        self.git('add','README.md')
        self.git('commit','-qm','new revision')
        with self.assertRaisesRegex(ValueError,'stale'):
            app.handle('start_review',{'plan_id':plan['id']})
        self.assertIsNone(app.public()['run'])

    def test_busy_and_cancel_do_not_launch_reviewers(self):
        entered = threading.Event()
        class Slow:
            binary = '/fake'
            def run(self, prompt, schema, cwd, cancel):
                entered.set()
                cancel.wait(2)
                raise ProviderError('cancelled')
        app = self.app(Slow())
        app.handle('chat', {'scope':'workspace','text':'hello'})
        self.assertTrue(entered.wait(1))
        with self.assertRaisesRegex(ValueError, 'active'):
            app.handle('chat', {'scope':'workspace','text':'second'})
        app.handle('cancel', {})
        app.wait()
        self.assertFalse(app.public()['active'])
        self.assertIn('cancel', app.public()['error'].lower())
        self.assertEqual(len(app.public()['usage']), 0)

    def test_failed_review_preserves_integrity_and_does_not_stay_running(self):
        class Broken:
            binary = '/fake'
            def run(self, prompt, schema, cwd, cancel):
                if 'Role: Orchestrator' in prompt:
                    return {'reply':'A review is ready','action':'propose_review'}, {}
                raise ProviderError('provider failed')
        app = self.app(Broken())
        app.handle('select_project', {'path':str(self.source)})
        app.handle('chat', {'scope':'project','text':'Review'})
        app.wait()
        app.handle('start_review', {'plan_id':app.public()['pending']['id']})
        app.wait()
        self.assertEqual(app.public()['run']['stage'], 'failed')
        self.assertTrue(app.public()['run']['verification']['unchanged'])

    def test_reopening_marks_interrupted_run_without_restarting_it(self):
        import runner
        app = self.app()
        app.handle('select_project', {'path':str(self.source)})
        run = runner.prepare(self.source, app.storage / 'runs')
        app.state.update(active='Researcher', run_id=run.name)
        app.persist()
        restored = self.app()
        self.assertIsNone(restored.public()['active'])
        self.assertEqual(restored.public()['run']['stage'], 'interrupted')
        self.assertIn('interrupted', restored.public()['error'])

    def test_malformed_model_action_cannot_dispatch(self):
        class Invalid:
            binary='/fake'
            def run(self,*args):
                return {'reply':'oops','action':'execute_shell'}, {}
        app = self.app(Invalid())
        app.handle('chat',{'scope':'workspace','text':'hello'})
        app.wait()
        self.assertIsNone(app.public()['pending'])
        self.assertTrue(app.public()['error'])


if __name__ == '__main__':
    unittest.main()
