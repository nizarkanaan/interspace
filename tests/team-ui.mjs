/* Controlled team projection test: no provider calls or personal data. */
export default async function check(page,url){
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);
  await page.evaluate(()=>{
    const tasks=[{id:'web',role:'web_searcher',role_version:1,objective:'Public Python heapq documentation only',expected_output:'Published source excerpts',dependencies:[],capabilities:['public_web_search']},{id:'research',role:'researcher',role_version:1,objective:'Compare evidence',expected_output:'Evidence-backed findings',dependencies:['web'],capabilities:['committed_snapshot','dependency_artifacts']},{id:'review',role:'reviewer',role_version:1,objective:'Check every claim',expected_output:'Verdict and gaps',dependencies:['research'],capabilities:['committed_snapshot','dependency_artifacts']}];
    const plan={id:'plan-a',kind:'team',project_id:'a',project:'Team fixture',goal:'Compare approaches',revision:'abcdef1234567890',digest:'exact-content-digest',tasks,limits:{planning_calls:1,max_calls:4,stage_seconds:240,retries:0}};
    const artifact={summary:'Checked combined result',findings:[{claim:'Source supports a bounded claim',kind:'fact',evidence:[{source:'web:team-a:0',start:1,end:1}]}],questions:['Full paper remains unread'],verdict:'not_reviewed'};
    const run={format:'team-v1',id:'team-a',project_id:'a',project:'Team fixture',stage:'running',goal:plan.goal,revision:plan.revision,plan,limits:plan.limits,tasks:tasks.map((t,i)=>({...t,status:i?'waiting':'running'})),jobs:[{id:'web',status:'reserved',tokens:null}],results:{},combined:null,evidence:{'web:team-a:0':{kind:'web',url:'https://docs.python.org/3/library/heapq.html',title:'Python heapq',excerpt:'Published supporting excerpt',lines:1,retrieved_at:'2026-11-11T12:00:00Z'}},sources:{'README.md':{lines:4}},events:[],artifact_id:'artifact-a'};
    const projects=[{id:'a',name:'Team fixture',brief:'Disposable',priority:'normal',next_action:'Inspect',latest_run:null,has_pending_plan:true}];
    let started=false;
    const state=()=>({version:2,project_id:'a',project:'Team fixture',projects,threads:{workspace:[],project:[]},pending:started?null:plan,active:started&&run.stage==='running'?'Web searcher':null,active_project_id:'a',active_run_id:started?run.id:null,active_project:'Team fixture',error:'',connection:{message:'Synthetic test'},usage:started?[{role:'Web searcher',project_id:'a',tokens:null,outcome:'failed'}]:[],run:started?run:null,runs:started?[run]:[]});
    window.teamFixture={plan,run,artifact,state,requests:[],finish(){run.stage='completed';run.tasks.forEach(t=>t.status='done');run.results={web:{...artifact,summary:'Search artifacts',web_sources:['web:team-a:0']},research:{...artifact,summary:'Research artifacts'},review:{...artifact,summary:'Reviewer artifacts',verdict:'accept'}};run.combined=artifact;run.verification={unchanged:true};window.interspaceReceive({type:'state',state:state()});},fail(){run.stage='failed';run.combined=null;run.tasks[0].status='done';run.tasks[1].status='failed';run.tasks[2].status='blocked';window.interspaceReceive({type:'state',state:state()});}};
    window.webkit={messageHandlers:{interspace:{postMessage(request){window.teamFixture.requests.push(request);if(request.method==='start_plan')started=true;queueMicrotask(()=>window.interspaceReceive({id:request.id,result:state()}));}}}};
    window.interspaceReceive({type:'state',state:state()});
  });
  const assert=(v,m)=>{if(!v)throw Error(m);};
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  assert((await page.locator('#plan').textContent()).includes('Public Python heapq documentation only'),'Public search brief missing');
  assert((await page.locator('#plan').textContent()).includes('Depends on'),'Dependencies not inspectable');
  await page.getByRole('button',{name:'Start this plan',exact:true}).click();
  const start=await page.evaluate(()=>window.teamFixture.requests.find(r=>r.method==='start_plan'));
  assert(start.params.plan_id==='plan-a'&&start.params.plan_digest==='exact-content-digest'&&start.params.project_id==='a','Start not bound to exact project plan');
  await page.locator('[data-view=lab]').click();
  assert((await page.locator('#task-list').textContent()).includes('Waiting'),'Dependency status missing');
  await page.locator('[data-view=lab]').click();
  assert(await page.locator('.lab-canvas').isVisible(),'Observatory missing team projection');
  await page.evaluate(()=>window.teamFixture.finish());
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  assert((await page.locator('#result-body').textContent()).includes('Checked combined result'),'Combined result not default');
  assert((await page.locator('#result-body').textContent()).includes('Full paper remains unread'),'Unresolved question missing');
  await page.locator('#artifact-browser summary').click();
  await page.getByRole('button',{name:'Researcher 1',exact:true}).click();
  assert((await page.locator('#result-body').textContent()).includes('Research artifacts'),'Specialist artifact missing');
  await page.locator('[data-view=lab]').click();
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  assert((await page.locator('#result-body').textContent()).includes('Research artifacts'),'Selection lost between views');
  await page.getByRole('button',{name:'Combined result',exact:true}).click();
  await page.locator('#result-body .citation').first().click();
  assert((await page.locator('#source-text').textContent()).includes('Published supporting excerpt'),'Retrieved excerpt missing');
  const link=page.locator('#source-box a');
  assert(await link.getAttribute('href')==='https://docs.python.org/3/library/heapq.html','Source URL missing');
  assert(await page.getByRole('button',{name:'Accept this report',exact:true}).isVisible(),'Reviewed acceptance missing');
  await page.evaluate(()=>window.teamFixture.fail());
  assert((await page.locator('#result-body').textContent()).includes('partial'),'Failure does not explain partial results');
  assert(await page.getByRole('button',{name:'Accept this report',exact:true}).count()===0,'Failed report can be accepted');
  const fits=[];
  for(const colorScheme of ['light','dark']){
    await page.emulateMedia({colorScheme});
    for(const width of [320,390,760,1024,1280]){
      await page.setViewportSize({width,height:900});
      const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      assert(fit.scroll<=fit.width,'Overflow at '+width+' '+colorScheme);fits.push({...fit,colorScheme});
    }
  }
  assert(errors.length===0,errors.join('\n'));
  return {checks:'inspectable graph, exact Start, live statuses, Observatory, combined and specialist artifacts, unresolved questions, excerpt links, partial failure, light/dark fit',fits};
}
