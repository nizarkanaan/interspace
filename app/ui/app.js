/* Native task desk. Every intention goes through the enumerated local bridge. */
(()=>{
const root=document.getElementById('ispace'),$=id=>document.getElementById(id);
let state=null,view='tasks',scope='task',taskTab='conversation',resultTab='combined',attempt='current',sequence=0,selectionEpoch=0,creating=false;
const pending=new Map(),drafts=new Map(),newDrafts=new Map();
const node=(tag,text,parent)=>{const e=document.createElement(tag);e.textContent=text;if(parent)parent.append(e);return e;};
const owner=()=>({project_id:state?.project_id,task_id:state?.task_id??null});
const sameOwner=p=>p.project_id===state?.project_id&&(p.task_id??null)===(state?.task_id??null);
const draftKey=()=>scope==='workspace'?'workspace':scope==='task'?'task:'+state?.project_id+':'+state?.task_id:'project:'+state?.project_id;
const saveDraft=()=>{if(state)drafts.set(draftKey(),$('message').value);};
const restoreDraft=()=>{const key=draftKey();$('message').value=drafts.has(key)?drafts.get(key):scope==='task'?state?.task?.draft||'':'';};
const roleDefinitions=[{id:'web_searcher',name:'Web searcher',department:'discovery',code:'WS',look:'Scout',prop:'scanner'},{id:'researcher',name:'Researcher',department:'research',code:'RS',look:'Researcher',prop:'book'},{id:'reviewer',name:'Reviewer',department:'review',code:'RV',look:'Reviewer',prop:'clipboard'},{id:'implementer',name:'Implementer',department:'engineering',code:'IM',look:'Builder',prop:'wrench'},{id:'tester',name:'Tester',department:'engineering',code:'TS',look:'Builder',prop:'test'}];
root.interspaceRoles={byName:name=>roleDefinitions.find(r=>r.name===name),departments:[{id:'discovery',name:'Web scouts'},{id:'research',name:'Research'},{id:'engineering',name:'Engineering'},{id:'review',name:'Review'}]};
function error(text){$('error').hidden=!text;$('error').textContent=text||'';}
function request(method,params={},options={}){return new Promise((resolve,reject)=>{
 const id=String(++sequence);if(!window.webkit?.messageHandlers?.interspace){reject(Error('Open Interspace.app to use the local backend.'));return;}
 pending.set(id,{resolve,reject,method,params,epoch:selectionEpoch,...options});window.webkit.messageHandlers.interspace.postMessage({id,method,params});
});}
window.interspaceReceive=message=>{
 if(message.type==='event'){window.interspaceStream.receive(message.event);return;}
 if(message.type==='spaces_auth'||message.type==='spaces_changed'){window.interspaceSpaces.receive(message);return;}
 if(message.type==='fatal'){error(message.error);$('send').disabled=true;return;}
 if(message.type==='state'){apply(message.state);return;}
 if(message.type==='auth'){$('auth').hidden=false;$('auth').textContent=message.text;return;}
 const call=pending.get(String(message.id));if(!call)return;pending.delete(String(message.id));
 const projectMethod=['list_sources','preview_source','save_sources','update_project'].includes(call.method);
 const scoped=call.params.project_id!==undefined;
 const navigation=['switch_project','select_task','choose_project'].includes(call.method);
 const changeReply=['approve_checks','apply_changes','change_evidence'].includes(call.method);
 const staleChange=changeReply&&(call.params.run_id!==state?.run?.id||call.params.plan_digest!==state?.run?.plan?.digest||call.params.candidate_digest!==state?.run?.candidate?.digest||call.params.artifact_id!==state?.run?.artifact_id);
 const stale=staleChange||call.manual||call.epoch!==selectionEpoch||(scoped&&!navigation&&(call.params.project_id!==state?.project_id||(!projectMethod&&Object.hasOwn(call.params,'task_id')&&!sameOwner(call.params))));
 if(message.error){if(!stale)error(message.error);call.reject(Error(message.error));}
 else{if(message.result?.threads&&!stale){if(!state||navigation||sameOwner(message.result))apply(message.result);}call.resolve(message.result);}
};
function apply(next){
 const changed=!state||state.project_id!==next.project_id||state.task_id!==next.task_id||state.run?.id!==next.run?.id;
 saveDraft();state=next;if(changed){attempt='current';resultTab=window.interspaceTeam.isTeam(next.run)||window.interspaceChanges.isChange(next.run)?'combined':'researcher';$('source-box').hidden=true;$('artifact-browser').open=false;}
 restoreDraft();error(state.error);render();
}
function navigate(next){saveDraft();selectionEpoch++;view=next;scope=next==='workspace'?'workspace':next==='project'?'project':'task';restoreDraft();render();}
function selectArtifact(id){resultTab=id;taskTab='result';navigate(state.task?'detail':'project');}
function openProject(id){saveDraft();const epoch=++selectionEpoch;return request('switch_project',{project_id:id}).then(()=>{if(epoch===selectionEpoch)navigate('tasks');}).catch(()=>{});}
function openAgent(id){saveDraft();selectionEpoch++;window.interspaceAgent.open(id);navigate('agent');}
function openTask(id){if(window.interspaceAgent.isAgent(id)){openAgent(id);return Promise.resolve();}saveDraft();const epoch=++selectionEpoch;return request('select_task',{project_id:state.project_id,task_id:id}).then(()=>{if(epoch!==selectionEpoch)return;taskTab=state.pending?'plan':state.run?'result':'conversation';navigate('detail');}).catch(()=>{});}
const sourceBlocked=()=>!!state.source_error||state.source_selection?.mode==='unconfirmed';
const resultVisible=()=>view==='detail'&&taskTab==='result'||view==='project';
function render(){if(!state)return;
 window.interspaceChanges.setContext(state,selectionEpoch);
 window.interspaceWorkspace.render(state,request,openProject);
 $('project-settings').hidden=view!=='settings'||!state.project_id;
 window.interspaceSources.render(state,request,view==='settings');
 root.interspaceLab?.unmount();
 const task=state.task,detail=view==='detail'&&!!task;
 if(view==='detail'&&!task){view='tasks';scope='task';}
 document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(view===b.dataset.view)));
 $('heading').textContent=detail?task.title:view==='agent'?window.interspaceAgent.title():view==='space'?window.interspaceSpaces.title():({tasks:'Tasks',new:'New task',lab:'Observatory',settings:'Settings',workspace:'Workspace advice',project:'Project conversation',running:'Running tasks'}[view]||'Tasks');
 $('heading-note').textContent=view==='tasks'?'An outcome, a plan, a place to follow through.':view==='lab'?'Recorded assignments, in their fixed departments.':'';
 $('breadcrumb').textContent=view==='workspace'?'Your workspace':state.project||'Your workspace';
 $('project-name').textContent=state.project||'Add a project to choose sources.';
 $('connection').textContent=state.connection?.message||'Not checked';
 $('project-conversation').disabled=!state.project_id;$('new-task').hidden=view==='new';$('new-task').disabled=!state.project_id||!!state.active;
 $('task-desk').hidden=view!=='tasks';$('new-task-panel').hidden=view!=='new';$('settings').hidden=view!=='settings';$('task-detail').hidden=!detail;
 $('task-project').textContent=state.project||'No project selected';$('task-count').textContent=(state.tasks||[]).length+' tasks';$('desk-tasks').replaceChildren();
 $('desk-empty').hidden=!!state.tasks?.length;
 for(const t of state.tasks||[]){const row=node('button','',$('desk-tasks'));row.className='desk-task';row.dataset.openTask=t.id;row.disabled=t.status==='unavailable';const title=node('div','',row);node('strong',t.title,title);node('small',t.status==='unavailable'?'Saved data unavailable — other tasks remain usable':t.mode==='agent'?'Agent task · workspace branch':t.run_count+' runs · specialist allowance '+t.specialist_limit,title);node('span',t.status.replaceAll('_',' '),row);row.onclick=()=>openTask(t.id);}
 $('task-meta').textContent=task?(task.mode==='python_fix'?'Python fix':'Read-only review')+' · Specialist allowance '+task.specialist_limit+' · '+(state.tasks?.find(t=>t.id===task.id)?.status||'draft').replaceAll('_',' '):'';
 document.querySelectorAll('[data-task-tab]').forEach(b=>b.setAttribute('aria-pressed',String(taskTab===b.dataset.taskTab)));
 $('task-allowance').hidden=!detail||taskTab!=='plan';if(task&&document.activeElement!==$('task-limit'))$('task-limit').value=task.specialist_limit;
 $('task-budget-form').hidden=!detail||taskTab!=='plan';if(task&&document.activeElement!==$('task-budget'))$('task-budget').value=task.token_budget??'';for(const control of $('task-budget-form').elements)control.disabled=!!state.active;
 $('task-tokens').textContent=task?tokenLine(task.tokens):'';
 const projected=state.plan_budget;$('plan-budget').hidden=!(detail&&taskTab==='plan'&&state.pending&&projected);$('plan-budget').textContent=projected?projectionText(projected,'This plan'):'';
 for(const control of $('task-allowance').elements)control.disabled=!!state.active;
 $('active-owner').hidden=!state.active;
 $('activity').textContent=state.active?state.active+' · '+(state.active_project||'Workspace')+(state.active_task?' / '+state.active_task:'')+' · working':'';
 $('stop').disabled=!state.active;
 const conversationVisible=detail&&taskTab==='conversation'||['workspace','project'].includes(view);
 $('conversation').hidden=!conversationVisible;$('conversation-title').textContent=scope==='workspace'?'Workspace Orchestrator':scope==='project'?'General project conversation':'Task conversation';
 $('send').disabled=!!state.active||(scope!=='workspace'&&sourceBlocked());$('message').disabled=!!state.active;
 $('composer-note').textContent=scope!=='workspace'&&sourceBlocked()?'Save this project’s sources in Settings before sending.':'Messages use your connected account.';
 $('transcript').replaceChildren();const messages=state.threads?.[scope]||[];
 if(!messages.length){const empty=node('div','',$('transcript'));empty.className='empty';node('p',scope==='workspace'?'Ask for advice on project priorities and next actions.':scope==='project'?'This conversation is separate from individual tasks.':'Describe the outcome, refine a plan, or ask about this task’s evidence.',empty);}
 for(const message of messages){const item=node('div','',$('transcript'));item.className='message '+(message.role==='user'?'user':'assistant');node('small',message.role==='user'?'You':'Orchestrator',item);node('div',message.text,item);}
 $('plan').replaceChildren();const plan=state.pending,showPlan=detail&&taskTab==='plan'||view==='project';$('plan').hidden=!showPlan||!plan;$('plan-empty').hidden=!detail||taskTab!=='plan'||!!plan;
 if(plan?.kind==='change'&&showPlan)window.interspaceChanges.renderPlan($('plan'),plan,state,startRequest,node);
 else if(plan?.kind==='team'&&showPlan)window.interspaceTeam.renderPlan($('plan'),plan,state,startRequest,node);
 else if(plan&&showPlan){const box=node('div','',$('plan'));box.className='plan';node('h3',plan.kind==='revision'?'Proposed read-only revision':'Proposed read-only review',box);node('p',plan.goal,box);node('p',(plan.roles||[]).join(' → ')+' · '+plan.limit+' · revision '+plan.revision.slice(0,12),box);const b=node('button',plan.kind==='revision'?'Start read-only revision':'Start read-only review',box);b.className='primary';b.disabled=!!state.active;b.onclick=()=>startRequest('start_review',{project_id:plan.project_id,task_id:state.task_id,plan_id:plan.id}).catch(()=>{});}
 // General project plans are visible in their own conversation surface.
 if(view==='project')$('conversation').after($('plan'));else $('task-allowance').after($('plan'));
 const showWork=detail&&taskTab==='activity'||view==='lab';$('work').hidden=!showWork;$('work-heading').textContent=view==='lab'?'Recorded specialists':'Task activity';
 const run=state.run;let items=[];if(run){if(window.interspaceChanges.isChange(run))items=window.interspaceChanges.items(run);else if(window.interspaceTeam.isTeam(run))items=window.interspaceTeam.items(run);else for(const role of roleDefinitions.filter(r=>['researcher','reviewer'].includes(r.id))){const result=run.results[role.id],started=run.events.some(e=>e.role===role.id&&e.status==='started'&&(e.round||0)===(run.revision_round||0));const label=result?'Done':state.active===role.name&&state.active_project_id===state.project_id&&state.active_task_id===state.task_id&&state.active_run_id===run.id?'Working':started?'Stopped':'Queued';items.push({id:role.id,role:role.name,assignment:role.name,department:role.department,instance:role.name+' 1',state:label,label,title:role.id==='researcher'?'Review selected evidence':'Check claims and proposal'});}}
 $('no-run').hidden=!!run;$('task-list').replaceChildren();for(const task of items){const item=node('div','',$('task-list'));item.className='task';const portrait=node('canvas','',item);portrait.dataset.characterRole=task.role;portrait.setAttribute('aria-hidden','true');const b=node('button','',item);b.setAttribute('aria-pressed',String(resultTab===task.id));node('strong',task.assignment||task.instance,b);node('small',task.title+' · '+task.label,b);b.onclick=()=>selectArtifact(task.id);}
 $('activity-events').replaceChildren();for(const event of run?.events||[]){const item=node('div','',$('activity-events'));item.className='event';node('small',event.time,item);node('h3',event.role+' · '+event.status.replaceAll('_',' '),item);node('p',event.detail,item);}
 $('usage').replaceChildren();for(const entry of state.usage||[]){if(scope!=='workspace'&&(entry.project_id!==state.project_id||(state.task_id&&entry.task_id!==state.task_id)))continue;const u=entry.tokens||{};node('p',entry.role+': '+(Object.keys(u).length?Object.entries(u).map(([k,v])=>k.replaceAll('_',' ')+' '+v).join(' · '):'usage unavailable')+chargeText(entry),$('usage'));}
 $('workspace-overview').hidden=view!=='workspace';const canvas=root.querySelector('.lab-canvas');canvas.hidden=view!=='lab'||!run;root.interspaceLab?.mount(canvas.hidden?null:canvas,items,resultTab,selectArtifact);
 renderResults();$('results').hidden=!run||!resultVisible();$('result-empty').hidden=!detail||taskTab!=='result'||!!run;
 if(view==='new')renderNew();
 window.interspaceAgent.render(state,view);window.interspaceSpaces.render(state,view);
}
function startRequest(method,params){const epoch=selectionEpoch,current={project_id:params.project_id,task_id:params.task_id??null};return request(method,params).then(result=>{if(epoch===selectionEpoch&&sameOwner(current)&&(method!=='start_change'||state.pending?.digest===params.plan_digest||state.run?.plan?.digest===params.plan_digest&&['queued','running'].includes(state.run.stage))){taskTab='activity';render();}return result;});}
function renderNew(){const d=newDrafts.get(state.project_id)||{goal:'',limit:'6',mode:'review',budget:'250000'};$('new-project').textContent=state.project;$('new-goal').value=d.goal;$('new-limit').value=d.limit;$('new-budget').value=d.budget||'250000';$('new-mode').value=d.mode||'review';$('new-mode-note').textContent=d.mode==='python_fix'?'Propose bounded Python replacements in an app-owned copy. Running checks and applying to the original project each need your exact approval. Mode is fixed when the task is created.':'Review approved committed evidence. The source project is never edited or executed. Mode is fixed when the task is created.';$('new-sources').textContent=sourceBlocked()?'Save project sources in Settings before requesting a plan. You can create a local draft now.':'Uses this project’s saved committed sources. Planning uses one call from your connected account; drafts stay local.';$('propose-task').disabled=creating||!!state.active||sourceBlocked();$('create-draft').disabled=creating||!!state.active;}
function saveNew(){if(state)newDrafts.set(state.project_id,{goal:$('new-goal').value,limit:$('new-limit').value,mode:$('new-mode').value,budget:$('new-budget').value});}
function tokens(n){return Number(n).toLocaleString('en-US');}
function tokenLine(t){if(!t)return '';const head=t.budget==null?'Tokens '+tokens(t.used)+' used · No budget set (set one on the Plan tab)':'Tokens '+tokens(t.used)+' / '+tokens(t.budget);const extra=[];if(t.reserved)extra.push(tokens(t.reserved)+' reserved for a running call');if(t.estimated)extra.push(tokens(t.estimated)+' estimated');if(t.unknown)extra.push(t.unknown+' older call'+(t.unknown===1?'':'s')+' without counts');if(t.overshoot)extra.push('over budget by '+tokens(t.overshoot));return head+(extra.length?' · '+extra.join(' · '):'');}
function projectionText(p,subject){let text=tokens(Math.max(0,p.remaining))+' of '+tokens(p.budget)+' tokens remain. '+subject+'\'s '+p.calls+' call'+(p.calls===1?' is':'s are')+' estimated at about '+tokens(p.projected)+' tokens.';if(!p.first_fits)text+=' Not even the smallest next call fits: raise the token budget before starting.';else if(!p.fits)text+=' This will likely stop early with budget exhausted; completed work would be kept.';return text;}
window.interspaceProjectionText=projectionText;
function chargeText(entry){if(!entry.charge_kind)return '';if(entry.charge_kind==='reserved')return ' · '+tokens(entry.estimate)+' reserved (estimate)';return ' · charged '+tokens(entry.charge)+(entry.charge_kind==='estimated'?' (estimated: no counts returned)':' (reported)');}
function allowance(input){const value=Number(input.value);if(!Number.isSafeInteger(value)||value<1){input.setCustomValidity('Enter a positive whole number within the safe integer range.');input.reportValidity();return null;}input.setCustomValidity('');return value;}
async function createTask(propose){
 const goal=$('new-goal').value.trim(),limit=allowance($('new-limit')),tokenBudget=limit===null?null:allowance($('new-budget'));if(!goal||limit===null||tokenBudget===null)return;
 const project_id=state.project_id,epoch=selectionEpoch,draft={...newDrafts.get(project_id)},rawGoal=$('new-goal').value;
 creating=true;renderNew();try{
  const result=await request('create_task',{project_id,title:Array.from(goal).slice(0,160).join(''),specialist_limit:limit,token_budget:tokenBudget,draft:rawGoal,mode:$('new-mode').value},{manual:true});
  const task_id=result.task_id;if(!task_id)throw Error('The local task could not be created.');
  const key='task:'+project_id+':'+task_id;drafts.set(key,rawGoal);
  const current=newDrafts.get(project_id);if(current?.goal===rawGoal&&current?.limit===draft.limit&&current?.mode===draft.mode&&current?.budget===draft.budget)newDrafts.delete(project_id);
  if(selectionEpoch!==epoch||state.project_id!==project_id||view!=='new')return;
  apply(result);taskTab='conversation';navigate('detail');
  if(propose){await request('chat',{scope:'task',project_id,task_id,text:goal});if(drafts.get(key)===rawGoal)drafts.set(key,'');if(draftKey()===key)restoreDraft();if(sameOwner({project_id,task_id})&&view==='detail'){taskTab=state.pending?'plan':'conversation';render();}}
 }catch(e){if(selectionEpoch===epoch&&state.project_id===project_id)error(e.message);}
 finally{creating=false;if(view==='new')renderNew();}
}
async function source(c){const reference={...owner(),run_id:state.run?.id};try{const result=await request('source',{...reference,source:c.source});if(!sameOwner(reference)||state.run?.id!==reference.run_id||result.task_id!==undefined&&result.task_id!==reference.task_id)return;$('source-box').hidden=false;$('source-title').textContent=c.source+':'+c.start+'–'+c.end;$('source-text').textContent=result.text.split('\n').slice(c.start-1,c.end).map((line,i)=>(c.start+i)+'  '+line).join('\n');$('source-title').scrollIntoView({block:'nearest'});}catch{}}
function renderResults(){const run=state?.run;$('results').hidden=!(run&&resultVisible());if(!run)return;const select=id=>{resultTab=id;renderResults();};if(window.interspaceChanges.isChange(run)){window.interspaceChanges.renderResults(state,resultTab,select,request,source,node);return;}if(window.interspaceTeam.isTeam(run)){window.interspaceTeam.renderResults(state,resultTab,select,request,source,node);return;}window.interspaceTeam.legacyTabs(resultTab,select,node);$('run-status').textContent=run.stage.replaceAll('_',' ');$('source-box').hidden=true;
const versionSelect=$('attempt');versionSelect.replaceChildren();const currentOption=node('option','Current report · round '+(run.revision_round||0),versionSelect);currentOption.value='current';for(const previous of run.previous_attempts||[]){const option=node('option','Previous report · round '+previous.round,versionSelect);option.value=String(previous.round);}if(attempt!=='current'&&!(run.previous_attempts||[]).some(a=>String(a.round)===attempt))attempt='current';versionSelect.value=attempt;
const controls=$('revision-controls');controls.replaceChildren();$('report-usage').replaceChildren();const used=run.revision_round||0,limit=run.revision_limit??1;node('p','Revision rounds used: '+used+'/'+limit+'. One round adds Researcher and Reviewer sessions; no automatic repeat.',$('report-usage'));
if(run.revision_instructions)node('p','Revision request: '+run.revision_instructions,controls);
if(attempt==='current'){const reference={project_id:state.project_id,task_id:state.task_id,run_id:run.id,artifact_id:run.artifact_id};if(run.stage==='needs_revision'&&used<limit){const b=node('button','Revise from reviewer feedback',controls);b.disabled=!!state.active;b.className='primary';b.onclick=()=>request('revise_run',reference).catch(()=>{});}else if(run.stage==='needs_revision'&&used>=limit){node('p','Revision limit reached. Inspect the remaining findings before explicitly starting any new review.',controls);}if(run.stage==='completed'&&run.results.reviewer?.verdict==='accept'){const b=node('button','Accept this report',controls);b.disabled=!!state.active;b.className='primary';b.onclick=()=>request('accept_report',reference).catch(()=>{});node('p','Acceptance records this report version only. It does not authorize an experiment or project changes.',controls);}if(run.stage==='accepted')node('p','This report version is accepted. No experiment or project change was authorized.',controls);}else node('p','Viewing a preserved previous version. Select Current report for available actions.',controls);
const out=$('result-body');out.replaceChildren();document.querySelectorAll('[data-result]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.result===resultTab)));$('integrity').textContent=run.verification?(run.verification.unchanged?'Source integrity verified: HEAD, Git status and tracked file hashes match the pre-run baseline.':'Source changed during this run. Inspect the checkout before further work.'):'Integrity check will run when the interaction finishes.';
if(resultTab==='events'){for(const event of run.events){const e=node('div','',out);e.className='finding';node('small',event.time,e);node('h3',event.role+' · '+event.status+' · round '+(event.round||0),e);node('p',event.detail,e);}return;}if(resultTab==='sources'){node('p','Committed revision '+run.revision+'. Selected technical evidence only; no fresh web search.',out);for(const [name,m] of Object.entries(run.sources)){const b=node('button',name+' · '+m.lines+' lines',out);b.className='citation';b.onclick=()=>source({source:name,start:1,end:Math.min(35,m.lines)});}return;}
const selected=attempt==='current'?run:(run.previous_attempts||[]).find(a=>String(a.round)===attempt);const result=selected?.results[resultTab];if(!result){node('p','No artifact received for this stage yet.',out);return;}node('h2',(resultTab==='researcher'?'Research report':'Independent review')+(result.verdict?' · '+result.verdict:''),out);node('p',result.summary,out);for(const finding of result.findings){const e=node('div','',out);e.className='finding';node('p',finding.claim,e);for(const c of finding.evidence){const b=node('button',c.source+':'+c.start+'–'+c.end,e);b.className='citation';b.onclick=()=>source(c);}}node('h3',resultTab==='researcher'?'Proposed experiment · not executed':'Review conclusion',out);node('p',result.proposal,out);}

$('attempt').onchange=()=>{attempt=$('attempt').value;renderResults();};
$('message').oninput=saveDraft;
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>navigate(b.dataset.view));
document.querySelectorAll('[data-task-tab]').forEach(b=>b.onclick=()=>{taskTab=b.dataset.taskTab;render();});
$('new-task').onclick=()=>navigate('new');$('back-tasks').onclick=()=>navigate('tasks');
$('new-goal').oninput=saveNew;$('new-mode').onchange=()=>{saveNew();renderNew();};$('new-limit').oninput=()=>{$('new-limit').setCustomValidity('');saveNew();};$('new-budget').oninput=()=>{$('new-budget').setCustomValidity('');saveNew();};
$('new-task-form').onsubmit=e=>{e.preventDefault();createTask(true);};$('create-draft').onclick=()=>createTask(false);
$('new-source-settings').onclick=()=>navigate('settings');
document.querySelectorAll('[data-space]').forEach(b=>b.onclick=()=>{window.interspaceSpaces.select(b.dataset.space);navigate('space');});
window.interspaceAgent.init({request,navigate,openAgent});
window.interspaceSpaces.init({request,navigate,mention:(ref,label)=>window.interspaceAgent.insertMention(ref,label),refresh:render});
$('task-budget-form').onsubmit=e=>{e.preventDefault();const value=allowance($('task-budget'));if(value!==null)request('update_task',{...owner(),token_budget:value}).catch(()=>{});};
$('task-allowance').onsubmit=e=>{e.preventDefault();const value=allowance($('task-limit'));if(value!==null)request('update_task',{...owner(),specialist_limit:value}).catch(()=>{});};
$('task-limit').oninput=()=>$('task-limit').setCustomValidity('');
$('project-conversation').onclick=()=>{saveDraft();const epoch=++selectionEpoch;request('select_task',{project_id:state.project_id,task_id:null}).then(()=>{if(epoch===selectionEpoch)navigate('project');}).catch(()=>{});};
document.querySelector('[data-action=choose]').onclick=()=>{selectionEpoch++;request('choose_project').then(()=>navigate('settings')).catch(()=>{});};
document.querySelector('[data-action=connection]').onclick=()=>request('connection').catch(()=>{});
document.querySelector('[data-action=signin]').onclick=()=>request('sign_in').catch(()=>{});
$('stop').onclick=()=>request('cancel').catch(()=>{});
$('composer').onsubmit=event=>{event.preventDefault();const raw=$('message').value,text=raw.trim();if(!text)return;const key=draftKey(),params={scope,text,project_id:scope==='workspace'?null:state.project_id};if(scope==='task')params.task_id=state.task_id;request('chat',params).then(()=>{if(drafts.get(key)===raw)drafts.set(key,'');if(draftKey()===key)restoreDraft();if(scope==='task'&&draftKey()===key&&state.pending){taskTab='plan';render();}}).catch(()=>{});};
window.interspaceBoot=()=>request('state').then(()=>request('connection')).catch(e=>error(e.message));
})();
