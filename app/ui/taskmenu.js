/* Task actions (docs/superpowers/specs/2026-11-20-archive-delete-design.md, "Task menu"): right-click a task in the
   sidebar, or press the context-menu key or Shift+F10 on it, for Open, Stop, Archive or Restore, and Delete. Delete asks
   in a dialog first; a code task's unmerged branch offers Review and merge, and the branch's fate is said before
   anything goes. Task titles and branch names are set as text. */
(()=>{
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const WORKING=['queued','starting','running','waiting_lock','cancelling','paused_ask','paused_scope','paused_team'];
let host=null,menu=null,opener=null;

function close(restore=true){
 if(!menu)return;menu.remove();menu=null;
 document.removeEventListener('mousedown',outside,true);window.removeEventListener('blur',onBlur);window.removeEventListener('resize',onBlur);
 if(restore&&opener&&document.contains(opener))opener.focus();opener=null;
}
const outside=e=>{if(menu&&!menu.contains(e.target))close(false);};
const onBlur=()=>close(false);

// Opens the menu for one task at (x, y), or under `anchor` when opened from the keyboard.
function open(id,{x,y,anchor}){
 close(false);
 const row=host.rowOf(id);if(!row)return;
 const state=host.stateOf(id)||row.status,working=WORKING.includes(state),archived=!!row.archived;
 opener=anchor||document.activeElement;
 menu=el('div','task-menu');menu.setAttribute('role','menu');menu.setAttribute('aria-label','Actions for '+(row.title||'this task'));menu.tabIndex=-1;
 const items=[
  ['open','Open',()=>host.open(id),false],
  ...(working?[['stop','Stop',()=>host.request('agent_cancel',{task_id:id},{manual:true}).catch(e=>host.error(e.message)),false]]:[]),
  ['archive',archived?'Restore':'Archive',()=>archive(id,!archived),working&&!archived],
  ['delete','Delete…',()=>confirmDelete(id),working]];
 for(const [key,label,run,disabled] of items){
  const b=el('button','task-menu-item'+(key==='delete'?' danger-text':''),label,menu);b.type='button';b.setAttribute('role','menuitem');b.dataset.action=key;b.tabIndex=-1;
  if(disabled){b.setAttribute('aria-disabled','true');b.title='Stop this task first.';}
  b.onclick=()=>{if(disabled)return;close(false);run();};
 }
 if(working)el('p','task-menu-note','Stop this task to archive or delete it.',menu);
 document.body.append(menu);
 const rect=anchor&&anchor.getBoundingClientRect(),w=menu.offsetWidth,h=menu.offsetHeight;
 let left=rect?rect.left+12:x,top=rect?rect.bottom-4:y;
 left=Math.max(8,Math.min(left,innerWidth-w-8));top=Math.max(8,Math.min(top,innerHeight-h-8));
 menu.style.left=left+'px';menu.style.top=top+'px';
 menu.addEventListener('keydown',key);
 document.addEventListener('mousedown',outside,true);window.addEventListener('blur',onBlur);window.addEventListener('resize',onBlur);
 (menu.querySelector('.task-menu-item:not([aria-disabled])')||menu).focus();
}
function key(e){
 const list=[...menu.querySelectorAll('.task-menu-item')],i=list.indexOf(document.activeElement);
 if(e.key==='Escape'||e.key==='Tab'){e.preventDefault();close(true);}
 else if(e.key==='ArrowDown'){e.preventDefault();list[(i+1)%list.length].focus();}
 else if(e.key==='ArrowUp'){e.preventDefault();list[(i-1+list.length)%list.length].focus();}
 else if(e.key==='Home'){e.preventDefault();list[0].focus();}
 else if(e.key==='End'){e.preventDefault();list[list.length-1].focus();}
}

function archive(id,archived){
 host.request('task_archive',{task_id:id,archived},{manual:true}).then(()=>host.notice(archived?'Archived “'+title(id)+'”. It is in the Archived list at the bottom of the sidebar.':'Restored “'+title(id)+'”.')).catch(e=>host.error(e.message));
}
const title=id=>host.rowOf(id)?.title||'this task';

// The delete dialog: what goes, then the branch, then the choices. Cancel has focus first.
function confirmDelete(id){
 const dialog=document.getElementById('delete-dialog'),name=title(id),research=host.isResearch(id);
 dialog.replaceChildren();
 const form=el('div','delete-confirm',null,dialog);
 el('h2','','Delete “'+name+'”?',form).id='delete-title';dialog.setAttribute('aria-labelledby','delete-title');
 const body=el('div','delete-body',null,form);el('p','muted','Checking what this task left behind…',body);
 const acts=el('div','actions',null,form);
 const cancel=el('button','quiet','Cancel',acts);cancel.type='button';cancel.id='delete-cancel';cancel.onclick=()=>dialog.close();
 dialog.onclose=()=>{const back=document.querySelector('[data-sidebar-task="'+CSS.escape(id)+'"]');if(back)back.focus();};
 if(!dialog.open)dialog.showModal();cancel.focus();
 host.request('task_delete_check',{task_id:id},{manual:true}).then(c=>{
  body.replaceChildren();
  if(c.working){el('p','error-text','Stop this task first. A working task, or one waiting on you, cannot be deleted.',body);return;}
  const parts=['its conversation',c.kind==='research'?'its report and corpus':'its private copy of the project'];if(c.subagents)parts.push(c.subagents+' subagent'+(c.subagents===1?'':'s'));
  el('p','','This permanently removes '+parts.slice(0,-1).join(', ')+' and '+parts[parts.length-1]+'. It cannot be undone.',body);
  const live=(c.branches||[]).filter(b=>b.exists),unmerged=live.filter(b=>!b.checked_out&&b.ahead>0),merged=live.filter(b=>!b.checked_out&&b.ahead===0),out=live.filter(b=>b.checked_out);
  const line=(b,cls,text)=>{const p=el('p','delete-branch'+(cls?' '+cls:''),null,body);p.append('Branch ');el('code','',b.name,p);p.append(text);};
  for(const b of unmerged)line(b,'warn',' has '+b.ahead+' commit'+(b.ahead===1?'':'s')+' not merged into '+(b.into||'your current branch')+'. Deleting the branch loses them unless you merge first.');
  for(const b of merged)line(b,'',' is fully merged into '+(b.into||'your current branch')+' and will be deleted with the task.');
  for(const b of out)line(b,'',' is checked out in your working copy, so it stays.');
  const send=branches=>{for(const b of acts.querySelectorAll('button'))b.disabled=true;
   host.request('task_delete',{task_id:id,branches},{manual:true}).then(res=>{
    const kept=(res.kept_branches||[]).map(k=>k.name+(k.reason?' ('+k.reason.replace(/\.$/,'')+')':''));
    dialog.onclose=null;dialog.close();
    host.deleted(id,research,'Deleted “'+name+'”.'+((res.deleted_branches||[]).length?' Deleted branch '+res.deleted_branches.join(', ')+'.':'')+(kept.length?' Kept branch '+kept.join(', ')+'.':''));
   }).catch(e=>{el('p','error-text',e.message,body).setAttribute('role','alert');for(const b of acts.querySelectorAll('button'))b.disabled=false;});};
  const branchable=unmerged.length+merged.length>0;
  if(unmerged.length&&host.review){const rv=el('button','primary','Review and merge first');rv.type='button';rv.id='delete-review';rv.onclick=()=>{dialog.onclose=null;dialog.close();host.review(id);};acts.prepend(rv);}
  const del=el('button','danger',branchable?'Delete task and branch':'Delete permanently');del.type='button';del.id='delete-confirm';del.onclick=()=>send(branchable?'delete':'keep');acts.insertBefore(del,cancel);
  if(unmerged.length){const k=el('button','','Delete task, keep branch');k.type='button';k.id='delete-keep';k.onclick=()=>send('keep');acts.insertBefore(k,cancel);}
 }).catch(e=>{body.replaceChildren();el('p','error-text',e.message,body).setAttribute('role','alert');});
}

window.interspaceTaskMenu={init(options){host=options;},open,close,confirmDelete};
})();
