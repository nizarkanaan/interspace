"""Task metadata and exact ownership, independent of the selected UI context."""
import hashlib
import json
from pathlib import Path
import uuid

import orchestration


def title(value):
    if not isinstance(value,str) or not value.strip() or len(value)>160:
        raise ValueError('Task title must contain 1–160 characters.')
    return value.strip()


def draft_text(value):
    if not isinstance(value,str) or len(value)>6000:
        raise ValueError('Task draft must be text of at most 6000 characters.')
    return value


def create(name='New task', specialist_limit=6, draft=''):
    return {'id':uuid.uuid4().hex,'title':title(name),
            'specialist_limit':orchestration.validate_specialist_limit(specialist_limit),'draft':draft_text(draft),
            'thread':[],'pending':None,'run_id':None,'run_ids':[],'error':'','error_status':None}


def validate(task, identity):
    try:
        if not isinstance(task,dict) or task['id']!=identity:raise ValueError()
        title(task['title']);orchestration.validate_specialist_limit(task['specialist_limit']);draft_text(task.get('draft',''))
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
    elif plan.get('policy_version')==2 and plan.get('limits',{}).get('specialist_limit')!=owner['specialist_limit']:
        raise ValueError('Task allowance changed; request a new proposal.')


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
