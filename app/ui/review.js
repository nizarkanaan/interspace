/* Review changes (docs/superpowers/specs/multi-provider/merge.md): the task branch's files and unified diff, an Into
   picker and an explicit Merge. Every text from the backend is set with textContent, never parsed as markup.
   The host calls init({request}) once; open(taskId, {project_id}) renders into #review-view. */
(()=>{
let host=null,current=null,ticket=0,returnFocus=null;
// Merges done in this session, by task, so the child card can show its merged state.
const merges=new Map();
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const short=commit=>String(commit||'').slice(0,8);
const CHANGE={add:'Added',modify:'Modified',delete:'Deleted',rename:'Renamed',copy:'Copied'};

const STYLE=`#review-view{display:grid;gap:14px;min-width:0;max-width:1280px;color:var(--ink,CanvasText)}
#review-view h2{margin:0;font-size:18px}#review-view h2:focus{outline:none}
#review-view .review-meta,#review-view .review-note{color:var(--muted,GrayText);font-size:13px;margin:0;overflow-wrap:anywhere}
#review-view .review-files{list-style:none;margin:0;padding:0;display:grid;gap:4px}
#review-view .review-files li{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;min-width:0}
#review-view .review-path{font-family:ui-monospace,SFMono-Regular,monospace;overflow-wrap:anywhere;min-width:0}
#review-view .review-change{color:var(--muted,GrayText);min-width:6em}
#review-view .review-add{color:light-dark(#1d6b36,#7fd99a)}#review-view .review-del{color:light-dark(#a3352d,#ffb1a6)}
#review-view .diff-patch{max-height:60vh}
#review-view .review-merge{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px}
#review-view select,#review-view button{font:inherit;min-height:32px;padding:4px 10px;border-radius:6px;border:1px solid var(--line,GrayText);background:var(--bg,Canvas);color:var(--ink,CanvasText);max-width:100%}
#review-view button.primary{background:var(--accent,#245bea);color:var(--on-accent,#fff);border-color:transparent}
#review-view button:disabled,#review-view select:disabled{opacity:.55;cursor:not-allowed}
#review-view :focus-visible{outline:2px solid var(--accent,Highlight);outline-offset:2px}
#review-view .review-result{border:1px solid var(--line,GrayText);border-radius:6px;padding:10px 12px;font-size:14px;display:grid;gap:6px}
#review-view .review-result:empty{display:none}
#review-view .review-result.bad{border-color:var(--warn,#a3352d)}
#review-view .review-result ul{margin:0;padding-left:18px;font-family:ui-monospace,SFMono-Regular,monospace;overflow-wrap:anywhere}
#review-view .review-error{color:var(--warn,#a3352d);margin:0}
@supports not (color:light-dark(white,black)){#review-view .review-add{color:#1d6b36}#review-view .review-del{color:#a3352d}@media(prefers-color-scheme:dark){#review-view .review-add{color:#7fd99a}#review-view .review-del{color:#ffb1a6}}}
@media(max-width:520px){#review-view .review-merge{display:grid;grid-template-columns:1fr}#review-view .review-merge select,#review-view .review-merge button{width:100%}}`;

function style(){if(document.getElementById('review-style'))return;const s=el('style',null,STYLE);s.id='review-style';document.head.append(s);}
function request(method,params){
 const send=host?.request||window.interspaceRequest;
 if(!send)return Promise.reject(new Error('Review is not connected to the backend.'));
 return send(method,params,{manual:true});
}
const root=()=>document.getElementById('review-view');

function open(taskId,options={}){
 const mount=root();if(!mount)return;
 style();
 const mine=++ticket;
 if(!options.reload){const from=document.activeElement;returnFocus=from&&from.id&&!mount.contains(from)?from.id:null;}
 current={task_id:taskId,project_id:options.project_id||host?.projectOf?.(taskId)||null,summary:null,branches:null,current:null,into:null,error:'',merging:false,result:null,loading:true};
 const view=current;
 render(true);
 const live=()=>ticket===mine;
 const loads=[request('review_summary',{task_id:taskId}).then(r=>{if(live())view.summary=r;})];
 if(view.project_id)loads.push(request('review_branches',{project_id:view.project_id}).then(r=>{if(!live())return;view.branches=r.branches||[];view.current=r.current||null;}));
 Promise.all(loads).catch(e=>{if(live())view.error=e.message||String(e);}).finally(()=>{
  if(!live())return;
  view.loading=false;
  if(!view.branches)view.branches=[];
  const head=view.summary?.branch;
  const choices=view.branches.filter(b=>b!==head);
  view.into=choices.includes(view.current)?view.current:(choices[0]||null);
  render(true);
 });
}

function reload(){if(current)open(current.task_id,{project_id:current.project_id,reload:true});}
// Back to the view Review was opened from, with focus on the control that opened it.
function back(){
 ticket++;const id=returnFocus;host?.back?.();
 if(id)document.getElementById(id)?.focus();
}

function merge(){
 const view=current;if(!view||view.merging||!view.summary||!view.into)return;
 const mine=ticket;
 view.merging=true;view.result=null;view.error='';render(false);
 request('review_merge',{task_id:view.task_id,into:view.into,expected_head:view.summary.head_commit})
  .then(r=>{if(r?.status==='merged'){merges.set(view.task_id,{into:view.into,merge_commit:r.merge_commit||null});host?.changed?.();}if(ticket===mine)view.result=r;})
  .catch(e=>{if(ticket===mine)view.error=e.message||String(e);})
  .finally(()=>{if(ticket!==mine)return;view.merging=false;render(false,true);});
}

function render(focusHeading,focusResult){
 const mount=root(),view=current;if(!mount||!view)return;
 mount.replaceChildren();
 mount.setAttribute('aria-busy',view.loading||view.merging?'true':'false');
 if(host?.back){const b=el('button','review-back','← Back to the task',mount);b.type='button';b.setAttribute('aria-label','Back to the task');b.addEventListener('click',back);}
 const h=el('h2',null,'Review changes',mount);h.tabIndex=-1;
 const s=view.summary;
 if(view.loading){el('p','review-note','Loading the changes…',mount);if(focusHeading)h.focus();return;}
 if(s){
  el('p','review-meta','Branch '+s.branch+' · '+short(s.base_commit)+'…'+short(s.head_commit),mount);
  const files=s.files||[];
  const totals=files.reduce((t,f)=>({a:t.a+(f.additions||0),d:t.d+(f.deletions||0)}),{a:0,d:0});
  el('p','review-note',files.length?files.length+(files.length===1?' file changed, ':' files changed, ')+'+'+totals.a+' −'+totals.d:'No changes on this branch.',mount);
  if(files.length){
   const list=el('ul','review-files',null,mount);list.setAttribute('aria-label','Changed files');
   for(const f of files){
    const li=el('li',null,null,list);
    el('span','review-change',CHANGE[f.change]||f.change,li);
    el('span','review-path',f.old_path&&f.old_path!==f.path?f.old_path+' → '+f.path:f.path,li);
    if(f.binary)el('span','review-note','binary',li);
    else{el('span','review-add','+'+(f.additions||0),li);el('span','review-del','−'+(f.deletions||0),li);}
   }
  }
  if(s.patch){
   const pre=el('pre','diff-patch',null,mount);pre.tabIndex=0;pre.setAttribute('aria-label','Unified diff');
   for(const line of s.patch.replace(/\n$/,'').split('\n')){
    const cls=/^(\+\+\+|---|diff |index |similarity |rename |new file|deleted file|Binary )/.test(line)?'meta':line[0]==='+'?'add':line[0]==='-'?'del':line.startsWith('@@')?'hunk':'ctx';
    el('span','diff-line '+cls,line+'\n',pre);
   }
  }
  if(s.truncated)el('p','review-note','The diff is too long to show in full. The merge includes every change.',mount);
  const row=el('div','review-merge',null,mount);
  const label=el('label',null,'Into',row);label.htmlFor='review-into';
  const pick=el('select',null,null,row);pick.id='review-into';
  const choices=(view.branches||[]).filter(b=>b!==s.branch);
  for(const b of choices){const o=el('option',null,b+(b===view.current?' (current)':''),pick);o.value=b;}
  if(view.into)pick.value=view.into;
  pick.disabled=view.merging||!choices.length;
  pick.addEventListener('change',()=>{view.into=pick.value;view.result=null;render(false);document.getElementById('review-into')?.focus();});
  const button=el('button','primary',view.merging?'Merging…':'Merge',row);button.type='button';button.id='review-merge';
  button.disabled=view.merging||!view.into||!files.length;
  button.addEventListener('click',merge);
  if(!choices.length)el('p','review-note','No other local branch to merge into.',mount);
 }
 if(view.error){const e=el('p','review-error',view.error,mount);e.setAttribute('role','alert');e.tabIndex=-1;}
 const out=el('div','review-result',null,mount);out.setAttribute('role','status');out.tabIndex=-1;
 const r=view.result;
 if(r){
  out.dataset.status=r.status;
  if(r.status==='merged'){
   el('p',null,r.merge_commit?'Merged into '+view.into+' as '+short(r.merge_commit)+'.':(r.detail||'Already merged.'),out);
  }else{
   out.classList.add('bad');
   const title={conflict:'Conflicts. Nothing was changed.',stale:'The branch changed since you reviewed it.',dirty:'Not merged.'}[r.status]||'Not merged.';
   el('strong',null,title,out);
   if(r.detail)el('p',null,r.detail,out);
   if(r.conflicts?.length){const ul=el('ul',null,null,out);ul.setAttribute('aria-label','Conflicting files');for(const p of r.conflicts)el('li',null,p,ul);}
   if(r.status==='stale'){const again=el('button',null,'Review the new changes',out);again.type='button';again.addEventListener('click',reload);}
  }
 }
 if(focusResult&&(r||view.error))(r?out:mount.querySelector('.review-error'))?.focus();
 else if(focusHeading)h.focus();
}

window.interspaceReview={init(options){host=options||null;},
 open(taskId,options){open(taskId,options);host?.show?.();if(!current?.loading)return;root()?.querySelector('h2')?.focus();},
 merged:taskId=>merges.get(taskId)||null};
})();
