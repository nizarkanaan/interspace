"""Bounded Python replacement policy and immutable evidence; no execution authority."""
import copy
import difflib
import json
import math
import os
from pathlib import Path
import re
import stat
import unicodedata

import orchestration as policy
import runner
import sources

FORMAT='change-v1'
ROLES=('researcher','implementer','tester','reviewer')
CHECKS=('baseline','regression','candidate')
TERMINAL=policy.TERMINAL|{'ready_to_apply','applied','application_failed','recovery_required','abandoned'}
MAX_WRITE_PATHS=8
MAX_FILE_BYTES=100000
MAX_TOTAL_BYTES=200000
RECIPE='python_unittest_v1'


def _canonical(name):
    return unicodedata.normalize('NFC',name).casefold()


def _write_paths(value):
    if not isinstance(value,list) or len(value)>MAX_WRITE_PATHS:
        raise ValueError('At most eight Python write paths are allowed.')
    for name in value:
        if sources.path_reason(name) or not name.endswith('.py') or any(p.startswith('.') or sources.path_reason(p) for p in name.split('/')):
            raise ValueError('Invalid Python write path.')
    keys=[_canonical(p) for p in value]
    if len(set(keys))!=len(keys) or any(a.startswith(b+'/') for a in keys for b in keys if a!=b):raise ValueError('Duplicate, overlapping or case-colliding write paths.')
    return sorted(value)


def _tasks(tasks,limit):
    limit=policy.validate_specialist_limit(limit)
    if not isinstance(tasks,list) or not 3<=len(tasks)<=limit:raise ValueError('Editing needs Implementer, Tester and Reviewer within the allowance.')
    normalized=[]
    for task in tasks:
        policy.fields(task,('id','role','objective','expected_output','dependencies','write_paths'),'editing assignment')
        identity=policy.text(task['id'],'Assignment ID',40)
        if identity in policy.RESERVED_TASK_IDS or not re.fullmatch('[a-z][a-z0-9_-]{0,39}',identity) or task['role'] not in ROLES:raise ValueError('Unsupported editing assignment.')
        policy.text(task['objective'],'Assignment',2000);policy.text(task['expected_output'],'Expected output',1000)
        deps=task['dependencies']
        if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps) or len(set(deps))!=len(deps):raise ValueError('Invalid dependencies.')
        paths=_write_paths(task['write_paths'])
        if (task['role']=='implementer')!=bool(paths):raise ValueError('Only Implementers require write paths.')
        normalized.append(dict(copy.deepcopy(task),write_paths=paths))
    ids=[t['id'] for t in normalized]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate assignment ID.')
    ordered=[]
    while len(ordered)<len(tasks):
        ready=[t for t in normalized if t['id'] not in {x['id'] for x in ordered} and set(t['dependencies'])<={x['id'] for x in ordered}]
        if not ready:raise ValueError('Unknown, cyclic or self dependency.')
        ordered.append(ready[0])
    if not set(ROLES[1:])<={t['role'] for t in ordered}:raise ValueError('Implementer, Tester and Reviewer are required.')
    implementers={t['id'] for t in ordered if t['role']=='implementer'}
    nonreviewers={t['id'] for t in ordered if t['role']!='reviewer'}
    all_paths=[]
    for task in ordered:
        ancestors=policy.ancestors(ordered,task['id'])
        if task['role']=='tester' and not implementers<=ancestors:raise ValueError('Tester must follow every Implementer.')
        if task['role']=='reviewer' and not nonreviewers<=ancestors:raise ValueError('Reviewer must cover every non-Reviewer.')
        all_paths+=task['write_paths']
    _write_paths(all_paths)
    if not any(p.startswith('tests/') for p in all_paths) or not any(not p.startswith('tests/') for p in all_paths):raise ValueError('Approve at least one code and one tests/ path.')
    return ordered


def write_paths(plan):
    return sorted(p for t in plan['tasks'] for p in t['write_paths'])


def _limits(tasks,limit):
    return dict(planning_calls=1,max_calls=len(tasks)+1,specialist_limit=limit,stage_seconds=240,retries=0,
                max_test_processes=3,test_seconds=30,test_output_bytes=100000,max_write_paths=8,
                file_bytes=100000,total_bytes=200000)


def make_plan(project,revision,goal,assignments,specialist_limit,task_id):
    tasks=_tasks(assignments,specialist_limit);selected=sources.scope(project)
    if selected is None:raise ValueError('Editing requires an explicit saved source selection.')
    sources.revision(project,revision)
    if selected['revision']!=revision:raise ValueError('Source selection is stale.')
    import uuid
    plan=dict(id=uuid.uuid4().hex,kind='change',policy_version=1,mode='python_fix',project_id=project['id'],project=project['name'],
              source_path=str(sources.root(project)),revision=revision,goal=policy.text(goal,'Goal',6000),
              task_id=policy.text(task_id,'User task ID',80),source_scope=selected,tasks=tasks,recipe=copy.deepcopy(RECIPE),limits=_limits(tasks,specialist_limit))
    entries=sources.tree(project,revision)
    for name in write_paths(plan):
        if name in entries and name not in selected['paths']:raise ValueError('Existing writes must be selected committed sources.')
        for other in entries:
            if _canonical(name)==_canonical(other) and name!=other:raise ValueError('Case-colliding source target.')
        _target(project,name, None if name not in entries else runner.digest(sources.blob(project,entries[name]).encode()))
    plan['digest']=policy.plan_digest(plan)
    validate_plan(plan)
    return plan


def validate_plan(plan):
    try:
        policy.fields(plan,('id','kind','policy_version','mode','project_id','project','source_path','revision','goal','task_id','source_scope','tasks','recipe','limits','digest'),'change plan')
        if plan['kind']!='change' or plan['mode']!='python_fix' or plan['policy_version']!=1 or plan['digest']!=policy.plan_digest(plan):raise ValueError('The editing plan changed.')
        for key in ('id','project_id','project','source_path','revision','goal','task_id'):policy.text(plan[key],key,6000)
        selected=sources.validate_scope(plan['source_scope'])
        if selected['revision']!=plan['revision'] or plan['recipe']!=RECIPE:raise ValueError('Invalid source scope or recipe.')
        tasks=_tasks(plan['tasks'],plan['limits']['specialist_limit'])
        if tasks!=plan['tasks'] or plan['limits']!=_limits(tasks,plan['limits']['specialist_limit']):raise ValueError('Invalid editing limits or task order.')
    except (KeyError,TypeError,AttributeError) as error:raise ValueError('Malformed editing plan.') from error


def _target(project,name,expected):
    """Preflight only; application repeats checks with pinned descriptors and exchanges."""
    root=sources.root(project);current=root
    for part in name.split('/')[:-1]:
        current=current/part
        if current.is_symlink():raise ValueError('Symlink source parent.')
        if current.exists() and not current.is_dir():raise ValueError('Non-directory source parent.')
    target=root/name
    # Check aliases even on case-sensitive filesystems, so approval is portable.
    current=root
    for part in name.split('/'):
        if current.is_dir() and any(_canonical(p.name)==_canonical(part) and p.name!=part for p in current.iterdir()):raise ValueError('Source path alias.')
        current=current/part
    try:meta=target.lstat()
    except FileNotFoundError:
        if expected is not None:raise ValueError('Existing target disappeared.')
        return
    if expected is None:raise ValueError('New-file target already exists, including untracked files.')
    if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or meta.st_mode & (stat.S_ISUID|stat.S_ISGID|stat.S_ISVTX):raise ValueError('Target must be a regular singly linked file with supported permissions.')
    if runner.digest(target.read_bytes())!=expected:raise ValueError('Source target changed from committed bytes.')


def check_current(project,run,record):
    validate_record(record,run)
    if project['id']!=record['project_id'] or str(sources.root(project))!=record['source_path'] or sources.scope(project)!=record['source_scope']:raise ValueError('Project or selected source scope changed.')
    sources.revision(project,record['revision'])
    if runner.fingerprint(Path(record['source_path']))!=record['baseline']:raise ValueError('Source checkout changed.')
    for name in write_paths(record['plan']):_target(project,name,record['sources'].get(name,{}).get('sha256'))


def prepare(project,plan,storage):
    validate_plan(plan)
    # Recheck proposed destinations before any snapshot is produced.
    entries=sources.tree(project,plan['revision'])
    for name in write_paths(plan):
        if name in entries and name not in plan['source_scope']['paths']:raise ValueError('Existing writes must be selected committed sources.')
        _target(project,name,None if name not in entries else runner.digest(sources.blob(project,entries[name]).encode()))
    run=sources.prepare(project,plan,storage);record=sources.load(run)
    record.update(format=FORMAT,task_id=plan['task_id'],limits=copy.deepcopy(plan['limits']),tasks=[dict(copy.deepcopy(t),status='waiting' if t['dependencies'] else 'queued') for t in plan['tasks']],
                  jobs=[],results={},combined=None,candidate=dict(replacements={},hashes={},diff='',digest='',frozen=False),checks=dict(reservations=[],results={}),test_approval=None,application=None)
    (run/'candidate').mkdir()
    for name in record['sources']:
        target=run/'candidate'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((run/'sources'/name).read_bytes())
    _refresh_candidate(record)
    runner.save(run/'run.json',record)
    return run


def _candidate_values(record):
    replacements=record['candidate']['replacements'];hashes={}
    for name,body in sorted(replacements.items()):
        hashes[name]=runner.digest(body.encode('utf-8'))
        original=record['sources'].get(name)
        # Original bodies are bound via their manifest; diff body is verified with run in validate_record.
        hashes[name]={'original':original['sha256'] if original else None,'candidate':hashes[name]}
    return hashes


def _diff_lines(body):
    # Only LF delimits source lines; CR and Unicode separators are literal bytes.
    parts=body.split('\n')
    return [line+'\n' for line in parts[:-1]]+([parts[-1]] if parts[-1] else [])


def _refresh_candidate(record,run=None):
    candidate=record['candidate'];candidate['hashes']=_candidate_values(record)
    if run is not None:
        diffs=[]
        for name,body in sorted(candidate['replacements'].items()):
            old=(Path(run)/'sources'/name).read_bytes().decode('utf-8') if name in record['sources'] else ''
            for line in difflib.unified_diff(_diff_lines(old),_diff_lines(body),fromfile='a/'+name if name in record['sources'] else '/dev/null',tofile='b/'+name):
                diffs.append(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n')
        candidate['diff']=''.join(diffs)
    candidate['digest']=policy.digest({k:candidate[k] for k in ('replacements','hashes','diff')})


def candidate_digest(run,record):
    validate_record(record,run)
    return record['candidate']['digest']


def load(run):
    record=sources.load(run);validate_record(record,run);return record


def _safe_file(root,name):
    target=root/name
    if any(p.is_symlink() for p in (target,*target.parents)) or not target.is_file() or target.stat().st_nlink!=1:raise ValueError('Invalid materialized candidate file.')
    return target


def evidence(run,record):
    run=Path(run);result={}
    for name in record['sources']:
        result['original:'+name]=_safe_file(run/'sources',name).read_bytes().decode('utf-8')
    for name in sorted(set(record['sources'])|set(record['candidate']['replacements'])):
        result['candidate:'+name]=_safe_file(run/'candidate',name).read_bytes().decode('utf-8')
    for name,value in record['checks']['results'].items():result['check:'+name]=json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n'
    for name in record['sources']:
        if name not in result:result[name]=result['original:'+name]
    return result


def _evidence_counts(record):
    counts={}
    for name,meta in record['sources'].items():
        counts['original:'+name]=meta['lines']
        counts['candidate:'+name]=len(sources.lf_lines(record['candidate']['replacements'][name])) if name in record['candidate']['replacements'] else meta['lines']
    for name,body in record['candidate']['replacements'].items():counts['candidate:'+name]=len(sources.lf_lines(body))
    for name,value in record['checks']['results'].items():counts['check:'+name]=len(sources.lf_lines(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n'))
    for name,meta in record['sources'].items():
        if name not in counts:counts[name]=meta['lines']
    return counts


def validate_result(run,record,assignment,result):
    policy.fields(result,('summary','findings','questions','verdict','files'),'editing result')
    policy.text(result['summary'],'Summary',6000);policy.questions(result['questions'],max(120,20+41*len(record['tasks'])) if assignment['role'] in ('combined','synthesis') else 20,6000)
    if result['verdict'] not in (('accept','revise','blocked') if assignment['role']=='reviewer' else ('not_reviewed',)):raise ValueError('Invalid editing verdict.')
    approved=next((t for t in record['tasks'] if t['id']==assignment.get('id')),None)
    if assignment['role'] not in ('combined','synthesis') and (approved is None or any(assignment.get(k)!=approved[k] for k in record['plan']['tasks'][record['tasks'].index(approved)])):raise ValueError('Unapproved assignment.')
    files=result['files']
    if not isinstance(files,list):raise ValueError('Files must be a list.')
    if assignment['role']!='implementer' and files:raise ValueError('Only Implementers return files.')
    if assignment['role']=='implementer':
        names=[]
        for file in files:
            policy.fields(file,('path','content'),'replacement');names.append(file['path'])
            if not isinstance(file['content'],str) or '\0' in file['content']:raise ValueError('Replacement must be UTF-8 text.')
            try:size=len(file['content'].encode('utf-8'))
            except UnicodeEncodeError as error:raise ValueError('Replacement must be UTF-8.') from error
            if size>MAX_FILE_BYTES:raise ValueError('Replacement exceeds byte limit.')
        if sorted(names)!=assignment['write_paths']:raise ValueError('Every exact approved path must be returned once.')
    if not isinstance(result['findings'],list) or len(result['findings'])>20:raise ValueError('At most twenty findings.')
    available=_evidence_counts(record)
    for finding in result['findings']:
        policy.fields(finding,('claim','kind','evidence'),'finding');policy.text(finding['claim'],'Claim',3000)
        if finding['kind'] not in ('fact','interpretation','proposal') or not isinstance(finding['evidence'],list) or not 1<=len(finding['evidence'])<=10:raise ValueError('Finding needs bounded evidence.')
        for citation in finding['evidence']:
            policy.fields(citation,('source','start','end'),'citation');identity=citation['source']
            if identity not in available or (assignment['role'] in ('researcher','implementer') and identity.startswith(('candidate:','check:'))):raise ValueError('Evidence unavailable to this assignment.')
            a,b=citation['start'],citation['end']
            if type(a) is not int or type(b) is not int or not 1<=a<=b<=available[identity]:raise ValueError('Invalid evidence line range.')
    return copy.deepcopy(result)


def stage_candidate(run,record,assignment,result):
    validate_record(record,run)
    if record['candidate']['frozen'] or record['test_approval'] is not None or record['stage'] not in ('queued','running'):raise ValueError('Candidate is frozen.')
    artifact=validate_result(run,record,assignment,result)
    if assignment['role']!='implementer':raise ValueError('Only Implementers stage replacements.')
    candidate=copy.deepcopy(record['candidate'])
    for file in artifact['files']:
        if file['path'] in candidate['replacements']:raise ValueError('Replacement already staged.')
        candidate['replacements'][file['path']]=file['content']
    if sum(len(body.encode('utf-8')) for body in candidate['replacements'].values())>MAX_TOTAL_BYTES:raise ValueError('Candidate exceeds total byte limit.')
    for file in artifact['files']:_safe_file(Path(run)/'candidate',file['path']) if file['path'] in record['sources'] else None
    for file in artifact['files']:
        target=Path(run)/'candidate'/file['path']
        if any(p.is_symlink() for p in (target,*target.parents)):raise ValueError('Symlink candidate destination.')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(file['content'].encode('utf-8'))
    record['candidate']=candidate;_refresh_candidate(record,run);runner.save(Path(run)/'run.json',record)
    return artifact


def validate_record(record,run=None):
    try:
        validate_plan(record['plan'])
        if record['format']!=FORMAT:raise ValueError('Not an editing run.')
        for key in ('project_id','source_path','revision','goal','task_id','source_scope','limits'):
            if record[key]!=record['plan'][key]:raise ValueError('Saved editing scope changed.')
        if not isinstance(record['sources'],dict) or set(record['sources'])!=set(record['source_scope']['paths']):raise ValueError('Original manifest scope changed.')
        for meta in record['sources'].values():
            policy.fields(meta,('sha256','lines','bytes','blob'),'original source manifest')
            if not isinstance(meta['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',meta['sha256']) or type(meta['bytes']) is not int or not 0<=meta['bytes']<=sources.MAX_FILE_BYTES or type(meta['lines']) is not int or not 0<=meta['lines']<=meta['bytes'] or not isinstance(meta['blob'],str) or not re.fullmatch('[0-9a-f]{40,64}',meta['blob']):raise ValueError('Invalid original source manifest.')
        if len(record['tasks'])!=len(record['plan']['tasks']):raise ValueError('Assignment count changed.')
        for task,approved in zip(record['tasks'],record['plan']['tasks']):
            if any(task.get(k)!=v for k,v in approved.items()) or task['status'] not in ('queued','waiting','running','done','failed','cancelled','blocked'):raise ValueError('Saved editing assignment changed.')
        ids={t['id'] for t in record['tasks']}
        if not isinstance(record['jobs'],list) or len(record['jobs'])>record['limits']['max_calls'] or len({j['id'] for j in record['jobs']})!=len(record['jobs']):raise ValueError('Invalid call reservations.')
        if any(j['id'] not in ids|{'synthesis'} or j['status'] not in ('reserved','completed','failed','cancelled','interrupted') for j in record['jobs']):raise ValueError('Invalid saved job.')
        for job in record['jobs']:
            tokens=job['tokens']
            if tokens is not None and (not isinstance(tokens,dict) or any(type(v) is not int or v<0 for v in tokens.values())):raise ValueError('Invalid saved job usage.')
        if not isinstance(record['results'],dict) or not set(record['results'])<=ids or not isinstance(record['events'],list):raise ValueError('Invalid result ownership.')
        if record['stage'] not in TERMINAL|{'queued','running','synthesizing','awaiting_test_approval','checking','applying'}:raise ValueError('Invalid editing stage.')
        candidate=record['candidate'];policy.fields(candidate,('replacements','hashes','diff','digest','frozen'),'candidate')
        if type(candidate['frozen']) is not bool or not isinstance(candidate['replacements'],dict) or not set(candidate['replacements'])<=set(write_paths(record['plan'])):raise ValueError('Invalid candidate scope.')
        if any(not isinstance(body,str) or '\0' in body or len(body.encode('utf-8'))>MAX_FILE_BYTES for body in candidate['replacements'].values()) or sum(len(b.encode('utf-8')) for b in candidate['replacements'].values())>MAX_TOTAL_BYTES:raise ValueError('Invalid replacement bytes.')
        if candidate['hashes']!=_candidate_values(record) or candidate['digest']!=policy.digest({k:candidate[k] for k in ('replacements','hashes','diff')}):raise ValueError('Candidate digest changed.')
        if candidate['frozen'] and set(candidate['replacements'])!=set(write_paths(record['plan'])):raise ValueError('Incomplete frozen candidate.')
        checks=record['checks']
        if not isinstance(checks,dict) or not isinstance(checks['reservations'],list) or not isinstance(checks['results'],dict) or not set(checks['results'])<=set(CHECKS):raise ValueError('Malformed check bundle.')
        reservations=[r['id'] for r in checks['reservations']]
        if len(reservations)>3 or len(set(reservations))!=len(reservations) or not set(reservations)<=set(CHECKS) or not set(checks['results'])<=set(reservations):raise ValueError('Check reservation ceiling exceeded or result unreserved.')
        for result in checks['results'].values():
            if not isinstance(result,dict) or result.get('status') not in ('passed','failed','error','cancelled','timeout','output_limit','unavailable'):raise ValueError('Invalid saved check status.')
            if result.get('exit_code') is not None and type(result['exit_code']) is not int:raise ValueError('Invalid saved check exit code.')
            if any(type(result.get(k)) is not int or result[k]<0 for k in ('tests','failures','errors')):raise ValueError('Invalid saved check counts.')
            if any(not isinstance(result.get(k),str) for k in ('stdout','stderr')) or sum(len(result[k].encode('utf-8')) for k in ('stdout','stderr'))>100000:raise ValueError('Invalid saved check output.')
            if type(result.get('duration')) not in (int,float) or not math.isfinite(result['duration']) or result['duration']<0 or not isinstance(result.get('runtime'),dict):raise ValueError('Invalid saved check runtime.')
        for identity,result in record['results'].items():
            task=next(t for t in record['tasks'] if t['id']==identity)
            if task['role']=='implementer' and any(candidate['replacements'].get(f['path'])!=f['content'] for f in result['files']):raise ValueError('Implementer artifact differs from candidate.')
        if record['test_approval'] is not None:
            approval=record['test_approval']
            if not isinstance(approval,dict) or approval.get('candidate_digest')!=candidate['digest'] or approval.get('plan_digest')!=record['plan']['digest'] or approval.get('recipe')!=RECIPE:raise ValueError('Test approval binding changed.')
            runtime=approval.get('runtime')
            if not isinstance(runtime,dict) or any(not isinstance(runtime.get(k),str) or not runtime[k] for k in ('executable','sha256','framework_root','version','recipe')) or runtime['recipe']!=RECIPE:raise ValueError('Invalid approved runtime identity.')
        for identity,result in record['results'].items():validate_result(run,record,next(t for t in record['tasks'] if t['id']==identity),result)
        if record['combined'] is not None:validate_result(run,record,{'role':'synthesis'},record['combined'])
        if run is not None:
            run=Path(run)
            if record['id']!=run.name:raise ValueError('Run identity changed.')
            actual={str(p.relative_to(run/'candidate')) for p in (run/'candidate').rglob('*') if not p.is_dir() or p.is_symlink()}
            if actual!=set(record['sources'])|set(candidate['replacements']):raise ValueError('Unexpected candidate file.')
            for name,meta in record['sources'].items():
                raw=_safe_file(run/'sources',name).read_bytes()
                if len(raw)>sources.MAX_FILE_BYTES or len(raw)!=meta['bytes'] or runner.digest(raw)!=meta['sha256'] or b'\0' in raw or len(sources.lf_lines(raw.decode('utf-8')))!=meta['lines']:raise ValueError('Original snapshot manifest changed.')
            for name in set(record['sources'])|set(candidate['replacements']):
                expected=candidate['replacements'].get(name)
                raw=_safe_file(run/'candidate',name).read_bytes()
                if expected is not None:
                    if raw!=expected.encode('utf-8'):raise ValueError('Candidate bytes changed.')
                elif runner.digest(raw)!=record['sources'][name]['sha256']:raise ValueError('Unmodified candidate bytes changed.')
            calculated=copy.deepcopy(record);_refresh_candidate(calculated,run)
            if calculated['candidate']!=candidate:raise ValueError('Candidate diff changed.')
    except (KeyError,TypeError,AttributeError,UnicodeError) as error:raise ValueError('Malformed saved editing record.') from error


def artifact_id(record):
    return policy.digest({k:record.get(k) for k in ('id','project_id','task_id','revision','source_scope','plan','sources','candidate','checks','results','combined')})


def interrupt(record,stage,detail):
    policy.interrupt(record,stage,detail)
