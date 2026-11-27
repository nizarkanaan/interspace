/* Agent task view and running-tasks view. Dispatches only the enumerated agent_* and scope_* intentions
   (scheduler.md, scope.md); every scope digest it sends was displayed from a backend reply. */
(()=>{
const S=window.interspaceStream,Scope=window.interspaceScope,P=window.interspaceProviders;
const scopes=new Map(),drafts=new Map();
let host=null,state=null,view='tasks',current=null,shownDraftFor=null,clientCount=0;
const $=id=>document.getElementById(id);
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const tokens=n=>Number(n||0).toLocaleString('en-US');

// Research tasks (no project) are listed in state.research.tasks; state.tasks holds the selected project's tasks.
const allRows=()=>{const seen=new Set();return [...(state?.tasks||[]),...(Array.isArray(state?.research?.tasks)?state.research.tasks:[])].filter(t=>t&&typeof t.id==='string'&&!seen.has(t.id)&&seen.add(t.id));};
const row=id=>allRows().find(t=>t&&t.id===id);
const scheduled=id=>[...(state?.scheduler?.running||[]),...(state?.scheduler?.queued||[])].find(t=>t.task_id===id);
const isAgent=id=>row(id)?.mode==='agent'||row(id)?.kind==='research'||!!scheduled(id)||S.has(id);
const title=id=>row(id)?.title||'Agent task '+String(id).slice(0,8);
// A subagent is a child task: its parent comes from the task row, the scheduler entry or the parent's events.
const parentOf=id=>row(id)?.parent_task_id||scheduled(id)?.parent_task_id||S.parentOf(id)||null;
const subOf=id=>{const p=parentOf(id);return p?S.children(p).find(c=>c.task_id===id)||null:null;};
const providerOf=id=>row(id)?.provider||scheduled(id)?.provider||subOf(id)?.provider||null;
const roleOf=id=>row(id)?.role||scheduled(id)?.role||subOf(id)?.role||(parentOf(id)?'subagent':'orchestrator');
const projectName=id=>(state?.projects||[]).find(p=>p.id===id)?.name||'Project '+String(id).slice(0,8);
// A research task has no project: no workspace, no Review or Merge. A subagent inherits its root task's kind.
const isResearch=id=>{for(let t=id,i=0;t&&i<8;t=parentOf(t),i++){const r=row(t);if(r)return r.kind==='research'||r.project_id===null&&r.kind!=='project';}return false;};
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
// A message the app sends for the user (Check claims), leaving any draft in the composer alone.
function post(id,text){
 const clientId='c-'+Date.now().toString(36)+'-'+(++clientCount);S.optimistic(id,text,clientId);
 host.request('agent_message',{task_id:id,text,client_id:clientId},{manual:true}).catch(e=>{S.failed(id,clientId,e.message);});
}
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
 const st=status(id);el('p','agent-status',S.statusText(st),container).setAttribute('role','status');
 // After a restart nothing resumes by itself: say so plainly, and offer no resume action.
 if(st?.state==='interrupted'&&!compact)el('p','interrupted-note','The app closed while this '+(parentOf(id)?'subagent':'task')+' was working. Nothing resumed, and nothing will on its own. Its branch and changes are kept'+(parentOf(id)?'.':'; send a message to start a new turn.'),container);
 const b=S.budget(id),q=scheduled(id);el('p','agent-budget footnote',b?S.budgetText(b):q?.tokens?'Tokens '+tokens(q.tokens.used)+(q.tokens.budget==null?' used':' / '+tokens(q.tokens.budget)):'',container);
 const usage=window.interspaceResearchCards.usageText(S.usage(id));if(usage)el('p','research-usage footnote',usage,container);
 const provider=providerOf(id),parent=parentOf(id),model=row(id)?.model||subOf(id)?.model||null;
 const line=el('p','footnote runtime-line',null,container);
 line.append((parent?P.roleTitle(roleOf(id))+' subagent':'Orchestrator')+' on ');
 if(provider)P.badge(provider,line);else line.append('your default provider');
 line.append(model?' · '+model:' · default model');
 if(isResearch(id))line.append(' · Research task: no project, so no files, commands or branch');
 if(parent&&!compact){const up=el('button','link-button','Part of “'+title(parent)+'”',container);up.type='button';up.onclick=()=>host.openAgent(parent);}
 const w=S.workspace(id);if(w)el('p','footnote mono','Branch '+w.branch+' · base '+w.base_commit,container);
 if(w&&!compact&&window.interspaceReview&&!isResearch(id)){const r=el('button','','Review changes',container);r.type='button';r.id='review-head-'+String(id).replace(/[^A-Za-z0-9_-]/g,'_');r.onclick=()=>window.interspaceReview.open(id);}
}
function scopeArea(id){
 const info=scopeInfo(id),box=$('agent-scope');if(box.dataset.rev===id+':'+info.rev)return;box.dataset.rev=id+':'+info.rev;
 const list=box.querySelector('.scope-chips');Scope.chips(list,info,projectName);
 const actions=box.querySelector('.scope-actions');actions.replaceChildren();
 if(info.scope){const edit=el('button','',info.editing?'Close editor':'Edit scope',actions);edit.type='button';edit.disabled=info.saving;edit.setAttribute('aria-expanded',String(info.editing));edit.onclick=()=>{info.editing=!info.editing;if(info.editing)openEditor(id);touch(id);};
  if(!Scope.approved(info)){const ok=el('button','primary','Approve scope',actions);ok.type='button';ok.disabled=info.saving;ok.onclick=()=>approveScope(id);}}
 if(info.error)el('p','error-text',info.error,actions).setAttribute('role','alert');
 const editor=$('agent-scope-editor');
 if(info.editing&&info.scope){if(editor.dataset.for!==id+':'+info.scope.version){editor.dataset.for=id+':'+info.scope.version;Scope.editor(editor,info,{projectName,saving:info.saving,onSave:doc=>saveScope(id,doc),onClose:()=>{info.editing=false;touch(id);}});}else editor.querySelector('button[type=submit]').disabled=info.saving;}
 else{editor.replaceChildren();delete editor.dataset.for;}
}
function renderAgent(){
 const id=current;$('agent-view').hidden=view!=='agent'||!id;
 // Leaving the reader undoes the split: while `placed` stays true the page-level scroll guard keeps every other
 // page (Settings, the desks) pinned to the top.
 if($('agent-view').hidden){place(false);return;}
 head($('agent-head'),id);$('agent-stop').hidden=!stoppable(id);$('agent-back').textContent=isResearch(id)?'← Research':'← Tasks';
 scopeArea(id);
 outputsArea(id);
 const {tab,talk,split}=layoutTabs(id);
 $('agent-stream').hidden=!talk;$('agent-composer').hidden=!talk;detailToggle(talk);$('agent-scope-editor').hidden=split?tab!=='details':!talk;
 scopeNote(id,talk);
 // A newer scope than the one displayed (edited elsewhere) is reloaded before it can be approved.
 const ev=S.scopeEvent(id),info=scopeInfo(id);const seen=ev&&ev.scope_version+':'+ev.scope_digest;
 // At most one reload per scope event: a reply that still differs (or an event without a digest) never loops.
 if(ev&&info.digest&&ev.scope_digest!==info.digest&&!info.loading&&!info.saving&&ev.scope_version>=(info.scope?.version||0)&&info.reloadedFor!==seen){info.reloadedFor=seen;loadScope(id);}
 // In the split reader the conversation column scrolls on its own; elsewhere the window does.
 const stream=$('agent-stream'),chat=split?document.querySelector('#agent-view .agent-main'):null;
 const stick=chat?chat.scrollTop+chat.clientHeight>=chat.scrollHeight-80:innerHeight+scrollY>=document.documentElement.scrollHeight-80;
 S.render(stream,id);
 if(!stream.children.length&&!stream.querySelector('.empty'))el('p','empty muted','No activity yet. Describe what the agent should do.',stream);
 if(stick&&talk&&document.activeElement!==$('agent-message')){if(chat)chat.scrollTop=chat.scrollHeight;else scrollTo(0,document.documentElement.scrollHeight);}
 if(shownDraftFor!==id){shownDraftFor=id;$('agent-message').value=drafts.get(id)||'';}
 const reason=gate(id);$('agent-send').disabled=!!reason;
 $('agent-note').textContent=reason||'Enter sends · Shift+Enter adds a line · / for commands · @ to mention';
 if(tab==='corpus')corpusArea(id);
 if(tab==='report')reportArea(id);
 if(tab==='evidence')evidenceArea(id);
}
// A task's outputs (report and BibTeX), from its latest `outputs` event.
function outputsArea(id){
 const box=$('agent-outputs'),data=S.outputs(id),key=id+':'+JSON.stringify(data)+':'+outputsRev;
 if(box.dataset.key===key)return;box.dataset.key=key;
 const keep=document.activeElement&&box.contains(document.activeElement)?document.activeElement.id:null;
 window.interspaceResearchCards.outputsPanel(box,id,data,{request:host.request,refresh:()=>{outputsRev++;refresh();},openReport:isResearch(id)&&!parentOf(id)?()=>{tabs.set(id,'report');refresh();const t=$('agent-tabs');if(t)scrollTo(0,0);requestAnimationFrame(()=>{const f=$('agent-report');if(f)f.focus();});}:null});
 if(keep){const again=document.getElementById(keep);if(again)again.focus();}
}
let outputsRev=0;
// Corpus tab (2026-11-20-task-corpus-design.md): root research tasks only. Fetched when opened, and again (at most
// once a second) after a `corpus` event while it is open.
const tabs=new Map(),corpora=new Map();
// Task details (2026-11-20-details-panel-and-display-design.md): status, scope and outputs sit in a side panel; in a
// narrow window the panel is the Details tab. Corpus is for root research tasks only.
const narrowQuery=matchMedia('(max-width: 1099px)');
function layoutTabs(id){
 const nav=$('agent-tabs'),narrow=narrowQuery.matches,root=isResearch(id)&&!parentOf(id),split=root&&!narrow;
 place(split);
 const report=root&&reportOutput(id)!=null;
 let tab=tabs.get(id)||'conversation';
 if(split){
  // Split reader (2026-11-20-split-reader-design.md): the conversation is always beside the results.
  const info=scopeInfo(id),waiting=!!info.scope&&!Scope.approved(info);
  if(tab==='conversation'||tab==='report'&&!report)tab=waiting?'details':report?'report':'corpus';
 }else{
  if((tab==='corpus'||tab==='evidence')&&!root||tab==='details'&&!narrow)tab='conversation';
  if(tab==='report'&&!report)tab='conversation';
 }
 const shown={conversation:!split,report,corpus:root,evidence:root,details:split||narrow};
 for(const b of nav.querySelectorAll('[data-agent-tab]')){b.hidden=!shown[b.dataset.agentTab];b.setAttribute('aria-pressed',String(b.dataset.agentTab===tab));}
 nav.querySelector('[data-agent-tab=details]').textContent=split?'Scope and outputs':'Details';
 nav.hidden=Object.values(shown).filter(Boolean).length<2;
 $('agent-corpus').hidden=tab!=='corpus';$('agent-evidence').hidden=tab!=='evidence';$('agent-report').hidden=tab!=='report';$('agent-details').hidden=(split||narrow)&&tab!=='details';
 topbar(id,split);
 return {tab,talk:split||tab==='conversation',split};
}
// Moves the result sections between the side-panel layout and the split reader's results column.
let placed=false;
// Resizable split (2026-11-20): drag the divider, use the arrow keys on it, or double-click to reset. The width is a
// per-viewer convenience kept in localStorage, which can be unavailable; the default then applies.
const SPLIT_DEFAULT=420,SPLIT_MIN=300,RESULTS_MIN=420,SPLIT_STEP=24;
function splitLimits(){const w=document.querySelector('#agent-view .agent-layout')?.getBoundingClientRect().width||innerWidth;return [SPLIT_MIN,Math.max(SPLIT_MIN,w-RESULTS_MIN)];}
function splitWidth(next){
 let px=next;if(px==null){try{px=Number(localStorage.getItem('interspace.splitWidth'))||SPLIT_DEFAULT;}catch{px=SPLIT_DEFAULT;}}
 const [lo,hi]=splitLimits();px=Math.round(Math.min(hi,Math.max(lo,px)));
 $('agent-view').style.setProperty('--chat-width',px+'px');
 const h=$('split-handle');h.setAttribute('aria-valuemin',String(lo));h.setAttribute('aria-valuemax',String(hi));h.setAttribute('aria-valuenow',String(px));h.setAttribute('aria-valuetext',px+' pixels wide');
 if(next!=null){try{localStorage.setItem('interspace.splitWidth',String(px));}catch{}}
 return px;
}
function splitHandle(){
 const h=$('split-handle'),now=()=>Number(h.getAttribute('aria-valuenow'))||SPLIT_DEFAULT;
 h.addEventListener('pointerdown',e=>{
  if(e.button!==0)return;e.preventDefault();h.setPointerCapture(e.pointerId);document.body.classList.add('resizing');
  const left=document.querySelector('#agent-view .agent-layout').getBoundingClientRect().left;
  const move=ev=>splitWidth(ev.clientX-left);
  const up=()=>{h.removeEventListener('pointermove',move);h.removeEventListener('pointerup',up);h.removeEventListener('pointercancel',up);document.body.classList.remove('resizing');};
  h.addEventListener('pointermove',move);h.addEventListener('pointerup',up);h.addEventListener('pointercancel',up);
 });
 h.addEventListener('dblclick',()=>{try{localStorage.removeItem('interspace.splitWidth');}catch{}splitWidth(SPLIT_DEFAULT);try{localStorage.removeItem('interspace.splitWidth');}catch{}});
 h.addEventListener('keydown',e=>{
  const [lo,hi]=splitLimits(),map={ArrowLeft:now()-SPLIT_STEP,ArrowRight:now()+SPLIT_STEP,Home:lo,End:hi};
  if(e.key in map){e.preventDefault();splitWidth(map[e.key]);}
  else if(e.key==='Enter'){e.preventDefault();splitWidth(SPLIT_DEFAULT);try{localStorage.removeItem('interspace.splitWidth');}catch{}}
 });
 addEventListener('resize',()=>{if(placed)splitWidth(now());});
}
function place(split){
 if(split===placed)return;placed=split;
 const main=document.querySelector('#agent-view .agent-main'),results=$('agent-results'),layout=document.querySelector('#agent-view .agent-layout');
 const parts=['agent-tabs','agent-scope-editor','agent-report','agent-corpus','agent-evidence','agent-details'].map(x=>$(x));
 $('agent-view').classList.toggle('split',split);results.hidden=!split;$('agent-topbar').hidden=!split;$('split-handle').hidden=!split;if(split)splitWidth(null);
 if(split){$('agent-topbar').prepend($('agent-back'));$('agent-topbar-status').after($('agent-detail-toggle'));results.append(...parts);}
 else{main.prepend($('agent-back'));$('agent-back').after($('agent-tabs'));$('agent-scope-note').after($('agent-scope-editor'));$('agent-stream').before($('agent-report'),$('agent-corpus'),$('agent-evidence'),$('agent-detail-toggle'));layout.append($('agent-details'));}
}
function topbar(id,split){
 if(!split)return;
 const st=status(id),b=S.budget(id),info=scopeInfo(id);
 $('agent-topbar-status').textContent=S.statusText(st)+(b?' · '+S.budgetText(b):'');
 const scope=$('agent-topbar-scope');scope.hidden=!info.scope;
 scope.textContent=info.scope?(Scope.approved(info)?'Scope approved · v'+info.scope.version:'Scope needs approval'):'';
 scope.className=info.scope&&!Scope.approved(info)?'scope-waiting':'';
 $('agent-topbar-stop').hidden=!stoppable(id);
}
// Simple or Detailed conversation (2026-11-27-readable-workspace-design.md): one click beside the conversation, the
// same setting as Settings → Conversation display.
function detailToggle(talk){
 const b=$('agent-detail-toggle'),detailed=window.interspaceDisplay?.get?.()?.detail==='detailed';
 b.hidden=!talk;b.textContent=detailed?'Detailed view':'Simple view';b.setAttribute('aria-pressed',String(detailed));
}
function scopeNote(id,talk){
 const info=scopeInfo(id),waiting=!!info.scope&&!Scope.approved(info)&&!info.editing;
 $('agent-scope-note').hidden=!talk||!waiting;
}
function openEditor(id){
 if(placed)tabs.set(id,'details');else if(narrowQuery.matches)tabs.set(id,'conversation');
 requestAnimationFrame(()=>{const e=$('agent-scope-editor');if(e&&!e.hidden)e.scrollIntoView({block:'start'});});
}
// Report tab (2026-11-20-report-reader-design.md): report.md at reading width, refetched when its output changes.
const reports=new Map();
const reportOutput=id=>(Array.isArray(S.outputs(id)?.outputs)?S.outputs(id).outputs:[]).find(o=>o&&o.name==='report.md')||null;
function reportInfo(id){if(!reports.has(id))reports.set(id,{text:null,truncated:false,loading:false,error:'',key:null,rev:0,saving:false,note:'',saveError:''});return reports.get(id);}
function reportArea(id){
 const r=reportInfo(id),o=reportOutput(id),key=JSON.stringify(o),c=corpusInfo(id);
 if(!c.data&&!c.loading&&!c.error)loadCorpus(id);
 if(o&&r.key!==key&&!r.loading){r.key=key;r.loading=true;r.error='';r.rev++;
  host.request('task_output_read',{task_id:id,name:'report.md'},{manual:true}).then(x=>{if(typeof x?.text!=='string')throw Error('The report could not be read.');r.text=x.text;r.truncated=!!x.truncated;})
   .catch(e=>{r.error=e.message||'The report could not be read.';}).finally(()=>{r.loading=false;r.rev++;refresh();});}
 // Claim check (2026-11-20-claim-check-design.md): loaded when the tab opens and again after each `claims` event.
 const ev=JSON.stringify(S.claims(id));
 if(r.claimsSeen!==ev&&!r.claimsLoading){r.claimsSeen=ev;r.claimsLoading=true;host.request('task_claims',{task_id:id},{manual:true}).then(x=>{r.claims=x;}).catch(()=>{}).finally(()=>{r.claimsLoading=false;r.rev++;refresh();});}
 const busy=['queued','starting','running','waiting_lock','cancelling'].includes(status(id)?.state);
 const box=$('agent-report'),k=id+':'+r.rev+':'+c.rev+':'+busy;if(box.dataset.key===k)return;box.dataset.key=k;
 const keep=document.activeElement&&box.contains(document.activeElement)?document.activeElement.id:null;
 box.tabIndex=-1;
 window.interspaceReader.render(box,{name:'report.md',bytes:o?.bytes,text:r.text,truncated:r.truncated,corpus:c.data,loading:r.loading,error:r.error,saving:r.saving,note:r.note,saveError:r.saveError,
  claims:r.claims,checking:r.checking,checkError:r.checkError,canCheck:!!r.text&&!busy,
  onCheck:()=>{r.checking=true;r.checkError='';r.rev++;refresh();
   host.request('claims_start',{task_id:id},{manual:true}).then(x=>{r.claims=x;const why=gate(id);if(why)throw Error(why);post(id,'Check the claims in the saved report.');})
    .catch(e=>{r.checkError=e.message||'The claim check could not start.';}).finally(()=>{r.checking=false;r.rev++;refresh();});},
  onSave:()=>{r.saving=true;r.note='';r.saveError='';r.rev++;refresh();host.request('task_output_save',{task_id:id,name:'report.md'},{manual:true}).then(x=>{r.note=x?.saved?'Saved.':'Not saved.';}).catch(e=>{r.saveError=e.message||'The report was not saved.';}).finally(()=>{r.saving=false;r.rev++;refresh();});}});
 if(keep){const again=document.getElementById(keep);if(again)again.focus();}
}
// Evidence tab (2026-11-20-evidence-table-design.md): loaded when opened and again after each `evidence` event.
const tables=new Map();
function evidenceArea(id){
 if(!tables.has(id))tables.set(id,{data:null,loading:false,error:'',note:'',seen:null,busy:false,rev:0,ui:{}});
 const t=tables.get(id),ev=JSON.stringify(S.evidence(id));
 const load=()=>{t.loading=true;host.request('task_table',{task_id:id},{manual:true}).then(x=>{t.data=x;t.error='';}).catch(e=>{t.error=e.message;}).finally(()=>{t.loading=false;t.rev++;refresh();});};
 if(t.seen!==ev&&!t.loading){t.seen=ev;load();}
 const busy=['queued','starting','running','waiting_lock','cancelling'].includes(status(id)?.state);
 const box=$('agent-evidence'),k=id+':'+t.rev+':'+busy;if(box.dataset.key===k)return;box.dataset.key=k;
 window.interspaceEvidence.render(box,t.data,t.ui,{busy:t.busy,canFill:!busy,error:t.error,note:t.note,
  onFill:(columns,rows)=>{t.busy=true;t.error='';t.rev++;refresh();
   host.request('table_start',{task_id:id,columns,rows},{manual:true}).then(x=>{t.data=x;t.ui.editing=false;const why=gate(id);if(why)throw Error(why);post(id,'Fill the evidence table.');t.note='Asked the Orchestrator to fill the table with Claude and Codex. Approve the team in the conversation.';})
    .catch(e=>{t.error=e.message||'The table could not start.';}).finally(()=>{t.busy=false;t.rev++;refresh();});},
  onResolve:(row,column,value)=>{host.request('table_resolve',{task_id:id,row,column,value},{manual:true}).then(x=>{t.data=x;}).catch(e=>{t.error=e.message;}).finally(()=>{t.rev++;refresh();});},
  onExport:()=>{t.note='';host.request('table_export',{task_id:id},{manual:true}).then(()=>host.request('task_output_save',{task_id:id,name:'evidence.csv'},{manual:true})).then(r=>{t.note=r?.saved?'Saved evidence.csv.':'Not saved.';}).catch(e=>{t.error=e.message;}).finally(()=>{t.rev++;refresh();});}});
}
function corpusInfo(id){if(!corpora.has(id))corpora.set(id,{data:null,loading:false,error:'',loadedFor:undefined,timer:null,ui:{q:'',filter:'all',sort:'found',all:false},rev:0});return corpora.get(id);}
function loadCorpus(id){
 const c=corpusInfo(id);if(c.loading)return;c.loading=true;c.rev++;c.loadedFor=JSON.stringify(S.corpus(id));
 host.request('task_corpus',{task_id:id},{manual:true}).then(r=>{c.data=r&&typeof r==='object'?r:null;c.error='';}).catch(e=>{c.error=e.message||'The corpus could not be loaded.';}).finally(()=>{c.loading=false;c.rev++;refresh();});
}
function corpusArea(id){
 const c=corpusInfo(id),ev=JSON.stringify(S.corpus(id));
 if(!c.data&&!c.loading&&!c.error)loadCorpus(id);
 // Refetch (debounced) whenever the latest corpus event differs from the one the shown data was fetched for, so an
 // event that lands while a fetch is still out is not lost.
 else if(!c.loading&&ev!==c.loadedFor&&!c.timer)c.timer=setTimeout(()=>{c.timer=null;if(current===id&&tabs.get(id)==='corpus')loadCorpus(id);},1000);
 const box=$('agent-corpus'),key=id+':'+c.rev;if(box.dataset.key===key)return;box.dataset.key=key;
 window.interspaceCorpus.render(box,c.data,c.ui,{loading:c.loading,error:c.error,refresh:()=>{c.rev++;refresh();}});
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
  el('span','footnote',S.statusText(S.childStatus(c.task_id,c.state))+(c.tokens_used!=null?' · '+tokens(c.tokens_used)+' tokens':''),li);
  const b=el('button','quiet','Open',li);b.type='button';b.setAttribute('aria-label','Open '+P.roleTitle(c.role||'subagent')+' subagent');b.onclick=()=>host.openAgent(c.task_id);
 }
 list.hidden=!list.children.length;
}
function columnIds(){
 const ids=[];const add=raw=>{const id=parentOf(raw)||raw;if(id&&!ids.includes(id))ids.push(id);};
 for(const t of state?.scheduler?.running||[])add(t.task_id);for(const t of state?.scheduler?.queued||[])add(t.task_id);
 for(const t of allRows())if(t&&(t.mode==='agent'||t.kind==='research'))add(t.id);for(const id of S.ids())add(id);
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
  host=options;S.init({request:options.request,open:id=>host.openAgent(id),rowStatus:id=>row(id)?.status||null,stamp:id=>{const m=window.interspaceReview?.merged?.(id);return m?m.into+':'+m.merge_commit:'';},changed:id=>{if(view==='agent'&&(id===current||parentOf(id)===current)||view==='running')refresh();}});
  window.interspaceComposer.attach({input:$('agent-message'),menu:$('agent-menu'),form:$('agent-composer'),commands,mentions,onSend:send,onInput:text=>{if(current)drafts.set(current,text);}});
  for(const b of $('agent-tabs').querySelectorAll('[data-agent-tab]'))b.onclick=()=>{if(!current)return;const nav=$('agent-tabs'),stuck=nav.getBoundingClientRect().top<=1;tabs.set(current,b.dataset.agentTab);if(b.dataset.agentTab==='corpus'){const c=corpusInfo(current);if(c.data)loadCorpus(current);}refresh();
   // Conversation opens at its latest message; Corpus opens at its top when the tab row is pinned.
   if(placed)$('agent-results').scrollTop=0;
   else if(b.dataset.agentTab==='conversation')scrollTo(0,document.documentElement.scrollHeight);
   else if(stuck){let p=nav.previousElementSibling;while(p&&p.hidden)p=p.previousElementSibling;scrollTo(0,p?p.getBoundingClientRect().bottom+scrollY:0);}};
  $('agent-scope-review').onclick=()=>{if(!current)return;if(narrowQuery.matches||placed){tabs.set(current,'details');refresh();}const b=$('agent-scope').querySelector('.primary')||$('agent-scope').querySelector('button');if(b)b.focus();};
  narrowQuery.addEventListener('change',()=>refresh());
  splitHandle();
  // In the split reader only the columns scroll. Focus and scrollIntoView can still scroll the page itself, which
  // shifted the whole view up and left a blank band; any such scroll is undone at once.
  addEventListener('scroll',()=>{if(placed&&(scrollX||scrollY))scrollTo(0,0);},{passive:true});
  $('agent-stop').onclick=()=>cancel(current);
  $('agent-detail-toggle').onclick=()=>{const D=window.interspaceDisplay;D.setDetail(D.get().detail==='detailed'?'simple':'detailed');};
  $('agent-topbar-stop').onclick=()=>cancel(current);
  $('agent-topbar-scope').onclick=()=>{if(!current)return;tabs.set(current,'details');refresh();$('agent-results').scrollTop=0;};$('agent-back').onclick=()=>host.navigate(current&&isResearch(current)?'research':'tasks');
 },
 isAgent,isResearch,stateOf:id=>S.status(id)?.state||null,researchRows:()=>(Array.isArray(state?.research?.tasks)?state.research.tasks:[]).filter(t=>t&&typeof t.id==='string'&&!t.parent_task_id&&!parentOf(t.id)),title:()=>title(current),current:()=>current,parentOf,
 setDraft(id,text){drafts.set(id,text);if(current===id)shownDraftFor=null;},
 open(id){current=id;S.sync(id);if(!scopes.has(id)||!scopeInfo(id).scope)loadScope(id);},
 render(nextState,nextView){state=nextState;view=nextView;refresh();}
};
})();
