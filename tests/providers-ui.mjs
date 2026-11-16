/* Settings → Providers and the New task Orchestrator choice against a fake bridge only
   (docs/superpowers/specs/multi-provider/providers.md): no backend, CLI, sign-in or model call. */
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async loc=>(await loc.textContent())||'';
 await page.goto(url);
 await page.evaluate(()=>{
  const project={id:'p1',name:'Fixture project',brief:'',priority:'normal',next_action:''};
  const rows=[];
  const state=()=>({version:4,projects:[project],project_id:'p1',project:'Fixture project',task_id:null,task:null,tasks:rows,active:null,error:'',scheduler:{max_running:4,running:[],queued:[]}});
  const routing={v:1,orchestrator:{provider:'claude',model:null},roles:{researcher:{provider:'codex',model:null},implementer:{provider:'claude',model:null},reviewer:{provider:'codex',model:null},tester:{provider:'claude',model:null},writer:{provider:'claude',model:null}}};
  const list={providers:[
   {name:'claude',title:'Claude',models:['claude-sonnet-5-5','claude-opus-5-5','claude-haiku-5-5'],default_model:'claude-sonnet-5-5',capabilities:{write:true,web_search:true,approvals:true}},
   {name:'codex',title:'Codex',models:[],default_model:null,capabilities:{write:true,web_search:true,approvals:true}},
   {name:'gemini',title:'Gemini',models:[],default_model:null,capabilities:{write:false,web_search:true,approvals:false}}],
   status:[{provider:'claude',state:'signed_out',account:null,detail:'Not signed in'},{provider:'codex',state:'signed_out',account:null,detail:''},{provider:'gemini',state:'missing_cli',account:null,detail:'Literal <img src=x onerror="window.pwned=1"> not found'}],routing};
  const scope={v:1,task_id:null,version:1,projects:[{project_id:'p1',access:'write',read:['**'],write:['**'],deny:[]}],commands:{workspace:'allow',allow:[],deny:[]},network:{default:'deny',allow_hosts:[],deny_hosts:[]},apps:[],web_search:'deny',limits:{token_budget:250000,time_limit_s:3600}};
  const f=window.provFixture={requests:[],hold:{},held:[],failNext:{},
   respond(r,result){window.interspaceReceive({id:r.id,result});},fail(r,error){window.interspaceReceive({id:r.id,error});}};
  window.webkit={messageHandlers:{interspace:{postMessage(r){
   f.requests.push(r);const p=r.params||{};if(f.hold[r.method]){f.held.push(r);return;}
   if(f.failNext[r.method]){const e=f.failNext[r.method];delete f.failNext[r.method];queueMicrotask(()=>f.fail(r,e));return;}
   let result={};
   if(r.method==='state')result=state();
   else if(r.method==='providers_list')result=JSON.parse(JSON.stringify(list));
   else if(r.method==='provider_sign_in')result=p.provider==='codex'?{provider:'codex',kind:'device',url:'https://auth.example.invalid/device',code:'ABCD-1234',detail:'The code expires in 15 minutes.'}:{provider:p.provider,kind:'terminal',command:'claude auth login'};
   else if(r.method==='provider_status'){const s={provider:p.provider,state:'signed_in',account:'Ada <b>Lovelace</b>',detail:''};list.status=list.status.map(x=>x.provider===p.provider?s:x);result=s;}
   else if(r.method==='routing_update'){list.routing=p.routing;result=p.routing;}
   else if(r.method==='scope_default')result={scope};
   else if(r.method==='agent_create'){rows.push({id:'N'+rows.length,mode:'agent',title:p.title,status:'idle',provider:p.provider,model:p.model});result={task_id:'N'+(rows.length-1)};queueMicrotask(()=>window.interspaceReceive({type:'state',state:state()}));}
   else if(r.method==='task_events')result={events:[],last_seq:0,complete:true};
   else if(r.method==='scope_get')result={scope:{...scope,task_id:p.task_id},scope_digest:'sha256:aa',scope_approval:null};
   queueMicrotask(()=>f.respond(r,result));
  }}}};
  window.interspaceReceive({type:'state',state:state()});
 });
 const req=method=>page.evaluate(m=>window.provFixture.requests.filter(r=>r.method===m).map(r=>r.params),method);
 const settings=page.locator('#providers-settings');

 // Connection status per provider, from providers_list; detail text stays literal.
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('#providers-settings .provider-item').length===3);
 const item=name=>settings.locator('.provider-item[data-provider='+name+']');
 assert((await text(item('claude'))).includes('Signed out · Not signed in')&&(await text(item('codex'))).includes('Signed out'),'Signed-out status missing');
 assert((await text(item('gemini'))).includes('Command-line tool not installed · Literal <img src=x onerror="window.pwned=1"> not found'),'Missing CLI status wrong: '+await text(item('gemini')));
 assert(await settings.locator('img').count()===0&&!(await page.evaluate(()=>window.pwned)),'Status detail inserted as markup');
 assert((await text(item('gemini'))).includes('read-only roles')&&(await text(item('claude'))).includes('can write in its own workspace'),'Capabilities not shown');
 assert(await item('gemini').getByRole('button',{name:'Sign in to Gemini',exact:true}).isDisabled(),'Sign in offered without the CLI');
 for(const name of ['claude','codex','gemini'])assert(await item(name).locator('.provider-badge[data-provider='+name+']').count()===1,'Badge missing: '+name);

 // Device sign-in shows the URL and code; a terminal sign-in shows the command. Keyboard reaches both.
 await item('codex').getByRole('button',{name:'Sign in to Codex',exact:true}).focus();
 await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.querySelector('#providers-settings .provider-item[data-provider=codex] .device-code'));
 const codex=await text(item('codex'));
 assert(codex.includes('https://auth.example.invalid/device')&&codex.includes('ABCD-1234')&&codex.includes('expires in 15 minutes'),'Device sign-in incomplete: '+codex);
 assert(await item('codex').locator('a').count()===0,'Sign-in URL rendered as a link');
 await item('claude').getByRole('button',{name:'Sign in to Claude',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .provider-item[data-provider=claude] .sign-in-steps'));
 assert((await text(item('claude'))).includes('Run this in Terminal')&&(await text(item('claude'))).includes('claude auth login'),'Terminal sign-in instruction missing');
 assert(JSON.stringify(await req('provider_sign_in'))==='[{"provider":"codex"},{"provider":"claude"}]','Sign-in params wrong');
 // Check status after signing in: account shown literally, instructions and Sign in gone.
 await item('codex').getByRole('button',{name:'Check Codex status',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .provider-item[data-provider=codex]').textContent.includes('Signed in as'));
 const signedIn=await text(item('codex'));
 assert(signedIn.includes('Signed in as Ada <b>Lovelace</b>')&&!signedIn.includes('ABCD-1234')&&await item('codex').getByRole('button',{name:'Sign in to Codex'}).count()===0,'Signed-in state wrong: '+signedIn);
 assert(JSON.stringify(await req('provider_status'))==='[{"provider":"codex"}]','Status params wrong');
 assert(await item('codex').locator('b').count()===0,'Account inserted as markup');
 // A failed status check is shown on that provider and keeps the rest usable.
 await page.evaluate(()=>{window.provFixture.failNext.provider_status='The status check timed out.';});
 await item('claude').getByRole('button',{name:'Check Claude status',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .provider-item[data-provider=claude]').textContent.includes('timed out'));

 // Routing defaults: write roles refuse providers without write; models are checked; the update is exact.
 const routing=settings.locator('.routing-form');
 assert(await routing.getByLabel('Orchestrator provider').inputValue()==='claude'&&await routing.getByLabel('Researcher provider').inputValue()==='codex','Routing not filled');
 for(const role of ['Implementer','Tester'])assert(await routing.getByLabel(role+' provider').locator('option[value=gemini]').isDisabled(),role+' offers a provider without write');
 assert(!(await routing.getByLabel('Reviewer provider').locator('option[value=gemini]').isDisabled()),'Read role refuses a read-only provider');
 await routing.getByLabel('Researcher provider').selectOption('gemini');
 await routing.getByLabel('Reviewer model').fill('codex-fixture-1');
 await routing.getByLabel('Orchestrator model').fill('bad model');
 await routing.getByRole('button',{name:'Save defaults',exact:true}).click();
 assert((await req('routing_update')).length===0,'Invalid model reached the backend');
 await routing.getByLabel('Orchestrator model').fill('claude-nope');
 await routing.getByRole('button',{name:'Save defaults',exact:true}).click();
 assert((await req('routing_update')).length===0,'Model outside the provider list reached the backend');
 await routing.getByLabel('Orchestrator model').fill('claude-opus-5-5');
 assert((await text(routing)).includes('Unsaved changes'),'Unsaved state not shown');
 await page.evaluate(()=>{window.provFixture.failNext.routing_update='Implementer needs a provider that can write.';});
 await routing.getByRole('button',{name:'Save defaults',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .route-error').textContent.includes('Implementer'));
 assert(await settings.locator('.routing-form').getByLabel('Orchestrator model').inputValue()==='claude-opus-5-5','Draft lost after a failed save');
 await settings.locator('.routing-form').getByRole('button',{name:'Save defaults',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .route-status').textContent==='Saved');
 const updates=await req('routing_update');
 const expected={v:1,orchestrator:{provider:'claude',model:'claude-opus-5-5'},roles:{researcher:{provider:'gemini',model:null},implementer:{provider:'claude',model:null},reviewer:{provider:'codex',model:'codex-fixture-1'},tester:{provider:'claude',model:null},writer:{provider:'claude',model:null}}};
 assert(updates.length===2&&JSON.stringify(updates[1])===JSON.stringify({routing:expected}),'routing_update not exact: '+JSON.stringify(updates));

 // New task: the Orchestrator defaults to the routing choice and can be overridden; no old runtime picker.
 await page.getByRole('button',{name:'New task',exact:true}).click();
 assert(await page.locator('#new-runtime').count()===0,'Old runtime picker still present');
 await page.waitForFunction(()=>document.querySelector('#new-provider option')?.textContent==='Your default: Claude · claude-opus-5-5');
 assert(await page.locator('#new-provider').inputValue()==='','Default not selected');
 assert(await page.locator('#new-model').getAttribute('placeholder')==='Default: claude-opus-5-5','Model placeholder does not show the default');
 await page.locator('#new-title').fill('Default orchestrator');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#new-agent-scope .scope-editor'));
 assert((await text(page.locator('#new-agent-scope-note'))).includes('Orchestrator on Claude · claude-opus-5-5 (from your defaults)'),'Scope note misses the Orchestrator: '+await text(page.locator('#new-agent-scope-note')));
 await page.getByRole('button',{name:'Create task',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#agent-view').hidden);
 let creates=await req('agent_create');
 assert(creates.length===1&&creates[0].provider==='claude'&&creates[0].model==='claude-opus-5-5'&&creates[0].title==='Default orchestrator','Default create params: '+JSON.stringify(creates));
 assert((await text(page.locator('#agent-head'))).includes('Orchestrator on Claude · claude-opus-5-5'),'Header misses the Orchestrator provider');
 // Override with a free-text model on a provider without a model list; a list provider refuses other names.
 await page.getByRole('button',{name:'New task',exact:true}).click();
 await page.locator('#new-title').fill('Codex orchestrator');
 await page.locator('#new-provider').selectOption('claude');await page.locator('#new-model').fill('gpt-5');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 assert((await req('scope_default')).length===1,'Model outside the provider list accepted');
 await page.locator('#new-provider').selectOption('codex');
 assert((await page.locator('#new-model').getAttribute('placeholder'))==='The provider’s default','Placeholder not updated for the override');
 await page.locator('#new-model').fill('codex-fixture-2');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#new-agent-scope .scope-editor'));
 assert(!(await text(page.locator('#new-agent-scope-note'))).includes('from your defaults'),'Override labelled as a default');
 await page.getByRole('button',{name:'Create task',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#agent-view').hidden);
 creates=await req('agent_create');
 assert(creates.length===2&&creates[1].provider==='codex'&&creates[1].model==='codex-fixture-2','Override create params: '+JSON.stringify(creates[1]));
 await page.locator('[data-view=tasks]').click();
 assert((await text(page.locator('#desk-tasks'))).includes('Orchestrator on Codex · codex-fixture-2'),'Desk row misses the override');

 // Light/dark, 320-1280 fit for Settings → Providers and the New task form.
 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:900});
  for(const target of ['settings','new']){
   if(target==='settings')await page.locator('[data-view=settings]').click();else{await page.locator('[data-view=tasks]').click();await page.getByRole('button',{name:'New task',exact:true}).click();}
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+target+' '+width+' '+colorScheme);fits.push(fit);
   if(width===390||width===1280&&colorScheme==='light')await page.screenshot({path:'workspace-data/providers-'+target+'-'+colorScheme+'-'+width+'.png',fullPage:true});
  }
 }}
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'provider status per provider (signed out, missing CLI, signed in, failed check), literal detail/account text, device sign-in URL and code by keyboard, terminal instruction, Check status, routing editor with write-role gating, model validation, failed save keeps the draft, exact routing_update, New task Orchestrator default from routing and override with exact agent_create params, no old runtime picker, light/dark 320-1280 fit',responsiveStates:fits.length};
}
