/* Task desk with fixture state only: desk rows, earlier tasks shown read-only, Settings and sign-in. No backend or model. */
import {execFileSync} from 'node:child_process';
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async sel=>(await page.locator(sel).textContent())||'';
 await page.goto(url);
 await page.evaluate(()=>{
  const projects=[{id:'a',name:'Fixture project',brief:'Disposable',priority:'normal',next_action:''},{id:'b',name:'Other project',brief:'',priority:'normal',next_action:''}];
  const history={mode:'review',label:'Earlier task (read-only)',messages:[{role:'user',text:'Compare the two sources'},{role:'assistant',text:'Literal <img src=x onerror="window.pwned=1"> reply'}],
   plan:'Goal: Compare the two sources\n- Researcher 1: Read the README',reports:[{run_id:'run-1',goal:'Compare the two sources',stage:'completed',text:'Combined result · accept\nTwo sources agree.'}],error:''};
  const rows={a:[{id:'agent-1',title:'Fix the parser',mode:'agent',status:'idle',provider:'claude',model:'claude-opus-5-5'},{id:'old-1',title:'Compare the two sources',mode:'review',status:'read_only',read_only:true},{id:'old-2',title:'Fix value',mode:'python_fix',status:'read_only',read_only:true}],b:[]};
  let project='a',task=null,active=null;
  const state=()=>({version:4,projects,project_id:project,project:projects.find(p=>p.id===project).name,task_id:task,
   task:task&&task!=='agent-1'?{id:task,title:rows[project].find(r=>r.id===task).title,mode:rows[project].find(r=>r.id===task).mode,token_budget:null,tokens:{used:1200,budget:null,reserved:0,estimated:0,unknown:1,overshoot:0},agent:null,history:task==='old-1'?history:{mode:'python_fix',label:'Earlier task (read-only)',messages:[],plan:'',reports:[],error:'Stopped early'}}:null,
   tasks:rows[project],active,connection:{message:'Synthetic fixture'},error:'',scheduler:{max_running:4,running:[],queued:[]}});
  const f=window.deskFixture={requests:[],state,setActive(v){active=v;window.interspaceReceive({type:'state',state:state()});}};
  window.webkit={messageHandlers:{interspace:{postMessage(r){
   f.requests.push(r);const p=r.params||{};let result=null;
   if(r.method==='switch_project'){project=p.project_id;task=null;}
   if(r.method==='select_task')task=p.task_id;
   if(r.method==='update_project')Object.assign(projects.find(x=>x.id===p.project_id),p);
   if(r.method==='sign_in'){active='Signing in';result={started:true};}
   if(r.method==='cancel'){active=null;result={cancellation_requested:true};}
   if(['task_events'].includes(r.method))result={events:[],last_seq:0,complete:true};
   if(r.method==='scope_get')result={scope:null,scope_digest:null,scope_approval:null};
   queueMicrotask(()=>{if(['sign_in','cancel'].includes(r.method))window.interspaceReceive({type:'state',state:state()});window.interspaceReceive({id:r.id,result:result||state()});});
  }}}};
  window.interspaceReceive({type:'state',state:state()});
 });
 assert(await page.getByRole('heading',{name:'Tasks',exact:true}).isVisible(),'Native app must open on Tasks');
 // The removed surfaces are gone from the sidebar.
 const sidebar=await text('aside');
 for(const gone of ['Observatory','Workspace advice','Project conversation','Notion','Zotero','Google Drive'])assert(!sidebar.includes(gone),'Removed surface still in the sidebar: '+gone);
 const desk=await text('#desk-tasks');
 assert(desk.includes('Orchestrator on Claude · claude-opus-5-5 · own task branch'),'Agent row label missing: '+desk);
 assert(await page.locator('#desk-tasks .provider-badge[data-provider=claude]').count()===1,'Provider badge missing on the desk row');
 assert(desk.includes('Earlier task (read-only) · Read-only review')&&desk.includes('Earlier task (read-only) · Fix & test (Python)'),'Earlier rows not labelled: '+desk);

 // New task is agent-only: no mode choice, no draft, straight to the scope review.
 await page.getByRole('button',{name:'New task',exact:true}).click();
 assert(await page.locator('#new-agent-fields').isVisible(),'Agent fields hidden');
 assert(await page.locator('#new-mode').count()===0&&await page.getByRole('button',{name:'Create draft'}).count()===0,'Old task modes still offered');
 assert(await page.getByRole('button',{name:'Review scope',exact:true}).isVisible(),'Review scope missing');

 // An earlier task opens read-only: conversation, plan and result text, and no action that runs anything.
 await page.locator('[data-view=tasks]').click();
 await page.locator('[data-open-task="old-1"]').click();
 assert(await page.locator('#task-detail').isVisible()&&await page.locator('#agent-view').isHidden(),'Earlier task did not open read-only');
 assert((await text('#task-label')).includes('Earlier task (read-only)'),'Read-only label missing');
 assert((await text('#task-meta')).includes('Read-only review'),'Mode label missing');
 assert((await text('#task-tokens')).includes('Tokens 1,200 used'),'Token line missing');
 const transcript=await text('#transcript');
 assert(transcript.includes('Compare the two sources')&&transcript.includes('Literal <img src=x onerror="window.pwned=1"> reply'),'Conversation missing: '+transcript);
 assert(await page.locator('#transcript img').count()===0&&!(await page.evaluate(()=>window.pwned)),'Saved text inserted as markup');
 await page.locator('[data-task-tab=plan]').click();
 assert((await text('#plan-text')).includes('- Researcher 1: Read the README'),'Plan text missing');
 await page.locator('[data-task-tab=result]').click();
 assert((await text('#result-body')).includes('Two sources agree.')&&(await text('#result-body')).includes('completed'),'Result text missing');
 const buttons=await page.locator('#task-detail button').allTextContents();
 assert(JSON.stringify(buttons)===JSON.stringify(['← Tasks','Conversation','Plan','Result']),'Earlier task offers actions: '+JSON.stringify(buttons));
 assert(await page.locator('#task-detail textarea, #task-detail input, #task-detail form').count()===0,'Earlier task has an input');
 const sent=await page.evaluate(()=>window.deskFixture.requests.map(r=>r.method));
 assert(sent.every(m=>['state','select_task','switch_project','providers_list','research_sources'].includes(m)),'Reading an earlier task sent '+sent.join(','));
 await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task="old-2"]').click();
 await page.locator('[data-task-tab=plan]').click();assert(await page.locator('#plan-empty').isVisible(),'Empty plan not explained');
 await page.locator('[data-task-tab=result]').click();assert((await text('#result-body')).includes('Stopped early'),'Saved error missing');

 // Agent rows still open the agent view.
 await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task="agent-1"]').click();
 assert(await page.locator('#agent-view').isVisible()&&await page.locator('#task-detail').isHidden(),'Agent row did not open the agent view');

 // Settings: project details and Providers (no old OpenAI connection section); the active banner still stops.
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 assert(await page.locator('#project-settings').isVisible(),'Project details unreachable');
 assert(await page.getByRole('heading',{name:'Providers',exact:true}).isVisible(),'Providers settings missing');
 assert(await page.getByRole('button',{name:'Sign in with ChatGPT'}).count()===0&&await page.getByRole('button',{name:'Check connection'}).count()===0,'Old connection controls still shown');
 await page.evaluate(()=>window.deskFixture.setActive('Working'));
 assert(await page.locator('#active-owner').isVisible()&&(await text('#activity')).includes('Working'),'Active banner missing');
 await page.getByRole('button',{name:'Stop',exact:true}).first().click();
 const methods=await page.evaluate(()=>window.deskFixture.requests.map(r=>r.method));
 assert(methods.includes('providers_list')&&methods.at(-1)==='cancel','Settings actions not sent: '+methods.join(','));

 // Light/dark fit at every width for each surface.
 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:1000});
  for(const surface of ['tasks','new','detail','settings']){
   if(surface==='detail'){await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task="old-1"]').click();await page.locator('[data-task-tab=result]').click();}
   else if(surface==='new'){await page.locator('[data-view=tasks]').click();await page.getByRole('button',{name:'New task',exact:true}).click();}
   else await page.locator('[data-view='+surface+']').click();
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+colorScheme+' '+width+' '+surface);fits.push(fit);
   if(width===1280&&colorScheme==='light'||width===320&&colorScheme==='dark')await page.screenshot({path:'workspace-data/task-desk-'+surface+'-'+colorScheme+'-'+width+'.png',fullPage:true});
  }
 }}
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});

 // Actual reopened backend projections of earlier tasks through the real UI.
 const reopened=JSON.parse(execFileSync(process.env.INTERSPACE_PYTHON||'python3',['tests/task_saved_state_fixture.py'],{encoding:'utf8'}));
 for(const fixture of reopened){for(const selected of ['nonselected','selected']){
  assert(fixture.raw_preserved,'Saved malformed raw record was rewritten');
  await page.goto(url);
  await page.evaluate(({fixture,selected})=>{window.requests=[];window.webkit={messageHandlers:{interspace:{postMessage(r){window.requests.push(r.method);const next=r.method==='switch_project'?fixture.other:r.params.task_id===null?fixture.general:fixture.healthy;queueMicrotask(()=>window.interspaceReceive({id:r.id,result:next}));}}}};window.interspaceReceive({type:'state',state:fixture[selected]});},{fixture,selected});
  assert(await page.locator('[data-open-task=broken]').isDisabled(),'Malformed '+selected+' task was not isolated');
  assert(await page.locator('[data-open-task=healthy]').isEnabled(),'Malformed '+selected+' task hid healthy task');
  await page.locator('[data-open-task=healthy]').click();
  assert(await page.getByRole('heading',{name:'Healthy task',exact:true}).isVisible(),'Healthy task detail unreachable');
  assert((await text('#transcript')).includes('Healthy conversation survives'),'Healthy task conversation missing');
  await page.locator('[data-task-tab=plan]').click();
  assert((await text('#plan-text')).includes('Healthy saved plan'),'Healthy saved plan missing');
  await page.locator('#project-picker').selectOption('other');
  assert((await text('#breadcrumb')).includes('Other healthy project'),'Malformed task broke other project navigation');
  assert(await page.evaluate(()=>window.requests.every(m=>['select_task','switch_project'].includes(m))),'Reopened history sent a work request');
 }}
 assert(!errors.length,errors.join('\n'));
 return {checks:'Tasks default, removed surfaces absent, agent-only New task, earlier tasks read-only with conversation/plan/result text and no actions, literal saved text, agent rows open the agent view, Settings Providers and Stop, reopened backend projections with malformed-task isolation, light/dark 320-1280 fit',responsiveSurfaces:fits.length};
}
