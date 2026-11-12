/* New agent task: title, project, runtime and model, then the default scope (scope_default) in the scope editor.
   Nothing is created until "Create task"; the new task opens with its scope unapproved, so the user approves
   it before the first message. Every digest the UI later sends comes from a backend reply. */
(()=>{
const Scope=window.interspaceScope;
const MODEL=/^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,127}$/;
const RUNTIMES={codex:'Codex',claude:'Claude Code'};
const $=id=>document.getElementById(id);
let host=null,state=null,step=null,loading=false,formError='',stepCount=0;
const projectName=id=>(state?.projects||[]).find(p=>p.id===id)?.name||'Project '+String(id).slice(0,8);
const firstLine=text=>Array.from(String(text).trim().split('\n')[0].trim()).slice(0,160).join('');

// Draft fields, kept per desk project by app.js with the rest of the new-task draft.
function read(){return {title:$('new-title').value,agentProject:$('new-agent-project').value,runtime:$('new-runtime').value,model:$('new-model').value};}
function fill(d,nextState){
 state=nextState||state;
 const select=$('new-agent-project'),list=state?.projects||[],signature=JSON.stringify(list.map(p=>[p.id,p.name]));
 if(select.dataset.signature!==signature){select.replaceChildren();for(const p of list){const o=document.createElement('option');o.value=p.id;o.textContent=p.name;select.append(o);}select.dataset.signature=signature;}
 select.value=list.some(p=>p.id===d.agentProject)?d.agentProject:state.project_id;
 $('new-title').value=d.title||'';$('new-runtime').value=RUNTIMES[d.runtime]?d.runtime:'codex';$('new-model').value=d.model||'';
}
function invalid(input,text){input.setCustomValidity(text);input.reportValidity();return true;}

async function review(){
 if(loading||step)return;
 const titleInput=$('new-title'),modelInput=$('new-model');titleInput.setCustomValidity('');modelInput.setCustomValidity('');
 const title=titleInput.value.trim()||firstLine($('new-goal').value),model=modelInput.value.trim(),project_id=$('new-agent-project').value,provider=$('new-runtime').value;
 if(!title)return invalid(titleInput,'Give the task a title.');
 if(Array.from(title).length>160)return invalid(titleInput,'Use at most 160 characters.');
 if(model&&!MODEL.test(model))return invalid(modelInput,'Use a model name: letters, digits and . _ : / - only.');
 if(!project_id||!RUNTIMES[provider])return;
 const desk=state.project_id;loading=true;formError='';host.refresh();
 try{
  const result=await host.request('scope_default',{project_id},{manual:true});
  if(!result?.scope)throw Error('The default scope could not be loaded.');
  step={id:++stepCount,desk,project_id,title,provider,model:model||null,goal:$('new-goal').value,scope:result.scope,saving:false,error:''};
 }catch(error){formError=error.message;}
 finally{loading=false;host.refresh();}
}
async function create(doc){
 const s=step;if(!s||s.saving)return;s.saving=true;s.error='';host.refresh();
 try{
  const result=await host.request('agent_create',{project_id:s.project_id,title:s.title,scope:doc,provider:s.provider,model:s.model},{manual:true});
  if(!result?.task_id)throw Error('The agent task could not be created.');
  if(step===s)step=null;
  await host.created({task_id:result.task_id,project_id:s.project_id,desk:s.desk,goal:s.goal.trim()});
 }catch(error){s.error=error.message;}
 finally{s.saving=false;host.refresh();}
}
function back(){step=null;host.refresh();}

// Called by app.js renderNew while the "Agent" mode is chosen (or a scope review is open).
function render(nextState){
 state=nextState;const s=step&&step.desk===state.project_id?step:null,box=$('new-agent-scope'),editor=$('new-agent-scope-host');
 $('new-task-form').hidden=!!s;box.hidden=!s;
 $('propose-task').disabled=loading||!(state.projects||[]).length;
 $('new-sources').hidden=!formError;$('new-sources').textContent=formError;
 if(!s){editor.replaceChildren();delete editor.dataset.step;$('new-agent-error').textContent='';return;}
 $('new-agent-scope-note').textContent='“'+s.title+'” · '+projectName(s.project_id)+' · '+RUNTIMES[s.provider]+(s.model?' · '+s.model:'')+'. This is the starting scope: the project workspace only, no apps, no network. Change it here; after Create task, approve it on the task before the first message.';
 $('new-agent-error').textContent=s.error;
 if(editor.dataset.step!==String(s.id)){editor.dataset.step=String(s.id);Scope.editor(editor,{scope:s.scope},{projectName,heading:'Review scope',note:'Nothing is created until you choose Create task.',submitLabel:'Create task',closeLabel:'Back',saving:s.saving,onSave:create,onClose:back});}
 const submit=editor.querySelector('button[type=submit]');if(submit)submit.disabled=s.saving;
}
window.interspaceAgentNew={init(options){host=options;},render,review,read,fill,reviewing:()=>!!(step&&state&&step.desk===state.project_id),runtimeName:p=>RUNTIMES[p]||p};
})();
