/* Wave 3C review fixes, against fixture events and a fake bridge only: no backend, runtime or provider.
   Each check names the failure it guards against. */
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async loc=>(await loc.textContent())||'';
 await page.goto(url);
 await page.evaluate(()=>{
  const project={id:'p1',name:'Fixture project',brief:'',priority:'normal',next_action:''};
  const rows=[{id:'T',mode:'agent',title:'Add input validation',status:'running',provider:'claude',model:null},
   {id:'C1',mode:'agent',title:'Researcher',status:'running',provider:'codex',model:null,parent_task_id:'T',role:'researcher'}];
  const scheduler={max_running:4,running:[{task_id:'T',project_id:'p1',state:'running',parent_task_id:null,role:'orchestrator',provider:'claude',tokens:{used:1200,budget:250000},lock:null},
   {task_id:'C1',project_id:'p1',state:'running',parent_task_id:'T',role:'researcher',provider:'codex',tokens:{used:300,budget:250000},lock:null}],queued:[]};
  const providers={providers:[
   {name:'claude',title:'Claude',models:[],default_model:null,capabilities:{write:true,web_search:true}},
   {name:'codex',title:'Codex',models:[],default_model:null,capabilities:{write:true,web_search:true}}],
   status:[{provider:'codex',state:'signed_out',account:null,detail:''},{provider:'claude',state:'signed_out',account:null,detail:''}],
   routing:{v:1,orchestrator:{provider:'claude',model:null},roles:{researcher:{provider:'codex',model:null},implementer:{provider:'claude',model:null},reviewer:{provider:'codex',model:null},tester:{provider:'claude',model:null},writer:{provider:'claude',model:null}}}};
  const scope={v:1,task_id:'T',version:1,projects:[{project_id:'p1',access:'write',read:['**'],write:['**'],deny:[]}],commands:{workspace:'allow',allow:[],deny:[]},network:{default:'deny',allow_hosts:[],deny_hosts:[]},apps:[],web_search:'deny',limits:{token_budget:250000,time_limit_s:3600}};
  const f=window.hardFixture={requests:[],history:{},signIn:{},rows,scheduler,
   // Detailed: these checks need the full team and subagent cards, which the default Simple conversation folds.
   state:()=>({version:4,projects:[project],project_id:'p1',project:'Fixture project',task_id:null,task:null,tasks:f.rows,active:null,error:'',scheduler:f.scheduler,display:{detail:'detailed'}}),
   events(p){const events=(f.history[p.task_id]||[]).filter(e=>e.seq>p.after_seq);return {events,last_seq:events.length?events.at(-1).seq:p.after_seq,complete:true};}};
  window.webkit={messageHandlers:{interspace:{postMessage(r){
   f.requests.push(r);const p=r.params||{};let result={};
   if(r.method==='state')result=f.state();
   else if(r.method==='providers_list')result=providers;
   else if(r.method==='provider_sign_in')result=f.signIn[p.provider];
   else if(r.method==='task_events')result=f.events(p);
   else if(r.method==='scope_get')result={scope:{...scope,task_id:p.task_id},scope_digest:'sha256:aa',scope_approval:{v:1,scope_version:1,scope_digest:'sha256:aa',approved_at:'2026-11-15T09:00:00.000Z',by:'user'}};
   else if(r.method==='team_answer')result={status:'approved'};
   queueMicrotask(()=>window.interspaceReceive({id:r.id,result}));
  }}}};
  window.interspaceReceive({type:'state',state:f.state()});
  window.interspaceProviders.load();
 });
 const ev=(task,seq,kind,data,extra={})=>({v:1,task_id:task,project_id:'p1',seq,at:'2026-11-15T10:00:00.000Z',kind,turn_id:'u1',item_id:null,data,...extra});
 const push=events=>page.evaluate(list=>{for(const event of list)window.interspaceReceive({type:'event',event});},events);
 const req=method=>page.evaluate(m=>window.hardFixture.requests.filter(r=>r.method===m).map(r=>r.params),method);
 const status=(task,seq,state)=>ev(task,seq,'status',{state,detail:'',queue_position:null,reason:null},{turn_id:null});
 const dupIds=()=>page.evaluate(()=>{const seen=new Map();for(const e of document.querySelectorAll('[id]'))seen.set(e.id,(seen.get(e.id)||0)+1);return [...seen].filter(([,n])=>n>1).map(([id])=>id);});

 // 1. A team proposal shown in both the task view and the Running view: one editable form, no duplicate ids,
 //    so a label never points at a hidden copy and an edit in one place is the edit that is approved.
 await page.locator('[data-open-task="T"]').click();
 await push([status('T',1,'running'),
  ev('T',2,'team_proposed',{team_id:'team1',summary:'Research it.',budget:{used:1200,budget:250000},members:[
   {member_id:'m1',role:'researcher',brief:'Map the parser',provider:'codex',model:null,access:'read',default:true}]}),
  status('T',3,'paused_team')]);
 await page.locator('[data-view=running]').click();
 const column=page.locator('#running-view .task-column[data-task="T"]');
 assert(await column.locator('.card.team').count()===1,'Running view lost the team card');
 assert(await column.locator('.card.team textarea, .card.team select, .card.team input').count()===0,'Running view duplicates the team editor');
 assert(await column.getByRole('button',{name:'Review the proposed team',exact:true}).count()===1,'Running view has no way to the team');
 let dups=await dupIds();assert(!dups.length,'Duplicate element ids: '+dups.join(', '));
 await column.getByRole('button',{name:'Review the proposed team',exact:true}).click();
 assert(await page.locator('#agent-view').isVisible()&&await page.locator('#agent-view .card.team textarea').count()===1,'Review the proposed team did not open the task');

 // 2. An expanded child stream stays in the task view after visiting Running: it is never moved into a compact card.
 await page.locator('#agent-view .card.team').getByRole('button',{name:'Approve team',exact:true}).click();
 await page.evaluate(()=>{window.hardFixture.history.C1=[{v:1,task_id:'C1',project_id:'p1',seq:1,at:'2026-11-15T10:00:00.000Z',kind:'message',turn_id:'u1',item_id:'a1',data:{role:'assistant',text:'Found the parser',final:true}}];});
 await push([ev('T',4,'team_answered',{team_id:'team1',decision:'approve',members:[],note:null}),
  ev('T',5,'subagent_started',{team_id:'team1',member_id:'m1',task_id:'C1',role:'researcher',provider:'codex',model:null,access:'read'},{item_id:'sub_C1'}),status('T',6,'running')]);
 const card=page.locator('#agent-view .card.subagent[data-child="C1"]');
 await card.getByRole('button',{name:'Show Researcher activity',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-view .card.subagent[data-child="C1"] .stream.nested')?.textContent.includes('Found the parser'));
 await page.locator('[data-view=running]').click();
 dups=await dupIds();assert(!dups.length,'Duplicate element ids with an expanded child: '+dups.join(', '));
 await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task="T"]').click();
 assert((await text(card)).includes('Found the parser'),'Expanded child activity vanished after visiting Running: '+await text(card));

 // 3. Sign-in: only an https verification address is shown as an address to open.
 await page.evaluate(()=>{const f=window.hardFixture;f.signIn.codex={provider:'codex',kind:'device',url:'javascript:alert(1)',code:'ABCD-1234',detail:''};
  f.signIn.claude={provider:'claude',kind:'device',url:'https://auth.example.invalid/device',code:'WXYZ-9876',detail:''};});
 await page.locator('[data-view=settings]').click();
 await page.getByRole('button',{name:'Sign in to Codex',exact:true}).click();
 const codex=page.locator('.provider-item[data-provider=codex]');
 await page.waitForFunction(()=>document.querySelector('.provider-item[data-provider=codex] .sign-in-steps'));
 const shown=await text(codex);
 assert(!shown.includes('javascript:')&&!shown.includes('ABCD-1234')&&!shown.includes('Open this address'),'Non-https sign-in address offered: '+shown);
 assert(shown.includes('not a secure https address'),'Refused sign-in address not explained: '+shown);
 await page.getByRole('button',{name:'Sign in to Claude',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.provider-item[data-provider=claude] .sign-in-steps'));
 const ok=await text(page.locator('.provider-item[data-provider=claude]'));
 assert(ok.includes('https://auth.example.invalid/device')&&ok.includes('WXYZ-9876'),'https sign-in address not shown: '+ok);

 // 4. Defence in depth: the page policy runs only the app's own script files, never an inline script, so a future
 //    markup slip in model text could not reach the bridge.
 const ran=await page.evaluate(async()=>{const s=document.createElement('script');s.textContent='window.inlineRan=1';document.body.append(s);
  const h=document.createElement('div');h.setAttribute('onclick','window.attrRan=1');document.body.append(h);h.click();await new Promise(r=>setTimeout(r,50));s.remove();h.remove();return !!(window.inlineRan||window.attrRan);});
 assert(!ran,'Inline script ran: the content security policy allows inline scripts');
 const policy=await page.evaluate(()=>document.querySelector('meta[http-equiv=Content-Security-Policy]')?.content||'');
 assert(/script-src 'self'(;|$)/.test(policy)&&policy.includes("default-src 'none'")&&policy.includes("connect-src 'none'"),'Unexpected policy: '+policy);

 assert(!errors.length,'Page errors: '+errors.join('; '));
 return {checks:'one editable team form (Running view links to it, no duplicate ids), expanded child stream kept after visiting Running, only https sign-in addresses shown, no inline script execution'};
}
