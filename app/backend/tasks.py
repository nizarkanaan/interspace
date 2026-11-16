"""Task metadata and exact ownership, independent of the selected UI context.

New tasks are agent tasks. Tasks of the earlier modes (`review`, `python_fix`) still load and are shown
read-only through `history`; nothing in them can run.
"""
import hashlib
import json
from pathlib import Path
import re
import uuid

import budget

MODES = ('agent',)
LEGACY_MODES = ('review','python_fix')
# Agent task run states (events.md `status`); None means no turn has started yet.
AGENT_STATES = ('queued','starting','running','waiting_lock','paused_ask','paused_scope','paused_team','idle','cancelling',
                'completed','failed','cancelled','budget_exhausted','time_limit','interrupted')
# Agent runtimes (scheduler.md runtime adapter): Codex app-server (2A) or Claude Code (2B).
PROVIDERS = ('codex','claude')
DEFAULT_PROVIDER = 'codex'
MODEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,127}$')
MAX_SAFE_INTEGER = 9007199254740991
# Saved run stages that ended; any other saved stage was cut off when an earlier version quit.
FINISHED_STAGES = ('completed','completed_unreviewed','accepted','needs_revision','blocked','failed','cancelled',
                   'interrupted','integrity_failed','budget_exhausted','awaiting_test_approval','ready_to_apply',
                   'applied','application_failed','recovery_required','abandoned')
MAX_REPORT_CHARS = 24000
# Agent task roles (orchestration.md): every new task is an Orchestrator task; subagents are child tasks with a
# team role. `implementer` and `tester` are write roles (providers.md); the other team roles read only.
ORCHESTRATOR = 'orchestrator'
TEAM_ROLES = ('researcher','implementer','reviewer','tester','writer')
WRITE_ROLES = ('implementer','tester')
ROLES = (ORCHESTRATOR,)+TEAM_ROLES
ACCESS = ('read','write')
MAX_BRIEF_CHARS = 6000
CHILD_FIELDS = ('parent_task_id','brief','access','team_id','member_id')


def title(value):
    if not isinstance(value,str) or not value.strip() or len(value)>160:
        raise ValueError('Task title must contain 1–160 characters.')
    return value.strip()


def draft_text(value):
    if not isinstance(value,str) or len(value)>6000:
        raise ValueError('Task draft must be text of at most 6000 characters.')
    return value


def validate_mode(value):
    if value not in MODES+LEGACY_MODES:raise ValueError('Unknown task mode.')
    return value


def validate_specialist_limit(value):
    """The specialist allowance of an earlier task (kept for loading saved tasks)."""
    if type(value) is not int or not 1<=value<=MAX_SAFE_INTEGER:
        raise ValueError('Specialist allowance must be a positive JavaScript-safe integer.')
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


def create(name='New agent task', *, project_id, provider=None, model=None, token_budget=budget.DEFAULT_BUDGET):
    """A new Orchestrator task. The scope (scope.md) is attached by the caller, which needs the task ID to build it."""
    if not isinstance(project_id,str) or not project_id:raise ValueError('An agent task needs a project.')
    return {'id':uuid.uuid4().hex,'title':title(name),'mode':'agent','role':ORCHESTRATOR,'draft':'',
            'token_budget':budget.validate(token_budget),'thread':[],'pending':None,'run_id':None,'run_ids':[],
            'error':'','error_status':None,'scope':None,'scope_approval':None,
            'provider':validate_provider(DEFAULT_PROVIDER if provider is None else provider),'model':validate_model(model),
            'agent':{'project_id':project_id,'state':None,'detail':'','reason':None,'turns':0,'active_s':0.0,'workspaces':{}}}


def role(task):
    """The task's role; agent tasks saved before the Orchestrator have none and run as plain agent tasks."""
    return task.get('role')


def brief(value):
    if not isinstance(value,str) or not value.strip() or len(value)>MAX_BRIEF_CHARS:
        raise ValueError('A subagent brief must contain 1–6,000 characters.')
    return value.strip()


def validate_access(value):
    if value not in ACCESS:raise ValueError('Access must be read or write.')
    return value


def child(parent, *, role, brief_text, provider, model, access, team_id, member_id):
    """A subagent row (orchestration.md): a normal agent task with the child fields. Scope is attached by the caller."""
    if role not in TEAM_ROLES:raise ValueError('Unknown subagent role.')
    text=brief(brief_text)
    label=role.capitalize()+': '+' '.join(text.split())
    task=create(label if len(label)<=160 else label[:159]+'…',project_id=parent['agent']['project_id'],
                provider=provider,model=model,token_budget=parent.get('token_budget'))
    task.update(role=role,brief=text,access=validate_access(access),parent_task_id=parent['id'],
                team_id=team_id,member_id=member_id)
    return task


def imported(name):
    """An earlier-mode review row for runs and plans migrated from schema version 2 (read-only)."""
    return {'id':uuid.uuid4().hex,'title':title(name),'mode':'review','specialist_limit':6,'draft':'',
            'token_budget':budget.DEFAULT_BUDGET,'thread':[],'pending':None,'run_id':None,'run_ids':[],'error':'','error_status':None}


def validate_agent(task):
    """Shape checks for the agent fields; scope contents are validated by scope.validate at the boundary."""
    agent=task.get('agent')
    if not isinstance(agent,dict) or not isinstance(agent.get('project_id'),str):raise ValueError()
    if agent.get('state') is not None and agent['state'] not in AGENT_STATES:raise ValueError()
    if type(agent.get('turns',0)) is not int or not isinstance(agent.get('workspaces',{}),dict):raise ValueError()
    if not isinstance(agent.get('active_s',0.0),(int,float)) or isinstance(agent.get('active_s'),bool):raise ValueError()
    validate_provider(task.get('provider',DEFAULT_PROVIDER))
    if task.get('role') is not None and task['role'] not in ROLES:raise ValueError()
    if task.get('parent_task_id') is not None:
        if task.get('role') not in TEAM_ROLES or task.get('access') not in ACCESS:raise ValueError()
        brief(task.get('brief'))
        if any(not isinstance(task.get(k),str) or not task[k] for k in ('parent_task_id','team_id','member_id')):raise ValueError()
    elif any(task.get(k) is not None for k in CHILD_FIELDS):raise ValueError()
    if validate_model(task.get('model'))!=task.get('model'):raise ValueError()
    if task.get('scope') is not None and not isinstance(task['scope'],dict):raise ValueError()
    if task.get('scope_approval') is not None and not isinstance(task['scope_approval'],dict):raise ValueError()


def validate(task, identity):
    try:
        if not isinstance(task,dict) or task['id']!=identity:raise ValueError()
        if validate_mode(task.get('mode','review'))=='agent':
            validate_agent(task)
            if 'specialist_limit' in task:validate_specialist_limit(task['specialist_limit'])
        else:
            validate_specialist_limit(task['specialist_limit'])
        title(task['title']);budget.validate(task.get('token_budget'));draft_text(task.get('draft',''))
        if not isinstance(task['thread'],list) or not isinstance(task['run_ids'],list):raise ValueError()
        for message in task['thread']:
            if (not isinstance(message,dict) or message.get('role') not in ('user','assistant')
                    or not isinstance(message.get('text'),str)):
                raise ValueError()
        if not isinstance(task.get('error',''),str):raise ValueError()
        status=task.get('error_status')
        if status is not None and (not isinstance(status,str) or status not in FINISHED_STAGES):raise ValueError()
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


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()


# -- read-only history of earlier tasks ------------------------------------------------------------

def _clip(text, limit=MAX_REPORT_CHARS):
    return text if len(text)<=limit else text[:limit-1]+'…'


def _str(value):
    return value if isinstance(value,str) else ''


def plan_text(plan):
    """Plain text of a saved plan or proposal: its goal and each assignment. Unknown shapes give ''."""
    if not isinstance(plan,dict):return ''
    lines=[]
    if _str(plan.get('goal')).strip():lines.append('Goal: '+plan['goal'].strip())
    for item in plan.get('tasks') if isinstance(plan.get('tasks'),list) else ():
        if not isinstance(item,dict):continue
        name=_str(item.get('label')) or _str(item.get('role')).replace('_',' ').capitalize() or 'Assignment'
        line='- '+name+': '+_str(item.get('objective')).strip()
        if _str(item.get('expected_output')).strip():line+=' (expected: '+item['expected_output'].strip()+')'
        lines.append(line)
    if isinstance(plan.get('roles'),list) and all(isinstance(r,str) for r in plan['roles']):
        lines.append('Roles: '+' → '.join(plan['roles']))
    return _clip('\n'.join(lines))


def _artifact_text(heading, artifact):
    if not isinstance(artifact,dict):return ''
    lines=[heading+(' · '+artifact['verdict'] if _str(artifact.get('verdict')) and artifact['verdict']!='not_reviewed' else '')]
    if _str(artifact.get('summary')).strip():lines.append(artifact['summary'].strip())
    for finding in artifact.get('findings') if isinstance(artifact.get('findings'),list) else ():
        if isinstance(finding,dict) and _str(finding.get('claim')).strip():lines.append('- '+finding['claim'].strip())
    if _str(artifact.get('proposal')).strip():lines.append('Proposal (not executed): '+artifact['proposal'].strip())
    questions=[q for q in artifact.get('questions') if isinstance(q,str) and q.strip()] if isinstance(artifact.get('questions'),list) else []
    if questions:lines.append('Open questions:\n'+'\n'.join('- '+q.strip() for q in questions))
    return '\n'.join(lines)


def report_text(record):
    """The final report of a saved run: the combined result, else the legacy research and review."""
    if not isinstance(record,dict):return ''
    if isinstance(record.get('combined'),dict):
        return _clip(_artifact_text('Combined result',record['combined']))
    results=record.get('results') if isinstance(record.get('results'),dict) else {}
    parts=[_artifact_text('Research report',results.get('researcher')),_artifact_text('Independent review',results.get('reviewer'))]
    return _clip('\n\n'.join(p for p in parts if p))


def _run(runs, run_id):
    if not isinstance(run_id,str) or not run_id or Path(run_id).name!=run_id:raise ValueError()
    record=json.loads((runs/run_id/'run.json').read_text(encoding='utf-8'))
    if not isinstance(record,dict):raise ValueError()
    return record


def history(task, runs):
    """What an earlier task shows, read-only: its conversation, plan text and final report text per run.

    Reads saved run records under `runs` and never writes them. Nothing in the result can start work.
    """
    reports=[];plan=plan_text(task.get('pending'))
    for run_id in reversed(task.get('run_ids') or []):
        try:
            record=_run(runs,run_id)
        except (OSError,ValueError,TypeError):
            reports.append({'run_id':str(run_id),'goal':'','stage':'unavailable','text':'This saved report is unavailable.'})
            continue
        stage=_str(record.get('stage')) or 'unknown'
        reports.append({'run_id':run_id,'goal':_clip(_str(record.get('goal')),2000),
                        'stage':stage if stage in FINISHED_STAGES else 'interrupted','text':report_text(record)})
        if not plan:plan=plan_text(record.get('plan'))
    return {'mode':task.get('mode','review'),'label':'Earlier task (read-only)',
            'messages':[{'role':m['role'],'text':m['text']} for m in task.get('thread') or []],
            'plan':plan,'reports':reports,'error':_str(task.get('error'))}


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
            task=imported(goal[:160] if isinstance(goal,str) and goal.strip() else 'Imported review')
            task.update(run_id=run_id,run_ids=[run_id])
            project['tasks'][task['id']]=task;run_owners[run_id]=task
        pending=project['pending']
        pending_owner=None
        if pending:
            pending_owner=run_owners.get(pending.get('run_id')) if pending.get('kind')=='revision' else None
            if pending_owner is None:
                goal=pending.get('goal','Imported task')
                pending_owner=imported(goal[:160] if isinstance(goal,str) and goal.strip() else 'Imported task')
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
