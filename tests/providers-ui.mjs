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
  const eff=['low','medium','high','xhigh','max'];
  const models={claude:[{id:'claude-sonnet-5-5',is_default:true,default_effort:'low',efforts:eff},{id:'claude-opus-5-5',is_default:false,default_effort:'low',efforts:eff},{id:'claude-haiku-5-5',is_default:false,default_effort:'low',efforts:eff}],
   codex:[{id:'codex-fixture-1',is_default:true,default_effort:'medium',efforts:['low','medium','high','xhigh']},{id:'codex-fixture-2',is_default:false,default_effort:'low',efforts:['low','medium','high']}],gemini:[]};
  const f=window.provFixture={requests:[],hold:{},held:[],failNext:{},modelError:{},
   respond(r,result){window.interspaceReceive({id:r.id,result});},fail(r,error){window.interspaceReceive({id:r.id,error});}};
  window.webkit={messageHandlers:{interspace:{postMessage(r){
   f.requests.push(r);const p=r.params||{};if(f.hold[r.method]){f.held.push(r);return;}
   if(f.failNext[r.method]){const e=f.failNext[r.method];delete f.failNext[r.method];queueMicrotask(()=>f.fail(r,e));return;}
   let result={};
   if(r.method==='state')result=state();
   else if(r.method==='providers_list')result=JSON.parse(JSON.stringify(list));
   else if(r.method==='provider_sign_in')result=p.provider==='codex'?{provider:'codex',kind:'device',url:'https://auth.example.invalid/device',code:'ABCD-1234',detail:'The code expires in 15 minutes.'}:{provider:p.provider,kind:'terminal',command:'claude auth login'};
   else if(r.method==='provider_status'){const s={provider:p.provider,state:'signed_in',account:'Ada <b>Lovelace</b>',detail:''};list.status=list.status.map(x=>x.provider===p.provider?s:x);result=s;}
   else if(r.method==='provider_sign_out'){const s={provider:p.provider,state:'signed_out',account:null,detail:''};list.status=list.status.map(x=>x.provider===p.provider?s:x);result=s;}
   else if(r.method==='provider_models')result=f.modelError[p.provider]?{provider:p.provider,models:[],error:f.modelError[p.provider]}:{provider:p.provider,models:models[p.provider]||[],error:''};
   else if(r.method==='routing_update'){list.routing=p.routing;result=p.routing;}
   else if(r.method==='scope_default')result={scope};
   else if(r.method==='agent_create'){rows.push({id:'N'+rows.length,mode:'agent',title:p.title,status:'idle',provider:p.provider||list.routing.orchestrator.provider,model:'provider' in p?p.model:list.routing.orchestrator.model});result={task_id:'N'+(rows.length-1)};queueMicrotask(()=>window.interspaceReceive({type:'state',state:state()}));}
   else if(r.method==='task_events')result={events:[],last_seq:0,complete:true};
   else if(r.method==='scope_get')result={scope:{...scope,task_id:p.task_id},scope_digest:'sha256:aa',scope_approval:null};
   queueMicrotask(()=>f.respond(r,result));
  }}}};
  f.state=state;
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
 // Sign out asks first, then sends provider_sign_out and shows the signed-out status; Cancel sends nothing.
 await item('codex').getByRole('button',{name:'Sign out of Codex',exact:true}).click();
 assert((await text(item('codex'))).includes('Sign out of Codex on this Mac?'),'Sign-out confirmation missing');
 await item('codex').getByRole('button',{name:'Cancel',exact:true}).click();
 assert((await req('provider_sign_out')).length===0&&(await text(item('codex'))).includes('Signed in as'),'Cancel signed out');
 await item('codex').getByRole('button',{name:'Sign out of Codex',exact:true}).focus();
 await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.activeElement?.textContent==='Sign out');
 await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.querySelector('#providers-settings .provider-item[data-provider=codex]').textContent.includes('Signed out'));
 assert(JSON.stringify(await req('provider_sign_out'))==='[{"provider":"codex"}]','Sign-out params wrong');
 assert(await item('codex').getByRole('button',{name:'Sign in to Codex',exact:true}).count()===1,'Sign in not offered after signing out');
 // Device sign-in completes through state.provider_status: no polling, the instructions close by themselves.
 await item('codex').getByRole('button',{name:'Sign in to Codex',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .provider-item[data-provider=codex] .device-code'));
 const statusCalls=(await req('provider_status')).length,listCalls=(await req('providers_list')).length;
 await page.waitForTimeout(400);
 assert((await req('provider_status')).length===statusCalls&&(await req('providers_list')).length===listCalls,'Sign-in still polls');
 await page.evaluate(()=>{const f=window.provFixture;window.interspaceReceive({type:'state',state:{...f.state(),provider_status:{codex:{provider:'codex',state:'signed_in',account:'Grace <i>H</i>',detail:''},bogus:{provider:'other',state:'signed_in'}}}});});
 await page.waitForFunction(()=>document.querySelector('#providers-settings .provider-item[data-provider=codex]').textContent.includes('Signed in as Grace <i>H</i>'));
 assert(await item('codex').locator('.device-code,i').count()===0,'Sign-in steps kept after state reported signed in');
 assert(await settings.locator('.provider-item[data-provider=other]').count()===0,'Mismatched status entry applied');
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
 await routing.getByLabel('Reviewer model').selectOption('codex-fixture-1');
 await routing.getByLabel('Researcher model').fill('bad model');
 await routing.getByRole('button',{name:'Save defaults',exact:true}).click();
 assert((await req('routing_update')).length===0,'Invalid model reached the backend');
 await routing.getByLabel('Researcher model').fill('');
 await routing.getByLabel('Orchestrator model').selectOption('claude-opus-5-5');
 assert((await text(routing)).includes('Unsaved changes'),'Unsaved state not shown');
 await page.evaluate(()=>{window.provFixture.failNext.routing_update='Implementer needs a provider that can write.';});
 await routing.getByRole('button',{name:'Save defaults',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .route-error').textContent.includes('Implementer'));
 assert(await settings.locator('.routing-form').getByLabel('Orchestrator model').inputValue()==='claude-opus-5-5','Draft lost after a failed save');
 await settings.locator('.routing-form').getByRole('button',{name:'Save defaults',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .route-status').textContent==='Saved');
 const updates=await req('routing_update');
 const expected={v:1,orchestrator:{provider:'claude',model:'claude-opus-5-5',effort:null},roles:{researcher:{provider:'gemini',model:null,effort:null},implementer:{provider:'claude',model:null,effort:null},reviewer:{provider:'codex',model:'codex-fixture-1',effort:null},tester:{provider:'claude',model:null,effort:null},writer:{provider:'claude',model:null,effort:null}}};
 assert(updates.length===2&&JSON.stringify(updates[1])===JSON.stringify({routing:expected}),'routing_update not exact: '+JSON.stringify(updates));


 // Model and effort pickers: lists come from provider_models; the effort follows the model.
 const optionsOf=async sel=>(await settings.locator(sel+' option').allTextContents());
 await routing.getByLabel('Researcher provider').selectOption('codex');
 await page.waitForFunction(()=>document.querySelectorAll('select#route-researcher-model option').length===3);
 assert(JSON.stringify(await optionsOf('select#route-researcher-model'))==='["Default (codex-fixture-1)","codex-fixture-1","codex-fixture-2"]','Codex model options: '+await optionsOf('select#route-researcher-model'));
 assert(JSON.stringify(await optionsOf('select#route-researcher-effort'))==='["Default (medium)","low","medium","high","xhigh"]','Effort options for the default model: '+await optionsOf('select#route-researcher-effort'));
 await routing.getByLabel('Researcher model').selectOption('codex-fixture-1');
 await routing.getByLabel('Researcher effort').selectOption('xhigh');
 await routing.getByLabel('Researcher model').selectOption('codex-fixture-2');
 assert(await routing.getByLabel('Researcher effort').inputValue()==='','Effort not reset when the model lacks it');
 assert(JSON.stringify(await optionsOf('select#route-researcher-effort'))==='["Default (low)","low","medium","high"]','Effort options follow the model');
 await routing.getByLabel('Researcher effort').selectOption('high');
 await routing.getByLabel('Researcher model').selectOption('codex-fixture-1');
 assert(await routing.getByLabel('Researcher effort').inputValue()==='high','Effort dropped though the new model offers it');
 // Switching provider refills both lists and resets the effort; each provider's list is asked for once.
 const claudeAsks=(await req('provider_models')).filter(x=>x.provider==='claude').length;
 await routing.getByLabel('Researcher provider').selectOption('claude');
 await page.waitForFunction(()=>document.querySelectorAll('select#route-researcher-model option').length===4);
 assert(JSON.stringify(await optionsOf('select#route-researcher-model'))==='["Default (claude-sonnet-5-5)","claude-sonnet-5-5","claude-opus-5-5","claude-haiku-5-5"]','Claude model options');
 assert(await routing.getByLabel('Researcher effort').inputValue()===''&&JSON.stringify(await optionsOf('select#route-researcher-effort'))==='["Default (low)","low","medium","high","xhigh","max"]','Claude effort options or reset wrong: '+await optionsOf('select#route-researcher-effort'));
 assert((await req('provider_models')).filter(x=>x.provider==='claude').length===claudeAsks,'Claude model list asked for again');
 // Save sends provider, model and effort for every role.
 await routing.getByLabel('Researcher model').selectOption('claude-opus-5-5');
 await routing.getByLabel('Researcher effort').selectOption('max');
 await routing.getByLabel('Orchestrator effort').selectOption('high');
 await routing.getByLabel('Reviewer effort').selectOption('xhigh');
 await routing.getByRole('button',{name:'Save defaults',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#providers-settings .route-status').textContent==='Saved');
 const sentRouting=(await req('routing_update'))[2].routing;
 assert(JSON.stringify(sentRouting)===JSON.stringify({v:1,orchestrator:{provider:'claude',model:'claude-opus-5-5',effort:'high'},roles:{researcher:{provider:'claude',model:'claude-opus-5-5',effort:'max'},implementer:{provider:'claude',model:null,effort:null},reviewer:{provider:'codex',model:'codex-fixture-1',effort:'xhigh'},tester:{provider:'claude',model:null,effort:null},writer:{provider:'claude',model:null,effort:null}}}),'Routing with effort not exact: '+JSON.stringify(sentRouting));
 // A failed list gives the typed box and the error sentence; signing out clears the remembered list.
 await page.evaluate(()=>{window.provFixture.modelError.codex='Sign in to Codex to see its models.';});
 await item('codex').getByRole('button',{name:'Sign out of Codex',exact:true}).click();
 await item('codex').getByRole('button',{name:'Sign out',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('input#route-reviewer-model'));
 assert((await text(settings.locator('.route-row[data-role=reviewer]'))).includes('Sign in to Codex to see its models.'),'Model error sentence not shown');
 assert(await settings.locator('select#route-reviewer-model').count()===0&&await settings.locator('input#route-reviewer-model').inputValue()==='codex-fixture-1','Typed box missing or lost its value');
 // A saved model the list no longer has is kept visible and blocks Save with a warning naming it.
 await settings.locator('input#route-reviewer-model').fill('gpt-5-old');
 await page.evaluate(()=>{window.provFixture.modelError.codex='';});
 await item('codex').getByRole('button',{name:'Check Codex status',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('select#route-reviewer-model'));
 const old=settings.locator('select#route-reviewer-model');
 assert(await old.inputValue()==='gpt-5-old'&&(await old.locator('option:checked').textContent())==='gpt-5-old (not available)','Unavailable model not shown: '+await old.inputValue());
 const before=(await req('routing_update')).length;
 await settings.locator('.routing-form').getByRole('button',{name:'Save defaults',exact:true}).click();
 assert((await text(settings.locator('.route-error'))).includes('gpt-5-old')&&(await req('routing_update')).length===before,'Unavailable model not refused with a warning');

 // New task: the Orchestrator defaults to the routing choice and can be overridden; no old runtime picker.
 await page.getByRole('button',{name:'New task',exact:true}).click();
 assert(await page.locator('#new-runtime').count()===0,'Old runtime picker still present');
 await page.waitForFunction(()=>document.querySelector('#new-provider option')?.textContent==='Your default: Claude · claude-opus-5-5');
 assert(await page.locator('#new-provider').inputValue()==='','Default not selected');
 await page.waitForFunction(()=>document.querySelector('select#new-model')&&document.querySelector('select#new-effort'));
 assert((await page.locator('#new-model option:checked').textContent())==='Your default: claude-opus-5-5'&&await page.locator('#new-datalist,#new-model-list').count()===0,'Model dropdown does not show the default');
 assert((await page.locator('#new-effort option:checked').textContent())==='Default (your default: high)','Effort default not shown: '+await page.locator('#new-effort option:checked').textContent());
 await page.locator('#new-title').fill('Default orchestrator');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#new-agent-scope .scope-editor'));
 assert((await text(page.locator('#new-agent-scope-note'))).includes('Orchestrator on Claude · claude-opus-5-5 · high effort (from your defaults)'),'Scope note misses the Orchestrator: '+await text(page.locator('#new-agent-scope-note')));
 await page.getByRole('button',{name:'Create task',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#agent-view').hidden);
 let creates=await req('agent_create');
 // Routing defaults are applied by the backend: without an override nothing names a provider or model.
 assert(creates.length===1&&!('provider' in creates[0])&&!('model' in creates[0])&&!('effort' in creates[0])&&!('role' in creates[0])&&creates[0].title==='Default orchestrator','Default create params: '+JSON.stringify(creates));
 assert((await text(page.locator('#agent-head'))).includes('Orchestrator on Claude · claude-opus-5-5'),'Header misses the Orchestrator provider');
 // Picking an effort sends it alone; another model resets the effort to Default; a provider change clears both.
 await page.getByRole('button',{name:'New task',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('select#new-effort'));
 await page.locator('#new-title').fill('Max effort');
 await page.locator('#new-effort').selectOption('max');
 await page.locator('#new-model').selectOption('claude-haiku-5-5');
 assert(await page.locator('#new-effort').inputValue()==='','Effort kept after another model');
 assert((await page.locator('#new-effort option:checked').textContent())==='Default (low)','Default label for a different model: '+await page.locator('#new-effort option:checked').textContent());
 await page.locator('#new-model').selectOption('');
 assert((await page.locator('#new-effort option:checked').textContent())==='Default (your default: high)','Routing default not restored');
 await page.locator('#new-effort').selectOption('max');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#new-agent-scope .scope-editor'));
 assert((await text(page.locator('#new-agent-scope-note'))).includes('Claude · claude-opus-5-5 · max effort.'),'Note misses the picked effort: '+await text(page.locator('#new-agent-scope-note')));
 await page.getByRole('button',{name:'Create task',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#agent-view').hidden);
 creates=await req('agent_create');
 assert(creates.length===2&&creates[1].effort==='max'&&!('provider' in creates[1])&&!('model' in creates[1]),'Effort create params: '+JSON.stringify(creates[1]));
 // Override the provider: its own models in a dropdown, effort back to Default.
 await page.getByRole('button',{name:'New task',exact:true}).click();
 await page.locator('#new-title').fill('Codex orchestrator');
 await page.locator('#new-effort').selectOption('high');
 await page.locator('#new-provider').selectOption('codex');
 await page.waitForFunction(()=>[...document.querySelectorAll('#new-model option')].some(o=>o.value==='codex-fixture-2'));
 assert(JSON.stringify(await page.locator('#new-model option').evaluateAll(o=>o.map(x=>x.value)))===JSON.stringify(['','codex-fixture-1','codex-fixture-2']),'Codex models not offered');
 assert(await page.locator('#new-model').inputValue()===''&&await page.locator('#new-effort').inputValue()==='','Provider change kept model or effort');
 await page.locator('#new-model').selectOption('codex-fixture-2');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#new-agent-scope .scope-editor'));
 assert(!(await text(page.locator('#new-agent-scope-note'))).includes('from your defaults'),'Override labelled as a default');
 await page.getByRole('button',{name:'Create task',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#agent-view').hidden);
 creates=await req('agent_create');
 assert(creates.length===3&&creates[2].provider==='codex'&&creates[2].model==='codex-fixture-2'&&!('effort' in creates[2]),'Override create params: '+JSON.stringify(creates[2]));
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
 return {checks:'sign out with confirmation, sign-in completion from state.provider_status without polling, defaults omitted from agent_create, provider status per provider (signed out, missing CLI, signed in, failed check), literal detail/account text, device sign-in URL and code by keyboard, terminal instruction, Check status, routing editor with write-role gating, model validation, failed save keeps the draft, exact routing_update, New task Orchestrator default from routing and override with exact agent_create params, no old runtime picker, light/dark 320-1280 fit',responsiveStates:fits.length};
}
