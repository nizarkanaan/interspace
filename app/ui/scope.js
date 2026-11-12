/* Task scope chips and editor (docs/superpowers/specs/agentic-spaces/scope.md).
   The UI edits a copy of the displayed document; the backend versions it and computes every digest. */
(()=>{
const APPS={notion:'Notion',github:'GitHub',gdrive:'Google Drive',zotero:'Zotero'};
const MAX_LIST=64,MAX_PATTERN=256;
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const tokens=n=>Number(n||0).toLocaleString('en-US');
// PROVISIONAL(0B-5): if the sandbox only has on/off network, this label becomes "Ask for each command that needs network".
const networkLabel=n=>n?.default==='deny'?'Network: off':'Network: ask per host';
const approved=info=>!!(info?.scope&&info.approval&&info.approval.scope_digest===info.digest&&info.approval.scope_version===info.scope.version);

function chips(list,info,projectName){
 list.replaceChildren();const s=info?.scope;
 if(!s){el('li','chip',info?.error?'Scope unavailable':'Loading scope…',list);return;}
 el('li','chip '+(approved(info)?'ok':'warn'),(approved(info)?'Approved':'Needs approval')+' · v'+s.version,list);
 for(const p of s.projects||[]){el('li','chip',projectName(p.project_id)+': '+p.access+' '+(p.access==='write'?(p.write||[]):(p.read||[])).join(', '),list);if(p.deny?.length)el('li','chip','Never: '+p.deny.join(', '),list);}
 if(s.commands)el('li','chip','Commands: '+s.commands.workspace+' in workspace'+(s.commands.allow?.length?' · '+s.commands.allow.length+' allowed':'')+(s.commands.deny?.length?' · '+s.commands.deny.length+' blocked':''),list);
 if(s.network)el('li','chip',networkLabel(s.network)+(s.network.allow_hosts?.length?' · '+s.network.allow_hosts.join(', '):''),list);
 for(const a of s.apps||[])el('li','chip',(APPS[a.app]||a.app)+': '+a.access+' '+(a.resources==='all'?'all resources':a.resources.length+' resource'+(a.resources.length===1?'':'s')),list);
 el('li','chip','Web search: '+s.web_search,list);
 if(s.limits){el('li','chip',tokens(s.limits.token_budget)+' tokens',list);el('li','chip',Math.round(s.limits.time_limit_s/60)+' min',list);}
}

const lines=text=>text.split('\n').map(x=>x.trim()).filter(Boolean);
function field(parent,label,control,id,help){const wrap=el('div','field',null,parent);const l=el('label','',label,wrap);l.htmlFor=id;control.id=id;wrap.append(control);if(help)el('span','footnote',help,wrap);return control;}
function area(parent,label,id,values,help){const t=document.createElement('textarea');t.rows=Math.max(2,Math.min(6,values.length+1));t.value=values.join('\n');return field(parent,label,t,id,help);}
function select(parent,label,id,options,value){const s=document.createElement('select');for(const [v,t] of options){const o=el('option','',t,s);o.value=v;}s.value=value;return field(parent,label,s,id);}
function number(parent,label,id,value,min,max){const i=document.createElement('input');i.type='number';i.min=min;if(max)i.max=max;i.step=1;i.value=value;return field(parent,label,i,id);}

function globErrors(list,label,errors){
 if(list.length>MAX_LIST)errors.push(label+': at most '+MAX_LIST+' patterns.');
 for(const g of list){if(g.length>MAX_PATTERN)errors.push(label+': “'+g.slice(0,40)+'…” is longer than '+MAX_PATTERN+' characters.');else if(g.startsWith('/')||g.includes('\\')||g.split('/').includes('..'))errors.push(label+': “'+g+'” must stay inside the workspace (no leading /, no .., no backslashes).');}
}
function hostErrors(list,label,errors){for(const h of list)if(!/^(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)*$/.test(h))errors.push(label+': “'+h+'” must be a lowercase host name without a scheme or port.');}
function argvList(text,label,errors){return lines(text).map(line=>{const argv=line.split(/\s+/);if(argv.length>8)errors.push(label+': “'+line+'” has more than 8 words.');return argv;});}

// Renders the editor for a deep copy of the displayed scope; onSave receives the edited copy, never a digest.
function editor(host,info,{projectName,onSave,onClose,saving,heading='Edit scope',note='Saving creates a new scope version. The task pauses before its next action until you approve it.',submitLabel='Save scope',closeLabel='Close editor'}){
 host.replaceChildren();const s=JSON.parse(JSON.stringify(info.scope)),uid='scope-'+String(s.task_id||'task').replace(/[^\w-]/g,'');
 const form=el('form','scope-editor',null,host);form.noValidate=true;
 el('h3','',heading,form);el('p','footnote',note,form);
 const read=[];
 (s.projects||[]).forEach((p,i)=>{const fs=el('fieldset','',null,form);el('legend','',projectName(p.project_id),fs);const id=uid+'-p'+i;
  read.push({p,access:select(fs,'Access',id+'-access',[['read','Read only'],['write','Read and write']],p.access),read:area(fs,'Read paths',id+'-read',p.read||[],'One pattern per line, for example src/**'),write:area(fs,'Write paths',id+'-write',p.write||[]),deny:area(fs,'Never paths',id+'-deny',p.deny||[])});});
 const cfs=el('fieldset','',null,form);el('legend','','Commands',cfs);
 const cmd={workspace:select(cfs,'Commands in the workspace',uid+'-cmd',[['allow','Allow'],['ask','Ask'],['deny','Deny']],s.commands?.workspace||'ask'),allow:area(cfs,'Always allowed commands',uid+'-cmd-allow',(s.commands?.allow||[]).map(a=>a.join(' ')),'One command prefix per line, for example git status'),deny:area(cfs,'Never allowed commands',uid+'-cmd-deny',(s.commands?.deny||[]).map(a=>a.join(' ')))};
 const nfs=el('fieldset','',null,form);el('legend','','Network for commands',nfs);
 const net={default:select(nfs,'Command network',uid+'-net',[['ask','Ask per host'],['deny','Off']],s.network?.default||'ask'),allow:area(nfs,'Allowed hosts',uid+'-net-allow',s.network?.allow_hosts||[]),deny:area(nfs,'Blocked hosts',uid+'-net-deny',s.network?.deny_hosts||[])};
 const apps=(s.apps||[]).map((a,i)=>{const fs=el('fieldset','',null,form);el('legend','',APPS[a.app]||a.app,fs);const id=uid+'-a'+i;
  const access=select(fs,'Access',id+'-access',[['read','Read only'],['write','Read and write']],a.access);
  const all=document.createElement('input');all.type='checkbox';all.checked=a.resources==='all';const allLabel=el('label','check',null,fs);allLabel.append(all,' All resources this account reaches');
  const list=el('ul','resource-list',null,fs);const rows=a.resources==='all'?[]:a.resources.map(r=>({...r}));
  const draw=()=>{list.replaceChildren();list.hidden=all.checked;rows.forEach((r,j)=>{const li=el('li','',null,list);el('span','mono',r.ref,li);const c=document.createElement('input');c.type='checkbox';c.checked=!!r.include_children;c.onchange=()=>{r.include_children=c.checked;};const cl=el('label','check',null,li);cl.append(c,' Include children');const b=el('button','quiet','Remove',li);b.type='button';b.setAttribute('aria-label','Remove '+r.ref);b.onclick=()=>{rows.splice(j,1);draw();};});};
  all.onchange=draw;draw();
  const add=document.createElement('input');add.placeholder=a.app+':page:…';field(fs,'Add a resource reference',add,id+'-add');
  const addButton=el('button','','Add resource',fs);addButton.type='button';addButton.onclick=()=>{const ref=add.value.trim();if(ref&&!rows.some(r=>r.ref===ref)){rows.push({ref,include_children:false});add.value='';draw();}};
  return {a,access,all,rows};});
 const gfs=el('fieldset','',null,form);el('legend','','Search and limits',gfs);
 const web=select(gfs,'Web search',uid+'-web',[['allow','Allow'],['ask','Ask'],['deny','Deny']],s.web_search||'ask');
 const budget=number(gfs,'Token budget',uid+'-budget',s.limits?.token_budget??250000,1);
 const minutes=number(gfs,'Time limit (minutes)',uid+'-time',Math.round((s.limits?.time_limit_s??3600)/60),1,1440);
 const errorBox=el('div','error-text',null,form);errorBox.setAttribute('role','alert');
 const actions=el('div','actions',null,form);const save=el('button','primary',submitLabel,actions);save.type='submit';save.disabled=!!saving;const close=el('button','',closeLabel,actions);close.type='button';close.onclick=onClose;
 form.onsubmit=event=>{
  event.preventDefault();const errors=[];
  for(const r of read){const p=r.p;p.access=r.access.value;p.read=lines(r.read.value);p.write=p.access==='write'?lines(r.write.value):[];p.deny=lines(r.deny.value);
   if(p.access==='read'&&lines(r.write.value).length)errors.push(projectName(p.project_id)+': write paths need read and write access.');
   globErrors(p.read,'Read paths',errors);globErrors(p.write,'Write paths',errors);globErrors(p.deny,'Never paths',errors);}
  if(s.commands){s.commands.workspace=cmd.workspace.value;s.commands.allow=argvList(cmd.allow.value,'Always allowed commands',errors);s.commands.deny=argvList(cmd.deny.value,'Never allowed commands',errors);}
  if(s.network){s.network.default=net.default.value;s.network.allow_hosts=lines(net.allow.value);s.network.deny_hosts=lines(net.deny.value);hostErrors(s.network.allow_hosts,'Allowed hosts',errors);hostErrors(s.network.deny_hosts,'Blocked hosts',errors);}
  for(const x of apps){x.a.access=x.access.value;x.a.resources=x.all.checked?'all':x.rows.map(r=>({ref:r.ref,include_children:!!r.include_children}));if(x.a.resources!=='all'&&!x.a.resources.length)errors.push((APPS[x.a.app]||x.a.app)+': choose at least one resource or All resources.');}
  s.web_search=web.value;
  const b=Number(budget.value),t=Number(minutes.value);
  if(!Number.isSafeInteger(b)||b<1)errors.push('Token budget must be a positive whole number.');
  if(!Number.isInteger(t)||t<1||t>1440)errors.push('Time limit must be 1 to 1,440 minutes.');
  if(s.limits){s.limits.token_budget=b;if(t!==Math.round(s.limits.time_limit_s/60))s.limits.time_limit_s=t*60;}
  errorBox.replaceChildren();for(const e of errors)el('p','',e,errorBox);
  if(!errors.length)onSave(s);
 };
 return form;
}
window.interspaceScope={chips,editor,approved,networkLabel};
})();
