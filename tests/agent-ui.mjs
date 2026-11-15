/* Agent task shell against fixture events only: no backend, runtime or provider. */
import {readFileSync} from 'node:fs';
export default async function check(page,url){
 const fixture=readFileSync('tests/fixtures/events/basic-task.jsonl','utf8').trim().split('\n').map(line=>JSON.parse(line));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const scope={v:1,task_id:'t1',version:1,projects:[{project_id:'p1',access:'write',read:['**'],write:['src/**','tests/**'],deny:[]}],commands:{workspace:'allow',allow:[],deny:[['git','push']]},network:{default:'ask',allow_hosts:[],deny_hosts:[]},apps:[],web_search:'ask',limits:{token_budget:250000,time_limit_s:3600}};
 const install=async()=>{
  await page.goto(url);
  await page.evaluate(({scope})=>{
   const project={id:'p1',name:'Fixture project',brief:'',priority:'normal',next_action:''};
   const rows=[{id:'t1',mode:'agent',title:'Fix the date parser',status:'idle',run_count:0,specialist_limit:1},{id:'t2',mode:'agent',title:'Tidy the reading list',status:'running',run_count:0,specialist_limit:1},{id:'L1',title:'Legacy review',status:'draft',run_count:0,specialist_limit:6}];
   let task=null;
   const state=()=>({version:3,projects:[project],project_id:'p1',project:'Fixture project',task_id:task,task:task?{id:task,title:rows.find(r=>r.id===task).title,specialist_limit:1,draft:'',mode:rows.find(r=>r.id===task).mode||'review'}:null,tasks:rows,threads:{workspace:[],project:[],task:[]},pending:null,run:null,runs:[],active:null,error:'',connection:{message:'Synthetic fixture'},usage:[],source_selection:{mode:'selected',selection_version:1,revision:'r',paths:['README.md']},source_error:'',scheduler:{max_running:4,running:[{task_id:'t2',project_id:'p1',state:'running',started_at:'2026-11-11T09:30:00.000Z',tokens:{used:100,budget:250000},lock:null}],queued:[],legacy_active:false}});
   const f=window.agentFixture={requests:[],history:{t1:[],t2:[]},scope:JSON.parse(JSON.stringify(scope)),hold:{},held:[],state,
    respond(r,result){window.interspaceReceive({id:r.id,result});},
    fail(r,error){window.interspaceReceive({id:r.id,error});}};
   window.webkit={messageHandlers:{interspace:{postMessage(r){
    f.requests.push(r);const p=r.params||{};
    if(f.hold[r.method]){f.held.push(r);return;}
    let result={};
    if(r.method==='select_task'){task=p.task_id;result=state();}
    else if(r.method==='state')result=state();
    else if(r.method==='task_events'){const events=(f.history[p.task_id]||[]).filter(e=>e.seq>p.after_seq);result={events,last_seq:events.length?events[events.length-1].seq:p.after_seq,complete:true};}
    else if(r.method==='scope_get')result={scope:p.task_id==='t1'?f.scope:{...f.scope,task_id:p.task_id},scope_digest:'sha256:aa',scope_approval:{v:1,scope_version:1,scope_digest:'sha256:aa',approved_at:'2026-11-11T09:30:00.000Z',by:'user'}};
    else if(r.method==='scope_update'){f.scope={...p.scope,version:p.base_version+1};result={scope:f.scope,scope_digest:'sha256:s2'};}
    else if(r.method==='scope_approve')result={scope_approval:{v:1,scope_version:p.scope_version,scope_digest:p.scope_digest,approved_at:'2026-11-11T09:40:00.000Z',by:'user'}};
    else if(r.method==='agent_answer')result={accepted:true};
    else if(r.method==='agent_message')result={state:'queued',position:1};
    else if(r.method==='agent_cancel')result={cancellation_requested:true};
    else if(r.method==='task_blob')result={blob_id:p.blob_id,text:'FULL OUTPUT line 1\nFULL OUTPUT line 2'};
    queueMicrotask(()=>f.respond(r,result));
   }}}};
   window.interspaceReceive({type:'state',state:state()});
  },{scope});
 };
 const push=events=>page.evaluate(list=>{for(const event of list)window.interspaceReceive({type:'event',event});},events);
 const req=method=>page.evaluate(m=>window.agentFixture.requests.filter(r=>r.method===m),method);
 const view=page.locator('#agent-view');
 const stream=page.locator('#agent-view .stream');
 const text=async loc=>(await loc.textContent())||'';
 const ev=(seq,kind,data,extra={})=>({v:1,task_id:'t2',project_id:'p1',seq,at:'2026-11-11T10:00:00.000Z',kind,turn_id:'u1',item_id:null,data,...extra});

 await install();
 // Agent rows open the agent view; legacy rows still open the legacy desk.
 assert(await page.locator('[data-open-task="t1"]').count()===1,'Agent task row missing');
 await page.locator('[data-open-task="t1"]').click();
 assert(await view.isVisible(),'Agent view hidden');
 assert(await page.locator('#task-detail').isHidden(),'Legacy detail shown for agent task');
 assert((await text(page.locator('#heading'))).includes('Fix the date parser'),'Agent heading missing');
 const history=await req('task_events');
 assert(history.length===1&&history[0].params.task_id==='t1'&&history[0].params.after_seq===0,'History not requested from seq 0: '+JSON.stringify(history));
 assert((await req('scope_get')).some(r=>r.params.task_id==='t1'),'Scope not requested');

 // Scope chips summarise the displayed scope and its approval.
 const chips=await text(page.locator('#agent-view .scope-chips'));
 for(const part of ['src/**','tests/**','write','Network','ask','Web search','250,000','60 min','Approved'])assert(chips.includes(part),'Scope chip missing '+part+': '+chips);

 // Streaming deltas, then the final message replaces them.
 await push(fixture.slice(0,6));
 assert((await text(stream)).includes('Fix the date parser and refresh the pinned test data.'),'User echo missing');
 assert((await text(stream)).includes("I'll run the parser tests first."),'Delta not rendered');
 assert(await page.locator('#agent-view [data-item="m1"] .streaming').count()===1,'Streaming marker missing during deltas');
 await push(fixture.slice(6,7));
 assert(await page.locator('#agent-view [data-item="m1"]').count()===1,'Delta and final message split into two cards');
 assert(await page.locator('#agent-view [data-item="m1"] .streaming').count()===0,'Streaming marker kept after final');
 assert((await text(page.locator('#agent-view [data-item="m1"]'))).split("I'll run the parser tests first.").length===2,'Final text duplicated');

 // Tool calls, results and a per-call diff.
 await push(fixture.slice(7,12));
 const c1=await text(page.locator('#agent-view [data-item="c1"]'));
 assert(c1.includes('python3 -m unittest tests.test_parser')&&c1.includes('FAIL: test_iso_dates')&&c1.includes('exit 1'),'Command card incomplete: '+c1);
 const c2=page.locator('#agent-view [data-item="c2"]');
 const c2Text=await text(c2);
 assert(c2Text.includes('src/parser.py')&&c2Text.includes('+2')&&c2Text.includes('Applied 1 file.'),'Patch card incomplete: '+c2Text);
 assert(await c2.locator('.diff-line.add').count()===2&&await c2.locator('.diff-line.del').count()===1,'Diff lines not classified');
 assert((await text(page.locator('#agent-view .agent-status'))).includes('Running'),'Running status missing');

 // Inline ask: Allow once sends the exact digest-bound answer without a scope digest.
 await push(fixture.slice(12,14));
 const ask=page.locator('#agent-view [data-item="a1"]');
 assert((await text(ask)).includes('Run `pip download dateparser-data`?'),'Ask title missing');
 assert((await text(ask)).includes('pip download dateparser-data'),'Ask request detail missing');
 assert((await text(page.locator('#agent-view .agent-status'))).includes('Needs your answer'),'Paused status missing');
 for(const name of ['Allow once','Add to scope','Deny'])assert(await ask.getByRole('button',{name,exact:true}).count()===1,'Ask option missing: '+name);
 await ask.getByRole('button',{name:'Allow once',exact:true}).click();
 const answers=await req('agent_answer');
 assert(answers.length===1&&JSON.stringify(answers[0].params)===JSON.stringify({task_id:'t1',ask_id:'a1',request_digest:fixture[12].data.request_digest,decision:'allow_once'}),'Allow once not exact: '+JSON.stringify(answers));
 assert(await ask.getByRole('button',{name:'Deny',exact:true}).isDisabled(),'Ask still answerable while sending');

 // The allowed command runs then finishes in one card; the answer closes the ask.
 await push(fixture.slice(14,17));
 assert((await text(page.locator('#agent-view [data-item="c3"]'))).includes('Running'),'Running command card missing');
 await push(fixture.slice(17));
 assert(await page.locator('#agent-view [data-item="c3"]').count()===1,'Command split into two cards');
 const c3=await text(page.locator('#agent-view [data-item="c3"]'));
 assert(c3.includes('Saved dateparser_data-1.0.tar.gz')&&c3.includes('Done'),'Command result missing: '+c3);
 assert((await text(ask)).includes('Allowed once')&&await ask.getByRole('button').count()===0,'Answered ask not closed');
 assert((await text(stream)).includes('Fixed parse_date to strip whitespace')||(await text(stream)).includes('Fixed `parse_date`')||(await stream.locator('code').filter({hasText:'parse_date'}).count())===1,'Final message missing');
 assert((await text(page.locator('#agent-view .agent-budget'))).includes('21,480 / 250,000'),'Budget header wrong: '+await text(page.locator('#agent-view .agent-budget')));
 assert((await text(page.locator('#agent-view .agent-status'))).includes('Waiting for your message'),'Idle status missing');
 assert(!/\$|USD|dollar|price/i.test(await text(view)),'Money text shown');

 // Duplicate events are ignored; unknown kinds and versions show a plain row; text stays literal.
 const cards=await stream.locator('[data-item]').count();
 await push([fixture[18]]);
 assert(await stream.locator('[data-item]').count()===cards,'Duplicate seq rendered');
 await push([{...fixture[20],seq:22,kind:'mystery',item_id:null,data:{}},{...fixture[20],seq:23,kind:'message',item_id:'m9',data:{role:'assistant',text:'Literal <img src=x onerror="window.pwned=1"> **bold** text',final:true}},{...fixture[20],seq:24,v:2,kind:'message',item_id:'m10',data:{role:'assistant',text:'from the future',final:true}}]);
 assert((await text(stream)).includes('Unsupported event'),'Unknown kind not shown as unsupported');
 assert(!(await text(stream)).includes('from the future'),'Unknown version rendered as if understood');
 assert(await stream.locator('img').count()===0&&!(await page.evaluate(()=>window.pwned)),'Model text inserted as markup');
 assert((await text(stream)).includes('Literal <img src=x onerror="window.pwned=1">'),'Literal text lost');

 // Composer: /commands and @mentions by keyboard; Enter sends exactly; Shift+Enter keeps a newline.
 const box=page.locator('#agent-message');
 await box.focus();await box.fill('');await page.keyboard.type('/sc');
 const menu=page.locator('#agent-view [role=listbox]');
 assert(await menu.isVisible(),'Command menu hidden');
 assert((await text(menu)).includes('/scope'),'Scope command missing');
 assert(await box.getAttribute('aria-expanded')==='true'&&!!await box.getAttribute('aria-activedescendant'),'Combobox state not exposed');
 await page.keyboard.press('Enter');
 assert(await page.locator('#agent-view .scope-editor').isVisible(),'/scope did not open the editor');
 assert(await box.inputValue()==='','Command text left in composer');
 await page.locator('#agent-view .scope-editor').getByRole('button',{name:'Close editor',exact:true}).click();
 await box.focus();await page.keyboard.type('Check @par');
 assert((await text(menu)).includes('src/parser.py'),'File mention from events missing: '+await text(menu));
 await page.keyboard.press('Enter');
 assert(await box.inputValue()==='Check @src/parser.py ','Mention not inserted: '+await box.inputValue());
 await page.keyboard.type('@read');
 await page.keyboard.press('Escape');
 assert(await menu.isHidden(),'Escape did not close menu');
 await page.keyboard.press('Shift+Enter');await page.keyboard.type('next line');
 assert((await req('agent_message')).length===0,'Shift+Enter sent');
 await page.keyboard.press('Enter');
 const sent=await req('agent_message');
 assert(sent.length===1&&sent[0].params.task_id==='t1'&&sent[0].params.text==='Check @src/parser.py @read\nnext line'&&/^c-/.test(sent[0].params.client_id),'Message not exact: '+JSON.stringify(sent));
 assert(await box.inputValue()==='','Composer not cleared after send');
 assert(await stream.locator('.message.pending').count()===1,'Optimistic bubble missing');
 await push([{...fixture[2],seq:25,turn_id:'u2',item_id:'m11',data:{role:'user',text:'Check @src/parser.py @read\nnext line',final:true,client_id:sent[0].params.client_id}}]);
 assert(await stream.locator('.message.pending').count()===0&&(await text(stream)).split('next line').length===2,'Echo did not replace the optimistic bubble');
 await push([{...fixture[3],seq:26}]);
 assert(await page.locator('#agent-send').isDisabled(),'Send enabled while the agent runs');

 // Scope editor: validation, exact edit, displayed-digest approval.
 await page.locator('#agent-view').getByRole('button',{name:'Edit scope',exact:true}).click();
 const editor=page.locator('#agent-view .scope-editor');
 await editor.getByLabel('Write paths').fill('src/**\n../outside');
 await editor.getByRole('button',{name:'Save scope',exact:true}).click();
 assert((await req('scope_update')).length===0,'Invalid glob sent');
 assert((await text(editor)).includes('..'),'Glob error not shown');
 await editor.getByLabel('Write paths').fill('src/**\ntests/**\ndocs/**');
 await editor.getByLabel('Web search').selectOption('allow');
 await editor.getByRole('button',{name:'Save scope',exact:true}).click();
 const updates=await req('scope_update');
 const expected={...scope,projects:[{...scope.projects[0],write:['src/**','tests/**','docs/**']}],web_search:'allow'};
 assert(updates.length===1&&updates[0].params.task_id==='t1'&&updates[0].params.base_version===1&&JSON.stringify(updates[0].params.scope)===JSON.stringify(expected),'Scope edit not exact: '+JSON.stringify(updates[0]?.params));
 assert((await text(page.locator('#agent-view .scope-chips'))).includes('Needs approval'),'Edited scope not marked unapproved');
 await page.locator('#agent-view').getByRole('button',{name:'Approve scope',exact:true}).click();
 const approvals=await req('scope_approve');
 assert(approvals.length===1&&JSON.stringify(approvals[0].params)===JSON.stringify({task_id:'t1',scope_version:2,scope_digest:'sha256:s2'}),'Approval not bound to displayed digest');
 assert((await text(page.locator('#agent-view .scope-chips'))).includes('Approved'),'Approval not shown');

 // Second task: gap recovery, Add to scope with the copied digest, truncated output, cancel.
 await page.evaluate(()=>{window.agentFixture.history.t2=[];});
 await push([ev(1,'status',{state:'running',detail:'',queue_position:null,reason:null},{turn_id:null})]);
 await page.evaluate(e=>{window.agentFixture.history.t2.push(...e);},[ev(2,'message',{role:'assistant',text:'Second task working',final:true},{item_id:'x1'}),ev(3,'tool_call',{call_id:'x2',category:'command',tool:'shell',app:null,title:'ls',input:{argv:['ls'],cwd:'.'},decision:{decision:'allow',rule:'commands.workspace',scope_version:1}},{item_id:'x2'})]);
 await push([ev(4,'tool_result',{call_id:'x2',status:'ok',exit_code:0,duration_ms:5,output:{text:'partial',truncated:true,blob_id:'b1'},error:null},{item_id:'x2'})]);
 const gap=(await req('task_events')).filter(r=>r.params.task_id==='t2');
 assert(gap.some(r=>r.params.after_seq===1),'Gap not recovered from last seen seq: '+JSON.stringify(gap));
 await push([ev(5,'ask',{ask_id:'q2',call_id:'x3',reason:'network_host',title:'Allow network to pypi.org?',detail:'Not in the scope.',request:{category:'network',host:'pypi.org',port:443,via:'command'},options:['allow_once','add_to_scope','deny'],scope_patch:{network:{allow_hosts:['pypi.org']}},patched_scope_digest:'sha256:p2',request_digest:'sha256:r2'},{item_id:'q2'}),ev(6,'status',{state:'paused_ask',detail:'Allow network to pypi.org?',queue_position:null,reason:null},{turn_id:null})]);

 // Several tasks visible at once.
 await page.locator('[data-view=running]').click();
 const running=page.locator('#running-view');
 assert(await running.isVisible(),'Running view hidden');
 assert(await running.locator('.task-column').count()>=2,'Tasks not shown side by side');
 const col2=running.locator('.task-column[data-task="t2"]');
 const col2Text=await text(col2);
 assert(col2Text.includes('Second task working')&&col2Text.includes('Needs your answer'),'Second task column incomplete: '+col2Text);
 assert((await text(running.locator('.task-column[data-task="t1"]'))).includes('Fix the date parser'),'First task column missing');
 const order=await col2.locator('[data-item]').evaluateAll(n=>n.map(x=>x.dataset.item));
 assert(order.indexOf('x1')<order.indexOf('x2'),'Recovered events out of order: '+order);
 await col2.getByRole('button',{name:'Add to scope',exact:true}).click();
 const second=(await req('agent_answer')).filter(r=>r.params.task_id==='t2');
 assert(second.length===1&&JSON.stringify(second[0].params)===JSON.stringify({task_id:'t2',ask_id:'q2',request_digest:'sha256:r2',decision:'add_to_scope',scope_digest:'sha256:p2'}),'Add to scope not exact: '+JSON.stringify(second));
 await col2.getByRole('button',{name:'Stop',exact:true}).click();
 assert((await req('agent_cancel')).some(r=>r.params.task_id==='t2'),'Cancel not sent');
 await col2.getByRole('button',{name:'Open',exact:true}).click();
 assert((await text(page.locator('#heading'))).includes('Tidy the reading list'),'Open did not switch task');
 await page.locator('#agent-view').getByRole('button',{name:'Show full output',exact:true}).click();
 const blob=await req('task_blob');
 assert(blob.length===1&&blob[0].params.task_id==='t2'&&blob[0].params.blob_id==='b1','Blob request wrong');
 assert((await text(stream)).includes('FULL OUTPUT line 2'),'Full output not shown');

 // A failed answer re-enables the choices and shows the error inline.
 await push([ev(7,'ask',{ask_id:'q3',call_id:'x4',reason:'escalation',title:'Run `make install` outside the sandbox?',detail:'Commands that leave the sandbox always ask.',request:{category:'command',argv:['make','install'],command:null,cwd:'.',sandbox:'escalated',network:false,project_id:'p1'},options:['allow_once','deny'],scope_patch:null,patched_scope_digest:null,request_digest:'sha256:r3'},{item_id:'q3'})]);
 const q3=page.locator('#agent-view [data-item="q3"]');
 assert(await q3.getByRole('button',{name:'Add to scope',exact:true}).count()===0,'Add to scope offered for an escalation ask');
 await page.evaluate(()=>{window.agentFixture.hold.agent_answer=true;});
 await q3.getByRole('button',{name:'Deny',exact:true}).click();
 await page.evaluate(()=>{const f=window.agentFixture;f.fail(f.held.pop(),'The ask is no longer open.');f.hold.agent_answer=false;});
 assert((await text(q3)).includes('The ask is no longer open.')&&!(await q3.getByRole('button',{name:'Deny',exact:true}).isDisabled()),'Failed answer not recoverable');

 // Legacy rows keep the legacy desk.
 await page.locator('[data-view=tasks]').click();
 await page.locator('[data-open-task="L1"]').click();
 assert(await page.locator('#task-detail').isVisible()&&await view.isHidden(),'Legacy task did not open the legacy desk');

 // Light/dark, 320-1280 fit for the agent and running views.
 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:900});
  for(const target of ['agent','running']){
   if(target==='agent'){await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task="t1"]').click();}else await page.locator('[data-view=running]').click();
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+target+' '+width+' '+colorScheme);fits.push(fit);
   if(width===390)await page.screenshot({path:'workspace-data/agent-'+(url.includes('/dist/')?'packaged':'source')+'-'+target+'-'+colorScheme+'-390.png',fullPage:true});
  }
 }}
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'agent rows and legacy rows, history replay, streaming deltas, tool/diff/command cards, exact Allow once/Add to scope/Deny answers, failed answer recovery, duplicates/unknown kinds/versions, literal text, /commands and @mentions by keyboard, optimistic echo, running send gate, scope chips/editor/validation/exact edit/digest approval, gap recovery, truncated output blob, cancel, several running tasks at once, light/dark 320-1280 fit',responsiveStates:fits.length};
}
