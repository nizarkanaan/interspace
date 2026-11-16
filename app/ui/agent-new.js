/* New task: a conversation with the Orchestrator (docs/superpowers/specs/multi-provider/orchestration.md).
   Title, project, and the Orchestrator's provider and model (default from your routing, overridable), then the
   default scope (scope_default) in the scope editor. Nothing is created until "Create task"; the new task opens
   with its scope unapproved, so the user approves it before the first message. Every digest the UI later sends
   comes from a backend reply. */
(()=>{
const Scope=window.interspaceScope,P=window.interspaceProviders;
const $=id=>document.getElementById(id);
let host=null,state=null,step=null,loading=false,formError='',stepCount=0;
const projectName=id=>(state?.projects||[]).find(p=>p.id===id)?.name||'Project '+String(id).slice(0,8);
const firstLine=text=>Array.from(String(text).trim().split('\n')[0].trim()).slice(0,160).join('');

// The provider and model the Orchestrator will use: an override, or the routing default.
function resolved(provider,model){
 const route=P.routeFor('orchestrator');
 if(provider)return {provider,model:model||null,overridden:true};
 return {provider:route?.provider||null,model:model||route?.model||null,overridden:!!model};
}
function defaultLabel(){const r=P.routeFor('orchestrator');return r?.provider?'Your default: '+P.title(r.provider)+(r.model?' · '+r.model:''):'Your default';}
function fillProviders(value){
 const select=$('new-provider'),signature=JSON.stringify([defaultLabel(),P.list().map(p=>[p.name,p.title])]);
 if(select.dataset.signature!==signature){P.providerOptions(select,{value,defaultLabel:defaultLabel()});select.dataset.signature=signature;}
 select.value=[...select.options].some(o=>o.value===value)?value:'';
 syncModel();
}
function syncModel(){
 const provider=$('new-provider').value||P.routeFor('orchestrator')?.provider||'',input=$('new-model'),list=$('new-model-list');
 const p=P.get(provider);list.replaceChildren();for(const m of p?.models||[]){const o=document.createElement('option');o.value=m;list.append(o);}
 input.placeholder=!$('new-provider').value&&P.routeFor('orchestrator')?.model?'Default: '+P.routeFor('orchestrator').model:p?.default_model?'Default: '+p.default_model:'The provider’s default';
}

// Draft fields, kept per desk project by app.js with the rest of the new-task draft.
function read(){return {title:$('new-title').value,agentProject:$('new-agent-project').value,provider:$('new-provider').value,model:$('new-model').value};}
function fill(d,nextState){
 state=nextState||state;
 const select=$('new-agent-project'),list=state?.projects||[],signature=JSON.stringify(list.map(p=>[p.id,p.name]));
 if(select.dataset.signature!==signature){select.replaceChildren();for(const p of list){const o=document.createElement('option');o.value=p.id;o.textContent=p.name;select.append(o);}select.dataset.signature=signature;}
 select.value=list.some(p=>p.id===d.agentProject)?d.agentProject:state.project_id;
 $('new-title').value=d.title||'';$('new-model').value=d.model||'';fillProviders(d.provider||'');
}
function invalid(input,text){input.setCustomValidity(text);input.reportValidity();return true;}

async function review(){
 if(loading||step)return;
 const titleInput=$('new-title'),modelInput=$('new-model');titleInput.setCustomValidity('');modelInput.setCustomValidity('');
 const title=titleInput.value.trim()||firstLine($('new-goal').value),model=modelInput.value.trim(),project_id=$('new-agent-project').value;
 const choice=resolved($('new-provider').value,model);
 if(!title)return invalid(titleInput,'Give the task a title.');
 if(Array.from(title).length>160)return invalid(titleInput,'Use at most 160 characters.');
 const problem=P.checkModel(choice.provider,model);if(problem)return invalid(modelInput,problem);
 if(!project_id)return;
 const desk=state.project_id;loading=true;formError='';host.refresh();
 try{
  const result=await host.request('scope_default',{project_id},{manual:true});
  if(!result?.scope)throw Error('The default scope could not be loaded.');
  step={id:++stepCount,desk,project_id,title,...choice,goal:$('new-goal').value,scope:result.scope,saving:false,error:''};
 }catch(error){formError=error.message;}
 finally{loading=false;host.refresh();}
}
async function create(doc){
 const s=step;if(!s||s.saving)return;s.saving=true;s.error='';host.refresh();
 try{
  const params={project_id:s.project_id,title:s.title,scope:doc};
  // Without a known routing default and no override, the backend applies routing.orchestrator itself.
  if(s.provider){params.provider=s.provider;params.model=s.model;}
  const result=await host.request('agent_create',params,{manual:true});
  if(!result?.task_id)throw Error('The task could not be created.');
  if(step===s)step=null;
  await host.created({task_id:result.task_id,project_id:s.project_id,desk:s.desk,goal:s.goal.trim()});
 }catch(error){s.error=error.message;}
 finally{s.saving=false;host.refresh();}
}
function back(){step=null;host.refresh();}

function render(nextState){
 state=nextState;const s=step&&step.desk===state.project_id?step:null,box=$('new-agent-scope'),editor=$('new-agent-scope-host');
 $('new-task-form').hidden=!!s;box.hidden=!s;
 $('propose-task').disabled=loading||!(state.projects||[]).length;
 $('new-sources').hidden=!formError;$('new-sources').textContent=formError;
 if(!s){editor.replaceChildren();delete editor.dataset.step;$('new-agent-error').textContent='';return;}
 const note=$('new-agent-scope-note');note.replaceChildren();
 note.append('“'+s.title+'” · '+projectName(s.project_id)+' · Orchestrator on ');
 if(s.provider)P.badge(s.provider,note);else note.append('your default provider');
 note.append((s.model?' · '+s.model:' · default model')+(s.overridden?'':' (from your defaults)')+'. This is the starting scope: the project workspace only, no network. Subagents the Orchestrator proposes work inside it. Change it here; after Create task, approve it on the task before the first message.');
 $('new-agent-error').textContent=s.error;
 if(editor.dataset.step!==String(s.id)){editor.dataset.step=String(s.id);Scope.editor(editor,{scope:s.scope},{projectName,heading:'Review scope',note:'Nothing is created until you choose Create task.',submitLabel:'Create task',closeLabel:'Back',saving:s.saving,onSave:create,onClose:back});}
 const submit=editor.querySelector('button[type=submit]');if(submit)submit.disabled=s.saving;
}
window.interspaceAgentNew={init(options){host=options;$('new-provider').addEventListener('change',syncModel);},render,review,read,fill,reviewing:()=>!!(step&&state&&step.desk===state.project_id)};
})();
