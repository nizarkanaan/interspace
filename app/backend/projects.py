"""Versioned personal project registry. Source folders are never written here."""
import copy
import json
from pathlib import Path
import uuid

import runner
import tasks


def empty_state():
    return {'version':4, 'projects':{}, 'selected_project_id':None,
            'threads':{'workspace':[]}, 'active':None, 'active_project_id':None,
            'active_run_id':None, 'active_task_id':None, 'error_task_id':None, 'error':'', 'error_project_id':None, 'usage':[],
            'connection':{'ready':False,'message':'Not checked yet'}}


def new_project(source):
    identity = uuid.uuid4().hex
    return {'id':identity,'name':Path(source).name,'source_path':str(source),
            'source_selection':{'mode':'unconfirmed','version':1,'selection_version':0,'revision':None,'paths':[]},
            'context_path':'docs/PROJECT_CONTEXT.md','thread':[], 'pending':None,
            'run_id':None,'run_ids':[], 'tasks':{},'selected_task_id':None, 'brief':'','priority':'normal','next_action':''}


def load(storage):
    path = storage/'state.json'
    if not path.exists():
        return empty_state()
    raw = path.read_bytes()
    old = json.loads(raw)
    if old.get('version') == 4:
        return old
    if old.get('version') == 3:
        backup(storage,3,raw)
        return add_token_budgets(old)
    if old.get('version') == 2:
        backup(storage,2,raw)
        return add_token_budgets(tasks.migrate(old,storage))
    if old.get('version') != 1:
        raise ValueError('Unsupported state schema version. Saved data was not changed.')
    # Exclusive creation keeps the first original backup across interrupted migrations.
    try:
        with (storage/'state.v1-backup.json').open('xb') as original_backup:
            original_backup.write(raw)
    except FileExistsError:
        pass
    state = empty_state()
    for key in ('active','error','usage','connection'):
        if key in old:
            state[key] = copy.deepcopy(old[key])
    state['threads']['workspace'] = old['threads']['workspace']
    if old.get('project_path'):
        project = new_project(old['project_path'])
        project.pop('source_selection')
        project.update(thread=old['threads']['project'],pending=old.get('pending'),run_id=old.get('run_id'))
        if project['pending']:
            project['pending']['project_id'] = project['id']
        if project['run_id']:
            project['run_ids'] = [project['run_id']]
        state['projects'][project['id']] = project
        state['selected_project_id'] = project['id']
        if state['active']:
            state.update(active_project_id=project['id'],active_run_id=project['run_id'])
        if state['error']:
            state['error_project_id'] = project['id']
        for entry in state['usage']:
            if entry.get('run_id') in project['run_ids']:
                entry['project_id'] = project['id']
    state['version']=2
    backup(storage,2,json.dumps(state,ensure_ascii=False).encode())
    return add_token_budgets(tasks.migrate(state,storage))


def add_token_budgets(state):
    """Version 4: tasks that existed before budgets have none; usage history is kept as-is."""
    for project in state.get('projects',{}).values():
        saved=project.get('tasks') if isinstance(project,dict) else None
        for task in (saved.values() if isinstance(saved,dict) else ()):
            if isinstance(task,dict):task['token_budget']=None
    state['version']=4
    return state


def backup(storage, version, raw):
    try:
        with (storage/('state.v'+str(version)+'-backup.json')).open('xb') as output:
            output.write(raw)
    except FileExistsError:
        pass


def selected(state, reference=None):
    identity = state['selected_project_id']
    if not identity or identity not in state['projects']:
        raise ValueError('Choose a project first.')
    if reference is not None and reference.get('project_id') != identity:
        raise ValueError('The selected project changed; this request is stale.')
    return state['projects'][identity]


def register(state, source, storage):
    if not isinstance(source,str) or not source.strip():
        raise ValueError('Enter a repository folder path.')
    source = Path(source).expanduser().resolve()
    if not source.is_dir() or storage.is_relative_to(source) or source.is_relative_to(storage):
        raise ValueError('Choose a Git repository separate from Interspace app data.')
    # A nested folder must not accidentally identify a different scope of the same repo.
    root = Path(runner.git(source,'rev-parse','--show-toplevel').decode().strip()).resolve()
    if source != root:
        raise ValueError('Choose the Git repository root folder.')
    head = runner.git(source,'rev-parse','HEAD').decode().strip()
    runner.git(source,'show',head+':README.md')
    names = runner.git(source,'ls-tree','-r','--name-only',head).decode().splitlines()
    context = 'docs/PROJECT_CONTEXT.md' if 'docs/PROJECT_CONTEXT.md' in names else 'README.md'
    project = next((p for p in state['projects'].values() if p['source_path']==str(source)),None)
    if project is None:
        project = new_project(source)
        state['projects'][project['id']] = project
    project['context_path'] = context
    state['selected_project_id'] = project['id']
    return project


def update(project, params):
    limits = {'name':64,'brief':1200,'next_action':500}
    updates = {}
    for key, limit in limits.items():
        if key in params:
            value = params[key]
            if not isinstance(value,str) or len(value)>limit or (key=='name' and not value.strip()):
                raise ValueError(key+' must contain '+('1–' if key=='name' else 'at most ')+str(limit)+' characters.')
            updates[key] = value.strip()
    if 'priority' in params:
        if params['priority'] not in ('high','normal','low'):
            raise ValueError('Choose high, normal or low priority.')
        updates['priority'] = params['priority']
    project.update(updates)
