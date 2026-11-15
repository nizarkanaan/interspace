"""Local app protocol: projects, agent tasks and read-only history of earlier tasks. Transport: JSON lines on pipes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import importlib
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pilot'))
import runner
from codex_auth import AuthError, CodexAuth
import projects
import tasks
import budget
import scheduler

AGENT_METHODS = ('agent_create', 'agent_message', 'agent_answer', 'agent_cancel', 'task_events', 'task_blob',
                 'scope_get', 'scope_update', 'scope_approve', 'scope_default', 'scheduler_settings')
APP_METHODS = ('state', 'connection', 'cancel', 'sign_in', 'switch_project', 'select_task', 'add_project',
               'select_project', 'update_project')
STATE_PUBLISH_INTERVAL_S = 0.25  # At most 4 coarse state updates per second (scheduler.md).


def optional_module(name):
    """An optional backend module (scope, audit, runtime), or None when it cannot be imported."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


class ScopeAdapter:
    """The scope.py functions the scheduler and the scope methods call (1E). One place to reconcile names."""

    def __init__(self, module):
        self.module = module

    def _need(self):
        if self.module is None:
            raise ValueError('Agent tasks need the scope engine, which is not in this build yet.')
        return self.module

    def validate(self, document, *, project_ids=None):
        result = self._need().validate(document, project_ids=project_ids)
        return document if result is None else result

    def digest(self, scope):
        return self._need().digest(scope)

    def default(self, task, project_ids):
        return self._need().default(task, project_ids)

    def decide(self, scope, approval, request, *, workspace_roots, now, **options):
        return self._need().decide(scope, approval, request, workspace_roots=workspace_roots, now=now, **options)

    def request_digest(self, request):
        return self._need().request_digest(request)

    def apply_answer(self, document, approval, ask, answer, *, now):
        """scope.apply_answer: binds the answer to the exact ask and applies add_to_scope (README answer path)."""
        return self._need().apply_answer(document, approval, ask, answer, now=now)

    def merge_patch(self, scope, patch):
        """The patched copy with `version` unchanged; the scheduler increments it."""
        return self._need().merge_patch(scope, patch)


class AuditAdapter:
    """Audit writes. `log` is 1E's `audit.AuditLog` (or a test fake) with `append(record)`, which raises
    when the record is not durable. Without it every write fails, so agent actions fail closed."""

    def __init__(self, log):
        self.log = log

    def append(self, record):
        if self.log is None:
            raise OSError('The audit log is not in this build yet.')
        return self.log.append(record)


class AgentStore:
    """The task store the scheduler uses, over `Application.state` and its lock."""

    def __init__(self, app):
        self.app = app
        self.lock = app.lock

    @property
    def state(self):
        return self.app.state

    def agent_tasks(self):
        for project in self.app.state['projects'].values():
            saved = project.get('tasks') if isinstance(project, dict) else None
            for task in (saved.values() if isinstance(saved, dict) else ()):  # Damaged saved data is skipped.
                if isinstance(task, dict) and task.get('mode') == 'agent':
                    yield task

    def task(self, task_id):
        if isinstance(task_id, str):
            for project in self.app.state['projects'].values():
                saved = project.get('tasks')
                task = saved.get(task_id) if isinstance(saved, dict) else None
                if task is not None:
                    return tasks.validate(task, task_id)
        raise ValueError('Unknown task.')

    def project(self, project_id):
        return self.app.state['projects'].get(project_id)

    def changed(self, task_id=None):
        self.app.persist()
        self.app.publish_soon()


def reply_for(line, app):
    """Answer one request line exactly as the original single-threaded stdin loop did."""
    request = None
    try:
        request = json.loads(line) if isinstance(line, (str, bytes)) else line
        if not isinstance(request, dict):
            raise ValueError('Request must be an object')
        return {'id': request.get('id'), 'result': app.handle(request.get('method'), request.get('params', {}))}
    except Exception as error:
        return {'id': request.get('id') if isinstance(request, dict) else None,
                'error': str(error) if isinstance(error, (ValueError, AuthError)) else 'Request failed. Check the project folder and try again.'}


class Router:
    """The stdin side of the backend.

    One reader thread reads every line. Other methods run on one dispatcher thread in arrival order. Agent,
    scope and event requests run on their own small pool, so they never wait behind other requests.
    """

    def __init__(self, app, emit, agent_workers=2):
        self.app = app
        self.emit = emit
        self.legacy = queue.Queue()
        self.agents = ThreadPoolExecutor(max_workers=agent_workers, thread_name_prefix='agent')
        self.dispatcher = threading.Thread(target=self._dispatch, daemon=True, name='legacy-dispatch')
        self.dispatcher.start()

    def route(self, line):
        try:
            message = json.loads(line)
        except ValueError:
            message = None
        if isinstance(message, dict):
            method = message.get('method')
            if method in AGENT_METHODS:
                self.agents.submit(self._answer, message)
                return 'agent'
        self.legacy.put(line)
        return 'legacy'

    def _answer(self, request):
        self.emit(reply_for(request, self.app))

    def _dispatch(self):
        while True:
            line = self.legacy.get()
            if line is None:
                return
            self.emit(reply_for(line, self.app))

    def serve(self, stream, closed):
        for line in stream:
            self.route(line)
            if closed.is_set():
                break

    def close(self, timeout_s=30):
        self.legacy.put(None)
        self.dispatcher.join(timeout_s)
        self.agents.shutdown(wait=False)


class Application:
    """The backend for one data root. `provider` is the Codex sign-in helper (`codex_auth.CodexAuth` or a fake)."""

    def __init__(self, storage, provider=None, emit=None, *, scope_api=None, audit_api=None, runtime_factory=None,
                 interrupt_grace_s=scheduler.INTERRUPT_GRACE_S):
        self.storage = Path(storage).resolve()
        self.storage.mkdir(parents=True, exist_ok=True)
        self.provider = provider or CodexAuth()
        self.emit = emit or (lambda message: None)
        self.lock = threading.RLock()
        self._publish_guard = threading.Lock()
        self._last_publish = 0.0
        self._publish_timer = None
        self._history = {}  # Earlier tasks never change, so their read-only view is built once.
        self.cancel = threading.Event()
        self.worker = None
        self.state = projects.load(self.storage)
        budget.recover(self.state)  # A reservation held at shutdown is charged its estimate, never released.
        if self.state.get('active'):
            # A sign-in, or an interaction of an earlier version, was running when the app quit. Nothing resumes.
            self.state.update(active=None, active_project_id=None, active_run_id=None, active_task_id=None)
        self.setup_agents(scope_api, audit_api, runtime_factory, interrupt_grace_s)
        self.persist()

    def setup_agents(self, scope_api, audit_api, runtime_factory, interrupt_grace_s):
        """Agentic tasks (scheduler.md)."""
        self.scope = ScopeAdapter(scope_api if scope_api is not None else optional_module('scope'))
        if audit_api is None:
            module = optional_module('audit')
            audit_api = module.AuditLog(self.storage/'audit') if module is not None and hasattr(module,'AuditLog') else None
        self.audit = AuditAdapter(audit_api)
        self.events = scheduler.EventLog(self.storage/'tasks', forward=lambda event: self.emit({'type':'event','event':event}))
        self.store = AgentStore(self)
        self.locks = scheduler.Locks()
        scheduler.recover(self.store, self.events)
        settings = self.state.get('scheduler_settings')
        try:
            max_running = scheduler.validate_max_running(settings.get('max_running'))
        except (AttributeError, ValueError):
            max_running = scheduler.DEFAULT_MAX_RUNNING
        self.scheduler = scheduler.Scheduler(
            max_running=max_running, runtime_factory=runtime_factory or self.default_runtime_factory(), policy=self.scope,
            audit=self.audit, events=self.events, budget_gate=scheduler.BudgetGate(self.store), locks=self.locks,
            clock=time.time, tasks=self.store, workspaces=scheduler.Workspaces(self.storage/'workspaces'),
            interrupt_grace_s=interrupt_grace_s, decide_options={'app_data':str(self.storage)})

    def default_runtime_factory(self):
        """`runtime.make_factory(app)` -> `runtime_factory(task_id)`; `no_runtime` while it is absent or broken.

        The factory reads the task's `provider` (codex or claude) and `model` from `app.store.task(task_id)`.
        """
        module = optional_module('runtime')
        make = getattr(module, 'make_factory', None)
        if not callable(make):
            return self.no_runtime
        try:
            factory = make(self)
        except Exception:
            return self.no_runtime  # Agent turns then fail closed with runtime_unavailable; the app still opens.
        return factory if callable(factory) else self.no_runtime

    @staticmethod
    def no_runtime(task_id):
        raise ValueError('The agent runtime is not in this build yet.')

    def publish_soon(self):
        """Coarse state updates for agent tasks, at most 4 per second; the last change is always published."""
        if getattr(self, 'scheduler', None) is None:
            return  # Startup recovery: the first state is sent when the UI asks for it.
        with self._publish_guard:
            wait = self._last_publish + STATE_PUBLISH_INTERVAL_S - time.monotonic()
            if wait > 0:
                if self._publish_timer is None:
                    self._publish_timer = threading.Timer(wait, self._timed_publish)
                    self._publish_timer.daemon = True
                    self._publish_timer.start()
                return
            self._last_publish = time.monotonic()
        self.emit({'type':'state','state':self.public()})

    def _timed_publish(self):
        with self._publish_guard:
            self._publish_timer = None
            self._last_publish = time.monotonic()
        self.emit({'type':'state','state':self.public()})

    def persist(self):
        runner.save(self.storage / 'state.json', self.state)

    def publish(self):
        self.persist()
        self.emit({'type':'state','state':self.public()})

    def wait(self):
        if self.worker:
            self.worker.join(timeout=30)

    # -- projection --------------------------------------------------------------------------------

    def summaries(self):
        return [{key:project.get(key,'') for key in ('id','name','brief','priority','next_action')}
                for project in self.state['projects'].values()]

    def task_summaries(self, project):
        result=[]
        for identity,task in tasks.entries(project):
            try:
                tasks.validate(task,identity)
                row=dict(id=identity,title=task['title'],mode=task.get('mode','review'))
                if row['mode']=='agent':
                    row.update(status=task['agent'].get('state') or 'draft',provider=tasks.provider(task),model=task.get('model'))
                else:
                    row.update(status='read_only',read_only=True)
                result.append(row)
            except ValueError:
                result.append(dict(id=identity,title='Unavailable saved task',status='unavailable'))
        return result

    def public(self):
        with self.lock:
            project = self.state['projects'].get(self.state['selected_project_id'])
            task=None;task_error=''
            if project:
                try:task=tasks.selected(project)
                except ValueError as error:task_error=str(error)
            data = copy.deepcopy({key:self.state[key] for key in ('version','active','connection')})
            data.update(task_id=project.get('selected_task_id') if project and isinstance(project.get('selected_task_id'),str) else None,
                        task=self.task_view(task) if task else None,
                        tasks=self.task_summaries(project) if project else [],
                        project_id=project['id'] if project else None,project=project['name'] if project else None,
                        projects=self.summaries())
            data['scheduler']=self.scheduler.snapshot()
            # Only app-level errors (sign-in) are shown here; an earlier task's error is part of its history.
            app_error=self.state.get('error_project_id') is None and self.state.get('error_task_id') is None
            data['error']=task_error or (self.state.get('error','') if app_error else '')
            return data

    def task_view(self, task):
        view={'id':task['id'],'title':task['title'],'mode':task.get('mode','review'),'token_budget':task.get('token_budget'),
              'tokens':self.token_summary(task),'agent':self.agent_summary(task)}
        if view['mode']!='agent':
            if task['id'] not in self._history:
                self._history[task['id']]=tasks.history(task,self.storage/'runs')
            view['history']=copy.deepcopy(self._history[task['id']])
        return view

    def agent_summary(self, task):
        """Agent run state and scope approval for the task view; the scope itself comes from scope_get."""
        if task.get('mode')!='agent':return None
        scope=task.get('scope') or {}
        try:approved=self.scheduler.approved(task)
        except (KeyError,TypeError,ValueError):approved=False
        agent=task['agent']
        return {'state':agent.get('state'),'detail':agent.get('detail',''),'reason':agent.get('reason'),
                'provider':tasks.provider(task),'model':task.get('model'),
                'scope_version':scope.get('version'),'scope_approved':approved,'project_id':agent['project_id'],
                'last_seq':self.events.last_seq(task['id'])}

    def token_summary(self, task):
        totals=budget.ledger(self.state,task['id'],task.get('token_budget'))
        return {k:v for k,v in totals.items() if k!='entries'}

    # -- requests ----------------------------------------------------------------------------------

    def handle(self, method, params):
        if not isinstance(params, dict):
            raise ValueError('request params must be an object')
        if method in AGENT_METHODS:
            return self.handle_agent(method, params)
        if method not in APP_METHODS:
            raise ValueError('Unknown method')
        with self.lock:
            if method == 'state':
                return self.public()
            if method == 'connection':
                self.state['connection'] = self.provider.status()
                self.publish()
                return self.public()
            if method == 'cancel':
                self.cancel.set()
                return {'cancellation_requested':bool(self.state['active'])}
            if method == 'sign_in':
                self.start_sign_in()
                return {'started':True}
            if method == 'switch_project':
                identity = params.get('project_id')
                if not isinstance(identity,str) or identity not in self.state['projects']:
                    raise ValueError('Unknown project.')
                self.state['selected_project_id'] = identity
                self.publish()
                return self.public()
            if method=='select_task':
                project=projects.selected(self.state,params)
                identity=params.get('task_id')
                if 'task_id' not in params:raise ValueError('Choose a task.')
                if identity is not None:
                    if not isinstance(identity,str):raise ValueError('Unknown task.')
                    tasks.validate(dict(tasks.entries(project)).get(identity),identity)
                project['selected_task_id']=identity
                self.publish()
                return self.public()
            if method in ('add_project','select_project'):
                projects.register(self.state,params.get('path'),self.storage)
                self.publish()
                return self.public()
            projects.update(projects.selected(self.state,params),params)
            self.publish()
            return self.public()

    def start_sign_in(self):
        """Codex device sign-in on its own thread. Stop (`cancel`) ends it; nothing else runs in this slot."""
        if self.state['active']:
            raise ValueError('Sign-in is already running. Stop it before starting again.')
        self.cancel.clear()
        self.state.update(active='Signing in',active_project_id=None,active_task_id=None,active_run_id=None,
                          error='',error_project_id=None,error_task_id=None)
        self.publish()

        def execute():
            try:
                self.provider.sign_in(self.cancel, lambda text: self.emit({'type':'auth','text':text}))
                with self.lock:
                    self.state['connection'] = self.provider.status()
            except Exception as error:
                with self.lock:
                    self.state['error'] = str(error) if isinstance(error,(ValueError,AuthError)) else 'Sign-in failed. Check the Codex installation.'
            finally:
                with self.lock:
                    self.state['active']=None
                    self.publish()
        self.worker = threading.Thread(target=execute,daemon=True,name='codex-sign-in')
        self.worker.start()

    def handle_agent(self, method, params):
        if method=='scheduler_settings':
            if 'max_running' in params:
                value=self.scheduler.set_max_running(params['max_running'])
                with self.lock:
                    self.state['scheduler_settings']={'max_running':value}
                    self.publish()
            return {'max_running':self.scheduler.max_running}
        if method=='agent_create':
            return self.agent_create(params)
        if method=='scope_default':
            return self.scope_default(params)
        task_id=params.get('task_id')
        with self.lock:
            task=self.store.task(task_id)
            if task.get('mode')!='agent':raise ValueError('This is not an agent task.')
            project_id=task['agent']['project_id']
        if method=='agent_message':
            result=self.scheduler.submit(task_id,project_id,params.get('text'),params.get('client_id'))
            return {'state':result['state'],'position':result['position']}
        if method=='agent_answer':
            return self.scheduler.answer(task_id,params.get('ask_id'),params.get('decision'),text=params.get('text'),
                                         scope_digest=params.get('scope_digest'),request_digest=params.get('request_digest'))
        if method=='agent_cancel':
            return {'cancellation_requested':self.scheduler.cancel(task_id)}
        if method=='task_events':
            return self.events.read(task_id,params.get('after_seq'),params.get('limit',500))
        if method=='task_blob':
            return self.events.blob(task_id,params.get('blob_id'))
        with self.lock:
            if method=='scope_get':
                return {'scope':copy.deepcopy(task['scope']),'scope_digest':self.scope.digest(task['scope']),
                        'scope_approval':copy.deepcopy(task.get('scope_approval'))}
            if method=='scope_update':
                return self.scope_update(task,params)
            if method=='scope_approve':
                return self.scope_approve(task,params)
        raise ValueError('Unknown method')

    def audit_scope(self, task, before, after, before_digest, after_digest):
        record={'v':1,'actor':'user','kind':'scope',
                'task_id':task['id'],'project_id':task['agent']['project_id'],'turn_id':None,'call_id':None,'request':None,
                'decision':None,'rule':None,'scope_version':after['version'],'scope_digest':after_digest,'outcome':None,
                'idempotency_key':None,'detail':{'from_version':before['version'] if before else None,'to_version':after['version'],
                                                 'from_digest':before_digest,'to_digest':after_digest}}
        try:
            self.audit.append(record)
        except Exception:
            raise ValueError('Could not record the scope change in the audit log, so nothing was changed.') from None

    def scope_event(self, task, change, summary):
        self.events.append(task['id'],task['agent']['project_id'],'scope',
                           {'scope_version':task['scope']['version'],'scope_digest':self.scope.digest(task['scope']),
                            'change':change,'by':'user','summary':summary})

    def scope_default(self, params):
        """The starting scope for the new agent task form; creates nothing (README coordinator ruling)."""
        with self.lock:
            project_id=params.get('project_id')
            project=self.state['projects'].get(project_id) if isinstance(project_id,str) else None
            if project is None:raise ValueError('Unknown project.')
            try:limit=budget.validate(project.get('token_budget'))
            except ValueError:limit=None  # A damaged saved project budget falls back to the default.
            builder=getattr(self.scope.module,'project_default',None) if self.scope.module is not None else None
            if builder is None:raise ValueError('Agent tasks need the scope engine, which is not in this build yet.')
            return {'scope':builder(project_id,token_budget=limit,project_ids=list(self.state['projects']))}

    def agent_create(self, params):
        with self.lock:
            project_id=params.get('project_id')
            project=self.state['projects'].get(project_id) if isinstance(project_id,str) else None
            if project is None:raise ValueError('Unknown project.')
            if not isinstance(project.get('tasks',{}),dict):raise ValueError('Saved tasks are unavailable; preserve app data before recovery.')
            runtime=tasks.validate_provider(params.get('provider',tasks.DEFAULT_PROVIDER))
            task=tasks.create(params.get('title','New agent task'),project_id=project_id,
                              provider=runtime,model=tasks.validate_model(params.get('model')))
            proposed=params.get('scope')
            document=self.scope.default(task,[project_id]) if proposed is None else copy.deepcopy(proposed)
            if not isinstance(document,dict):raise ValueError('Scope must be an object.')
            document.update(v=1,task_id=task['id'],version=1)
            self.scope.validate(document,project_ids=list(self.state['projects']))
            task.update(scope=document,token_budget=budget.validate(document['limits']['token_budget']))
            digest=self.scope.digest(document)
            self.audit_scope(task,None,document,None,digest)
            project.setdefault('tasks',{})[task['id']]=task
            project['selected_task_id']=task['id']
            self.scope_event(task,'edited','Scope drafted; approve it to start.')
            self.publish()
            return {'task_id':task['id'],'scope_digest':digest}

    def scope_update(self, task, params):
        current=task['scope']
        if type(params.get('base_version')) is not int or params['base_version']!=current['version']:
            raise ValueError('The scope changed since you opened it. Reload it and edit again.')
        if not isinstance(params.get('scope'),dict):raise ValueError('Scope must be an object.')
        document=copy.deepcopy(params['scope'])
        document.update(v=1,task_id=task['id'],version=current['version']+1)
        self.scope.validate(document,project_ids=list(self.state['projects']))
        limit=budget.validate(document['limits']['token_budget'])
        digest=self.scope.digest(document)
        self.audit_scope(task,current,document,self.scope.digest(current),digest)
        task.update(scope=document,scope_approval=None,token_budget=limit)
        self.scope_event(task,'edited','Scope edited; approve it before the task continues.')
        self.scheduler.scope_changed(task['id'])
        self.publish()
        return {'scope':copy.deepcopy(document),'scope_digest':digest}

    def scope_approve(self, task, params):
        current=task['scope'];digest=self.scope.digest(current)
        if params.get('scope_version')!=current['version'] or params.get('scope_digest')!=digest:
            raise ValueError('The scope changed since it was shown. Review it again before approving.')
        self.audit_scope(task,current,current,digest,digest)
        task['scope_approval']={'v':1,'scope_version':current['version'],'scope_digest':digest,
                                'approved_at':scheduler.iso_time(time.time()),'by':'user'}
        self.scope_event(task,'approved','Scope approved.')
        self.scheduler.scope_changed(task['id'])
        self.publish()
        return {'scope_approval':copy.deepcopy(task['scope_approval'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root',type=Path,required=True)
    args = parser.parse_args()
    output_lock = threading.Lock()
    output_closed = threading.Event()
    app = None
    def emit(message):
        if output_closed.is_set():
            return
        with output_lock:
            try:
                print(json.dumps(message,ensure_ascii=False),flush=True)
            except BrokenPipeError:
                output_closed.set()
                # Avoid a second broken-pipe error when Python flushes at shutdown.
                null = os.open(os.devnull, os.O_WRONLY)
                os.dup2(null, sys.stdout.fileno())
                os.close(null)
                if app:
                    app.cancel.set()
    import fcntl
    args.data_root = args.data_root.resolve()
    args.data_root.mkdir(parents=True,exist_ok=True)
    instance_lock = (args.data_root/'app.lock').open('a')
    try:
        fcntl.flock(instance_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        emit({'type':'fatal','error':'Interspace is already running with this workspace. Return to its existing window.'})
        return
    router = None
    try:
        app = Application(args.data_root,emit=emit)
        router = Router(app,emit)
        router.serve(sys.stdin,output_closed)
    finally:
        if router:
            router.close()
        if app:
            app.cancel.set()
            app.scheduler.shutdown()
            app.wait()
        instance_lock.close()


if __name__=='__main__':
    main()
