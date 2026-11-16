/* Agent task view and running-tasks view. Dispatches only the enumerated agent_* and scope_* intentions
   (scheduler.md, scope.md); every scope digest it sends was displayed from a backend reply. */
(()=>{
const S=window.interspaceStream,Scope=window.interspaceScope,P=window.interspaceProviders;
const scopes=new Map(),drafts=new Map();
let host=null,state=null,view='tasks',current=null,shownDraftFor=null,clientCount=0;
const $=id=>document.getElementById(id);
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const tokens=n=>Number(n||0).toLocaleString('en-US');

const row=id=>(state?.tasks||[]).find(t=>t.id===id);
const scheduled=id=>[...(state?.scheduler?.running||[]),...(state?.scheduler?.queued||[])].find(t=>t.task_id===id);
const isAgent=id=>row(id)?.mode==='agent'||!!scheduled(id)||S.has(id);
const title=id=>row(id)?.title||'Agent task '+String(id).slice(0,8);
// A subagent is a child task: its parent comes from the task row, the scheduler entry or the parent's events.
const parentOf=id=>row(id)?.parent_task_id||scheduled(id)?.parent_task_id||S.parentOf(id)||null;
const subOf=id=>{const p=parentOf(id);return p?S.children(p).find(c=>c.task_id===id)||null:null;};
const providerOf=id=>row(id)?.provider||scheduled(id)?.provider||subOf(id)?.provider||null;
const roleOf=id=>row(id)?.role||scheduled(id)?.role||subOf(id)?.role||(parentOf(id)?'subagent':'orchestrator');
const projectName=id=>(state?.projects||[]).find(p=>p.id===id)?.name||'Project '+String(id).slice(0,8);
function status(id){const s=S.status(id);if(s)return s;const q=scheduled(id);if(q)return {state:q.state||'queued',queue_position:q.position??null,detail:'',reason:null};const r=row(id);return r&&r.status&&r.status!=='draft'?{state:r.status,detail:'',queue_position:null,reason:null}:null;}
const stoppable=id=>{const s=status(id);return !!s&&!S.terminal(s)&&!['idle','cancelling'].includes(s.state);};

function scopeInfo(id){if(!scopes.has(id))scopes.set(id,{scope:null,digest:null,approval:null,error:'',editing:false,saving:false,rev:0});return scopes.get(id);}
function touch(id){scopeInfo(id).rev++;refresh();}
function loadScope(id){const info=scopeInfo(id);info.loading=true;host.request('scope_get',{task_id:id},{manual:true}).then(r=>{info.scope=r?.scope||null;info.digest=r?.scope_digest||null;info.approval=r?.scope_approval||null;info.error=info.scope?'':'This task has no scope yet.';}).catch(e=>{info.error=e.message;}).finally(()=>{info.loading=false;touch(id);});}
function saveScope(id,doc){const info=scopeInfo(id);info.saving=true;info.error='';touch(id);host.request('scope_update',{task_id:id,base_version:info.scope.version,scope:doc},{manual:true}).then(r=>{info.scope=r.scope;info.digest=r.scope_digest;info.approval=null;info.editing=false;}).catch(e=>{info.error=e.message;}).finally(()=>{info.saving=false;touch(id);});}
function approveScope(id){const info=scopeInfo(id);if(!info.scope||Scope.approved(info))return;info.saving=true;info.error='';touch(id);host.request('scope_approve',{task_id:id,scope_version:info.scope.version,scope_digest:info.digest},{manual:true}).then(r=>{info.approval=r.scope_approval;}).catch(e=>{info.error=e.message;}).finally(()=>{info.saving=false;touch(id);});}
function cancel(id){host.request('agent_cancel',{task_id:id},{manual:true}).catch(e=>{const info=scopeInfo(id);info.error=e.message;touch(id);});}

// Composer gate: a turn runs to completion before the next message; the scope must be approved.
function gate(id){const s=status(id),info=scopeInfo(id);if(s?.state==='paused_team')return 'Approve or decline the proposed team first.';if(S.busy(s))return 'The agent is working. You can send when this turn finishes.';if(info.scope&&!Scope.approved(info))return 'Approve the scope before sending.';return '';}
function send(text){
 const id=current;if(!id||gate(id))return;
 const clientId='c-'+Date.now().toString(36)+'-'+(++clientCount);
 drafts.set(id,'');$('agent-message').value='';S.optimistic(id,text,clientId);
 host.request('agent_message',{task_id:id,text,client_id:clientId},{manual:true}).catch(e=>{S.failed(id,clientId,e.message);if(!drafts.get(id)){drafts.set(id,text);if(current===id)$('agent-message').value=text;}});
}
const commands=()=>[
 {name:'scope',hint:'Edit this task’s scope',run:()=>{scopeInfo(current).editing=true;touch(current);}},
 {name:'approve',hint:'Approve the displayed scope',run:()=>approveScope(current)},
 {name:'stop',hint:'Stop this task',run:()=>cancel(current)},
 {name:'running',hint:'Show every running task',run:()=>host.navigate('running')},
 {name:'tasks',hint:'Back to the task desk',run:()=>host.navigate('tasks')}
];
const mentions=()=>S.mentions(current);

function head(container,id,compact){
 container.replaceChildren();
 el('p','agent-status',S.statusText(status(id)),container).setAttribute('role','status');
 const b=S.budget(id),q=scheduled(id);el('p','agent-budget footnote',b?S.budgetText(b):q?.tokens?'Tokens '+tokens(q.tokens.used)+' / '+tokens(q.tokens.budget):'',container);
 const provider=providerOf(id),parent=parentOf(id),model=row(id)?.model||subOf(id)?.model||null;
 const line=el('p','footnote runtime-line',null,container);
 line.append((parent?P.roleTitle(roleOf(id))+' subagent':'Orchestrator')+' on ');
 if(provider)P.badge(provider,line);else line.append('your default provider');
 line.append(model?' · '+model:' · default model');
 if(parent&&!compact){const up=el('button','link-button','Part of “'+title(parent)+'”',container);up.type='button';up.onclick=()=>host.openAgent(parent);}
 const w=S.workspace(id);if(w)el('p','footnote mono','Branch '+w.branch+' · base '+w.base_commit,container);
 if(w&&!compact&&window.interspaceReview){const r=el('button','','Review changes',container);r.type='button';r.onclick=()=>window.interspaceReview.open(id);}
}
function scopeArea(id){
 const info=scopeInfo(id),box=$('agent-scope');if(box.dataset.rev===id+':'+info.rev)return;box.dataset.rev=id+':'+info.rev;
 const list=box.querySelector('.scope-chips');Scope.chips(list,info,projectName);
 const actions=box.querySelector('.scope-actions');actions.replaceChildren();
 if(info.scope){const edit=el('button','',info.editing?'Close editor':'Edit scope',actions);edit.type='button';edit.disabled=info.saving;edit.setAttribute('aria-expanded',String(info.editing));edit.onclick=()=>{info.editing=!info.editing;touch(id);};
  if(!Scope.approved(info)){const ok=el('button','primary','Approve scope',actions);ok.type='button';ok.disabled=info.saving;ok.onclick=()=>approveScope(id);}}
 if(info.error)el('p','error-text',info.error,actions).setAttribute('role','alert');
 const editor=box.querySelector('.scope-host');
 if(info.editing&&info.scope){if(editor.dataset.for!==id+':'+info.scope.version){editor.dataset.for=id+':'+info.scope.version;Scope.editor(editor,info,{projectName,saving:info.saving,onSave:doc=>saveScope(id,doc),onClose:()=>{info.editing=false;touch(id);}});}else editor.querySelector('button[type=submit]').disabled=info.saving;}
 else{editor.replaceChildren();delete editor.dataset.for;}
}
function renderAgent(){
 const id=current;$('agent-view').hidden=view!=='agent'||!id;if($('agent-view').hidden)return;
 head($('agent-head'),id);$('agent-stop').hidden=!stoppable(id);
 scopeArea(id);
 // A newer scope than the one displayed (edited elsewhere) is reloaded before it can be approved.
 const ev=S.scopeEvent(id),info=scopeInfo(id);if(ev&&info.digest&&ev.scope_digest!==info.digest&&!info.loading&&!info.saving&&ev.scope_version>=(info.scope?.version||0))loadScope(id);
 const stream=$('agent-stream');const stick=innerHeight+scrollY>=document.documentElement.scrollHeight-80;
 S.render(stream,id);
 if(!stream.children.length&&!stream.querySelector('.empty'))el('p','empty muted','No activity yet. Describe what the agent should do.',stream);
 if(stick&&document.activeElement!==$('agent-message'))scrollTo(0,document.documentElement.scrollHeight);
 if(shownDraftFor!==id){shownDraftFor=id;$('agent-message').value=drafts.get(id)||'';}
 const reason=gate(id);$('agent-send').disabled=!!reason;
 $('agent-note').textContent=reason||'Enter sends · Shift+Enter adds a line · / for commands · @ to mention';
}
// Children are grouped under their parent's column; a child whose parent is unknown still gets the parent's column.
function children(id){
 const out=new Map();
 for(const t of [...(state?.scheduler?.running||[]),...(state?.scheduler?.queued||[])])if(t.parent_task_id===id)out.set(t.task_id,{task_id:t.task_id,role:t.role,provider:t.provider,state:t.state||'queued',tokens_used:t.tokens?.used});
 for(const c of S.children(id)){const was=out.get(c.task_id)||{};out.set(c.task_id,{...c,...Object.fromEntries(Object.entries(was).filter(([,v])=>v!=null))});}
 return [...out.values()];
}
function childRows(list,id){
 list.replaceChildren();list.setAttribute('aria-label','Subagents');
 for(const c of children(id)){
  const li=el('li','child-row',null,list);li.dataset.child=c.task_id;
  if(c.provider)P.badge(c.provider,li);el('strong','',P.roleTitle(c.role||'subagent'),li);
  el('span','footnote',S.statusText(S.status(c.task_id)||{state:c.state||'queued'})+(c.tokens_used!=null?' · '+tokens(c.tokens_used)+' tokens':''),li);
  const b=el('button','quiet','Open',li);b.type='button';b.setAttribute('aria-label','Open '+P.roleTitle(c.role||'subagent')+' subagent');b.onclick=()=>host.openAgent(c.task_id);
 }
 list.hidden=!list.children.length;
}
function columnIds(){
 const ids=[];const add=raw=>{const id=parentOf(raw)||raw;if(id&&!ids.includes(id))ids.push(id);};
 for(const t of state?.scheduler?.running||[])add(t.task_id);for(const t of state?.scheduler?.queued||[])add(t.task_id);
 for(const t of state?.tasks||[])if(t.mode==='agent')add(t.id);for(const id of S.ids())add(id);
 return ids;
}
function renderRunning(){
 const box=$('running-view');box.hidden=view!=='running';if(box.hidden)return;
 const grid=$('running-grid'),ids=columnIds();$('running-empty').hidden=!!ids.length;
 const s=state?.scheduler;$('running-note').textContent=s?(s.running?.length||0)+' running of '+s.max_running+' at once · '+(s.queued?.length||0)+' queued':'';
 const columns=new Map([...grid.children].map(c=>[c.dataset.task,c]));
 ids.forEach((id,i)=>{
  let col=columns.get(id);
  if(!col){col=el('section','task-column');col.dataset.task=id;col.setAttribute('aria-label',title(id));const top=el('div','column-head',null,col);el('h2','',null,top);el('div','column-status',null,col);const acts=el('div','actions',null,col);
   el('ul','child-rows',null,col);const open=el('button','','Open',acts);open.type='button';open.onclick=()=>host.openAgent(id);const stop=el('button','','Stop',acts);stop.type='button';stop.className='stop';stop.onclick=()=>cancel(id);el('div','stream compact',null,col);}
  col.querySelector('h2').textContent=title(id);head(col.querySelector('.column-status'),id,true);childRows(col.querySelector('.child-rows'),id);col.querySelector('.stop').hidden=!stoppable(id);
  S.render(col.querySelector('.stream'),id,{compact:true});
  if(grid.children[i]!==col)grid.insertBefore(col,grid.children[i]||null);
 });
 for(const c of [...grid.children])if(!ids.includes(c.dataset.task))c.remove();
}
function refresh(){if(!state)return;renderAgent();renderRunning();}

window.interspaceAgent={
 init(options){
  host=options;S.init({request:options.request,open:id=>host.openAgent(id),changed:id=>{if(view==='agent'&&(id===current||parentOf(id)===current)||view==='running')refresh();}});
  window.interspaceComposer.attach({input:$('agent-message'),menu:$('agent-menu'),form:$('agent-composer'),commands,mentions,onSend:send,onInput:text=>{if(current)drafts.set(current,text);}});
  $('agent-stop').onclick=()=>cancel(current);$('agent-back').onclick=()=>host.navigate('tasks');
 },
 isAgent,title:()=>title(current),current:()=>current,parentOf,
 setDraft(id,text){drafts.set(id,text);if(current===id)shownDraftFor=null;},
 open(id){current=id;S.sync(id);if(!scopes.has(id)||!scopeInfo(id).scope)loadScope(id);},
 render(nextState,nextView){state=nextState;view=nextView;refresh();}
};
})();
