/* New team runs share the native app's state and fixed department artwork. */
window.interspaceTeam=(()=>{
  const $=id=>document.getElementById(id);
  const roles={web_searcher:{name:'Web searcher',department:'discovery'},researcher:{name:'Researcher',department:'research'},reviewer:{name:'Reviewer',department:'review'}};
  const labels={waiting:'Waiting for dependencies',queued:'Queued',running:'Working',done:'Done',failed:'Failed',cancelled:'Cancelled',blocked:'Blocked'};
  const isTeam=run=>run?.format==='team-v1';
  function renderPlan(container,plan,state,request,node){
    const panel=node('div','',container);panel.className='plan';
    node('h3','Proposed specialist team',panel);node('p',plan.goal,panel);
    for(const task of plan.tasks){
      const item=node('div','',panel);item.className='assignment';
      node('h4',roles[task.role].name+' · '+task.id,item);
      node('p',task.objective,item);
      node('p','Expected output: '+task.expected_output,item).className='muted';
      node('p','Depends on: '+(task.dependencies.join(', ')||'None'),item).className='footnote';
      node('p','Access: '+(task.role==='web_searcher'?'Live public web search only':'Committed snapshot and assigned dependency artifacts'),item).className='footnote';
      if(task.role==='web_searcher')node('p','Public brief sent to web search: '+task.objective,item).className='notice';
    }
    node('p','Usage ceiling: '+plan.tasks.length+' specialist calls + 1 synthesis = '+plan.limits.max_calls+' calls after Start. One planning call already used. Four minutes per call; no retries.',panel);
    node('p','Committed revision '+plan.revision.slice(0,12)+'. This limits calls and stage time; token spend, search actions and remaining account allowance are not capped.',panel).className='footnote';
    const button=node('button','Start this plan',panel);button.className='primary';button.disabled=!!state.active;
    button.onclick=()=>request('start_plan',{project_id:plan.project_id,plan_id:plan.id,plan_digest:plan.digest}).catch(()=>{});
  }
  function items(run){
    return run.tasks.map(task=>({id:task.id,role:roles[task.role].name,department:roles[task.role].department,
      instance:roles[task.role].name+' 1',state:labels[task.status]||task.status,label:labels[task.status]||task.status,title:task.objective}));
  }
  function tabButton(id,title,selected,parent,onSelect,node){
    const button=node('button',title,parent);button.dataset.result=id;button.setAttribute('aria-pressed',String(selected===id));
    button.onclick=()=>onSelect(id);return button;
  }
  function legacyTabs(selected,onSelect,node){
    const tabs=$('result-tabs');tabs.replaceChildren();
    for(const [id,title] of [['researcher','Research report'],['reviewer','Review'],['events','Run history'],['sources','Sources']])tabButton(id,title,selected,tabs,onSelect,node);
    $('attempt').parentElement.hidden=false;
  }
  function webSource(run,id,node){
    const evidence=run.evidence[id];if(!evidence)return;
    $('source-box').hidden=false;$('source-title').replaceChildren();
    node('span',evidence.title+' · retrieved '+evidence.retrieved_at,$('source-title'));
    const link=node('a','Open published source ↗',$('source-title'));link.href=evidence.url;link.target='_blank';link.rel='noopener noreferrer';
    $('source-text').textContent=evidence.excerpt;
    $('source-title').scrollIntoView({block:'nearest'});
  }
  function cite(run,c,parent,source,node){
    const evidence=run.evidence[c.source];
    const button=node('button',evidence?evidence.title+' · excerpt '+c.start+'–'+c.end:c.source+':'+c.start+'–'+c.end,parent);
    button.className='citation';button.onclick=()=>evidence?webSource(run,c.source,node):source(c);
  }
  function renderResults(state,selected,onSelect,request,source,node){
    const run=state.run;const tabs=$('result-tabs');tabs.replaceChildren();
    const valid=['combined','sources','events',...run.tasks.map(t=>t.id)];if(!valid.includes(selected))selected='combined';
    tabButton('combined','Combined result',selected,tabs,onSelect,node);
    for(const task of run.tasks)tabButton(task.id,roles[task.role].name,selected,tabs,onSelect,node);
    for(const [id,title] of [['sources','Evidence'],['events','Run history']])tabButton(id,title,selected,tabs,onSelect,node);
    $('attempt').parentElement.hidden=true;$('source-box').hidden=true;
    $('run-status').textContent=run.stage.replaceAll('_',' ');
    const controls=$('revision-controls');controls.replaceChildren();
    node('p',(run.stage==='completed_unreviewed'?'Unreviewed result. ':'')+'Calls reserved: '+run.jobs.length+'/'+run.limits.max_calls+'. No retries or automatic revision.',controls);
    if(run.stage==='completed'){
      const button=node('button','Accept this report',controls);button.className='primary';button.disabled=!!state.active;
      button.onclick=()=>request('accept_report',{project_id:state.project_id,run_id:run.id,artifact_id:run.artifact_id}).catch(()=>{});
      node('p','Accepts this exact report only. No experiment or project change is authorized.',controls).className='footnote';
    }else if(run.stage==='accepted')node('p','This report version is accepted.',controls);
    if(['needs_revision','blocked'].includes(run.stage))node('p','Inspect the unresolved review findings. Further work needs a new plan in project chat.',controls);
    const out=$('result-body');out.replaceChildren();
    $('integrity').textContent=run.verification?(run.verification.unchanged?'Source integrity verified against the committed snapshot and original working checkout.':'Source changed; this report cannot be accepted.'):'Source integrity will be checked when this interaction finishes.';
    if(selected==='events'){
      for(const event of run.events){const item=node('div','',out);item.className='finding';node('small',event.time,item);node('h3',event.role+' · '+event.status.replaceAll('_',' '),item);node('p',event.detail,item);}return;
    }
    if(selected==='sources'){
      node('p','Committed revision '+run.revision+'. Web evidence contains retrieved excerpts; full pages are not independently checked by the Reviewer.',out);
      for(const [name,meta] of Object.entries(run.sources))cite(run,{source:name,start:1,end:Math.min(35,meta.lines)},out,source,node);
      for(const id of Object.keys(run.evidence))cite(run,{source:id,start:1,end:run.evidence[id].lines},out,source,node);return;
    }
    const task=run.tasks.find(t=>t.id===selected);
    if(task){
      const box=node('div','',out);box.className='assignment';node('h3',roles[task.role].name+' · '+(labels[task.status]||task.status),box);
      node('p',task.objective,box);node('p','Depends on: '+(task.dependencies.join(', ')||'None'),box).className='footnote';
      node('p','Expected output: '+task.expected_output,box).className='footnote';if(task.error)node('p',task.error,box).className='error';
    }
    const artifact=selected==='combined'?run.combined:run.results[selected];
    if(!artifact){
      node('p',['failed','cancelled','interrupted','integrity_failed'].includes(run.stage)?'The run stopped. Saved partial artifacts remain available in the specialist tabs.':'No artifact received yet. Work and dependencies are recorded above.',out);return;
    }
    node('h2',selected==='combined'?'Combined result':'Specialist result',out);node('p',artifact.summary,out);
    if(artifact.verdict&&artifact.verdict!=='not_reviewed')node('p','Reviewer verdict: '+artifact.verdict,out).className='notice';
    for(const finding of artifact.findings){const item=node('div','',out);item.className='finding';node('small',finding.kind,item);node('p',finding.claim,item);for(const c of finding.evidence)cite(run,c,item,source,node);}
    for(const id of artifact.web_sources||[])cite(run,{source:id,start:1,end:run.evidence[id].lines},out,source,node);
    node('h3','Unresolved questions',out);
    if(!artifact.questions.length)node('p','No additional questions reported. This is not proof that all uncertainty is resolved.',out);
    for(const question of artifact.questions)node('p',question,out);
  }
  return {isTeam,renderPlan,items,renderResults,legacyTabs};
})();
