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

import budget
import runner
import sources

FORMAT = 'team-v1'
FORMATS = (FORMAT,sources.FORMAT)


def is_team(record):
    return record.get('format') in FORMATS

RESERVED_TASK_IDS = {'synthesis','combined','sources','events'}
ROLES = {'web_searcher':{'name':'Web searcher','capabilities':['public_web_search']},
         'researcher':{'name':'Researcher','capabilities':['committed_snapshot','dependency_artifacts']},
         'reviewer':{'name':'Reviewer','capabilities':['committed_snapshot','dependency_artifacts']}}
TERMINAL = {'completed','completed_unreviewed','accepted','needs_revision','blocked','failed','cancelled','interrupted','integrity_failed','budget_exhausted'}


def object_schema(properties):
    return {'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}


TEXT = {'type':'string','minLength':1}
TASK_SCHEMA = object_schema({'id':TEXT,'role':{'type':'string','enum':list(ROLES)},
                             'objective':TEXT,'expected_output':TEXT,
                             'dependencies':{'type':'array','items':TEXT}})
CHAT_SCHEMA = object_schema({'reply':TEXT,'action':{'type':'string','enum':['answer','propose_plan','propose_revision']},
                             'tasks':{'type':'array','items':TASK_SCHEMA}})
CITATION = object_schema({'source':TEXT,'start':{'type':'integer'},'end':{'type':'integer'}})
EVIDENCE_GUIDANCE = (
    'Every finding, including a proposal, requires 1–10 citations to supplied source IDs and LF line ranges. '
    'For proposals, cite the source context motivating the change; this is not evidence the proposal is implemented or validated. '
    'Put ideas without relevant supplied evidence in unresolved questions instead of findings. Never invent a citation. ')
RESULT_SCHEMA = object_schema({'summary':TEXT,'findings':{'type':'array','items':object_schema({
    'claim':TEXT,'kind':{'type':'string','enum':['fact','interpretation','proposal']},
    'evidence':{'type':'array','minItems':1,'maxItems':10,'items':CITATION,
                'description':EVIDENCE_GUIDANCE}})},'questions':{'type':'array','items':TEXT},
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


def validate_specialist_limit(value):
    if type(value) is not int or not 1<=value<=9007199254740991:
        raise ValueError('Specialist allowance must be a positive JavaScript-safe integer.')
    return value


def chat_schema(specialist_limit):
    limit=validate_specialist_limit(specialist_limit)
    schema=copy.deepcopy(CHAT_SCHEMA)
    schema['properties']['tasks']['maxItems']=limit
    schema['properties']['tasks']['items']['properties']['dependencies']['maxItems']=limit-1
    return schema


def validate_tasks(tasks, *, policy_version=1, specialist_limit=3):
    if type(policy_version) is not int or policy_version not in (1,2):
        raise ValueError('Unsupported specialist policy version.')
    limit=validate_specialist_limit(specialist_limit) if policy_version==2 else 3
    if not isinstance(tasks,list) or not 1<=len(tasks)<=limit:
        raise ValueError('A team needs one to '+str(limit)+' specialist assignments.')
    normalized=[]
    for task in tasks:
        fields(task,('id','role','objective','expected_output','dependencies'),'assignment')
        identity=text(task['id'],'Task ID',40)
        if identity in RESERVED_TASK_IDS:
            raise ValueError('Task ID is reserved for internal jobs or result views.')
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',identity) or not isinstance(task['role'],str) or task['role'] not in ROLES:
            raise ValueError('Unsupported task ID or executable role.')
        text(task['objective'],'Assignment',2000); text(task['expected_output'],'Expected output',1000)
        deps=task['dependencies']
        if not isinstance(deps,list) or len(deps)>len(tasks)-1 or any(not isinstance(d,str) for d in deps) or len(set(deps))!=len(deps):
            raise ValueError('Dependencies must be distinct task IDs.')
        if task['role']=='web_searcher' and deps:
            raise ValueError('Web searcher cannot receive private dependency artifacts.')
        normalized.append(dict(copy.deepcopy(task),role_version=1,capabilities=list(ROLES[task['role']]['capabilities'])))
    ids=[t['id'] for t in normalized]
    if len(set(ids))!=len(ids) or (policy_version==1 and len({t['role'] for t in normalized})!=len(ids)):
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
        if task['role']=='reviewer':
            required=({t['id'] for t in ordered if t['role']!='reviewer'} if policy_version==2 else set(ids)-{task['id']})
            if not required or not required<=ancestors(ordered,task['id']):
                raise ValueError('Reviewer must cover every non-review specialist assignment.')
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


def make_plan(project, revision, goal, tasks, *, specialist_limit=None, task_id=None, token_budget=None):
    version=2 if specialist_limit is not None else 1
    tasks=validate_tasks(tasks,policy_version=version,specialist_limit=specialist_limit if version==2 else 3)
    plan={'id':uuid.uuid4().hex,'kind':'team','project_id':project['id'],'project':project['name'],
          'source_path':str(Path(project['source_path']).resolve()),'revision':revision,
          'goal':text(goal,'Goal',6000),'tasks':tasks,
          'limits':{'planning_calls':1,'max_calls':len(tasks)+1,'stage_seconds':240,'retries':0}}
    if version==2:
        plan['policy_version']=2
        plan['limits']['specialist_limit']=validate_specialist_limit(specialist_limit)
        if budget.validate(token_budget) is not None:plan['limits']['token_budget']=token_budget
    if task_id is not None:plan['task_id']=text(task_id,'User task ID',80)
    selected=sources.scope(project)
    if selected is not None:plan['source_scope']=copy.deepcopy(selected)
    plan['digest']=plan_digest(plan)
    return plan


def validate_plan(plan):
    if plan.get('kind')!='team' or plan.get('digest')!=plan_digest(plan):
        raise ValueError('The plan changed; request a new proposal.')
    if 'source_scope' in plan:
        sources.validate_scope(plan['source_scope'])
        if plan['source_scope']['revision']!=plan['revision']:raise ValueError('Plan source revision changed.')
    version=plan.get('policy_version',1)
    limit=plan.get('limits',{}).get('specialist_limit',3)
    if 'task_id' in plan:text(plan['task_id'],'User task ID',80)
    raw=[{k:v for k,v in task.items() if k not in ('role_version','capabilities')} for task in plan['tasks']]
    limits={'planning_calls':1,'max_calls':len(raw)+1,'stage_seconds':240,'retries':0}
    if version==2:limits['specialist_limit']=validate_specialist_limit(limit)
    if version==2 and 'token_budget' in plan.get('limits',{}):limits['token_budget']=budget.validate(plan['limits']['token_budget'])
    if validate_tasks(raw,policy_version=version,specialist_limit=limit)!=plan['tasks'] or plan['limits']!=limits:
        raise ValueError('Invalid plan capabilities or usage limits.')


def validate_record(record):
    """Reject incomplete saved metadata before it reaches UI or recovery actions."""
    try:
        validate_plan(record['plan'])
        if 'task_id' in record:text(record['task_id'],'User task ID',80)
        if ('task_id' in record['plan'] or record['plan'].get('policy_version',1)==2) and record.get('task_id')!=record['plan'].get('task_id'):
            raise ValueError('Saved user task scope changed.')
        if (record.get('format')==sources.FORMAT)!=('source_scope' in record['plan']):
            raise ValueError('Team format and source scope do not match.')
        for key in ('project_id','source_path','revision','goal'):
            if record[key]!=record['plan'][key]:raise ValueError('Saved team scope changed.')
        if record['limits']!=record['plan']['limits'] or not isinstance(record['tasks'],list) or len(record['tasks'])!=len(record['plan']['tasks']):
            raise ValueError('Invalid saved team assignments or limits.')
        for task, approved in zip(record['tasks'],record['plan']['tasks']):
            if any(task[k]!=v for k,v in approved.items()) or task['status'] not in ('queued','waiting','running','done','failed','cancelled','blocked'):
                raise ValueError('Invalid saved assignment.')
        ids={t['id'] for t in record['tasks']}
        if not isinstance(record['jobs'],list) or len(record['jobs'])>record['limits']['max_calls']:
            raise ValueError('Invalid saved call reservations.')
        job_ids=[]
        for job in record['jobs']:
            if job['id'] not in ids|{'synthesis'} or job['status'] not in ('reserved','completed','failed','cancelled','interrupted'):
                raise ValueError('Invalid saved job.')
            tokens=job['tokens']
            if tokens is not None and (not isinstance(tokens,dict) or any(type(v) is not int or v<0 for v in tokens.values())):
                raise ValueError('Invalid saved usage.')
            job_ids.append(job['id'])
        if len(set(job_ids))!=len(job_ids) or not isinstance(record['results'],dict) or not set(record['results'])<=ids:
            raise ValueError('Invalid saved artifact ownership.')
        expanded=record['plan'].get('policy_version',1)==2
        search_ids={t['id'] for t in record['tasks'] if t['role']=='web_searcher'}
        if not isinstance(record['evidence'],dict) or len(record['evidence'])>10*(len(search_ids) if expanded else 1):
            raise ValueError('Invalid saved web evidence.')
        source_counts={identity:0 for identity in search_ids}
        for identity, evidence in record['evidence'].items():
            if not identity.startswith('web:'+record['id']+':') or evidence['task_id'] not in search_ids or evidence['kind']!='web':
                raise ValueError('Invalid saved web source ownership.')
            if expanded:
                prefix='web:'+record['id']+':'+evidence['task_id']+':'
                if identity not in {prefix+str(i) for i in range(10)}:
                    raise ValueError('Invalid saved web source assignment namespace.')
                source_counts[evidence['task_id']]+=1
                if source_counts[evidence['task_id']]>10:
                    raise ValueError('Search assignment exceeds its source allowance.')
            public_url(evidence['url']);text(evidence['title'],'Source title',500)
            text(evidence['excerpt'],'Excerpt',1600);text(evidence['retrieved_at'],'Retrieval time',80)
            if evidence['lines']!=len(evidence['excerpt'].split('\n')):raise ValueError('Invalid saved excerpt lines.')
        for task in record['tasks']:
            if task['id'] not in record['results']:continue
            result=record['results'][task['id']]
            if task['role']=='web_searcher':
                text(result['summary'],'Search summary',6000);questions(result['questions'])
                if not isinstance(result['web_sources'],list) or any(i not in record['evidence'] for i in result['web_sources']):
                    raise ValueError('Invalid saved search result.')
                if expanded and (not 1<=len(result['web_sources'])<=10 or len(set(result['web_sources']))!=len(result['web_sources']) or
                                 set(result['web_sources'])!={i for i,e in record['evidence'].items() if e['task_id']==task['id']}):
                    raise ValueError('Saved search result does not own its evidence.')
            else:validate_artifact(record,task,result)
        if expanded and any(e['task_id'] not in record['results'] for e in record['evidence'].values()):
            raise ValueError('Saved evidence has no producing search result.')
        if record['combined'] is not None:
            validate_artifact(record,{'role':'combined'},record['combined'])
        if record['stage'] not in TERMINAL|{'queued','running','synthesizing'}:
            raise ValueError('Invalid saved team stage.')
    except (KeyError,TypeError,AttributeError) as error:
        raise ValueError('Saved team metadata is incomplete or malformed.') from error


def prepare(project, plan, storage):
    validate_plan(plan)
    run=(sources.prepare(project,plan,storage) if 'source_scope' in plan else
         runner.prepare(Path(project['source_path']),storage,required_paths=('README.md',project['context_path']),project_name=project['name']))
    record=sources.load(run)
    if record['revision']!=plan['revision']:
        raise ValueError('Source revision changed while preparing the team snapshot.')
    record.update(format=sources.FORMAT if 'source_scope' in plan else FORMAT,project_id=project['id'],goal=plan['goal'],plan=copy.deepcopy(plan),
                  stage='queued',limits=copy.deepcopy(plan['limits']),evidence={},jobs=[],combined=None,results={},events=[],
                  provider='Codex CLI · bounded specialist team',
                  usage='Returned token counts per job; unknown consumption remains unknown. Calls and deadlines do not cap monetary spend.',
                  tasks=[dict(copy.deepcopy(t),status='waiting' if t['dependencies'] else 'queued') for t in plan['tasks']])
    if 'task_id' in plan:record['task_id']=plan['task_id']
    record.pop('verification',None)
    runner.event(record,'Orchestrator','planned','Approved specialist plan saved; assignments and call limit cannot expand.')
    runner.save(run/'run.json',record)
    # The legacy offline viewer cannot represent team runs. The native app owns their view.
    if (run/'index.html').exists():(run/'index.html').unlink()
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


def questions(value, maximum=20, character_limit=2000):
    if not isinstance(value,list) or len(value)>maximum:
        raise ValueError('At most twenty unresolved questions are allowed.')
    return [text(q,'Unresolved question',character_limit) for q in value]


def validate_artifact(record, task, result, observed_urls=()):
    expanded=record.get('plan',{}).get('policy_version',1)==2
    if task['role']=='web_searcher':
        if expanded and not any(t['id']==task.get('id') and t['role']=='web_searcher' for t in record['tasks']):
            raise ValueError('Evidence must belong to an approved search assignment.')
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
            identity='web:'+record['id']+':'+(task['id']+':' if expanded else '')+str(index)
            additions[identity]=dict(copy.deepcopy(source),kind='web',retrieved_at=datetime.now(timezone.utc).isoformat(),
                                     lines=len(source['excerpt'].split('\n')),task_id=task['id'])
        if expanded:
            search_count=sum(t['role']=='web_searcher' for t in record['tasks'])
            if any(i in record['evidence'] for i in additions) or len(record['evidence'])+len(additions)>10*search_count:
                raise ValueError('Search evidence already exists or exceeds the approved allowance.')
        record['evidence'].update(additions)
        return {'summary':result['summary'],'findings':[],'questions':copy.deepcopy(result['questions']),
                'verdict':'not_reviewed','web_sources':list(additions)}
    fields(result,('summary','findings','questions','verdict'),'result')
    text(result['summary'],'Summary',6000)
    # Combined questions also preserve full Reviewer summaries (6,000) and claims (3,000).
    # Each assignment contributes twenty questions; each Reviewer can add its
    # summary and twenty claims. Synthesis contributes twenty further questions.
    combined_limit=max(120,20+41*len(record['tasks'])) if expanded else 120
    questions(result['questions'],combined_limit,6000) if task['role']=='combined' else questions(result['questions'])
    if result['verdict'] not in (('accept','revise','blocked') if task['role']=='reviewer' else ('not_reviewed',)):
        raise ValueError('Invalid review verdict for this role.')
    if not isinstance(result['findings'],list) or not 0<=len(result['findings'])<=20:
        raise ValueError('At most twenty findings are allowed.')
    for finding in result['findings']:
        fields(finding,('claim','kind','evidence'),'finding');text(finding['claim'],'Finding',3000)
        if finding['kind'] not in ('fact','interpretation','proposal') or not isinstance(finding['evidence'],list) or not 1<=len(finding['evidence'])<=10:
            raise ValueError('Each fact, interpretation or proposal needs 1–10 citations. Put unsupported ideas in unresolved questions.')
        for citation in finding['evidence']:
            fields(citation,('source','start','end'),'citation')
            source=citation['source']
            manifest=record['sources'].get(source) or record['evidence'].get(source)
            if not manifest:
                raise ValueError('Unknown or cross-run citation source.')
            if expanded and source in record['evidence'] and task['role'] not in ('combined','synthesis'):
                if task.get('id') not in {t['id'] for t in record['tasks']} or manifest['task_id'] not in ancestors(record['tasks'],task['id']):
                    raise ValueError('Web citation is outside this assignment dependency ancestors.')
            start,end=citation['start'],citation['end']
            if type(start) is not int or type(end) is not int or not 1<=start<=end<=manifest['lines']:
                raise ValueError('Invalid citation line range.')
    return copy.deepcopy(result)


def artifact_id(record):
    artifact={k:record.get(k) for k in ('id','project_id','revision','sources','goal','plan','evidence','results','combined')}
    if 'task_id' in record:artifact['task_id']=record['task_id']
    return digest(artifact)


def verify(run):
    return sources.verify(run)

def accept(run, reference):
    record=sources.load(run)
    if reference.get('run_id')!=record['id'] or reference.get('artifact_id')!=artifact_id(record):
        raise ValueError('The report changed; this action is stale.')
    if record['stage']=='accepted' and record.get('user_acceptance',{}).get('artifact_id')==reference['artifact_id']:
        return False
    reviewers=[r for t in record['tasks'] if t['role']=='reviewer' for r in [record['results'].get(t['id'],{})]]
    accepted=(all(r.get('verdict')=='accept' for r in reviewers) if record['plan'].get('policy_version',1)==2 else
              bool(reviewers) and reviewers[0].get('verdict')=='accept')
    if record['stage']!='completed' or not record.get('combined') or not reviewers or not accepted:
        raise ValueError('Reviewed acceptance requires a complete synthesis and Reviewer acceptance.')
    if not verify(run)['unchanged']:
        raise ValueError('Source checkout changed; acceptance is unavailable.')
    record=sources.load(run)
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
        if job['status']=='reserved': job['status']=stage if stage in ('cancelled','interrupted') else 'failed'
    runner.event(record,'Orchestrator',stage,detail)
