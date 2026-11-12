/* Agent task view and running-tasks view. Dispatches only the enumerated agent_* and scope_* intentions
   (scheduler.md, scope.md); every scope digest it sends was displayed from a backend reply. */
(()=>{
const S=window.interspaceStream,Scope=window.interspaceScope;
const scopes=new Map(),drafts=new Map(),extraMentions=[];
let host=null,state=null,view='tasks',current=null,lastAgent=null,shownDraftFor=null,clientCount=0;
const $=id=>document.getElementById(id);
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const tokens=n=>Number(n||0).toLocaleString('en-US');

const row=id=>(state?.tasks||[]).find(t=>t.id===id);
const scheduled=id=>[...(state?.scheduler?.running||[]),...(state?.scheduler?.queued||[])].find(t=>t.task_id===id);
const isAgent=id=>row(id)?.mode==='agent'||!!scheduled(id)||S.has(id);
const title=id=>row(id)?.title||'Agent task '+String(id).slice(0,8);
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
function gate(id){const s=status(id),info=scopeInfo(id);if(S.busy(s))return 'The agent is working. You can send when this turn finishes.';if(info.scope&&!Scope.approved(info))return 'Approve the scope before sending.';return '';}
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
 {name:'spaces',hint:'Browse connected apps',run:()=>host.navigate('space')},
 {name:'running',hint:'Show every running task',run:()=>host.navigate('running')},
 {name:'tasks',hint:'Back to the task desk',run:()=>host.navigate('tasks')}
];
function mentions(){
 const info=scopeInfo(current),out=[...S.mentions(current)];
 for(const a of info.scope?.apps||[])if(Array.isArray(a.resources))for(const r of a.resources)out.push({value:r.ref,hint:S.appName(a.app)});
 return [...extraMentions,...out];
}
function insertMention(ref,label){
 if(!lastAgent)return {ok:false,text:'Open an agent task first, then mention this again.'};
 extraMentions.unshift({value:ref,hint:label||''});
 const draft=drafts.get(lastAgent)||'';drafts.set(lastAgent,draft+(draft&&!/\s$/.test(draft)?' ':'')+'@'+ref+' ');
 shownDraftFor=null;if(current===lastAgent&&view==='agent')$('agent-message').value=drafts.get(lastAgent);
 return {ok:true,text:'Added @'+ref+' to the message for “'+title(lastAgent)+'”.'};
}

function head(container,id){
 container.replaceChildren();
 el('p','agent-status',S.statusText(status(id)),container).setAttribute('role','status');
 const b=S.budget(id),q=scheduled(id);el('p','agent-budget footnote',b?S.budgetText(b):q?.tokens?'Tokens '+tokens(q.tokens.used)+' / '+tokens(q.tokens.budget):'',container);
 const w=S.workspace(id);if(w)el('p','footnote mono','Branch '+w.branch+' · base '+w.base_commit,container);
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
function columnIds(){
 const ids=[];const add=id=>{if(id&&!ids.includes(id))ids.push(id);};
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
   const open=el('button','','Open',acts);open.type='button';open.onclick=()=>host.openAgent(id);const stop=el('button','','Stop',acts);stop.type='button';stop.className='stop';stop.onclick=()=>cancel(id);el('div','stream compact',null,col);}
  col.querySelector('h2').textContent=title(id);head(col.querySelector('.column-status'),id);col.querySelector('.stop').hidden=!stoppable(id);
  S.render(col.querySelector('.stream'),id,{compact:true});
  if(grid.children[i]!==col)grid.insertBefore(col,grid.children[i]||null);
 });
 for(const c of [...grid.children])if(!ids.includes(c.dataset.task))c.remove();
}
function refresh(){if(!state)return;renderAgent();renderRunning();}

window.interspaceAgent={
 init(options){
  host=options;S.init({request:options.request,changed:id=>{if(view==='agent'&&id===current||view==='running')refresh();}});
  window.interspaceComposer.attach({input:$('agent-message'),menu:$('agent-menu'),form:$('agent-composer'),commands,mentions,onSend:send,onInput:text=>{if(current)drafts.set(current,text);}});
  $('agent-stop').onclick=()=>cancel(current);$('agent-back').onclick=()=>host.navigate('tasks');
 },
 isAgent,title:()=>title(current),insertMention,
 open(id){current=id;lastAgent=id;S.sync(id);if(!scopes.has(id)||!scopeInfo(id).scope)loadScope(id);},
 render(nextState,nextView){state=nextState;view=nextView;refresh();}
};
})();
