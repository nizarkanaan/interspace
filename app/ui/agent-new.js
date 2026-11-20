/* New task: a conversation with the Orchestrator (docs/superpowers/specs/multi-provider/orchestration.md).
   Two kinds (docs/superpowers/specs/research/tasks.md): a Research question needs no project and runs research-only;
   a Project task works in a project's workspace. Title, project (project tasks only), a research preset, and the
   Orchestrator's provider and model (default from your routing, overridable), then the default scope in the scope
   editor. Nothing is created until "Create task"; the new task opens with its scope unapproved, so the user approves
   it before the first message. Every digest the UI later sends comes from a backend reply. */
(()=>{
const Scope=window.interspaceScope,P=window.interspaceProviders;
const $=id=>document.getElementById(id);
let host=null,state=null,step=null,loading=false,formError='',stepCount=0;
const projectName=id=>(state?.projects||[]).find(p=>p.id===id)?.name||'Project '+String(id).slice(0,8);
const firstLine=text=>Array.from(String(text).trim().split('\n')[0].trim()).slice(0,160).join('');
const MAX_MESSAGE=6000;
// Presets only shape the first message; the Orchestrator's own research workflow does the rest.
const CHECK='Check every reference with the citation checker before answering, cite only papers you retrieved, and say which references could not be verified.';
const PRESETS={
 question:{label:'Open question',ask:'Your research question',placeholder:'What do you want to find out?',compose:q=>q},
 literature_review:{label:'Literature review',ask:'Topic of the review',placeholder:'For example: retrieval-augmented generation for question answering',compose:q=>'Write a literature review on: '+q+'\n\nSearch the research sources, read the most relevant papers and follow their citations. Summarise the main findings, methods, open questions and disagreements. '+CHECK},
 related_work:{label:'Related work',ask:'Your topic, or your paper’s title and abstract',placeholder:'Paste a title and abstract, or describe the work',compose:q=>'Write a related-work section for: '+q+'\n\nFind the closest prior work in the research sources, group it by approach, and say how each group relates to this work. '+CHECK},
 verify_references:{label:'Verify my references',ask:'Notes for the check (optional)',placeholder:'Anything the check should know, for example the field',bib:true,compose:(q,bib)=>'Check each reference below with the citation checker. Report which are verified, which differ from the published record and how, which were not found, and which are retracted. Do not add, remove or rewrite references.'+(q?'\n\nNotes: '+q:'')+'\n\nReferences:\n'+bib}
};

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
const radio=name=>document.querySelector('input[name='+name+']:checked')?.value||'';
function setRadio(name,value){for(const r of document.querySelectorAll('input[name='+name+']'))r.checked=r.value===value;}
const kind=()=>radio('new-kind')||'project';
const preset=()=>PRESETS[radio('new-preset')]?radio('new-preset'):'question';
// The first message: the user's own words for a project task, the preset's composition for a research question.
function message(){
 if(kind()!=='research')return $('new-goal').value;
 const p=PRESETS[preset()];return p.compose($('new-goal').value.trim(),$('new-bib').value.trim());
}

// Draft fields, kept per desk project by app.js with the rest of the new-task draft.
function read(){return {title:$('new-title').value,agentProject:$('new-agent-project').value,provider:$('new-provider').value,model:$('new-model').value,kind:kind(),preset:preset(),bib:$('new-bib').value};}
function fill(d,nextState){
 state=nextState||state;
 const select=$('new-agent-project'),list=state?.projects||[],signature=JSON.stringify(list.map(p=>[p.id,p.name]));
 if(select.dataset.signature!==signature){select.replaceChildren();for(const p of list){const o=document.createElement('option');o.value=p.id;o.textContent=p.name;select.append(o);}select.dataset.signature=signature;}
 select.value=list.some(p=>p.id===d.agentProject)?d.agentProject:state.project_id||list[0]?.id||'';
 $('new-title').value=d.title||'';$('new-model').value=d.model||'';fillProviders(d.provider||'');
 setRadio('new-kind',d.kind==='project'&&list.length?'project':d.kind==='research'||!list.length?'research':'project');
 setRadio('new-preset',PRESETS[d.preset]?d.preset:'question');$('new-bib').value=d.bib||'';
 sync();
}
// Shows the fields of the chosen kind and preset.
function sync(){
 const research=kind()==='research',p=PRESETS[preset()],projects=(state?.projects||[]).length>0;
 const projectRadio=document.querySelector('input[name=new-kind][value=project]');projectRadio.disabled=!projects;
 projectRadio.closest('label').title=projects?'':'Add a project folder first';
 $('new-presets').hidden=!research;$('new-project').hidden=research;$('new-bib-field').hidden=!research||!p.bib;
 $('new-agent-project').hidden=research;$('new-agent-project-label').hidden=research;
 $('new-goal-label').textContent=research?p.ask:'First message (optional: it waits in the task’s composer until you approve the scope)';
 $('new-goal').placeholder=research?p.placeholder:'Describe the outcome you want…';
 $('new-mode-note').textContent=research
  ?'A research question is a conversation with the Orchestrator, without a project. It and the subagents it proposes only read: they search the research sources you allow, follow citations, and run the citation checker. You approve every team before it runs. A finished answer gives you a report and a BibTeX file of the checked references. Next you review the task scope; nothing runs until you approve it.'
  :'A task is a conversation with the Orchestrator. It answers you directly, or proposes a team of subagents on your providers that you approve before anything runs. Each agent works in its own copy of the project and commits to an interspace/task-… branch you merge. Next you review the task scope; nothing runs until you approve it.';
 const text=research?message():'';$('new-preview').hidden=!research||!text.trim();$('new-preview-text').textContent=text;
}
function invalid(input,text){input.setCustomValidity(text);input.reportValidity();return true;}

async function review(){
 if(loading||step)return;
 const titleInput=$('new-title'),modelInput=$('new-model'),goal=$('new-goal'),bib=$('new-bib');
 for(const i of [titleInput,modelInput,goal,bib])i.setCustomValidity('');
 const research=kind()==='research',p=PRESETS[preset()],question=goal.value.trim();
 if(research&&p.bib&&!bib.value.trim())return invalid(bib,'Paste the references to check.');
 if(research&&!p.bib&&!question)return invalid(goal,'Enter your '+(preset()==='question'?'research question':p.ask.toLowerCase())+'.');
 const text=research?message():goal.value;
 if(research&&text.length>MAX_MESSAGE)return invalid(p.bib?bib:goal,'This is too long for one message ('+text.length.toLocaleString('en-US')+' of '+MAX_MESSAGE.toLocaleString('en-US')+' characters). Check fewer references at a time.');
 const fallback=research?(preset()==='question'?firstLine(question):p.label+(question?': '+firstLine(question):'')):firstLine(goal.value);
 const title=titleInput.value.trim()||Array.from(fallback).slice(0,160).join(''),model=modelInput.value.trim(),project_id=research?null:$('new-agent-project').value;
 const choice=resolved($('new-provider').value,model);
 if(!title)return invalid(titleInput,'Give the task a title.');
 if(Array.from(title).length>160)return invalid(titleInput,'Use at most 160 characters.');
 const problem=P.checkModel(choice.provider,model);if(problem)return invalid(modelInput,problem);
 if(!research&&!project_id)return;
 const desk=state.project_id;loading=true;formError='';host.refresh();
 try{
  // A research question takes the research default scope: no project, research sources only (tasks.md).
  const result=await host.request('scope_default',research?{project_id:null,kind:'research'}:{project_id},{manual:true});
  if(!result?.scope)throw Error('The default scope could not be loaded.');
  step={id:++stepCount,desk,kind:research?'research':'project',project_id,title,...choice,preset:research?preset():null,goal:text,scope:result.scope,saving:false,error:''};
 }catch(error){formError=error.message;}
 finally{loading=false;host.refresh();}
}
async function create(doc){
 const s=step;if(!s||s.saving)return;s.saving=true;s.error='';host.refresh();
 try{
  const params={project_id:s.project_id,title:s.title,scope:doc};
  if(s.kind==='research')params.kind='research';
  // The backend applies routing.orchestrator itself (role 'orchestrator'); only what the user changed is sent.
  // A model typed for the default provider names that provider too, since the model is checked against it.
  if(s.overridden){if(s.provider)params.provider=s.provider;params.model=s.model;}
  const result=await host.request('agent_create',params,{manual:true});
  if(!result?.task_id)throw Error('The task could not be created.');
  if(step===s)step=null;
  await host.created({task_id:result.task_id,project_id:s.project_id,kind:s.kind,desk:s.desk,goal:s.goal.trim()});
 }catch(error){s.error=error.message;}
 finally{s.saving=false;host.refresh();}
}
function back(){step=null;host.refresh();}

function render(nextState){
 state=nextState;const s=step&&step.desk===state.project_id?step:null,box=$('new-agent-scope'),editor=$('new-agent-scope-host');
 $('new-task-form').hidden=!!s;box.hidden=!s;
 $('propose-task').disabled=loading||kind()!=='research'&&!(state.projects||[]).length;
 $('new-sources').hidden=!formError;$('new-sources').textContent=formError;
 if(!s){editor.replaceChildren();delete editor.dataset.step;$('new-agent-error').textContent='';sync();return;}
 const note=$('new-agent-scope-note');note.replaceChildren();
 note.append('“'+s.title+'” · '+(s.kind==='research'?(PRESETS[s.preset]?.label||'Research question')+', no project':projectName(s.project_id))+' · Orchestrator on ');
 if(s.provider)P.badge(s.provider,note);else note.append('your default provider');
 note.append((s.model?' · '+s.model:' · default model')+(s.overridden?'':' (from your defaults)')+'. '+(s.kind==='research'
  ?'This is the starting scope: research sources only, with no project, files, commands or network. Subagents the Orchestrator proposes only read, inside it.'
  :'This is the starting scope: the project workspace only, no network. Subagents the Orchestrator proposes work inside it.')+' Change it here; after Create task, approve it on the task before the first message.');
 $('new-agent-error').textContent=s.error;
 if(editor.dataset.step!==String(s.id)){editor.dataset.step=String(s.id);Scope.editor(editor,{scope:s.scope},{projectName,heading:'Review scope',note:'Nothing is created until you choose Create task.',submitLabel:'Create task',closeLabel:'Back',saving:s.saving,onSave:create,onClose:back});}
 const submit=editor.querySelector('button[type=submit]');if(submit)submit.disabled=s.saving;
}
window.interspaceAgentNew={init(options){host=options;$('new-provider').addEventListener('change',syncModel);
 for(const r of document.querySelectorAll('input[name=new-kind],input[name=new-preset]'))r.addEventListener('change',()=>{host.changed?.();sync();host.refresh();});
 for(const id of ['new-goal','new-bib'])$(id).addEventListener('input',()=>{$(id).setCustomValidity('');sync();});},
 render,review,read,fill,sync,reviewing:()=>!!(step&&state&&step.desk===state.project_id)};
})();
