"""Bounded team plans, evidence and report acceptance. No model or network calls."""
import copy
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

import runner

FORMAT = 'team-v1'
ROLES = {'web_searcher':{'name':'Web searcher','capabilities':['public_web_search']},
         'researcher':{'name':'Researcher','capabilities':['committed_snapshot','dependency_artifacts']},
         'reviewer':{'name':'Reviewer','capabilities':['committed_snapshot','dependency_artifacts']}}
TERMINAL = {'completed','completed_unreviewed','accepted','needs_revision','blocked','failed','cancelled','interrupted','integrity_failed'}


def object_schema(properties):
    return {'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}


TEXT = {'type':'string'}
TASK_SCHEMA = object_schema({'id':TEXT,'role':{'type':'string','enum':list(ROLES)},
                             'objective':TEXT,'expected_output':TEXT,
                             'dependencies':{'type':'array','items':TEXT}})
CHAT_SCHEMA = object_schema({'reply':TEXT,'action':{'type':'string','enum':['answer','propose_plan','propose_revision']},
                             'tasks':{'type':'array','items':TASK_SCHEMA}})
CITATION = object_schema({'source':TEXT,'start':{'type':'integer'},'end':{'type':'integer'}})
RESULT_SCHEMA = object_schema({'summary':TEXT,'findings':{'type':'array','items':object_schema({
    'claim':TEXT,'kind':{'type':'string','enum':['fact','interpretation','proposal']},
    'evidence':{'type':'array','items':CITATION}})},'questions':{'type':'array','items':TEXT},
    'verdict':{'type':'string','enum':['not_reviewed','accept','revise','blocked']}})
SEARCH_SCHEMA = object_schema({'summary':TEXT,'sources':{'type':'array','items':object_schema({
    'url':TEXT,'title':TEXT,'excerpt':TEXT})},'questions':{'type':'array','items':TEXT}})


def text(value, label, limit, empty=False):
    if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()):
        raise ValueError(label+' must be bounded nonempty text (maximum '+str(limit)+' characters).')
    return value


def fields(value, required, label):
    if not isinstance(value,dict) or set(value)!=set(required):
        raise ValueError('Invalid '+label+' fields.')


def validate_tasks(tasks):
    if not isinstance(tasks,list) or not 1<=len(tasks)<=3:
        raise ValueError('A team needs one to three specialist assignments.')
    normalized=[]
    for task in tasks:
        fields(task,('id','role','objective','expected_output','dependencies'),'assignment')
        identity=text(task['id'],'Task ID',40)
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',identity) or task['role'] not in ROLES:
            raise ValueError('Unsupported task ID or executable role.')
        text(task['objective'],'Assignment',2000); text(task['expected_output'],'Expected output',1000)
        deps=task['dependencies']
        if not isinstance(deps,list) or len(deps)>2 or any(not isinstance(d,str) for d in deps) or len(set(deps))!=len(deps):
            raise ValueError('Dependencies must be distinct task IDs.')
        if task['role']=='web_searcher' and deps:
            raise ValueError('Web searcher cannot receive private dependency artifacts.')
        normalized.append(dict(copy.deepcopy(task),role_version=1,capabilities=list(ROLES[task['role']]['capabilities'])))
    ids=[t['id'] for t in normalized]
    if len(set(ids))!=len(ids) or len({t['role'] for t in normalized})!=len(ids):
        raise ValueError('Task IDs and executable roles must be unique.')
    for task in normalized:
        if task['id'] in task['dependencies'] or any(d not in ids for d in task['dependencies']):
            raise ValueError('Unknown or self-referencing dependency.')
    ordered=[]
    while len(ordered)<len(normalized):
        done={t['id'] for t in ordered}
        ready=[t for t in normalized if t['id'] not in done and set(t['dependencies'])<=done]
        if not ready:
            raise ValueError('Task dependencies contain a cycle.')
        ordered.append(ready[0])
    for task in ordered:
        if task['role']=='reviewer' and (not task['dependencies'] or ancestors(ordered,task['id'])!=set(ids)-{task['id']}):
            raise ValueError('Reviewer must cover every other specialist assignment.')
    return ordered


def ancestors(tasks, identity):
    by_id={t['id']:t for t in tasks}
    pending=list(by_id[identity]['dependencies']); result=set()
    while pending:
        item=pending.pop()
        if item not in result:
            result.add(item);pending.extend(by_id[item]['dependencies'])
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def plan_digest(plan):
    return digest({k:v for k,v in plan.items() if k!='digest'})


def make_plan(project, revision, goal, tasks):
    tasks=validate_tasks(tasks)
    plan={'id':uuid.uuid4().hex,'kind':'team','project_id':project['id'],'project':project['name'],
          'source_path':str(Path(project['source_path']).resolve()),'revision':revision,
          'goal':text(goal,'Goal',6000),'tasks':tasks,
          'limits':{'planning_calls':1,'max_calls':len(tasks)+1,'stage_seconds':240,'retries':0}}
    plan['digest']=plan_digest(plan)
    return plan


def validate_plan(plan):
    if plan.get('kind')!='team' or plan.get('digest')!=plan_digest(plan):
        raise ValueError('The plan changed; request a new proposal.')
    raw=[{k:v for k,v in task.items() if k not in ('role_version','capabilities')} for task in plan['tasks']]
    if validate_tasks(raw)!=plan['tasks'] or plan['limits']!={'planning_calls':1,'max_calls':len(raw)+1,'stage_seconds':240,'retries':0}:
        raise ValueError('Invalid plan capabilities or usage limits.')


def prepare(project, plan, storage):
    validate_plan(plan)
    run=runner.prepare(Path(project['source_path']),storage,required_paths=('README.md',project['context_path']),project_name=project['name'])
    record=runner.load(run)
    if record['revision']!=plan['revision']:
        raise ValueError('Source revision changed while preparing the team snapshot.')
    record.update(format=FORMAT,project_id=project['id'],goal=plan['goal'],plan=copy.deepcopy(plan),
                  stage='queued',limits=copy.deepcopy(plan['limits']),evidence={},jobs=[],combined=None,results={},events=[],
                  provider='Codex CLI · bounded specialist team',
                  tasks=[dict(copy.deepcopy(t),status='waiting' if t['dependencies'] else 'queued') for t in plan['tasks']])
    record.pop('verification',None)
    runner.event(record,'Orchestrator','planned','Approved specialist plan saved; assignments and call limit cannot expand.')
    runner.save(run/'run.json',record)
    # The legacy offline viewer cannot represent team runs. The native app owns their view.
    (run/'index.html').unlink()
    return run


def public_url(value):
    text(value,'Public source URL',2000)
    if any(c.isspace() or ord(c)<32 for c in value) or '\\' in value:
        raise ValueError('Invalid public source URL.')
    try:
        parsed=urlsplit(value); host=parsed.hostname or ''; parsed.port
    except ValueError as error:
        raise ValueError('Invalid public source URL.') from error
    if parsed.scheme not in ('https','http') or not host or parsed.username is not None or parsed.password is not None or '%' in host:
        raise ValueError('Only public http/https source URLs without credentials are allowed.')
    host=host.rstrip('.').lower()
    try:
        address=ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host or not re.fullmatch(r'[a-z0-9.-]+',host) or not re.search(r'\.[a-z]{2,}$',host) or host.endswith(('.local','.localhost','.internal','.invalid','.test')) or host=='localhost':
            raise ValueError('Local or ambiguous source host is not allowed.')
    else:
        if not address.is_global:
            raise ValueError('Private or local source address is not allowed.')
    return value


def questions(value):
    if not isinstance(value,list) or len(value)>20:
        raise ValueError('At most twenty unresolved questions are allowed.')
    return [text(q,'Unresolved question',2000) for q in value]


def validate_artifact(record, task, result, observed_urls=()):
    if task['role']=='web_searcher':
        fields(result,('summary','sources','questions'),'search result')
        text(result['summary'],'Search summary',6000); questions(result['questions'])
        if not isinstance(result['sources'],list) or not 1<=len(result['sources'])<=10:
            raise ValueError('Search must return one to ten observed sources.')
        additions={}
        for index,source in enumerate(result['sources']):
            fields(source,('url','title','excerpt'),'web source')
            url=public_url(source['url'])
            if url not in observed_urls:
                raise ValueError('Web source lacks observed retrieval provenance.')
            text(source['title'],'Source title',500);text(source['excerpt'],'Supporting excerpt',1600)
            identity='web:'+record['id']+':'+str(index)
            additions[identity]=dict(copy.deepcopy(source),kind='web',retrieved_at=datetime.now(timezone.utc).isoformat(),
                                     lines=len(source['excerpt'].split('\n')),task_id=task['id'])
        record['evidence'].update(additions)
        return {'summary':result['summary'],'findings':[],'questions':copy.deepcopy(result['questions']),
                'verdict':'not_reviewed','web_sources':list(additions)}
    fields(result,('summary','findings','questions','verdict'),'result')
    text(result['summary'],'Summary',6000);questions(result['questions'])
    if result['verdict'] not in (('accept','revise','blocked') if task['role']=='reviewer' else ('not_reviewed',)):
        raise ValueError('Invalid review verdict for this role.')
    if not isinstance(result['findings'],list) or not 0<=len(result['findings'])<=20:
        raise ValueError('At most twenty findings are allowed.')
    for finding in result['findings']:
        fields(finding,('claim','kind','evidence'),'finding');text(finding['claim'],'Finding',3000)
        if finding['kind'] not in ('fact','interpretation','proposal') or not isinstance(finding['evidence'],list) or not 1<=len(finding['evidence'])<=10:
            raise ValueError('Each classified finding needs evidence.')
        for citation in finding['evidence']:
            fields(citation,('source','start','end'),'citation')
            source=citation['source']
            manifest=record['sources'].get(source) or record['evidence'].get(source)
            if not manifest:
                raise ValueError('Unknown or cross-run citation source.')
            start,end=citation['start'],citation['end']
            if type(start) is not int or type(end) is not int or not 1<=start<=end<=manifest['lines']:
                raise ValueError('Invalid citation line range.')
    return copy.deepcopy(result)


def artifact_id(record):
    return digest({k:record.get(k) for k in ('id','project_id','revision','sources','goal','plan','evidence','results','combined')})


def verify(run):
    record=runner.load(run)
    result={'unchanged':runner.fingerprint(Path(record['source_path']))==record['baseline'],
            'checked':'HEAD, Git status and SHA-256 of tracked files; untracked contents are not hashed.'}
    record['verification']=result
    runner.save(run/'run.json',record)
    return result


def accept(run, reference):
    record=runner.load(run)
    if reference.get('run_id')!=record['id'] or reference.get('artifact_id')!=artifact_id(record):
        raise ValueError('The report changed; this action is stale.')
    if record['stage']=='accepted' and record.get('user_acceptance',{}).get('artifact_id')==reference['artifact_id']:
        return False
    reviewers=[r for t in record['tasks'] if t['role']=='reviewer' for r in [record['results'].get(t['id'],{})]]
    if record['stage']!='completed' or not record.get('combined') or not reviewers or reviewers[0].get('verdict')!='accept':
        raise ValueError('Reviewed acceptance requires a complete synthesis and Reviewer acceptance.')
    if not verify(run)['unchanged']:
        raise ValueError('Source checkout changed; acceptance is unavailable.')
    record=runner.load(run)
    record['stage']='accepted'
    record['user_acceptance']={'artifact_id':reference['artifact_id'],'scope':'report_only','time':datetime.now(timezone.utc).isoformat()}
    runner.event(record,'User','accepted','Accepted this report version only; no project changes or experiment authorized.')
    runner.save(run/'run.json',record)
    return True


def interrupt(record, stage, detail):
    record['stage']=stage
    for task in record['tasks']:
        if task['status']=='running':
            task['status']='cancelled' if stage in ('cancelled','interrupted') else 'failed'
            task['error']=detail
        elif task['status'] in ('queued','waiting'):
            task['status']='blocked'
    for job in record['jobs']:
        if job['status']=='reserved': job['status']=stage
    runner.event(record,'Orchestrator',stage,detail)
