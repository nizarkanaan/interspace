/* Native task desk. Every intention goes through the enumerated local bridge. */
(()=>{
const $=id=>document.getElementById(id);
let state=null,view='tasks',taskTab='conversation',sequence=0,selectionEpoch=0;
const pending=new Map(),newDrafts=new Map();
const node=(tag,text,parent)=>{const e=document.createElement(tag);e.textContent=text;if(parent)parent.append(e);return e;};
const MODES={review:'Read-only review',python_fix:'Fix & test (Python)'};
const P=window.interspaceProviders,R=window.interspaceResearch;
let newKind=null;
function error(text){$('error').hidden=!text;$('error').textContent=text||'';}
function request(method,params={},options={}){return new Promise((resolve,reject)=>{
 const id=String(++sequence);if(!window.webkit?.messageHandlers?.interspace){reject(Error('Open Interspace.app to use the local backend.'));return;}
 pending.set(id,{resolve,reject,method,params,epoch:selectionEpoch,...options});window.webkit.messageHandlers.interspace.postMessage({id,method,params});
});}
window.interspaceReceive=message=>{
 if(message.type==='event'){window.interspaceStream.receive(message.event);return;}
 if(message.type==='fatal'){error(message.error);return;}
 if(message.type==='state'){apply(message.state);return;}
 if(message.type==='auth'){$('auth').hidden=false;$('auth').textContent=message.text;return;}
 const call=pending.get(String(message.id));if(!call)return;pending.delete(String(message.id));
 const navigation=['switch_project','select_task','choose_project'].includes(call.method);
 const scoped=call.params.project_id!==undefined;
 const stale=call.manual||call.epoch!==selectionEpoch||(scoped&&!navigation&&call.params.project_id!==state?.project_id);
 if(message.error){if(!stale)error(message.error);call.reject(Error(message.error));}
 else{if(message.result?.projects&&!stale)apply(message.result);call.resolve(message.result);}
};
function apply(next){P.fromState(next.provider_status);const changed=!state||state.project_id!==next.project_id||state.task_id!==next.task_id;state=next;if(changed)taskTab='conversation';error(state.error);render();}
function navigate(next){selectionEpoch++;if(next==='new')newKind=view==='research'||!state?.projects?.length?'research':'project';view=next;if(next==='settings'||next==='new'){P.load();R.load();}render();}
function openProject(id){const epoch=++selectionEpoch;return request('switch_project',{project_id:id}).then(()=>{if(epoch===selectionEpoch)navigate('tasks');}).catch(()=>{});}
function openAgent(id){selectionEpoch++;window.interspaceAgent.open(id);navigate('agent');}
function openTask(id){if(window.interspaceAgent.isAgent(id)){openAgent(id);return Promise.resolve();}const epoch=++selectionEpoch;return request('select_task',{project_id:state.project_id,task_id:id}).then(()=>{if(epoch!==selectionEpoch)return;taskTab='conversation';navigate('detail');}).catch(()=>{});}
function render(){if(!state)return;
 window.interspaceWorkspace.render(state,request,openProject);
 $('project-settings').hidden=view!=='settings'||!state.project_id;
 const task=state.task,detail=view==='detail'&&!!task&&task.mode!=='agent';
 if(view==='detail'&&!detail)view='tasks';
 document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(view===b.dataset.view)));
 $('heading').textContent=detail?task.title:view==='agent'?window.interspaceAgent.title():({tasks:'Tasks',research:'Research',new:'New task',settings:'Settings',running:'Running tasks',review:'Review changes'}[view]||'Tasks');
 $('heading-note').textContent=view==='tasks'?'An outcome, an agent, a branch you merge.':view==='research'?'Questions answered from scholarly sources. Each citation report shows which references were checked and which were verified.':'';
 $('breadcrumb').textContent=view==='research'||view==='agent'&&window.interspaceAgent.isResearch(window.interspaceAgent.current())?'Research':state.project||'Your workspace';
 $('project-name').textContent=state.project||'Add a project to see its details.';
 // A research question needs no project, so New task is always available.
 $('new-task').hidden=view==='new';$('new-task').textContent=view==='research'?'New research question':'New task';
 $('task-desk').hidden=view!=='tasks';$('research-desk').hidden=view!=='research';$('new-task-panel').hidden=view!=='new';$('settings').hidden=view!=='settings';$('review-view').hidden=view!=='review';$('task-detail').hidden=!detail;
 // Subagents are child tasks: they appear under their task, not as desk rows.
 const rows=(state.tasks||[]).filter(t=>!t.parent_task_id&&!window.interspaceAgent.parentOf(t.id)&&t.kind!=='research');
 $('task-project').textContent=state.project||'No project selected';$('task-count').textContent=rows.length+' tasks';$('desk-tasks').replaceChildren();
 $('desk-empty').hidden=!!rows.length;
 for(const t of rows){const row=node('button','',$('desk-tasks'));row.className='desk-task';row.dataset.openTask=t.id;row.disabled=t.status==='unavailable';const title=node('div','',row);node('strong',t.title,title);const sub=node('small',t.status==='unavailable'?'Saved data unavailable — other tasks remain usable':t.mode==='agent'?'':'Earlier task (read-only) · '+(MODES[t.mode]||t.mode),title);if(t.mode==='agent'&&t.status!=='unavailable'){sub.append('Orchestrator on ');if(t.provider)P.badge(t.provider,sub);else sub.append('your default provider');sub.append((t.model?' · '+t.model:'')+' · own task branch');}node('span',t.mode==='agent'?String(t.status).replaceAll('_',' '):t.status==='unavailable'?'unavailable':'read only',row);row.onclick=()=>openTask(t.id);}
 $('active-owner').hidden=!state.active;$('activity').textContent=state.active?state.active+' · working':'';$('stop').disabled=!state.active;
 if(detail)renderHistory(task);
 if(view==='new')renderNew();
 if(view==='settings'){P.renderSettings($('providers-settings'));R.renderSettings($('research-settings'));}
 window.interspaceAgent.render(state,view);
 renderResearch();
}
// The sidebar's Research entry: tasks without a project (research/tasks.md), next to the projects.
function renderResearch(){
 const rows=window.interspaceAgent.researchRows();
 $('research-nav-count').textContent=rows.length?String(rows.length):'';
 if(view!=='research')return;
 $('research-count').textContent=rows.length+' task'+(rows.length===1?'':'s');$('research-empty').hidden=!!rows.length;
 const list=$('research-tasks');list.replaceChildren();
 for(const t of rows){const row=node('button','',list);row.className='desk-task';row.dataset.openTask=t.id;row.disabled=t.status==='unavailable';const title=node('div','',row);node('strong',t.title,title);
  const sub=node('small','',title);if(t.status==='unavailable')sub.textContent='Saved data unavailable — other tasks remain usable';else{sub.append('Research · Orchestrator on ');if(t.provider)P.badge(t.provider,sub);else sub.append('your default provider');sub.append((t.model?' · '+t.model:'')+' · no project');}
  node('span',String(t.status||'').replaceAll('_',' '),row);row.onclick=()=>openAgent(t.id);}
}
// An earlier task: its conversation, plan text and result text. Nothing here sends anything.
function renderHistory(task){
 const h=task.history||{messages:[],plan:'',reports:[]};
 $('task-meta').textContent=(MODES[h.mode]||h.mode||'Earlier task')+' · '+(h.label||'Earlier task (read-only)');
 $('task-tokens').textContent=tokenLine(task.tokens);
 document.querySelectorAll('[data-task-tab]').forEach(b=>b.setAttribute('aria-pressed',String(taskTab===b.dataset.taskTab)));
 $('conversation').hidden=taskTab!=='conversation';$('plan-section').hidden=taskTab!=='plan';$('results').hidden=taskTab!=='result';
 $('transcript').replaceChildren();
 if(!h.messages.length){const empty=node('div','',$('transcript'));empty.className='empty';node('p','No conversation was saved for this task.',empty);}
 for(const m of h.messages){const item=node('div','',$('transcript'));item.className='message '+(m.role==='user'?'user':'assistant');node('small',m.role==='user'?'You':'Orchestrator',item);node('div',m.text,item);}
 $('plan-text').textContent=h.plan||'';$('plan-text').hidden=!h.plan;$('plan-empty').hidden=!!h.plan;
 const out=$('result-body');out.replaceChildren();$('result-empty').hidden=!!(h.reports.length||h.error);
 if(h.error){const e=node('p',h.error,out);e.className='error-text';}
 for(const r of h.reports){const box=node('article','',out);box.className='finding';node('h3',(r.goal||'Saved run')+' · '+String(r.stage).replaceAll('_',' '),box);const pre=node('pre',r.text||'No final report was saved for this run.',box);pre.className='history-text';pre.tabIndex=0;}
}
function renderNew(){let d=newDrafts.get(state.project_id);if(!d){d={goal:''};newDrafts.set(state.project_id,d);}if(newKind){d.kind=newKind;newKind=null;}$('new-project').textContent=state.project;$('new-goal').value=d.goal||'';window.interspaceAgentNew.fill(d,state);window.interspaceAgentNew.render(state);}
function saveNew(){if(state)newDrafts.set(state.project_id,{goal:$('new-goal').value,...window.interspaceAgentNew.read()});}
async function agentCreated({task_id,project_id,desk,goal}){
 newDrafts.delete(desk);if(goal)window.interspaceAgent.setDraft(task_id,goal);
 if(view!=='new'||state?.project_id!==desk)return;
 // A research task has no project: it opens without switching the desk's project.
 if(project_id!=null&&project_id!==state.project_id){const epoch=++selectionEpoch;try{await request('switch_project',{project_id});}catch{return;}if(epoch!==selectionEpoch)return;}
 openAgent(task_id);
}
function tokens(n){return Number(n).toLocaleString('en-US');}
function tokenLine(t){if(!t)return '';const head=t.budget==null?'Tokens '+tokens(t.used)+' used':'Tokens '+tokens(t.used)+' / '+tokens(t.budget);const extra=[];if(t.estimated)extra.push(tokens(t.estimated)+' estimated');if(t.unknown)extra.push(t.unknown+' older call'+(t.unknown===1?'':'s')+' without counts');if(t.overshoot)extra.push('over budget by '+tokens(t.overshoot));return head+(extra.length?' · '+extra.join(' · '):'');}

document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>navigate(b.dataset.view));
document.querySelectorAll('[data-task-tab]').forEach(b=>b.onclick=()=>{taskTab=b.dataset.taskTab;render();});
$('new-task').onclick=()=>navigate('new');$('back-tasks').onclick=()=>navigate('tasks');
$('new-goal').oninput=saveNew;
$('new-task-form').onsubmit=e=>{e.preventDefault();window.interspaceAgentNew.review();};
for(const id of ['new-title','new-model'])$(id).oninput=()=>{$(id).setCustomValidity('');saveNew();};
for(const id of ['new-agent-project','new-provider'])$(id).addEventListener('change',saveNew);
$('new-bib').addEventListener('input',saveNew);
window.interspaceAgentNew.init({request,refresh:()=>{if(state&&view==='new')renderNew();},changed:saveNew,created:agentCreated});
window.interspaceAgent.init({request,navigate,openAgent});
P.init({request,changed:()=>{if(state)render();}});
R.init({request,changed:()=>{if(state)render();}});
// Review and merge (stream 1D) registers here: it gets the bridge and a view of its own.
// It returns to the view it was opened from; the task's project comes from the open task or the desk.
let reviewFrom='tasks';
window.interspaceReview?.init?.({request,navigate,mount:$('review-view'),
 show:()=>{if(view!=='review')reviewFrom=view;navigate('review');},back:()=>navigate(reviewFrom),changed:()=>render(),
 projectOf:id=>state?.task?.id===id&&state.task.agent?.project_id||state?.project_id||null});
document.querySelector('[data-action=choose]').onclick=()=>{selectionEpoch++;request('choose_project').then(()=>navigate('settings')).catch(()=>{});};
$('stop').onclick=()=>request('cancel').catch(()=>{});
window.interspaceBoot=()=>request('state').then(()=>P.load()).catch(e=>error(e.message));
})();
