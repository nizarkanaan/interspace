/* Controlled Python editing. State and exact action identities are owned by the backend. */
window.interspaceChanges=(()=>{
 const $=id=>document.getElementById(id);
 const roles={researcher:{name:'Researcher',department:'research'},implementer:{name:'Implementer',department:'engineering'},tester:{name:'Tester',department:'engineering'},reviewer:{name:'Reviewer',department:'review'}};
 const statuses={waiting:'Waiting for dependencies',queued:'Queued',running:'Working',done:'Done',failed:'Failed',cancelled:'Cancelled',blocked:'Blocked'};
 const stages={budget_exhausted:'Budget exhausted',awaiting_test_approval:'Awaiting check approval',ready_to_apply:'Ready to apply',needs_revision:'Needs revision',recovery_required:'Recovery required',application_failed:'Application failed',integrity_failed:'Integrity failed',completed_unreviewed:'Unreviewed'};
 const phases=[['baseline','Original'],['regression','Regression'],['candidate','Candidate']];
 let context={state:null,epoch:0};const submitted=new Set();
 const isChange=run=>run?.format==='change-v1';
 const setContext=(state,epoch)=>{context={state,epoch};for(const key of submitted){const refs={...state.pending?.action_refs,...state.run?.action_refs};if(!Object.entries(refs).some(([method,ref])=>key===method+JSON.stringify(ref)))submitted.delete(key);}};
 const label=(task,tasks)=>roles[task.role].name+' '+(tasks.filter(t=>t.role===task.role).findIndex(t=>t.id===task.id)+1);
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const identity=(state,run)=>({project_id:state.project_id,task_id:state.task_id,run_id:run.id,plan_digest:run.plan.digest,candidate_digest:run.candidate.digest,artifact_id:run.artifact_id});
 function current(ref,epoch){const s=context.state;return epoch===context.epoch&&s?.project_id===ref.project_id&&s?.task_id===ref.task_id;}
 function action(parent,title,method,ref,state,request,node,gate=true){
  if(!ref||!gate)return;
  const epoch=context.epoch,key=method+JSON.stringify(ref),button=node('button',title,parent);button.className='primary';button.disabled=!!state.active||submitted.has(key);
  button.onclick=()=>{
   const s=context.state,live=method==='start_change'?s?.pending?.action_refs?.[method]:s?.run?.action_refs?.[method];
   if(!current(ref,epoch)||s.active||!same(live,ref)||submitted.has(key)||method==='approve_checks'&&!s.run.can_approve_checks||method==='apply_changes'&&!s.run.can_apply_changes)return;
   submitted.add(key);button.disabled=true;
   request(method,ref).catch(()=>{submitted.delete(key);if(current(ref,epoch))button.disabled=false;});
  };
 }
 function detail(parent,title,node){const d=node('details','',parent);node('summary',title,d);return d;}
 function exact(parent,ref,node){const d=detail(parent,'Exact approval identity',node);for(const [key,value] of Object.entries(ref||{})){
  if(value&&typeof value==='object'){node('h4',key.replaceAll('_',' '),d);for(const [k,v] of Object.entries(value))node('p',k.replaceAll('_',' ')+': '+v,d).className='mono';}
  else node('p',key.replaceAll('_',' ')+': '+value,d).className='mono';
 }return d;}
 function readable(plan){return typeof plan?.id==='string'&&typeof plan.digest==='string'&&typeof plan.goal==='string'&&typeof plan.revision==='string'&&Array.isArray(plan.source_scope?.paths)&&Array.isArray(plan.tasks)&&plan.tasks.length>0&&plan.tasks.every(t=>t&&Object.hasOwn(roles,t.role)&&typeof t.id==='string'&&typeof t.objective==='string'&&typeof t.expected_output==='string'&&Array.isArray(t.dependencies)&&Array.isArray(t.write_paths))&&Number.isSafeInteger(plan.limits?.max_calls);}
 function renderPlan(container,plan,state,request,node){
  const panel=node('div','',container);panel.className='plan';
  if(!readable(plan)){node('h3','Proposal unavailable',panel);node('p','This saved editing proposal is incomplete. Ask for a replacement in Conversation.',panel);return;}
  node('h3','Proposed Python fix',panel);node('p',plan.goal,panel);
  node('p','Generate a candidate in an app-owned copy. Checks and changes to the original project each require a separate approval.',panel).className='notice';
  for(const task of plan.tasks){const row=node('div','',panel);row.className='assignment';node('h4',label(task,plan.tasks),row);node('p',task.objective,row);
   if(task.write_paths.length){node('p','Exact write paths',row).className='footnote';for(const path of task.write_paths)node('p',path+' · '+(plan.source_scope.paths.includes(path)?'existing selected file':'new file; must be absent'),row).className='mono';}
   else node('p','No source writes assigned',row).className='footnote';
   const d=detail(row,'Assignment details',node);node('p','Expected output: '+task.expected_output,d);node('p','Depends on: '+(task.dependencies.map(id=>{const t=plan.tasks.find(t=>t.id===id);return t?label(t,plan.tasks):id;}).join(', ')||'None'),d);node('p','Text-only artifacts. No shell, tools, network or delegation.',d).className='footnote';
  }
  const scope=detail(panel,'Approved sources & scope',node);node('p','Original project: '+plan.source_path,scope).className='mono';node('p','Committed revision '+plan.revision,scope).className='mono';node('p','Source selection '+plan.source_scope.selection_version,scope);for(const path of plan.source_scope.paths)node('p',path,scope).className='mono';
  const footer=node('div','',panel);footer.className='plan-footer';node('p',plan.tasks.length+' specialist calls + 1 synthesis = '+plan.limits.max_calls+' calls after approval. One planning call already used.',footer);
  node('p','Four minutes per call; no retries or automatic repair. Token spend and remaining account allowance are unknown.',footer).className='footnote';
  node('p','Fixed Python unittest recipe · 3 test processes maximum · 30 seconds and 100,000 output bytes per process. At most 8 Python write paths, 100,000 generated bytes per file and 200,000 total.',footer).className='footnote';
  exact(footer,plan.action_refs?.start_change||{plan_digest:plan.digest},node);action(panel,'Generate candidate','start_change',plan.action_refs?.start_change,state,request,node);
  if(!plan.action_refs?.start_change)node('p','Generation is unavailable for this proposal. Check the current task, source selection and allowance; ask for a new plan if they changed.',panel).className='notice';
 }
 function items(run){return (run.tasks||[]).filter(t=>Object.hasOwn(roles,t.role)).map(t=>({id:t.id,role:roles[t.role].name,department:roles[t.role].department,number:run.tasks.filter(a=>a.role===t.role).findIndex(a=>a.id===t.id)+1,assignment:label(t,run.tasks),instance:label(t,run.tasks),state:statuses[t.status]||t.status,label:statuses[t.status]||t.status,title:t.objective}));}
 function readRef(state,run){
  if(run.action_refs?.change_evidence)return run.action_refs.change_evidence;
  // Applied approvals are consumed. Immutable read identities remain valid after a fresh reopen.
  if(run.stage==='applied'&&run.plan?.digest&&run.candidate?.digest&&run.artifact_id)return identity(state,run);
  return null;
 }
 async function evidence(state,run,source,request){
  const ref=readRef(state,run);if(!ref)return;const epoch=context.epoch;
  try{const result=await request('change_evidence',{...ref,source});
   if(!current(ref,epoch)||!isChange(context.state?.run)||!same(identity(context.state,context.state.run),ref)||Object.keys(ref).some(k=>result[k]!==ref[k])||result.source!==source)return;
   $('source-box').hidden=false;$('source-title').textContent=source;$('source-text').textContent=result.text;$('source-title').scrollIntoView({block:'nearest'});
  }catch{}
 }
 function cite(parent,text,source,state,run,request,node){const b=node('button',text,parent);b.className='citation';b.disabled=!readRef(state,run);b.onclick=()=>evidence(state,run,source,request);}
 function artifact(out,value,state,run,request,node){
  if(!value){node('p','No artifact received. Saved partial outputs remain inspectable.',out);return;}
  node('p',value.summary,out);if(value.verdict&&value.verdict!=='not_reviewed')node('p','Reviewer verdict: '+value.verdict,out).className='notice';
  for(const finding of value.findings||[]){const row=node('div','',out);row.className='finding';node('small',finding.kind,row);node('p',finding.claim,row);for(const c of finding.evidence||[])cite(row,c.source+':'+c.start+'–'+c.end,c.source,state,run,request,node);}
  node('h3','Unresolved questions',out);for(const question of value.questions||[])node('p',question,out);if(!value.questions?.length)node('p','No additional questions reported. Passing checks do not prove semantic correctness.',out).className='footnote';
 }
 function renderResults(state,selected,onSelect,request,source,node){
  const run=state.run,tabs=$('result-tabs');tabs.replaceChildren();
  const choices=[['combined','Change summary'],...(run.tasks||[]).filter(t=>Object.hasOwn(roles,t.role)).map(t=>[t.id,label(t,run.tasks)]),['sources','Evidence'],['events','Run history']];
  if(!choices.some(([id])=>id===selected))selected='combined';
  for(const [id,title] of choices){const b=node('button',title,tabs);b.dataset.result=id;b.setAttribute('aria-pressed',String(selected===id));b.onclick=()=>onSelect(id);}
  $('attempt').parentElement.hidden=true;$('source-box').hidden=true;$('run-status').textContent=stages[run.stage]||run.stage.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
  $('report-usage').replaceChildren();node('p','Calls reserved: '+run.jobs.length+'/'+run.limits.max_calls+'. Check processes reserved: '+run.checks.reservations.length+'/3. No retries.',$('report-usage'));
  $('integrity').textContent=run.stage==='applied'?'The recorded reviewed changes were applied. Original and candidate evidence remain preserved.':run.change_error||'Source and candidate identity are revalidated by the backend before each approval.';
  const controls=$('revision-controls');controls.replaceChildren();const gate=node('div','',controls);
  if(run.change_error)node('p',run.change_error+' Inspect the source or candidate; request a new plan rather than reusing this approval.',gate).className='notice error';
  if(run.stage==='awaiting_test_approval'){
   node('h3','Approve checks for this frozen candidate',gate);node('p','Run three checks in isolated project copies: original code with original tests; original code with proposed tests; proposed code with those same proposed tests. Each check has a 30-second deadline. Then continue the approved review calls below. The original project stays unchanged.',gate);
   const limits=detail(gate,'Check isolation & execution limits',node);node('p','At most 3 test processes. Read-only app-owned trees, separate writable scratch, a clean environment, no network or child programs. Each process has a 100,000-byte combined output limit. Unsupported restrictions or runtime make checks unavailable.',limits).className='footnote';
   const remaining=run.tasks.filter(t=>t.status!=='done');node('p','Continue '+remaining.length+' specialist calls ('+remaining.map(t=>label(t,run.tasks)).join(', ')+') + 1 synthesis = '+(run.limits.max_calls-run.jobs.length)+' remaining calls. Four minutes per call; no retries.',gate);
   if(run.budget_projection)node('p',window.interspaceProjectionText(run.budget_projection,'Continuing'),gate);
   node('p','Original tests must pass; candidate tests on original code must produce an assertion failure with no errors; candidate tests on candidate code must pass. Each phase needs at least one test.',gate).className='footnote';
   node('p',run.check_availability?.message||'A supported restricted runtime is unavailable.',gate).className='footnote';
   exact(gate,run.action_refs?.approve_checks||{...identity(state,run),recipe:run.plan.recipe,runtime:run.check_availability?.runtime},node);
   action(gate,'Run candidate checks','approve_checks',run.action_refs?.approve_checks,state,request,node,run.can_approve_checks);
  }else if(run.stage==='ready_to_apply'){
   node('h3','Apply this reviewed diff',gate);node('p','Write only the listed replacements to '+run.plan.source_path+'. Changes stay uncommitted. Interspace retains displaced originals and an application journal; other pending plans for this project are invalidated.',gate);
   for(const path of Object.keys(run.candidate.replacements))node('p',path,gate).className='mono';
   exact(gate,run.action_refs?.apply_changes||identity(state,run),node);action(gate,'Apply reviewed changes','apply_changes',run.action_refs?.apply_changes,state,request,node,run.can_apply_changes);
  }else{
   const messages={budget_exhausted:'Stopped: the token budget could not fit the next call, so it was not started. Completed artifacts and check results are kept. Raise the token budget on the Plan tab, then request a new plan or approval.',running:'Generating the candidate. No test process or source application is approved yet.',checking:'Checking the exact approved candidate, then continuing its approved team. No automatic repair.',applied:'Reviewed changes applied and left uncommitted. Commit them in your project, then refresh and save committed sources before requesting another plan.',needs_revision:'Checks or review need revision. Inspect the findings and request a new plan in Conversation; no automatic repair or retry.',failed:'The run failed. Saved partial artifacts remain available. Further work needs a new plan.',cancelled:'The run was stopped. Partial evidence is retained; nothing resumes automatically.',interrupted:'The run was interrupted. No automatic resume; inspect saved evidence and request a new plan.',abandoned:'A replacement plan superseded this candidate. Its approvals are unavailable.',recovery_required:'Application needs recovery inspection. Preserved files and journal remain available; Interspace will not rewrite the source automatically.',application_failed:'Application failed. Inspect the recorded outcome and preserved journal before further work.',blocked:'This change is blocked. Inspect the saved findings before requesting a new plan.'};
   node('p',messages[run.stage]||'No approval is available at this stage. Inspect saved evidence before further work.',gate);
  }
  if(run.application){node('p',run.application.detail||'Application status: '+run.application.status,gate);for(const file of run.application.files||[])node('p',file.path+' · '+file.status,gate).className='footnote';}
  const out=$('result-body');out.replaceChildren();
  if(selected==='events'){for(const event of run.events||[]){const row=node('div','',out);row.className='event';node('small',event.time,row);node('h3',event.role+' · '+event.status.replaceAll('_',' '),row);node('p',event.detail,row);}return;}
  if(selected==='sources'){
   node('h3','Immutable evidence',out);node('p','Original identities always read the approved committed bytes. Candidate identities read the proposed bytes; check identities read captured process output.',out);
   for(const path of Object.keys(run.sources||{}))cite(out,'Original · '+path,'original:'+path,state,run,request,node);
   for(const path of new Set([...Object.keys(run.sources||{}),...Object.keys(run.candidate.replacements||{})]))cite(out,'Candidate · '+path,'candidate:'+path,state,run,request,node);
   for(const [phase,title] of phases)if(run.checks.results[phase])cite(out,title+' output','check:'+phase,state,run,request,node);return;
  }
  if(selected!=='combined'){const task=run.tasks.find(t=>t.id===selected);node('h3',label(task,run.tasks)+' · '+(statuses[task.status]||task.status),out);node('p',task.objective,out);if(task.error)node('p',task.error,out).className='error';artifact(out,run.results[selected],state,run,request,node);return;}
  node('h3',run.stage==='applied'?'Applied changes':run.stage==='ready_to_apply'?'Reviewed changes':'Proposed changes',out);
  if(run.combined)artifact(out,run.combined,state,run,request,node);
  for(const task of run.tasks.filter(t=>t.role==='reviewer')){const review=run.results[task.id];if(review)node('p',label(task,run.tasks)+' · '+review.verdict+' · '+review.summary,out).className='notice';}
  node('h3','Proposed diff',out);
  if(run.candidate.diff){const pre=node('pre',run.candidate.diff,out);pre.className='change-diff';pre.tabIndex=0;pre.setAttribute('aria-label','Exact candidate diff');}
  else node('p','No complete diff is available yet. Saved partial artifacts can be inspected below.',out);
  for(const path of Object.keys(run.candidate.replacements||{})){const row=node('div','',out);row.className='change-file';if(run.sources[path])cite(row,'Original · '+path,'original:'+path,state,run,request,node);else node('span','New file · '+path,row).className='mono';cite(row,'Candidate · '+path,'candidate:'+path,state,run,request,node);}
  node('h3','Recorded checks',out);
  for(const [phase,title] of phases){const r=run.checks.results[phase],row=node('div','',out);row.className='check-row';node('strong',title,row);
   node('p',phase==='baseline'?'Original code + original tests':phase==='regression'?'Original code + candidate tests':'Candidate code + the same candidate tests',row).className='footnote';
   if(r){node('p',r.status+' · exit '+r.exit_code+' · '+r.tests+' tests · '+r.failures+' assertion failure'+(r.failures===1?'':'s')+' · '+r.errors+' errors',row);const d=detail(row,'Captured process details',node);node('p','Duration: '+r.duration+' seconds',d);cite(d,title+' output','check:'+phase,state,run,request,node);}
   else node('p',run.checks.reservations.some(r=>r.id===phase)?'Reserved; no result captured.':'Not run',row).className='muted';
  }
 }
 return {isChange,setContext,renderPlan,items,renderResults};
})();
