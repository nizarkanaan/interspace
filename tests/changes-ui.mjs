/* Real backend public snapshots and evidence, fake model/process results, disposable sources. */
import {execFileSync} from 'node:child_process';
export default async function check(page,url){
 const fixture=JSON.parse(execFileSync('python3',['tests/change_saved_state_fixture.py'],{encoding:'utf8'}));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const install=async name=>{
  await page.goto(url);
  if(!await page.evaluate(()=>!!document.getElementById('ispace').interspaceLab))await page.addScriptTag({path:'design/scene/lab-scene.js'});
  await page.evaluate(({fixture,name})=>{
   window.changeSceneLabels=[];const paint=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(text,...args){if(this.canvas.classList.contains('lab-canvas'))window.changeSceneLabels.push(text);return paint.call(this,text,...args);};
   const f=window.changeFixture={fixture,requests:[],current:name,held:null,hold:false,publish(name){this.current=name;window.interspaceReceive({type:'state',state:fixture[name]});}};
   window.webkit={messageHandlers:{interspace:{postMessage(r){
    f.requests.push(r);const s=fixture[f.current];let next=s;
    if(r.method==='create_task')next=fixture[r.params.mode==='python_fix'?'editing':'default'];
    if(r.method==='select_task')next=r.params.task_id===fixture.default.task_id?fixture.default:s;
    if(r.method==='chat')next=fixture.plan;
    const transitions={start_change:['start_change','running'],approve_checks:['approve_checks','checking'],apply_changes:['apply_changes','applied']};
    if(transitions[r.method]){
     const [action,target]=transitions[r.method],refs=s.pending?.action_refs?.[action]||s.run?.action_refs?.[action];
     if(JSON.stringify(r.params)!==JSON.stringify(refs)){queueMicrotask(()=>window.interspaceReceive({id:r.id,error:'Stale exact approval'}));return;}
     next=fixture[target];
    }
    if(r.method==='change_evidence'){
     const exact={project_id:s.project_id,task_id:s.task_id,run_id:s.run.id,plan_digest:s.run.plan.digest,candidate_digest:s.run.candidate.digest,artifact_id:s.run.artifact_id,source:r.params.source};
     if(Object.keys(exact).some(k=>r.params[k]!==exact[k])){queueMicrotask(()=>window.interspaceReceive({id:r.id,error:'Stale evidence'}));return;}
     next=fixture.evidence[r.params.source];
    }
    if(f.hold&&['change_evidence','approve_checks','apply_changes'].includes(r.method)){f.held={r,next};return;}
    queueMicrotask(()=>window.interspaceReceive({id:r.id,result:next}));
   }}}};window.interspaceReceive({type:'state',state:fixture[name]});
  },{fixture,name});
 };
 await install('default');await page.getByRole('button',{name:'New task',exact:true}).click();
 assert(await page.locator('#new-mode').count()===1,'New tasks need a plain task-mode choice');
 assert(await page.locator('#new-mode').inputValue()==='review','Read-only mode must remain default');
 await page.locator('#new-mode').selectOption('python_fix');await page.locator('#new-goal').fill('Fix the recorded value');
 await page.getByRole('button',{name:'Create draft',exact:true}).click();
 assert(await page.evaluate(()=>window.changeFixture.requests.find(r=>r.method==='create_task').params.mode)==='python_fix','Editing choice lost on durable task creation');
 assert((await page.locator('#task-meta').textContent()).includes('Python fix'),'Immutable mode missing in task detail');assert(await page.locator('#new-mode').isHidden(),'Created task mode remains editable');
 await page.evaluate(()=>window.changeFixture.publish('plan'));await page.locator('[data-task-tab=plan]').click();
 const planText=await page.locator('#plan').textContent();
 assert(planText.includes('main.py')&&planText.includes('tests/test_main.py')&&planText.includes('Implementer')&&planText.includes('Tester'),'Exact write scope and roles missing');
 assert(planText.includes('3 test processes')&&planText.includes('30 seconds'),'Fixed recipe and process budget missing');
 await page.getByRole('button',{name:'Generate candidate',exact:true}).focus();await page.keyboard.press('Enter');
 assert((await page.locator('#task-list').textContent()).includes('Implementer'),'Editing activity projection missing');
 await page.evaluate(()=>window.changeFixture.publish('paused'));await page.locator('[data-task-tab=result]').click();
 assert((await page.locator('#result-body').textContent()).includes('--- a/main.py'),'Readable unified candidate diff missing');
 assert((await page.locator('#result-body').textContent()).includes('awaiting')||(await page.locator('#run-status').textContent()).includes('Awaiting'),'Truthful test pause missing');
 assert(await page.getByRole('button',{name:'Run candidate checks',exact:true}).isVisible(),'Exact test approval absent');
 const pauseText=await page.locator('#revision-controls').textContent();
 assert(pauseText.includes(fixture.paused.run.candidate.digest)&&pauseText.includes(fixture.paused.run.check_availability.runtime.sha256)&&pauseText.includes(fixture.paused.run.check_availability.runtime.preset),'Approval must show full candidate/runtime identity');
 assert(pauseText.includes('3 remaining calls')&&pauseText.includes('Tester 1')&&pauseText.includes('Reviewer 1'),'Remaining approved calls not disclosed');
 assert(pauseText.includes('scratch')&&pauseText.includes('3 test processes'),'Check consequences unclear');
 await page.getByRole('button',{name:'Run candidate checks',exact:true}).click();
 assert((await page.locator('#run-status').textContent()).includes('Checking'),'Checking transition missing');
 assert(await page.getByRole('button',{name:'Run candidate checks',exact:true}).count()===0,'Consumed checks offered twice');
 await page.evaluate(()=>window.changeFixture.publish('ready'));
 await page.locator('[data-view=lab]').click();assert(await page.locator('.lab-canvas').isVisible(),'Editing Observatory missing');assert(await page.evaluate(()=>window.changeSceneLabels.includes('IM 1')&&window.changeSceneLabels.includes('TS 1')),'Existing fixed builder artwork not mapped to editing roles');await page.screenshot({path:'workspace-data/changes-'+(url.includes('/dist/')?'packaged':'source')+'-observatory-light-1280.png',fullPage:true});await page.locator('#task-list button').first().click();await page.locator('#artifact-browser summary').click();await page.getByRole('button',{name:'Change summary',exact:true}).click();await page.locator('#artifact-browser summary').click();
 const resultText=await page.locator('#result-body').textContent();
 assert(resultText.includes('Original')&&resultText.includes('Regression')&&resultText.includes('Candidate')&&resultText.includes('1 assertion failure'),'Actual three-phase check summary missing');
 assert(await page.getByRole('button',{name:'Apply reviewed changes',exact:true}).isVisible(),'Reviewed final Apply absent');
 assert((await page.locator('#revision-controls').textContent()).includes(fixture.ready.run.artifact_id),'Apply report identity missing');
 for(const [button,body] of [['Original · main.py','value = 1'],['Candidate · main.py','value = 2'],['Regression output','ACTUAL_FIXTURE_regression']]){
  if(button==='Regression output')await page.locator('.check-row').filter({hasText:'Regression'}).locator('summary').click();
  await page.getByRole('button',{name:button,exact:true}).click();assert((await page.locator('#source-text').textContent()).includes(body),'Evidence missing '+button);
 }
 await page.getByRole('button',{name:'Apply reviewed changes',exact:true}).focus();await page.keyboard.press('Enter');
 assert((await page.locator('#run-status').textContent()).includes('Applied'),'Applied transition missing');
 assert(await page.getByRole('button',{name:'Apply reviewed changes',exact:true}).count()===0,'Applied candidate can be applied twice');
 assert(fixture.source_after_apply==='value = 2\n','Fixture did not actually apply to its temp source');
 // A fresh applied UI has no action_refs; read-only immutable evidence identities still work.
 await install('reopened');await page.locator('[data-open-task="'+fixture.reopened.task_id+'"]').click();await page.locator('[data-task-tab=result]').click();
 assert(Object.keys(fixture.reopened.run.action_refs).length===0,'Fresh applied fixture retained approvals');
 for(const name of ['Original · main.py','Candidate · main.py','Regression output']){if(name==='Regression output')await page.locator('.check-row').filter({hasText:'Regression'}).locator('summary').click();await page.getByRole('button',{name,exact:true}).click();}
 assert((await page.locator('#source-text').textContent()).includes('ACTUAL_FIXTURE_regression'),'Fresh applied evidence inaccessible');
 // Revision/failure are actual terminal public projections, never an automatic repair.
 for(const name of ['revision','failed','stale']){
  await page.evaluate(n=>window.changeFixture.publish(n),name);await page.locator('[data-task-tab=result]').click();
  assert(await page.getByRole('button',{name:'Apply reviewed changes',exact:true}).count()===0,'Unsafe Apply at '+name);
  assert(await page.getByRole('button',{name:'Run candidate checks',exact:true}).count()===0,'Unsafe checks at '+name);
  assert((await page.locator('#revision-controls').textContent()).length>15,'Terminal/stale explanation absent '+name);
 }
 // A late check-approval reply cannot restore an older artifact over the reviewed result.
 await install('paused');await page.locator('[data-open-task="'+fixture.paused.task_id+'"]').click();await page.locator('[data-task-tab=result]').click();
 await page.evaluate(()=>window.changeFixture.hold=true);await page.getByRole('button',{name:'Run candidate checks',exact:true}).click();
 await page.evaluate(()=>{const f=window.changeFixture;f.publish('ready');window.interspaceReceive({id:f.held.r.id,result:f.held.next});f.hold=false;});
 assert((await page.locator('#run-status').textContent()).includes('Ready to apply'),'Late approval restored an older artifact');
 // Captured approval/evidence handlers cannot cross task or run ownership after navigation.
 await page.evaluate(()=>window.changeFixture.publish('ready'));const staleApply=await page.getByRole('button',{name:'Apply reviewed changes',exact:true}).elementHandle();
 await page.evaluate(()=>window.changeFixture.publish('default'));const before=await page.evaluate(()=>window.changeFixture.requests.length);
 await staleApply.evaluate(b=>b.click());assert(await page.evaluate(()=>window.changeFixture.requests.length)===before,'Detached stale Apply dispatched');
 await page.evaluate(()=>window.changeFixture.publish('ready'));await page.evaluate(()=>window.changeFixture.hold=true);await page.getByRole('button',{name:'Original · main.py',exact:true}).click();
 await page.evaluate(()=>window.changeFixture.publish('default'));await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task="'+fixture.default.task_id+'"]').click();await page.locator('#message').fill('Keep other task draft');
 await page.evaluate(()=>{const f=window.changeFixture;window.interspaceReceive({id:f.held.r.id,result:f.held.next});f.hold=false;});
 assert(await page.locator('#source-box').isHidden(),'Late change evidence leaked across owners');assert(await page.locator('#message').inputValue()==='Keep other task draft','Late evidence erased owner draft');
 // Untrusted model/source content remains literal, including diff and review strings.
 await page.evaluate(()=>{const f=window.changeFixture,s=structuredClone(f.fixture.ready);s.run.candidate.diff+='<img src=x onerror=alert(1)>\n';s.run.combined.summary='<script>throw 7</script>';window.interspaceReceive({type:'state',state:s});});
 await page.locator('[data-task-tab=result]').click();assert(await page.locator('#result-body img,#result-body script').count()===0,'Model markup executed');
 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:1000});for(const stage of ['plan','paused','ready','revision','failed','reopened']){
  await page.evaluate(n=>window.changeFixture.publish(n),stage);await page.locator('[data-task-tab='+ (stage==='plan'?'plan':'result')+']').click();
  const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+stage+' '+width+' '+colorScheme);fits.push({stage,colorScheme,...fit});
  if((stage==='ready'&&width===1280)||(stage==='paused'&&width===320))await page.screenshot({path:'workspace-data/changes-'+(url.includes('/dist/')?'packaged':'source')+'-'+stage+'-'+colorScheme+'-'+width+'.png',fullPage:true});
 }}}
 assert(!errors.length,errors.join('\n'));
 return {checks:'actual public mode/default, exact generation/check/apply refs, diff, full runtime approval, three-phase checks, status transitions, revision/failure/stale gates, fresh applied evidence, stale handlers/owner isolation, literal model text, keyboard, light/dark/narrow fit',responsiveStates:fits.length};
}
