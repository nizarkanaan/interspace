/* Sidebar task lists (docs/superpowers/specs/2026-11-20-sidebar-modes-design.md): the current mode's root tasks,
   grouped by what they need from you, each with its state in words. Titles come from tasks and are set as text. */
(()=>{
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const SHOWN=8;
const NEEDS={paused_ask:'Answer a question',paused_scope:'Approve a scope change',paused_team:'Approve the team'};
const WORKING={queued:'Queued',starting:'Starting',running:'Working',waiting_lock:'Waiting for the project',cancelling:'Stopping'};
const DONE={failed:'Stopped after an error',interrupted:'Interrupted',cancelled:'Stopped',read_only:'Earlier task, read only'};
const GROUPS=[['needs','Needs you'],['working','Working'],['done','Done']];
const expanded=new Set();
// Right-click, the context-menu key or Shift+F10 on a task opens its actions (taskmenu.js).
function actions(button,id,menu){
 if(typeof menu!=='function')return;
 button.setAttribute('aria-haspopup','menu');
 button.oncontextmenu=e=>{e.preventDefault();menu(id,{x:e.clientX,y:e.clientY,anchor:null});};
 button.onkeydown=e=>{if(e.key==='ContextMenu'||(e.key==='F10'&&e.shiftKey)){e.preventDefault();menu(id,{anchor:button});}};
}

// [group, words] for one task row; `live` is the stream's state when the task view has seen newer events.
function place(row,live){
 const state=live||row.status;
 if(NEEDS[state])return ['needs',NEEDS[state]];
 if(state==='draft'||!state)return ['needs',row.scope_approved?'Send the first message':'Approve the scope to start'];
 if(WORKING[state])return ['working',WORKING[state]];
 if(state==='idle'||state==='completed')return ['done',row.has_report?'Report ready':'Waiting for your message'];
 return ['done',DONE[state]||String(state).replaceAll('_',' ')];
}

function render(container,{mode,rows,currentId,open,stateOf,menu}){
 container.__render=()=>render(container,{mode,rows,currentId,open,stateOf,menu});
 container.replaceChildren();
 const all=(Array.isArray(rows)?rows:[]).filter(r=>r&&typeof r.id==='string'&&!r.parent_task_id&&r.status!=='unavailable');
 const list=all.filter(r=>!r.archived),archived=all.filter(r=>r.archived);
 if(!all.length){el('p','side-empty',mode==='research'?'No research questions yet.':'No code tasks in this project yet.',container);return;}
 if(!list.length)el('p','side-empty',mode==='research'?'No open research questions.':'No open code tasks.',container);
 const groups=Object.fromEntries(GROUPS.map(([k])=>[k,[]]));
 for(const row of list){const [k,words]=place(row,stateOf(row.id));groups[k].push({row,words});}
 for(const [key,label] of GROUPS){
  const items=groups[key];if(!items.length)continue;
  const section=el('section','side-group '+key,null,container);const id='side-'+mode+'-'+key;section.setAttribute('aria-labelledby',id);
  el('h2','',label+(items.length>1?' · '+items.length:''),section).id=id;
  const all=expanded.has(id);
  for(const {row,words} of items.slice(0,all?items.length:SHOWN)){
   const b=el('button','side-task',null,section);b.type='button';b.dataset.sidebarTask=row.id;
   if(row.id===currentId)b.setAttribute('aria-current','page');
   el('span','side-title',row.title||'Untitled task',b);el('span','side-state',words,b);
   b.title=row.title||'';b.onclick=()=>open(row.id);actions(b,row.id,menu);
  }
  if(items.length>SHOWN){const more=el('button','side-more',all?'Show fewer':'Show all '+items.length,section);more.type='button';more.id=id+'-more';more.setAttribute('aria-expanded',String(all));more.onclick=()=>{all?expanded.delete(id):expanded.add(id);render(container,{mode,rows,currentId,open,stateOf,menu});const again=document.getElementById(id+'-more');if(again)again.focus();};}
 }
 archivedGroup(container,archived,{mode,currentId,open,menu});
}
// Archived tasks (2026-11-20-archive-delete-design.md): out of the groups above, in one closed list at the bottom.
function archivedGroup(container,items,{mode,currentId,open,menu}){
 if(!items.length)return;
 const id='side-'+mode+'-archived',shown=expanded.has(id)||items.some(r=>r.id===currentId);
 const section=el('section','side-group archived',null,container);
 const toggle=el('button','side-archived-toggle',(shown?'Hide archived':'Archived')+' · '+items.length,section);toggle.type='button';toggle.id=id+'-toggle';toggle.setAttribute('aria-expanded',String(shown));
 toggle.onclick=()=>{shown?expanded.delete(id):expanded.add(id);const parent=container;const rerender=parent.__render;if(rerender)rerender();const again=document.getElementById(id+'-toggle');if(again)again.focus();};
 if(!shown)return;
 for(const row of items){const b=el('button','side-task',null,section);b.type='button';b.dataset.sidebarTask=row.id;if(row.id===currentId)b.setAttribute('aria-current','page');el('span','side-title',row.title||'Untitled task',b);el('span','side-state','Archived',b);b.title=row.title||'';b.onclick=()=>open(row.id);actions(b,row.id,menu);}
}

// Usage limits (2026-11-20-usage-limits-design.md): only what each provider reported, with the time of the reading.
const PROVIDERS=[['claude','Claude Code'],['codex','Codex']];
const STATUS={allowed:'Within the limit',allowed_warning:'Near the limit',rejected:'Limit reached'};
function clock(iso){
 const d=new Date(iso);if(isNaN(d))return '';
 const time=d.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
 return d.toDateString()===new Date().toDateString()?time:d.toLocaleDateString([],{weekday:'short'})+' '+time;
}
function renderUsage(container,readings){
 container.replaceChildren();
 el('h2','','Usage',container).id='sidebar-usage-title';
 const have=PROVIDERS.filter(([k])=>readings&&readings[k]&&Array.isArray(readings[k].windows)&&readings[k].windows.length);
 if(!have.length){el('p','usage-empty','Usage limits show after an agent runs.',container);return;}
 for(const [key,name] of have){
  const reading=readings[key],box=el('div','usage-provider',null,container);box.dataset.provider=key;
  const head=el('p','usage-head',null,box);el('strong','',name,head);const at=clock(reading.at);if(at)el('span','usage-at','as of '+at,head);
  for(const w of reading.windows){
   const used=typeof w.used_percent==='number'?w.used_percent:null,high=(used!=null&&used>=80)||w.status==='allowed_warning'||w.status==='rejected';
   const line=el('div','usage-window'+(high?' high':''),null,box);
   const words=[w.label||'Usage limit'];if(used!=null)words.push(Math.round(used)+'% used');if(STATUS[w.status])words.push(STATUS[w.status]);const reset=w.resets_at&&clock(w.resets_at);if(reset)words.push('resets '+reset);
   el('p','usage-text',words.join(' · '),line);
   if(used!=null){const bar=el('div','usage-bar',null,line);bar.setAttribute('aria-hidden','true');el('span','',null,bar).style.width=Math.max(0,Math.min(100,used))+'%';}
  }
 }
}

// Collapse to a thin rail. The choice is remembered; Focus mode passes {persist:false} to hide it without saving.
const SIDEBAR_KEY='interspace.sidebarCollapsed';
const read=()=>{try{return localStorage.getItem(SIDEBAR_KEY)==='1';}catch{return false;}};
function collapsed(){return document.body.classList.contains('sidebar-collapsed');}
function set(value,{persist=true}={}){
 const next=!!value,changed=next!==collapsed();
 document.body.classList.toggle('sidebar-collapsed',next);
 if(persist){try{localStorage.setItem(SIDEBAR_KEY,next?'1':'0');}catch{}}
 // The split reader measures its layout on resize.
 if(changed)window.dispatchEvent(new Event('resize'));
}
set(read(),{persist:false});
// What a task state asks of the user, in the sidebar's words ('' when nothing); Focus mode's banner uses it too.
const needs=state=>typeof state==='string'&&Object.hasOwn(NEEDS,state)?NEEDS[state]:'';
window.interspaceSidebar={render,place,renderUsage,collapsed,set,needs};
})();
