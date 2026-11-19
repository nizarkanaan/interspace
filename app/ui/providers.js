/* Provider registry in the UI (docs/superpowers/specs/multi-provider/providers.md): provider badges, model fields,
   and Settings → Providers with sign-in status and per-role routing defaults. Every provider name, title,
   model list and capability comes from providers_list; nothing here is provider-specific.
   Account names, details, URLs and codes are inserted with textContent only. */
(()=>{
const ROLES=['researcher','implementer','reviewer','tester','writer'],WRITE_ROLES=new Set(['implementer','tester']);
const MODEL_RE=/^[A-Za-z0-9._:-]{1,64}$/;
const STATE={signed_in:'Signed in',signed_out:'Signed out',missing_cli:'Command-line tool not installed',error:'Status check failed'};
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const roleTitle=role=>role==='orchestrator'?'Orchestrator':String(role).charAt(0).toUpperCase()+String(role).slice(1);
let request=()=>Promise.reject(Error('No bridge')),changed=()=>{};
let providers=[],status=new Map(),routing=null,loadError='',loading=null,rev=0,listSeq=0;
const signIn=new Map(),busy=new Set(),signingOut=new Set();
let draft=null,dirty=false,saving=false,saveNote='',saveError='';

const get=name=>providers.find(p=>p.name===name)||null;
// Until the registry answers, a provider is shown by its own name.
const title=name=>get(name)?.title||(name?String(name).charAt(0).toUpperCase()+String(name).slice(1):'Unknown provider');
const canWrite=name=>!!get(name)?.capabilities?.write;
const copy=v=>JSON.parse(JSON.stringify(v));
function touch(){rev++;changed();}

function load(){
 if(loading)return loading;
 const seq=++listSeq;
 loading=request('providers_list',{},{manual:true}).then(r=>{
  if(seq!==listSeq)return;
  providers=Array.isArray(r?.providers)?r.providers.filter(p=>p&&typeof p.name==='string'):[];
  status=new Map((r?.status||[]).filter(s=>s&&s.provider).map(s=>[s.provider,s]));
  routing=r?.routing&&typeof r.routing==='object'?r.routing:null;
  if(!dirty)draft=routing?copy(routing):null;
  loadError='';
 }).catch(e=>{loadError=e.message||'Providers could not be loaded.';}).finally(()=>{loading=null;touch();});
 return loading;
}

function badge(name,parent){const b=el('span','provider-badge',title(name),parent);b.dataset.provider=String(name||'');return b;}
// The model is free text checked by the registry pattern; a provider with a model list takes only those.
function checkModel(provider,model){
 if(!model)return '';
 if(!MODEL_RE.test(model))return 'Use a model name: letters, digits and . _ : - only (at most 64).';
 const list=get(provider)?.models||[];
 if(list.length&&!list.includes(model))return 'Choose one of '+title(provider)+'’s models: '+list.join(', ')+'.';
 return '';
}
function modelPlaceholder(provider){const p=get(provider);return p?.default_model?'Default: '+p.default_model:'The provider’s default';}
function fillModels(list,provider){list.replaceChildren();for(const m of get(provider)?.models||[]){const o=document.createElement('option');o.value=m;list.append(o);}}
function modelInput(parent,{id,label,provider,value}){
 const wrap=el('div','field',null,parent),l=el('label','',label,wrap);l.htmlFor=id;
 const input=el('input','',null,wrap);input.id=id;input.maxLength=64;input.autocomplete='off';input.spellcheck=false;input.value=value||'';input.placeholder=modelPlaceholder(provider);
 const list=el('datalist','',null,wrap);list.id=id+'-list';input.setAttribute('list',list.id);fillModels(list,provider);
 input.setProvider=next=>{input.placeholder=modelPlaceholder(next);fillModels(list,next);};
 return input;
}
function providerOptions(select,{value,needsWrite,defaultLabel}){
 select.replaceChildren();
 if(defaultLabel!=null){const o=el('option','',defaultLabel,select);o.value='';}
 const names=providers.map(p=>p.name);if(value&&!names.includes(value))names.push(value);
 for(const name of names){const o=el('option','',title(name)+(needsWrite&&!canWrite(name)?' (cannot write)':''),select);o.value=name;o.disabled=!!needsWrite&&!canWrite(name)&&!!get(name);}
 select.value=value||'';
}
function providerSelect(parent,{id,label,value,needsWrite,defaultLabel}){
 const wrap=el('div','field',null,parent),l=el('label','',label,wrap);l.htmlFor=id;
 const select=el('select','',null,wrap);select.id=id;providerOptions(select,{value,needsWrite,defaultLabel});
 return select;
}

// Settings → Providers.
function statusLine(name){
 const s=status.get(name);if(!s)return 'Status not checked';
 let text=STATE[s.state]||'Unknown status ('+s.state+')';
 if(s.state==='signed_in'&&s.account)text+=' as '+s.account;
 if(s.detail&&s.state!=='signed_in')text+=' · '+s.detail;
 return text;
}
function refreshStatus(name){
 busy.add(name);touch();
 request('provider_status',{provider:name},{manual:true}).then(r=>{if(r?.provider===name)status.set(name,r);if(r?.state==='signed_in')signIn.delete(name);})
  .catch(e=>{signIn.set(name,{error:e.message});}).finally(()=>{busy.delete(name);touch();});
}
// Sign-in completion arrives in the normal state message (state.provider_status[provider], auth_status shape),
// so nothing polls; Check status stays as a manual refresh.
const STATES=new Set(Object.keys(STATE));
function fromState(map){
 if(!map||typeof map!=='object')return;let moved=false;
 for(const [name,s] of Object.entries(map)){
  if(!s||typeof s!=='object'||s.provider!==name||!STATES.has(s.state))continue;
  const was=status.get(name);if(was&&was.state===s.state&&was.account===s.account&&was.detail===s.detail)continue;
  status.set(name,s);if(s.state==='signed_in')signIn.delete(name);moved=true;
 }
 if(moved)touch();
}
function signOut(name){
 signingOut.delete(name);busy.add(name);touch();
 request('provider_sign_out',{provider:name},{manual:true}).then(r=>{if(r?.provider===name&&STATES.has(r.state))status.set(name,r);else status.set(name,{provider:name,state:'signed_out',account:null,detail:''});signIn.delete(name);})
  .catch(e=>{signIn.set(name,{error:e.message});}).finally(()=>{busy.delete(name);touch();});
}
function beginSignIn(name){
 busy.add(name);touch();
 request('provider_sign_in',{provider:name},{manual:true}).then(r=>{signIn.set(name,r||{});}).catch(e=>{signIn.set(name,{error:e.message});}).finally(()=>{busy.delete(name);touch();});
}
function signInBox(name,parent){
 const s=signIn.get(name);if(!s)return;
 const box=el('div','sign-in-steps',null,parent);box.setAttribute('role','status');
 if(s.error){el('p','error-text',s.error,box);return;}
 if(s.kind==='device'){
  el('p','','Open this address in your browser and sign in:',box);el('p','mono select-all',s.url,box);
  if(s.code){el('p','','Then enter this code:',box);el('p','device-code mono select-all',s.code,box);}
  if(s.detail)el('p','footnote',s.detail,box);el('p','footnote','When you are done, choose Check status.',box);return;
 }
 if(s.kind==='terminal'){el('p','','Run this in Terminal, then choose Check status:',box);el('p','mono select-all',s.command,box);if(s.detail)el('p','footnote',s.detail,box);return;}
 el('p','footnote',s.detail||'Sign-in started.',box);
}
function routingRow(grid,role){
 const target=role==='orchestrator'?draft.orchestrator:(draft.roles[role]=draft.roles[role]||{provider:'',model:null});
 const row=el('div','route-row',null,grid);row.dataset.role=role;
 const head=el('div','route-role',null,row);el('strong','',roleTitle(role),head);
 el('span','footnote',role==='orchestrator'?'Runs every new task':WRITE_ROLES.has(role)?'Write role: needs a provider that can write':'Read role',head);
 const needsWrite=WRITE_ROLES.has(role);
 const select=providerSelect(row,{id:'route-'+role+'-provider',label:roleTitle(role)+' provider',value:target.provider,needsWrite});
 const model=modelInput(row,{id:'route-'+role+'-model',label:roleTitle(role)+' model',provider:target.provider,value:target.model||''});
 select.onchange=()=>{target.provider=select.value;model.setProvider(select.value);dirty=true;saveNote='Unsaved changes';saveError='';noteUpdate(grid);};
 model.oninput=()=>{model.setCustomValidity('');target.model=model.value.trim()||null;dirty=true;saveNote='Unsaved changes';saveError='';noteUpdate(grid);};
}
function noteUpdate(grid){const form=grid.closest('form');if(!form)return;form.querySelector('.route-status').textContent=saveNote;form.querySelector('.route-error').textContent=saveError;}
function save(form){
 if(saving||!draft)return;
 for(const role of ['orchestrator',...ROLES]){
  const target=role==='orchestrator'?draft.orchestrator:draft.roles[role];if(!target)continue;
  const input=form.querySelector('#route-'+role+'-model'),problem=checkModel(target.provider,target.model||'');
  if(problem){input.setCustomValidity(problem);input.reportValidity();return;}
  if(WRITE_ROLES.has(role)&&get(target.provider)&&!canWrite(target.provider)){saveError=roleTitle(role)+' needs a provider that can write.';noteUpdate(form);return;}
 }
 saving=true;saveError='';saveNote='Saving…';touch();
 const sent=copy(draft);
 request('routing_update',{routing:sent},{manual:true}).then(r=>{routing=r&&typeof r==='object'?r:sent;draft=copy(routing);dirty=false;saveNote='Saved';})
  .catch(e=>{saveError=e.message||'The defaults were not saved.';saveNote='Unsaved changes';}).finally(()=>{saving=false;touch();});
}
function renderSettings(container){
 if(container.dataset.rev===String(rev))return;container.dataset.rev=String(rev);
 const keep=document.activeElement&&container.contains(document.activeElement)?document.activeElement.id:null;
 container.replaceChildren();
 el('h2','','Providers',container);
 el('p','footnote','Each provider uses your own sign-in on this Mac. Interspace never sees or stores your password; tokens are counted per task, never money.',container);
 if(loadError){el('p','error-text',loadError,container).setAttribute('role','alert');}
 if(!providers.length&&!loadError){el('p','muted',loading?'Loading providers…':'No providers yet.',container);}
 const list=el('ul','provider-list',null,container);
 for(const p of providers){
  const li=el('li','provider-item',null,list);li.dataset.provider=p.name;
  const head=el('div','provider-head',null,li);badge(p.name,head);
  const s=status.get(p.name);el('span','provider-state '+(s?.state||'unknown'),statusLine(p.name),head);
  const caps=[];if(p.capabilities?.write)caps.push('can write in its own workspace');else caps.push('read-only roles');if(p.capabilities?.web_search)caps.push('web search');
  el('p','footnote',caps.join(' · ')+(p.models?.length?' · models: '+p.models.join(', '):' · any model name'),li);
  const actions=el('div','actions',null,li);
  const check=el('button','','Check status',actions);check.type='button';check.disabled=busy.has(p.name);check.setAttribute('aria-label','Check '+p.title+' status');check.onclick=()=>refreshStatus(p.name);
  if(s?.state!=='signed_in'){const b=el('button','primary','Sign in',actions);b.type='button';b.disabled=busy.has(p.name)||s?.state==='missing_cli';b.setAttribute('aria-label','Sign in to '+p.title);b.onclick=()=>beginSignIn(p.name);}
  else if(!signingOut.has(p.name)){const b=el('button','','Sign out',actions);b.type='button';b.id='sign-out-'+p.name;b.disabled=busy.has(p.name);b.setAttribute('aria-label','Sign out of '+p.title);b.onclick=()=>{signingOut.add(p.name);touch();document.getElementById('sign-out-confirm-'+p.name)?.focus();};}
  if(s?.state==='signed_in'&&signingOut.has(p.name)){
   const box=el('div','sign-in-steps',null,li);box.setAttribute('role','group');box.setAttribute('aria-label','Sign out of '+p.title);
   el('p','','Sign out of '+p.title+' on this Mac? Tasks on '+p.title+' cannot start until you sign in again.',box);
   const row=el('div','actions',null,box);
   const yes=el('button','primary','Sign out',row);yes.type='button';yes.id='sign-out-confirm-'+p.name;yes.onclick=()=>signOut(p.name);
   const no=el('button','','Cancel',row);no.type='button';no.onclick=()=>{signingOut.delete(p.name);touch();document.getElementById('sign-out-'+p.name)?.focus();};
  }
  signInBox(p.name,li);
 }
 if(draft&&providers.length){
  const form=el('form','routing-form',null,container);form.noValidate=false;
  el('h3','','Default provider for each role',form);
  el('p','footnote','New tasks and proposed teams start from these. The Orchestrator may suggest another provider with a reason; you approve every team before it runs.',form);
  const grid=el('div','route-grid',null,form);
  for(const role of ['orchestrator',...ROLES])routingRow(grid,role);
  const actions=el('div','actions',null,form);const b=el('button','primary','Save defaults',actions);b.type='submit';b.disabled=saving;
  el('span','footnote route-status',saveNote,actions).setAttribute('role','status');
  el('p','error-text route-error',saveError,form).setAttribute('role','alert');
  form.onsubmit=e=>{e.preventDefault();save(form);};
 }
 if(keep){const again=document.getElementById(keep);if(again&&container.contains(again))again.focus();}
}

window.interspaceProviders={
 init(options){request=options.request;changed=options.changed||changed;},
 load,fromState,loaded:()=>!!providers.length,list:()=>providers.slice(),get,title,canWrite,badge,checkModel,modelInput,providerSelect,providerOptions,
 routing:()=>routing,routeFor:role=>role==='orchestrator'?routing?.orchestrator||null:routing?.roles?.[role]||null,
 roleTitle,ROLES,isWriteRole:role=>WRITE_ROLES.has(role),renderSettings
};
})();
