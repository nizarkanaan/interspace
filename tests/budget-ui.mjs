/* Token budget journeys over real backend public snapshots; fake jobs/checks, disposable sources, no providers. */
import {execFileSync} from 'node:child_process';
export default async function check(page,url){
 const fixture=JSON.parse(execFileSync('python3',['tests/budget_saved_state_fixture.py'],{encoding:'utf8'}));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const install=async name=>{
  await page.goto(url);
  if(!await page.evaluate(()=>!!document.getElementById('ispace').interspaceLab))await page.addScriptTag({path:'design/scene/lab-scene.js'});
  await page.evaluate(({fixture,name})=>{
   const f=window.budgetFixture={requests:[],current:name};
   window.webkit={messageHandlers:{interspace:{postMessage(r){f.requests.push(r);queueMicrotask(()=>window.interspaceReceive({id:r.id,result:fixture[f.current]}));}}}};
   window.interspaceReceive({type:'state',state:fixture[name]});
  },{fixture,name});
 };
 const open=async(name,tab)=>{
  await install(name);await page.locator('[data-open-task="'+fixture[name].task_id+'"]').click();
  await page.locator('[data-task-tab='+tab+']').click();
 };
 const text=async sel=>(await page.locator(sel).textContent())||'';
 const noMoney=async name=>{const body=await page.locator('body').innerText();assert(!/\$|USD|dollar|price/i.test(body),'Money text shown in '+name);};

 // Header totals and plan projection that fits.
 await open('plan_fits','plan');
 assert((await text('#task-tokens')).includes('Tokens 16,714 / 250,000'),'Header totals missing: '+await text('#task-tokens'));
 assert((await text('#task-tokens')).includes('16,714 estimated'),'Estimated charge not marked');
 assert(await page.locator('#plan-budget').isVisible(),'Plan projection hidden');
 const fits=await text('#plan-budget');
 assert(fits.includes('233,286 of 250,000 tokens remain')&&fits.includes('4 calls'),'Plan projection wrong: '+fits);
 assert(!fits.includes('likely stop'),'Fitting plan warned');
 await noMoney('plan_fits');

 // Editing the budget sends an exact owned update.
 await page.locator('#task-budget').fill('90000');await page.getByRole('button',{name:'Save budget',exact:true}).click();
 const update=await page.evaluate(()=>window.budgetFixture.requests.find(r=>r.method==='update_task'));
 assert(update&&update.params.token_budget===90000&&update.params.task_id===fixture.plan_fits.task_id&&update.params.project_id===fixture.plan_fits.project_id,'Budget update not bound to owner');
 const sent=(await page.evaluate(()=>window.budgetFixture.requests.length));
 await page.locator('#task-budget').fill('0');await page.getByRole('button',{name:'Save budget',exact:true}).click();
 assert(await page.evaluate(()=>window.budgetFixture.requests.length)===sent,'Invalid budget was sent');

 // A plan that will not fit warns but is still inspectable.
 await open('plan_tight','plan');
 const tight=await text('#plan-budget');
 assert(tight.includes('30,000 of 250,000 tokens remain')&&tight.includes('likely stop early'),'Tight warning missing: '+tight);
 assert(await page.getByRole('button',{name:/Generate candidate/}).count()===1,'Start hidden despite first call fitting');

 // New task: default budget, validation and exact create request.
 await install('editing');
 await page.getByRole('button',{name:'New task',exact:true}).first().click();
 assert(await page.locator('#new-budget').inputValue()==='250000','Default budget missing');
 await page.locator('#new-goal').fill('Budgeted draft');await page.locator('#new-budget').fill('-3');
 await page.getByRole('button',{name:'Create draft',exact:true}).click();
 assert(!(await page.evaluate(()=>window.budgetFixture.requests.some(r=>r.method==='create_task'))),'Invalid new budget was sent');
 await page.locator('#new-budget').fill('120000');await page.getByRole('button',{name:'Create draft',exact:true}).click();
 const created=await page.evaluate(()=>window.budgetFixture.requests.find(r=>r.method==='create_task'));
 assert(created&&created.params.token_budget===120000&&created.params.specialist_limit===6,'Create did not send the budget');

 // Paused change: continuing projection and an exact check approval that carries the bound budget.
 await open('paused','result');
 assert((await text('#revision-controls')+await text('#results')).includes('Continuing\'s 3 calls are estimated'),'Check projection missing');
 await page.getByRole('button',{name:'Run candidate checks',exact:true}).click();
 const approve=await page.evaluate(()=>window.budgetFixture.requests.find(r=>r.method==='approve_checks'));
 assert(JSON.stringify(approve.params)===JSON.stringify(fixture.paused.run.action_refs.approve_checks)&&approve.params.token_budget===250000,'Check approval lost its budget binding');

 // Exhausted: plain stop message, no further actions, per-call charges labelled.
 await open('exhausted','result');
 const stopped=await text('#results')+await text('#revision-controls');
 assert(stopped.includes('token budget could not fit the next call'),'Exhausted message missing');
 assert(await page.getByRole('button',{name:'Apply reviewed changes',exact:true}).count()===0&&await page.getByRole('button',{name:'Run candidate checks',exact:true}).count()===0,'Actions offered after exhaustion');
 assert((await text('#task-meta')).includes('budget exhausted'),'Task status not shown');
 await page.locator('[data-task-tab=activity]').click();
 const usage=await page.locator('#usage').evaluate(n=>n.textContent);
 assert(usage.includes('charged')&&usage.includes('(estimated: no counts returned)'),'Per-call charges unlabeled: '+usage.slice(0,200));
 await noMoney('exhausted');

 // Older task without a budget.
 await open('legacy','plan');
 assert((await text('#task-tokens')).includes('No budget set'),'Legacy budget state missing');
 assert(await page.locator('#plan-budget').isHidden(),'Legacy plan shows a projection');

 const fits_=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:1000});for(const [stage,tab] of [['plan_tight','plan'],['paused','result'],['exhausted','result']]){
  await open(stage,tab);
  const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+stage+' '+width+' '+colorScheme);fits_.push(fit);
  if(width===390&&stage==='plan_tight')await page.screenshot({path:'workspace-data/budget-'+(url.includes('/dist/')?'packaged':'source')+'-'+stage+'-'+colorScheme+'-'+width+'.png',fullPage:true});
 }}}
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'header totals and estimated marking, plan projection and tight warning, owned budget edit and validation, new-task default and create binding, check-approval budget binding, exhausted stop without actions, labelled per-call charges, legacy no-budget state, no money text, light/dark responsive fit',responsiveStates:fits_.length};
}
