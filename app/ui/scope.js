/* Task scope chips and editor (docs/superpowers/specs/agentic-spaces/scope.md).
   The UI edits a copy of the displayed document; the backend versions it and computes every digest. */
(()=>{
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
 if(!(s.projects||[]).length)el('li','chip','No project: no files or commands',list);
 if(s.commands&&(s.projects||[]).length)el('li','chip','Commands: '+s.commands.workspace+' in workspace'+(s.commands.allow?.length?' · '+s.commands.allow.length+' allowed':'')+(s.commands.deny?.length?' · '+s.commands.deny.length+' blocked':''),list);
 if(s.network)el('li','chip',networkLabel(s.network)+(s.network.allow_hosts?.length?' · '+s.network.allow_hosts.join(', '):''),list);
 el('li','chip','Web search: '+s.web_search,list);
 for(const text of researchChips(s))el('li','chip research-chip',text,list);
 if(s.limits){if(s.limits.token_budget!=null)el('li','chip',tokens(s.limits.token_budget)+' tokens',list);el('li','chip',Math.round(s.limits.time_limit_s/60)+' min',list);}
}

// Research sources (docs/superpowers/specs/research/tasks.md): a missing key or source counts as off.
const RESEARCH={allow:'Allow',ask:'Ask',off:'Off'};
const researchTitle=name=>window.interspaceResearch?.title(name)||name;
function researchChips(s){
 const set=s.research?.sources&&typeof s.research.sources==='object'?s.research.sources:{};
 const by={allow:[],ask:[]};for(const [name,v] of Object.entries(set))if(by[v])by[v].push(researchTitle(name));
 const out=[];if(by.allow.length)out.push('Research: '+by.allow.join(', '));if(by.ask.length)out.push('Research, asks first: '+by.ask.join(', '));
 return out.length?out:['Research: off'];
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
 // A scope without projects (a research task) has no workspace, so no commands or command network to set.
 const workspace=(s.projects||[]).length>0;let cmd=null,net=null;
 if(workspace){
 const cfs=el('fieldset','',null,form);el('legend','','Commands',cfs);
 cmd={workspace:select(cfs,'Commands in the workspace',uid+'-cmd',[['allow','Allow'],['ask','Ask'],['deny','Deny']],s.commands?.workspace||'ask'),allow:area(cfs,'Always allowed commands',uid+'-cmd-allow',(s.commands?.allow||[]).map(a=>a.join(' ')),'One command prefix per line, for example git status'),deny:area(cfs,'Never allowed commands',uid+'-cmd-deny',(s.commands?.deny||[]).map(a=>a.join(' ')))};
 const nfs=el('fieldset','',null,form);el('legend','','Network for commands',nfs);
 net={default:select(nfs,'Command network',uid+'-net',[['ask','Ask per host'],['deny','Off']],s.network?.default||'ask'),allow:area(nfs,'Allowed hosts',uid+'-net-allow',s.network?.allow_hosts||[]),deny:area(nfs,'Blocked hosts',uid+'-net-deny',s.network?.deny_hosts||[])};
 }
 const rfs=el('fieldset','research-scope',null,form);el('legend','','Research sources',rfs);
 el('p','footnote','Allow: agents use the source without asking. Ask: each call waits for you. Off: never used. Research tools only read, and use no tokens.',rfs);
 const had=s.research?.sources&&typeof s.research.sources==='object'?s.research.sources:null;
 const names=[...new Set([...(window.interspaceResearch?.names()||[]),'fulltext',...Object.keys(had||{})])]; // Full text: any open-access host.
 const research=names.map(name=>{const c=select(rfs,researchTitle(name),uid+'-research-'+name.replace(/[^A-Za-z0-9_-]/g,'_'),Object.entries(RESEARCH),had?.[name]||'off');
  if(window.interspaceResearch&&!window.interspaceResearch.usable(name))c.closest('.field').append(el('span','footnote','Needs your key or email in Settings → Research sources before it can answer.'));
  return [name,c];});
 const gfs=el('fieldset','',null,form);el('legend','','Search and time limit',gfs);
 const web=select(gfs,'Web search',uid+'-web',[['allow','Allow'],['ask','Ask'],['deny','Deny']],s.web_search||'ask');
 const minutes=number(gfs,'Time limit (minutes)',uid+'-time',Math.round((s.limits?.time_limit_s??3600)/60),1,1440);
 const errorBox=el('div','error-text',null,form);errorBox.setAttribute('role','alert');
 const actions=el('div','actions',null,form);const save=el('button','primary',submitLabel,actions);save.type='submit';save.disabled=!!saving;const close=el('button','',closeLabel,actions);close.type='button';close.onclick=onClose;
 form.onsubmit=event=>{
  event.preventDefault();const errors=[];
  for(const r of read){const p=r.p;p.access=r.access.value;p.read=lines(r.read.value);p.write=p.access==='write'?lines(r.write.value):[];p.deny=lines(r.deny.value);
   if(p.access==='read'&&lines(r.write.value).length)errors.push(projectName(p.project_id)+': write paths need read and write access.');
   globErrors(p.read,'Read paths',errors);globErrors(p.write,'Write paths',errors);globErrors(p.deny,'Never paths',errors);}
  if(cmd&&s.commands){s.commands.workspace=cmd.workspace.value;s.commands.allow=argvList(cmd.allow.value,'Always allowed commands',errors);s.commands.deny=argvList(cmd.deny.value,'Never allowed commands',errors);}
  if(net&&s.network){s.network.default=net.default.value;s.network.allow_hosts=lines(net.allow.value);s.network.deny_hosts=lines(net.deny.value);hostErrors(s.network.allow_hosts,'Allowed hosts',errors);hostErrors(s.network.deny_hosts,'Blocked hosts',errors);}
  s.web_search=web.value;
  // A scope that never had research stays without the key unless a source is turned on, so its digest is unchanged.
  const chosen=Object.fromEntries(research.map(([name,c])=>[name,c.value]));
  if(had||Object.values(chosen).some(v=>v!=='off'))s.research={...(s.research||{}),sources:{...(had||{}),...chosen}};
  const t=Number(minutes.value);
  if(!Number.isInteger(t)||t<1||t>1440)errors.push('Time limit must be 1 to 1,440 minutes.');
  // No token limit is asked for; a scope keeps whatever budget it already had (none for new tasks).
  if(s.limits&&t!==Math.round(s.limits.time_limit_s/60))s.limits.time_limit_s=t*60;
  errorBox.replaceChildren();for(const e of errors)el('p','',e,errorBox);
  if(!errors.length)onSave(s);
 };
 return form;
}
window.interspaceScope={chips,editor,approved,networkLabel};
})();
