/* Native bridge journeys with disposable in-memory records; no model or source access. */
import {execFileSync} from 'node:child_process';
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(url);
 if(!await page.evaluate(()=>!!document.getElementById('ispace').interspaceLab))await page.addScriptTag({path:'design/scene/lab-scene.js'});
 if(url.includes('/dist/'))await page.evaluate(()=>{window.sceneLabels=[];const original=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(text,...args){if(this.canvas.classList.contains('lab-canvas'))window.sceneLabels.push(text);return original.call(this,text,...args);};});
 await page.evaluate(()=>{
  const projects=[{id:'a',name:'Fixture project',brief:'Disposable',priority:'normal',next_action:''},{id:'b',name:'Other project',brief:'',priority:'normal',next_action:''}];
  let project='a',task=null,active=null,count=0;
  const records={a:[],b:[]},general={a:[{role:'user',text:'General project history'}],b:[]};
  const selection={mode:'selected',selection_version:1,revision:'commit-a',paths:['README.md']};
  const assignments=[['web-1','web_searcher'],['web-2','web_searcher'],['research','researcher'],['review','reviewer']].map(([id,role],i)=>({id,role,instance_index:role==='web_searcher'?i+1:1,label:role==='web_searcher'?'Web searcher '+(i+1):role==='researcher'?'Researcher 1':'Reviewer 1',objective:'Objective '+id,expected_output:'Evidence '+id,dependencies:role==='web_searcher'?[]:role==='researcher'?['web-1','web-2']:['research'],capabilities:role==='web_searcher'?['public_web_search']:['committed_snapshot','dependency_artifacts']}));
  const artifact={summary:'Combined <img src=x onerror=alert(1)> literal result',findings:[{kind:'fact',claim:'A checked claim',evidence:[{source:'README.md',start:1,end:1}]}],questions:['An unresolved question'],verdict:'accept'};
  const selected=()=>records[project].find(t=>t.id===task);
  const state=()=>({version:3,projects,project_id:project,project:projects.find(p=>p.id===project).name,task_id:task,task:selected()?{id:task,title:selected().title,specialist_limit:selected().specialist_limit,draft:selected().draft||''}:null,tasks:records[project].map(t=>({id:t.id,title:t.title,specialist_limit:t.specialist_limit,status:t.pending?'plan_ready':t.run?.stage||'draft',run_count:t.runs.length,has_pending_plan:!!t.pending})),threads:{workspace:[],project:general[project],task:selected()?.thread||[]},pending:selected()?.pending||null,run:selected()?.run||null,runs:selected()?.runs||[],active:active?'Orchestrator':null,active_project_id:active?.project_id,active_project:active?'Fixture project':null,active_task_id:active?.task_id,active_task:active?.title,error:selected()?.error||'',connection:{message:'Synthetic fixture'},usage:[],source_selection:selection,source_error:''});
  window.deskFixture={requests:[],records,selection,state,heldSource:null,heldCreate:null,holdCreate:false,holdChat:false,finish(stage='completed'){const t=selected();active=null;t.run.stage=stage;t.run.tasks.forEach(x=>x.status=stage==='failed'?'failed':'done');t.run.combined=stage==='failed'?null:{...artifact,verdict:stage==='completed_unreviewed'?'not_reviewed':artifact.verdict};t.run.results={'web-1':artifact,'web-2':{...artifact,summary:'Second independent search'},research:artifact,review:artifact};t.run.events.push({time:'2026-11-11T15:01:00Z',role:'synthesis',status:stage,detail:'Recorded completion'});window.interspaceReceive({type:'state',state:state()});}};
  const respond=(r,result)=>queueMicrotask(()=>window.interspaceReceive({id:r.id,result}));
  window.webkit={messageHandlers:{interspace:{postMessage(r){
   const f=window.deskFixture;f.requests.push(r);const p=r.params;
   if(r.method==='switch_project'){project=p.project_id;task=null;}
   if(r.method==='select_task')task=p.task_id;
   if(r.method==='create_task'){const t={id:'task-'+(++count),title:p.title,specialist_limit:p.specialist_limit,draft:p.draft||'',thread:[],pending:null,run:null,runs:[]};records[p.project_id].push(t);task=t.id;if(f.holdCreate){f.heldCreate={request:r,result:state()};return;}}
   if(r.method==='update_task'){Object.assign(selected(),p);selected().pending=null;}
   if(r.method==='chat'){
    const t=records[p.project_id]?.find(t=>t.id===p.task_id);
    if(t){t.thread.push({role:'user',text:p.text});t.pending={id:'plan-'+t.id,kind:'team',policy_version:2,project_id:p.project_id,task_id:p.task_id,project:'Fixture project',goal:p.text,revision:'commit-a',digest:'digest-'+t.id,tasks:assignments,limits:{specialist_limit:t.specialist_limit,max_calls:5},source_scope:{selection_version:1,revision:'commit-a',paths:['README.md']}};}
    if(f.holdChat){f.heldChat=r;return;}if(t)t.draft='';
   }
   if(r.method==='start_plan'){const t=selected();const run={id:'run-'+t.id,format:'team-v2',project_id:project,task_id:task,stage:'running',goal:t.pending.goal,revision:'commit-a',plan:t.pending,limits:t.pending.limits,tasks:assignments.map((a,i)=>({...a,status:i?(a.dependencies.length?'waiting':'queued'):'running'})),jobs:[{id:'web-1',status:'reserved'}],events:[{time:'2026-11-11T15:00:00Z',role:'web-1',status:'started',detail:'Recorded reservation'}],results:{},combined:null,evidence:{},sources:{'README.md':{lines:1}},artifact_id:'artifact-'+t.id,verification:{unchanged:true}};t.run=run;t.runs.unshift(run);t.pending=null;active={project_id:project,task_id:task,title:t.title};}
   if(r.method==='update_project'){Object.assign(projects.find(x=>x.id===p.project_id),p);if(f.holdMetadata){f.heldMetadata={request:r,result:state()};return;}}
   if(r.method==='list_sources'){respond(r,{project_id:project,revision:'commit-a',selection:{...selection},suggested:['README.md'],files:[{path:'README.md',bytes:20,eligible:true}],limits:{files:16}});return;}
   if(r.method==='save_sources'){selection.selection_version++;selection.paths=p.paths;if(f.holdSave){f.heldSave={request:r,result:state()};return;}}
   if(r.method==='source'){f.heldSource=r;return;}
   if(r.method==='select_run')selected().run=selected().runs.find(x=>x.id===p.run_id);
   if(r.method==='accept_report')selected().run.stage='accepted';
   if(r.method==='cancel')active=null;
   respond(r,state());
  }}}};window.interspaceReceive({type:'state',state:state()});
 });
 const assert=(v,m)=>{if(!v)throw Error(m);};
 assert(await page.getByRole('heading',{name:'Tasks',exact:true}).isVisible(),'Native app must open on Tasks');
 await page.getByRole('button',{name:'New task',exact:true}).focus();await page.keyboard.press('Enter');
 await page.locator('#new-goal').fill('Compare evidence across two public sources. Identify established facts, interpretations and unresolved questions, then propose the smallest fair follow-up study with an explicit resource budget.');await page.locator('#new-limit').fill('9');
 await page.getByRole('button',{name:'Propose a plan',exact:true}).click();
 await page.locator('[data-task-tab=plan]').click();
 assert((await page.locator('#plan').textContent()).includes('Web searcher 2'),'Repeated assignment label missing');
 const calls=await page.evaluate(()=>window.deskFixture.requests);const create=calls.find(r=>r.method==='create_task'),chat=calls.find(r=>r.method==='chat');
 assert(create.params.specialist_limit===9&&create.params.title.length===160,'Raised allowance or bounded title lost');assert(chat.params.scope==='task'&&chat.params.task_id==='task-1'&&chat.params.text.length>160,'Full goal not sent to created owner');
 await page.evaluate(()=>{window.deskFixture.records.a[0].title='Compare evidence across two public sources';window.interspaceReceive({type:'state',state:window.deskFixture.state()});});
 await page.screenshot({path:'workspace-data/task-desk-native-proposed-plan-light-1280.png',fullPage:true});
 await page.getByRole('button',{name:'Start this plan',exact:true}).focus();await page.keyboard.press('Enter');
 const start=await page.evaluate(()=>window.deskFixture.requests.find(r=>r.method==='start_plan'));
 assert(start.params.task_id==='task-1'&&start.params.plan_digest==='digest-task-1','Start lost exact task/digest');
 await page.locator('[data-task-tab=activity]').click();assert((await page.locator('#task-list').textContent()).includes('Web searcher 2'),'Activity repeated roles ambiguous');
 await page.locator('[data-view=lab]').click();
 if(url.includes('/dist/')){assert(await page.evaluate(()=>!!document.getElementById('ispace').interspaceLab),'Packaged original scene missing');assert(await page.evaluate(()=>window.sceneLabels.includes('WS 2')),'Repeated Observatory figure has duplicate WS 1 label');assert(await page.evaluate(()=>document.querySelector('.lab-canvas').getContext('2d').getImageData(2,2,1,1).data[3]>0),'Packaged original scene did not draw');await page.screenshot({path:'workspace-data/task-desk-native-observatory-light-1280.png',fullPage:true});}
 await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task=task-1]').click();
 await page.evaluate(()=>window.deskFixture.finish());await page.locator('[data-task-tab=result]').click();
 for(const selection of ['assignment','canvas']){
  await page.locator('[data-view=lab]').click();
  if(selection==='assignment')await page.locator('#task-list button').first().click();
  else await page.locator('.lab-canvas').evaluate(canvas=>{const b=canvas.getBoundingClientRect(),h=Number(canvas.style.aspectRatio.split('/')[1]);canvas.dispatchEvent(new PointerEvent('pointerdown',{clientX:b.left+b.width*88/800,clientY:b.top+b.height*173/h}));});
  assert(await page.locator('#task-detail').isVisible()&&await page.locator('#results').isVisible(),'Task Observatory '+selection+' lost detail Result');
  assert(await page.locator('#result-tabs [data-result="web-1"]').getAttribute('aria-pressed')==='true','Task Observatory selected wrong assignment');
  assert((await page.locator('#result-body').textContent()).includes('Combined <img'),'Task Observatory '+selection+' lost assignment artifact');
  assert(await page.locator('#run-picker').inputValue()==='run-task-1','Task Observatory changed run identity');
 }
 assert((await page.locator('#result-body').textContent()).includes('An unresolved question'),'Questions missing');assert(await page.locator('#result-body img').count()===0,'Untrusted markup executed');
 assert(!await page.locator('#artifact-browser').evaluate(e=>e.open),'Secondary artifacts should start collapsed');
 await page.locator('#artifact-browser summary').click();
 await page.locator('#result-tabs').getByRole('button',{name:'Web searcher 2',exact:true}).click();assert((await page.locator('#result-body').textContent()).includes('Second independent search'),'Repeated role artifact mixed');
 await page.getByRole('button',{name:'Accept this report',exact:true}).click();const accepted=await page.evaluate(()=>window.deskFixture.requests.find(r=>r.method==='accept_report'));
 assert(accepted.params.task_id==='task-1'&&accepted.params.artifact_id==='artifact-task-1','Acceptance lost task/artifact');
 await page.locator('#result-tabs').getByRole('button',{name:'Combined result',exact:true}).click();await page.locator('#result-body .citation').click();
 await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.getByRole('button',{name:'New task',exact:true}).click();await page.locator('#new-goal').fill('Second task');await page.getByRole('button',{name:'Create draft',exact:true}).click();
 await page.evaluate(()=>window.interspaceReceive({id:window.deskFixture.heldSource.id,result:{task_id:'task-1',project_id:'a',run_id:'run-task-1',text:'PRIVATE OLD SOURCE'}}));
 assert(await page.locator('#source-box').isHidden(),'Late source leaked to another task');
 assert(!(await page.locator('#transcript').textContent()).includes('Compare evidence'),'Task history leaked');
 await page.getByRole('button',{name:'Settings',exact:true}).click();assert(await page.locator('#project-settings').isVisible(),'Settings metadata unreachable');assert(await page.locator('#sources-panel').isVisible(),'Settings sources unreachable');
 assert(await page.getByRole('button',{name:'Check connection',exact:true}).isVisible(),'Connection unreachable');
 await page.getByRole('button',{name:'Project conversation',exact:true}).click();assert((await page.locator('#transcript').textContent()).includes('General project history'),'General conversation missing');
 const generalCall=await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='select_task').at(-1));assert(generalCall.params.task_id===null,'General context did not clear task explicitly');
 // Leaving and reopening New task is a different draft context, even in one project.
 await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.getByRole('button',{name:'New task',exact:true}).click();await page.locator('#new-goal').fill('Earlier new task');
 await page.evaluate(()=>window.deskFixture.holdCreate=true);const sameProjectBefore=await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='chat').length);await page.getByRole('button',{name:'Propose a plan',exact:true}).click();
 await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.getByRole('button',{name:'New task',exact:true}).click();await page.locator('#new-goal').fill('Newer same-project goal');
 await page.evaluate(()=>{const h=window.deskFixture.heldCreate;window.interspaceReceive({id:h.request.id,result:h.result});window.deskFixture.holdCreate=false;});
 assert(await page.locator('#new-goal').inputValue()==='Newer same-project goal','Late create erased reopened draft');assert(await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='chat').length)===sameProjectBefore,'Late creation sent goal after returning to a new draft');
 // Creation is local and a late creation response must preserve the new context.
 await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.getByRole('button',{name:'New task',exact:true}).click();
 await page.locator('#new-goal').fill('Late created goal');await page.locator('#new-limit').fill('12');
 const before=await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='chat').length);
 await page.evaluate(()=>window.deskFixture.holdCreate=true);await page.getByRole('button',{name:'Propose a plan',exact:true}).click();
 await page.locator('#project-picker').selectOption('b');await page.getByRole('button',{name:'New task',exact:true}).click();await page.locator('#new-goal').fill('Keep B new draft');
 await page.evaluate(()=>{const h=window.deskFixture.heldCreate;window.interspaceReceive({id:h.request.id,result:h.result});window.deskFixture.holdCreate=false;});
 assert(await page.locator('#project-picker').inputValue()==='b','Late create changed project');assert(await page.locator('#new-goal').inputValue()==='Keep B new draft','Late create erased B draft');
 assert(await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='chat').length)===before,'Late create sent goal while away');
 await page.locator('#project-picker').selectOption('a');await page.getByRole('button',{name:'Late created goal',exact:false}).click();
 assert(await page.locator('#message').inputValue()==='Late created goal','Late created owner lost recoverable goal');
 await page.getByRole('button',{name:'Send →',exact:true}).click();await page.locator('[data-task-tab=plan]').click();
 await page.locator('#task-limit').fill('15');await page.getByRole('button',{name:'Save allowance',exact:true}).click();
 assert(await page.locator('#plan').isHidden(),'Allowance change retained approval');
 assert((await page.locator('#task-meta').textContent()).includes('15'),'Raised task allowance lost');
 // Source consent blocks provider work but still permits a local draft.
 await page.evaluate(()=>{window.deskFixture.selection.mode='unconfirmed';window.interspaceReceive({type:'state',state:window.deskFixture.state()});});
 await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.getByRole('button',{name:'New task',exact:true}).click();await page.locator('#new-goal').fill('Local only');
 assert(await page.getByRole('button',{name:'Propose a plan',exact:true}).isDisabled(),'Unconfirmed sources permit planning');
 const localBefore=await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='chat').length);await page.getByRole('button',{name:'Create draft',exact:true}).click();
 assert(await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='chat').length)===localBefore,'Local draft dispatched provider');assert(await page.locator('#send').isDisabled(),'Unconfirmed sources permit task chat');
 await page.evaluate(()=>{window.deskFixture.selection.mode='selected';window.interspaceReceive({type:'state',state:window.deskFixture.state()});});
 // Failed planning keeps the submitted task draft recoverable.
 await page.evaluate(()=>window.deskFixture.holdChat=true);await page.getByRole('button',{name:'Send →',exact:true}).click();
 await page.evaluate(()=>{const r=window.deskFixture.heldChat;window.interspaceReceive({id:r.id,error:'Synthetic planning rejection'});window.deskFixture.holdChat=false;});
 assert(await page.locator('#message').inputValue()==='Local only','Provider failure erased task draft');assert((await page.locator('#error').textContent()).includes('Synthetic planning rejection'),'Provider rejection hidden');
 // An actual active owner remains visible while browsing another task.
 await page.evaluate(()=>{const s=window.deskFixture.state();s.active='Web searcher 2';s.active_project='Fixture project';s.active_project_id='a';s.active_task='First task owner';s.active_task_id='task-1';s.active_run_id='run-task-1';window.interspaceReceive({type:'state',state:s});});
 assert((await page.locator('#active-owner').textContent()).includes('First task owner'),'Banner follows selection instead of active owner');await page.getByRole('button',{name:'Stop run',exact:true}).click();
 assert((await page.evaluate(()=>window.deskFixture.requests.at(-1))).method==='cancel','Stop did not target global actual owner');
 // Restore task-one report history and verify exact old artifact actions.
 await page.evaluate(()=>{const t=window.deskFixture.records.a[0];const old=JSON.parse(JSON.stringify(t.run));old.id='old-run';old.artifact_id='old-artifact';old.stage='completed';old.combined.summary='Preserved old combined';t.runs.push(old);});
 await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.locator('[data-open-task=task-1]').click();await page.locator('#artifact-browser summary').click();await page.locator('#run-picker').selectOption('old-run');
 assert((await page.locator('#result-body').textContent()).includes('Preserved old combined'),'Historical report not restored');await page.getByRole('button',{name:'Accept this report',exact:true}).click();
 const oldAccept=await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='accept_report').at(-1));assert(oldAccept.params.run_id==='old-run'&&oldAccept.params.artifact_id==='old-artifact'&&oldAccept.params.task_id==='task-1','Old report acceptance lost exact binding');
 await page.evaluate(()=>window.deskFixture.finish('failed'));assert((await page.locator('#result-body').textContent()).includes('partial'),'Failed output hides saved partials');assert(await page.getByRole('button',{name:'Accept this report',exact:true}).count()===0,'Failed report accepts');
 await page.evaluate(()=>window.deskFixture.finish('completed_unreviewed'));assert((await page.locator('#revision-controls').textContent()).includes('Unreviewed'),'Unreviewed result mislabeled');assert(await page.getByRole('button',{name:'Accept this report',exact:true}).count()===0,'Unreviewed report accepts');
 // Project settings replies carry old task snapshots; neither may restore Task A over B.
 for(const method of ['update_project','save_sources']){
  await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task=task-1]').click();await page.getByRole('button',{name:'Settings',exact:true}).click();
  if(method==='update_project'){if(!await page.locator('#project-settings').getAttribute('open'))await page.locator('#project-settings summary').click();await page.locator('#project-brief').fill('Saved scoped brief');await page.evaluate(()=>window.deskFixture.holdMetadata=true);await page.locator('#project-form').evaluate(f=>f.requestSubmit());}
  else{await page.locator('#sources-panel summary').click();await page.getByRole('checkbox',{name:'Select README.md',exact:true}).waitFor();await page.evaluate(()=>window.deskFixture.holdSave=true);await page.getByRole('button',{name:'Save sources',exact:true}).click();}
  await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task=task-2]').click();await page.locator('#message').fill('Keep B draft '+method);
  await page.evaluate(method=>{const f=window.deskFixture,h=method==='update_project'?f.heldMetadata:f.heldSave;window.interspaceReceive({id:h.request.id,result:h.result});f.holdSave=false;f.holdMetadata=false;},method);
  assert((await page.locator('#heading').textContent())==='Second task','Late '+method+' restored old selected task');assert(await page.locator('#message').inputValue()==='Keep B draft '+method,'Late '+method+' erased task draft');
 }
 await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task=task-1]').click();
 // Malformed saved proposals are isolated at the render boundary.
 for(const malformed of [{id:'malformed-saved',kind:'team'},{id:'invalid-role',kind:'team',digest:'x',goal:'Saved goal',revision:'x',limits:{max_calls:2},tasks:[{id:'a',role:'toString',objective:'Invalid role',expected_output:'Result',dependencies:[]}]}]){
  await page.evaluate(p=>{window.deskFixture.records.a[0].pending=p;window.interspaceReceive({type:'state',state:window.deskFixture.state()});},malformed);
  await page.locator('[data-task-tab=plan]').click();assert((await page.locator('#plan').textContent()).includes('Proposal unavailable'),'Malformed proposal lacks explanation');assert(await page.getByRole('button',{name:'Start this plan',exact:true}).count()===0,'Malformed proposal can start');
 }
 await page.locator('[data-view=tasks]').click();assert(await page.locator('[data-open-task=task-2]').isEnabled(),'Malformed proposal stranded unrelated tasks');
 await page.evaluate(()=>{window.deskFixture.records.a[0].pending=null;});
 // Screenshots and fit checks cover all reachable surfaces in both appearances.
 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:1000});
  for(const surface of ['result','conversation','plan','activity','lab','settings','tasks','new']){
   if(['result','conversation','plan','activity'].includes(surface)){await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task=task-1]').click();await page.locator('[data-task-tab='+surface+']').click();}
   else if(surface==='new')await page.getByRole('button',{name:'New task',exact:true}).click();else await page.locator('[data-view='+surface+']').click();
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+colorScheme+' '+width+' '+surface);fits.push({colorScheme,surface,...fit});
   if((width===1280&&colorScheme==='light'&&['tasks','plan','settings'].includes(surface))||(width===320&&colorScheme==='dark'&&['result','new'].includes(surface)))await page.screenshot({path:'workspace-data/task-desk-native-'+surface+'-'+colorScheme+'-'+width+'.png',fullPage:true});
  }
 }}
 // Positive safe integers are validated without a six-agent clamp.
 assert(await page.locator('#new-limit').getAttribute('max')===null,'Allowance has an artificial maximum');await page.locator('#new-goal').fill('Validate local allowance');
 const invalidBefore=await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='create_task').length);
 for(const value of ['0','1.5','9007199254740992']){await page.locator('#new-limit').fill(value);await page.getByRole('button',{name:'Create draft',exact:true}).click();}
 assert(await page.evaluate(()=>window.deskFixture.requests.filter(r=>r.method==='create_task').length)===invalidBefore,'Invalid allowance reached task creation');
 // An explicitly created local draft retains its full goal across a fresh UI session.
 const durableGoal='x'.repeat(159)+'🧪'+('Detailed evidence and outcome requirements. '.repeat(12));
 await page.locator('#new-goal').fill(durableGoal);await page.locator('#new-limit').fill('9');await page.getByRole('button',{name:'Create draft',exact:true}).click();
 const savedDraftState=await page.evaluate(()=>window.deskFixture.state());assert(savedDraftState.task.draft===durableGoal,'Create draft did not send/store full durable goal');assert(Array.from(savedDraftState.task.title).length===160&&savedDraftState.task.title.endsWith('🧪'),'Task title split a non-BMP character');assert(savedDraftState.threads.task.length===0,'Local draft inserted a chat');
 await page.goto(url);await page.evaluate(saved=>{window.savedDraftState=saved;window.draftRequests=[];window.webkit={messageHandlers:{interspace:{postMessage(r){window.draftRequests.push(r);if(r.method==='chat'){saved.task.draft='';saved.threads.task.push({role:'user',text:r.params.text});}queueMicrotask(()=>window.interspaceReceive({id:r.id,result:saved}));}}}};window.interspaceReceive({type:'state',state:saved});},savedDraftState);
 await page.locator('[data-open-task="'+savedDraftState.task_id+'"]').click();assert(await page.locator('#message').inputValue()===durableGoal,'Fresh UI lost saved full goal');assert(await page.evaluate(()=>window.draftRequests.every(r=>r.method!=='chat')),'Restoring a draft dispatched provider work');
 await page.locator('#message').fill('Newer session edit');await page.evaluate(()=>window.interspaceReceive({type:'state',state:window.savedDraftState}));assert(await page.locator('#message').inputValue()==='Newer session edit','Server draft replaced newer session edit');
 await page.evaluate(()=>{window.savedDraftState.source_selection.mode='unconfirmed';window.interspaceReceive({type:'state',state:window.savedDraftState});});assert(await page.locator('#send').isDisabled(),'Saved draft bypassed source consent');assert(await page.locator('#message').inputValue()==='Newer session edit','Source consent erased draft');
 await page.evaluate(()=>{window.savedDraftState.source_selection.mode='selected';window.interspaceReceive({type:'state',state:window.savedDraftState});});await page.getByRole('button',{name:'Send →',exact:true}).click();assert(await page.locator('#message').inputValue()==='','Consumed server draft reappeared after send');
 assert(await page.evaluate(()=>window.savedDraftState.task.draft)==='','Send retained consumed server draft');
 // Feed actual reopened backend projections through the real UI and bridge navigation.
 const reopened=JSON.parse(execFileSync('python3',['tests/task_saved_state_fixture.py'],{encoding:'utf8'}));
 for(const fixture of reopened){for(const selected of ['nonselected','selected']){
  assert(fixture.raw_preserved,'Saved malformed raw record was rewritten');
  await page.goto(url);
  await page.evaluate(({fixture,selected})=>{window.webkit={messageHandlers:{interspace:{postMessage(r){const next=r.method==='switch_project'?fixture.other:r.params.task_id===null?fixture.general:fixture.healthy;queueMicrotask(()=>window.interspaceReceive({id:r.id,result:next}));}}}};window.interspaceReceive({type:'state',state:fixture[selected]});},{fixture,selected});
  assert(await page.locator('[data-open-task=broken]').isDisabled(),'Malformed '+selected+' task was not isolated');
  assert(await page.locator('[data-open-task=healthy]').isEnabled(),'Malformed '+selected+' task hid healthy task');
  await page.locator('[data-open-task=healthy]').click();
  assert(await page.getByRole('heading',{name:'Healthy task',exact:true}).isVisible(),'Healthy task detail unreachable');
  assert((await page.locator('#transcript').textContent()).includes('Healthy conversation survives'),'Healthy task conversation missing');
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  assert((await page.locator('#transcript').textContent()).includes('General history survives'),'Malformed task broke general navigation');
  await page.locator('#project-picker').selectOption('other');
  assert((await page.locator('#breadcrumb').textContent()).includes('Other healthy project'),'Malformed task broke other project navigation');
 }}
 assert(!errors.length,errors.join('\n'));return {checks:'Tasks default, raised allowance, full goal, exact task Start/accept, repeated roles, artifacts/questions, late source isolation, Settings, preserved general conversation, creation race/draft recovery, editable allowance invalidation, source gate, failed chat, active owner/Stop, old acceptance, failed/unreviewed output, malformed-proposal isolation, late project-save snapshots, keyboard actions, durable full-goal fresh-session restoration',responsiveSurfaces:fits.length};
}
