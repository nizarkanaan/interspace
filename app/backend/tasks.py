"""Task metadata and exact ownership, independent of the selected UI context."""
import hashlib
import json
import re
from pathlib import Path
import uuid

import budget
import orchestration

MODES = ('review','python_fix','agent')
# Agent task run states (events.md `status`); None means no turn has started yet.
AGENT_STATES = ('queued','starting','running','waiting_lock','paused_ask','paused_scope','idle','cancelling',
                'completed','failed','cancelled','budget_exhausted','time_limit','interrupted')
# Agent runtimes (scheduler.md runtime adapter): Codex app-server (2A) or Claude Code (2B).
PROVIDERS = ('codex','claude')
DEFAULT_PROVIDER = 'codex'
MODEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,127}$')


def title(value):
    if not isinstance(value,str) or not value.strip() or len(value)>160:
        raise ValueError('Task title must contain 1–160 characters.')
    return value.strip()


def draft_text(value):
    if not isinstance(value,str) or len(value)>6000:
        raise ValueError('Task draft must be text of at most 6000 characters.')
    return value


def validate_mode(value):
    if value not in MODES:raise ValueError('Choose review, python_fix or agent task mode.')
    return value


def validate_provider(value):
    if value not in PROVIDERS:raise ValueError('Choose the codex or claude runtime.')
    return value


def validate_model(value):
    """An optional model name passed to the runtime; None (or blank) means the runtime's default."""
    if value is None:return None
    if not isinstance(value,str):raise ValueError('The model must be a model name.')
    value=value.strip()
    if not value:return None
    if not MODEL.match(value):raise ValueError('The model must be a model name of at most 128 letters, digits and . _ : / - [ ].')
    return value


def provider(task):
    """The runtime an agent task runs on; agent tasks saved before Wave 2 run on Codex."""
    return task.get('provider',DEFAULT_PROVIDER)


def create(name='New task', specialist_limit=6, draft='', mode='review', token_budget=budget.DEFAULT_BUDGET, project_id=None,
           provider=None, model=None):
    task={'id':uuid.uuid4().hex,'title':title(name),'mode':validate_mode(mode),
          'specialist_limit':orchestration.validate_specialist_limit(specialist_limit),'draft':draft_text(draft),
          'token_budget':budget.validate(token_budget),'thread':[],'pending':None,'run_id':None,'run_ids':[],'error':'','error_status':None}
    if mode!='agent' and (provider is not None or model is not None):
        raise ValueError('Only agent tasks choose a runtime or model.')
    if mode=='agent':
        # The scope (scope.md) is attached by the caller, which needs the task ID to build it.
        if not isinstance(project_id,str) or not project_id:raise ValueError('An agent task needs a project.')
        task.update(scope=None,scope_approval=None,provider=validate_provider(DEFAULT_PROVIDER if provider is None else provider),
                    model=validate_model(model),
                    agent={'project_id':project_id,'state':None,'detail':'','reason':None,'turns':0,'active_s':0.0,'workspaces':{}})
    return task


def validate_agent(task):
    """Shape checks for the agent fields; scope contents are validated by scope.validate at the boundary."""
    agent=task.get('agent')
    if not isinstance(agent,dict) or not isinstance(agent.get('project_id'),str):raise ValueError()
    if agent.get('state') is not None and agent['state'] not in AGENT_STATES:raise ValueError()
    if type(agent.get('turns',0)) is not int or not isinstance(agent.get('workspaces',{}),dict):raise ValueError()
    if not isinstance(agent.get('active_s',0.0),(int,float)) or isinstance(agent.get('active_s'),bool):raise ValueError()
    validate_provider(task.get('provider',DEFAULT_PROVIDER))
    if validate_model(task.get('model'))!=task.get('model'):raise ValueError()
    if task.get('scope') is not None and not isinstance(task['scope'],dict):raise ValueError()
    if task.get('scope_approval') is not None and not isinstance(task['scope_approval'],dict):raise ValueError()


def validate(task, identity):
    try:
        if not isinstance(task,dict) or task['id']!=identity:raise ValueError()
        if validate_mode(task.get('mode','review'))=='agent':validate_agent(task)
        title(task['title']);orchestration.validate_specialist_limit(task['specialist_limit']);budget.validate(task.get('token_budget'));draft_text(task.get('draft',''))
        if not isinstance(task['thread'],list) or not isinstance(task['run_ids'],list):raise ValueError()
        for message in task['thread']:
            if (not isinstance(message,dict) or message.get('role') not in ('user','assistant')
                    or not isinstance(message.get('text'),str)):
                raise ValueError()
        if not isinstance(task.get('error',''),str):raise ValueError()
        status=task.get('error_status')
        if status is not None and (not isinstance(status,str) or status not in orchestration.TERMINAL):raise ValueError()
        if any(not isinstance(r,str) or not r for r in task['run_ids']):raise ValueError()
        if task['run_id'] is not None and task['run_id'] not in task['run_ids']:raise ValueError()
        pending=task['pending']
        if pending is not None:
            if not isinstance(pending,dict) or not isinstance(pending.get('id'),str) or not pending['id'].strip():
                raise ValueError()
    except (KeyError,TypeError,ValueError):
        raise ValueError('Saved task is unavailable. Preserve app data before recovery.') from None
    return task


def entries(project):
    saved=project.get('tasks',{})
    return saved.items() if isinstance(saved,dict) else ()


def available(project):
    for identity,task in entries(project):
        try:yield validate(task,identity)
        except ValueError:continue


def selected(project):
    if not isinstance(project.get('tasks',{}),dict):
        raise ValueError('Saved task list is unavailable. Preserve app data before recovery.')
    identity=project.get('selected_task_id')
    if identity is None:return None
    if not isinstance(identity,str):
        raise ValueError('Saved task selection is unavailable. Preserve app data before recovery.')
    return validate(dict(entries(project)).get(identity),identity)


def owner(project, reference):
    task=selected(project)
    if reference.get('task_id')!=(task['id'] if task else None):
        raise ValueError('The selected task changed; this request is stale or missing its task reference.')
    return task if task is not None else project


def run_ids(project):
    return project['run_ids']+[r for task in available(project) for r in task['run_ids']]


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def clear_pending(project, owner, disposition='revoked'):
    """Clear a proposal while retaining imported provenance and its terminal lifecycle."""
    pending=owner.get('pending')
    if isinstance(pending,dict):
        identity=pending.get('id')
        binding=project.get('imported_plan_owners',{}).get(identity)
        if binding and owner is not project and binding.get('task_id')==owner['id']:
            states=project.setdefault('imported_plan_states',{})
            if states.get(identity) not in ('revoked','consumed'):
                states[identity]=disposition
    owner['pending']=None


def validate_plan_owner(project, owner, plan):
    binding=project.get('imported_plan_owners',{}).get(plan.get('id'))
    if binding is not None:
        if owner is project or binding!={'task_id':owner['id'],'fingerprint':fingerprint(plan)}:
            raise ValueError('Imported approval belongs to a different task or changed.')
        if project.get('imported_plan_states',{}).get(plan['id'])!='live':
            raise ValueError('Imported approval is no longer live (revoked or consumed). Request a new proposal.')
        return
    if owner is project:
        if plan.get('task_id') is not None:raise ValueError('Plan belongs to a task.')
    elif plan.get('task_id')!=owner['id']:
        raise ValueError('Plan belongs to a different task.')
    elif (plan.get('policy_version')==2 or plan.get('kind')=='change') and plan.get('limits',{}).get('specialist_limit')!=owner['specialist_limit']:
        raise ValueError('Task allowance changed; request a new proposal.')
    if owner is not project and (plan.get('policy_version')==2 or plan.get('kind')=='change') and plan.get('limits',{}).get('token_budget')!=owner.get('token_budget'):
        raise ValueError('Task token budget changed; request a new proposal.')


def migrate(state, storage):
    """Move legacy ownership once; never rewrite approval or artifact contents."""
    state.update(version=3,active_task_id=None,error_task_id=None)
    for project in state['projects'].values():
        project.update(tasks={},selected_task_id=None,imported_plan_owners={},imported_plan_states={})
        run_owners={}
        for run_id in project['run_ids']:
            try:
                if not isinstance(run_id,str) or Path(run_id).name!=run_id:raise ValueError('Invalid run ID')
                run_path=storage/'runs'/run_id/'run.json'
                if run_path.resolve().parent!=storage/'runs'/run_id:raise ValueError('Relocated run')
                record=json.loads(run_path.read_text())
                goal=record.get('goal','Imported review') if isinstance(record,dict) else 'Imported review'
            except (OSError,ValueError):goal='Imported review'
            task=create(goal[:160] if isinstance(goal,str) and goal.strip() else 'Imported review')
            task.update(run_id=run_id,run_ids=[run_id])
            project['tasks'][task['id']]=task;run_owners[run_id]=task
        pending=project['pending']
        pending_owner=None
        if pending:
            pending_owner=run_owners.get(pending.get('run_id')) if pending.get('kind')=='revision' else None
            if pending_owner is None:
                goal=pending.get('goal','Imported task')
                pending_owner=create(goal[:160] if isinstance(goal,str) and goal.strip() else 'Imported task')
                project['tasks'][pending_owner['id']]=pending_owner
            pending_owner['pending']=pending
            project['imported_plan_owners'][pending['id']]={'task_id':pending_owner['id'],'fingerprint':fingerprint(pending)}
            project['imported_plan_states'][pending['id']]='live'
        selected_owner=pending_owner or run_owners.get(project['run_id'])
        project['selected_task_id']=selected_owner['id'] if selected_owner else None
        if state.get('active_project_id')==project['id']:
            active_owner=run_owners.get(state.get('active_run_id')) or pending_owner
            state['active_task_id']=active_owner['id'] if active_owner else None
        if state.get('error_project_id')==project['id']:
            state['error_task_id']=state['active_task_id'] or (selected_owner['id'] if selected_owner else None)
            error_owner=project['tasks'].get(state['error_task_id'])
            if error_owner and state.get('error'):
                error_owner.update(error=state['error'],error_status='failed')
        for entry in state['usage']:
            task=run_owners.get(entry.get('run_id'))
            if task and entry.get('project_id')==project['id']:
                if 'task_id' in entry:entry['assignment_id']=entry['task_id']
                entry['task_id']=task['id']
        project.update(run_id=None,run_ids=[],pending=None)
    return state
