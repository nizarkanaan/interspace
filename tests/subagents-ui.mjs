/* Several subagents at once, restart and the review flow from a child, against fixture events and a fake bridge
   only (docs/superpowers/specs/multi-provider/orchestration.md, merge.md): no backend, runtime or provider. */
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async loc=>(await loc.textContent())||'';
 await page.goto(url);
 await page.evaluate(()=>{
  const project={id:'p1',name:'Fixture project',brief:'',priority:'normal',next_action:''};
  const rows=[{id:'T',mode:'agent',title:'Add input validation',status:'running',provider:'claude',model:null},
   {id:'C1',mode:'agent',title:'Researcher',status:'running',provider:'codex',model:null,parent_task_id:'T',role:'researcher'},
   {id:'C2',mode:'agent',title:'Implementer',status:'running',provider:'claude',model:null,parent_task_id:'T',role:'implementer'},
   {id:'S',mode:'agent',title:'Simple view check',status:'running',provider:'claude',model:null}];
  const scheduler={max_running:4,running:[{task_id:'T',project_id:'p1',state:'running',parent_task_id:null,role:'orchestrator',provider:'claude',tokens:{used:1200,budget:250000},lock:null},
   {task_id:'C1',project_id:'p1',state:'running',parent_task_id:'T',role:'researcher',provider:'codex',tokens:{used:300,budget:250000},lock:null},
   {task_id:'C2',project_id:'p1',state:'running',parent_task_id:'T',role:'implementer',provider:'claude',tokens:{used:300,budget:250000},lock:null}],queued:[]};
  const providers={providers:[
   {name:'claude',title:'Claude',models:['claude-sonnet-5-5','claude-opus-5-5','claude-haiku-5-5'],default_model:'claude-sonnet-5-5',capabilities:{write:true,web_search:true,approvals:true}},
   {name:'codex',title:'Codex',models:[],default_model:null,capabilities:{write:true,web_search:true,approvals:true}}],
   status:[],routing:{v:1,orchestrator:{provider:'claude',model:null},roles:{researcher:{provider:'codex',model:null},implementer:{provider:'claude',model:null},reviewer:{provider:'codex',model:null},tester:{provider:'claude',model:null},writer:{provider:'claude',model:null}}}};
  const scope={v:1,task_id:'T',version:1,projects:[{project_id:'p1',access:'write',read:['**'],write:['**'],deny:[]}],commands:{workspace:'allow',allow:[],deny:[]},network:{default:'deny',allow_hosts:[],deny_hosts:[]},apps:[],web_search:'deny',limits:{token_budget:250000,time_limit_s:3600}};
  const summary={branch:'interspace/task-c2c2c2c2',base_commit:'1111111111',head_commit:'2222222222',files:[{path:'src/parser.py',change:'modify',old_path:null,additions:2,deletions:1,binary:false}],
   patch:'diff --git a/src/parser.py b/src/parser.py\n--- a/src/parser.py\n+++ b/src/parser.py\n@@ -1,2 +1,3 @@\n def parse(x):\n-    return x\n+    if x is None: raise ValueError("<b>no</b>")\n+    return x\n',truncated:false};
  // No saved display at first, so the conversation starts Simple; the header toggle saves Detailed through display_update.
  const f=window.subFixture={requests:[],history:{},hold:{},held:[],rows,scheduler,display:undefined,
   state:()=>({version:4,projects:[project],project_id:'p1',project:'Fixture project',task_id:null,task:null,tasks:f.rows,active:null,error:'',scheduler:f.scheduler,display:f.display}),
   respond(r,result){window.interspaceReceive({id:r.id,result});},fail(r,error){window.interspaceReceive({id:r.id,error});},
   events(p){const events=(f.history[p.task_id]||[]).filter(e=>e.seq>p.after_seq);return {events,last_seq:events.length?events.at(-1).seq:p.after_seq,complete:true};}};
  window.webkit={messageHandlers:{interspace:{postMessage(r){
   f.requests.push(r);const p=r.params||{};if(f.hold[r.method]){f.held.push(r);return;}
   let result={};
   if(r.method==='state')result=f.state();
   else if(r.method==='providers_list')result=providers;
   else if(r.method==='task_events')result=f.events(p);
   else if(r.method==='scope_get')result={scope:{...scope,task_id:p.task_id},scope_digest:'sha256:aa',scope_approval:{v:1,scope_version:1,scope_digest:'sha256:aa',approved_at:'2026-11-15T09:00:00.000Z',by:'user'}};
   else if(r.method==='team_answer')result={status:'approved'};
   else if(r.method==='review_summary')result=summary;
   else if(r.method==='review_branches')result={branches:['feature/other','interspace/task-c2c2c2c2','main'],current:'feature/other'};
   else if(r.method==='review_merge')result={status:'merged',merge_commit:'abcdef1234567890',conflicts:[],detail:'Merged.'};
   else if(r.method==='display_update'){f.display=p.display;result=p.display;}
   queueMicrotask(()=>f.respond(r,result));
  }}}};
  window.interspaceReceive({type:'state',state:f.state()});
  window.interspaceProviders.load();
 });
 const ev=(task,seq,kind,data,extra={})=>({v:1,task_id:task,project_id:'p1',seq,at:'2026-11-15T10:00:00.000Z',kind,turn_id:'u1',item_id:null,data,...extra});
 const push=events=>page.evaluate(list=>{for(const event of list)window.interspaceReceive({type:'event',event});},events);
 const req=method=>page.evaluate(m=>window.subFixture.requests.filter(r=>r.method===m).map(r=>r.params),method);
 const history=(task,list)=>page.evaluate(([t,l])=>{window.subFixture.history[t]=l;},[task,list]);
 const status=(task,seq,state)=>ev(task,seq,'status',{state,detail:'',queue_position:null,reason:null},{turn_id:null});

 // Simple (the default, 2026-11-27-readable-workspace-design.md): a subagent is one line that opens in place and stays
 // open; orchestration calls are hidden unless they failed.
 await page.locator('[data-open-task="S"]').click();
 await push([status('S',1,'running'),
  ev('S',2,'tool_call',{call_id:'q1',category:'orchestrate',tool:'wait_for',title:'Wait for',input:{members:['s1']},decision:null},{item_id:'q1'}),
  ev('S',3,'tool_result',{call_id:'q1',status:'ok',output:{text:'{"members": {"s1": "running"}}',truncated:false}},{item_id:'q1'}),
  ev('S',4,'tool_call',{call_id:'q2',category:'orchestrate',tool:'start_member',title:'Start member',input:{member_id:'s9'},decision:null},{item_id:'q2'}),
  ev('S',5,'tool_result',{call_id:'q2',status:'error',error:{code:'not_found',message:'No member s9'},output:{text:'',truncated:false}},{item_id:'q2'}),
  ev('S',6,'tool_call',{call_id:'q3',category:'orchestrate',tool:'wait_for',title:'Still waiting',input:{},decision:null},{item_id:'q3'}),
  ev('S',7,'subagent_started',{team_id:'teamS',member_id:'s1',task_id:'SC1',role:'researcher',provider:'codex',model:null,access:'read',brief:'Survey the <i>parser</i> callers'},{item_id:'sub_SC1'}),
  ev('S',8,'subagent_status',{team_id:'teamS',member_id:'s1',task_id:'SC1',state:'running',tokens_used:700},{item_id:'sub_SC1'})]);
 const sv=page.locator('#agent-view #agent-stream'),line=sv.locator('.card.subagent[data-child="SC1"]');
 assert(await line.count()===1&&await line.evaluate(n=>n.classList.contains('is-line')),'Subagent not one line in Simple');
 const lineText=await text(line);
 assert(await line.locator('.provider-badge[data-provider=codex]').count()===1&&lineText.includes('Researcher')&&lineText.includes('Running'),'Subagent line misses badge, role or state: '+lineText);
 assert(!lineText.includes('Survey the')&&await line.getByRole('button',{name:'Open Researcher subagent'}).count()===0,'Subagent line shows its full card: '+lineText);
 const more=line.locator('button.sub-details');
 assert((await text(more))==='Details ▸'&&await more.getAttribute('aria-expanded')==='false','Subagent line has no Details');
 assert(await more.getAttribute('aria-label')==='Researcher details'&&await more.locator('span[aria-hidden=true]').textContent()==='▸','Subagent Details is not named for its role: '+await more.getAttribute('aria-label'));
 const svText=await text(sv);
 assert(!svText.includes('Wait for')&&!svText.includes('Still waiting'),'Orchestration call shown in Simple: '+svText);
 assert(svText.includes('Start member')&&svText.includes('No member s9'),'Failed orchestration call hidden in Simple: '+svText);
 await page.setViewportSize({width:320,height:900});
 const narrow=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
 assert(narrow.scroll<=narrow.width&&await page.locator('#agent-detail-toggle').isVisible(),'Simple line overflows or toggle hidden at 320');
 await page.setViewportSize({width:1280,height:1000});
 await more.click();
 assert(!(await line.evaluate(n=>n.classList.contains('is-line')))&&(await text(line)).includes('Survey the <i>parser</i> callers')&&await line.locator('i').count()===0,'Details did not open the full card: '+await text(line));
 assert(await line.getByRole('button',{name:'Open Researcher subagent',exact:true}).isVisible(),'Open missing after Details');
 await push([ev('S',9,'subagent_status',{team_id:'teamS',member_id:'s1',task_id:'SC1',state:'running',tokens_used:900},{item_id:'sub_SC1'})]);
 assert((await text(line)).includes('900 tokens')&&(await text(line)).includes('Survey the'),'Opened subagent card folded again');
 // Hide details folds it back to its line, focus returns to Details, and it stays folded as events arrive.
 const hide=line.locator('button.sub-details.is-open');
 assert((await text(hide))==='Hide details ▾'&&await hide.getAttribute('aria-expanded')==='true'&&await hide.getAttribute('aria-label')==='Hide Researcher details','Opened subagent card has no Hide details');
 await hide.click();
 assert(await line.evaluate(n=>n.classList.contains('is-line'))&&!(await text(line)).includes('Survey the'),'Hide details did not fold the subagent card: '+await text(line));
 assert(await page.evaluate(()=>document.activeElement?.matches('.card.subagent[data-child="SC1"] button.sub-details:not(.is-open)')),'Focus not back on Details');
 await push([ev('S',10,'subagent_status',{team_id:'teamS',member_id:'s1',task_id:'SC1',state:'running',tokens_used:950},{item_id:'sub_SC1'})]);
 assert(await line.evaluate(n=>n.classList.contains('is-line')),'Folded subagent card opened again on an event');
 // Detailed through the header toggle: the orchestration calls come back.
 await page.locator('#agent-detail-toggle').getByRole('button',{name:'Detailed',exact:true}).click();
 await page.waitForFunction(()=>window.subFixture.requests.some(r=>r.method==='display_update'));
 assert((await req('display_update')).at(-1).display.detail==='detailed','Toggle did not save Detailed');
 await page.waitForFunction(()=>document.querySelector('#agent-view #agent-stream')?.textContent.includes('Still waiting'));
 assert((await text(sv)).includes('Wait for'),'Detailed did not restore orchestration calls');
 await page.locator('[data-view=tasks]').click();

 await page.locator('[data-open-task="T"]').click();
 // A suggestion always carries its reason; one without a reason says so; a member the user changes is marked.
 await push([status('T',1,'running'),
  ev('T',2,'team_proposed',{team_id:'team1',summary:'Research and build.',budget:{used:1200,budget:250000},members:[
   {member_id:'m1',role:'researcher',brief:'Map the parser',provider:'codex',model:null,access:'read',default:true},
   {member_id:'m2',role:'implementer',brief:'Add validation',provider:'codex',model:null,access:'write',default:false,reason:'Codex <em>knows</em> this repo'},
   {member_id:'m3',role:'reviewer',brief:'Review it',provider:'claude',model:null,access:'read',default:false}]}),
  status('T',3,'paused_team')]);
 const team=page.locator('#agent-view .card.team');
 const member=id=>team.locator('[data-member="'+id+'"]');
 assert((await text(member('m2'))).includes('Suggested: Codex <em>knows</em> this repo')&&await team.locator('em').count()===0,'Suggested reason missing or not literal: '+await text(member('m2')));
 assert((await text(member('m3'))).includes('Suggested (no reason given)'),'Suggestion without a reason not flagged: '+await text(member('m3')));
 await team.getByLabel('Researcher provider').selectOption('claude');
 assert((await text(member('m1'))).includes('Your change')&&!(await text(member('m1'))).includes('Default'),'Edited member not marked as your change: '+await text(member('m1')));
 await team.getByLabel('Researcher provider').selectOption('codex');
 assert(!(await text(member('m1'))).includes('Your change'),'Change marker kept after undoing the edit');
 await team.getByRole('button',{name:'Approve team',exact:true}).click();
 assert(JSON.stringify(await req('team_answer'))===JSON.stringify([{task_id:'T',team_id:'team1',decision:'approve'}]),'Unedited approve not exact');

 // Two children stream at once: each card shows state, tokens and the latest activity line without expanding.
 await push([ev('T',4,'team_answered',{team_id:'team1',decision:'approve',members:[],note:null}),
  ev('T',5,'subagent_started',{team_id:'team1',member_id:'m1',task_id:'C1',role:'researcher',provider:'codex',model:null,access:'read'},{item_id:'sub_C1'}),
  ev('T',6,'subagent_started',{team_id:'team1',member_id:'m2',task_id:'C2',role:'implementer',provider:'codex',model:null,access:'write'},{item_id:'sub_C2'}),
  status('T',7,'running')]);
 await push([status('C1',1,'running'),status('C2',1,'running'),
  ev('C1',2,'message_delta',{role:'assistant',text_delta:'Reading the parser'},{item_id:'a1'}),
  ev('C2',2,'tool_call',{call_id:'b1',category:'command',tool:'shell',title:'Run the <i>tests</i>',input:{argv:['python3','-m','unittest']},decision:null},{item_id:'b1'}),
  ev('T',8,'subagent_status',{team_id:'team1',member_id:'m1',task_id:'C1',state:'running',tokens_used:1500},{item_id:'sub_C1'}),
  ev('C1',3,'message_delta',{role:'assistant',text_delta:' and its callers'},{item_id:'a1'}),
  ev('T',9,'subagent_status',{team_id:'team1',member_id:'m2',task_id:'C2',state:'running',tokens_used:2200},{item_id:'sub_C2'})]);
 const c1=page.locator('#agent-view .card.subagent[data-child="C1"]'),c2=page.locator('#agent-view .card.subagent[data-child="C2"]');
 assert(await page.locator('#agent-view .card.subagent').count()===2,'Subagent cards: '+await page.locator('#agent-view .card.subagent').count());
 let t1=await text(c1),t2=await text(c2);
 assert(t1.includes('Running')&&t1.includes('1,500 tokens')&&(await text(c1.locator('.sub-activity'))).includes('Reading the parser and its callers'),'C1 live progress: '+t1);
 assert(t2.includes('2,200 tokens')&&(await text(c2.locator('.sub-activity'))).includes('Run the <i>tests</i>')&&await c2.locator('i').count()===0,'C2 live progress: '+t2);
 assert(await c1.locator('.stream.nested').count()===0&&(await req('task_events')).filter(p=>p.task_id!=='S').every(p=>p.task_id==='T'),'Progress needed expanding or a history load');
 // Duplicates: a repeated start, a replayed seq and an older seq never add a card or a line.
 await push([ev('T',10,'subagent_started',{team_id:'team1',member_id:'m1',task_id:'C1',role:'researcher',provider:'codex',model:null,access:'read'},{item_id:'sub_C1'}),
  ev('T',9,'subagent_status',{team_id:'team1',member_id:'m2',task_id:'C2',state:'queued',tokens_used:0}),ev('C2',2,'message',{role:'assistant',text:'Replayed',final:true})]);
 assert(await page.locator('#agent-view .card.subagent').count()===2&&!(await text(c2)).includes('Replayed')&&(await text(c2)).includes('2,200 tokens'),'Duplicate event changed the cards');

 // Expanded child streams stay ordered under interleaved events and gap recovery.
 await history('C1',[status('C1',1,'running'),ev('C1',2,'message_delta',{role:'assistant',text_delta:'Reading the parser'},{item_id:'a1'}),ev('C1',3,'message_delta',{role:'assistant',text_delta:' and its callers'},{item_id:'a1'}),
  ev('C1',4,'message',{role:'assistant',text:'Found step four',final:true},{item_id:'a4'}),ev('C1',5,'message',{role:'assistant',text:'Found step five',final:true},{item_id:'a5'}),
  ev('C1',6,'message',{role:'assistant',text:'Found step six',final:true},{item_id:'a6'}),ev('C1',7,'message',{role:'assistant',text:'Found step seven',final:true},{item_id:'a7'})]);
 await c1.getByRole('button',{name:'Show Researcher activity',exact:true}).click();
 const nested=c1.locator('.stream.nested');
 await page.waitForFunction(()=>document.querySelector('.card.subagent[data-child="C1"] .stream.nested')?.textContent.includes('Found step seven'));
 const order=(await text(nested));
 assert(order.indexOf('step four')<order.indexOf('step five')&&order.indexOf('step five')<order.indexOf('step seven'),'Child history out of order: '+order);
 await page.evaluate(()=>{window.subFixture.hold.task_events=true;});
 await history('C1',[ev('C1',8,'message',{role:'assistant',text:'Found step eight',final:true},{item_id:'a8'}),ev('C1',9,'message',{role:'assistant',text:'Found step nine',final:true},{item_id:'a9'})]);
 await push([ev('C1',10,'message',{role:'assistant',text:'Found step ten',final:true},{item_id:'a10'}),ev('C2',3,'message',{role:'assistant',text:'Implementer edits parser.py',final:true},{item_id:'b3'}),
  ev('C1',11,'tool_call',{call_id:'a11',category:'file_read',tool:'read',title:'Read tests.py',input:{path:'tests.py'},decision:null},{item_id:'a11'})]);
 assert(!(await text(nested)).includes('step ten')&&(await text(c2.locator('.sub-activity'))).includes('Implementer edits parser.py'),'Out-of-order child event shown before the gap was filled');
 await c1.getByRole('button',{name:'Hide Researcher activity',exact:true}).focus();
 await page.evaluate(()=>{const f=window.subFixture;f.hold.task_events=false;for(const r of f.held.splice(0))f.respond(r,f.events(r.params));});
 await page.waitForFunction(()=>document.querySelector('.card.subagent[data-child="C1"] .stream.nested')?.textContent.includes('Read tests.py'));
 const filled=await text(nested);
 assert(filled.indexOf('step eight')<filled.indexOf('step nine')&&filled.indexOf('step nine')<filled.indexOf('step ten')&&filled.indexOf('step ten')<filled.indexOf('Read tests.py'),'Gap not filled in order: '+filled);
 assert((await nested.locator('[data-item]').evaluateAll(n=>n.map(x=>x.dataset.item))).length===new Set(await nested.locator('[data-item]').evaluateAll(n=>n.map(x=>x.dataset.item))).size,'Duplicate child items');
 await push([ev('C2',4,'message',{role:'assistant',text:'Implementer keeps going',final:true},{item_id:'b4'})]);
 assert(await page.evaluate(()=>document.activeElement?.getAttribute('aria-label'))==='Hide Researcher activity','Focus lost when a sibling streamed');
 // A gap the backend cannot fill is noted once and later events still show.
 await push([ev('C1',14,'message',{role:'assistant',text:'After the gap',final:true},{item_id:'a14'})]);
 await page.waitForFunction(()=>document.querySelector('.card.subagent[data-child="C1"] .stream.nested')?.textContent.includes('After the gap'));
 assert((await text(nested)).includes('Some earlier events could not be loaded.'),'Unfillable gap not noted');

 // A write child finishes with a diff: Review changes → Merge by keyboard, then the merged state on its card.
 await push([status('C2',5,'completed'),ev('T',11,'subagent_finished',{team_id:'team1',member_id:'m2',task_id:'C2',state:'completed',report_excerpt:'Added validation.',diff_summary:{branch:'interspace/task-c2c2c2c2',files:[{path:'src/parser.py',change:'modify',additions:2,deletions:1}]}},{item_id:'sub_C2'})]);
 assert((await text(c2)).includes('Completed')&&(await text(c2)).includes('1 file changed · +2 −1'),'Finished child card: '+await text(c2));
 await c2.getByRole('button',{name:'Review Implementer changes',exact:true}).focus();
 await page.keyboard.press('Enter');
 await page.waitForFunction(()=>!document.querySelector('#review-view').hidden&&document.querySelector('#review-merge'));
 assert(JSON.stringify(await req('review_branches'))==='[{"project_id":"p1"}]','Review opened without the project: '+JSON.stringify(await req('review_branches')));
 assert((await text(page.locator('#review-view'))).includes('raise ValueError("<b>no</b>")')&&await page.locator('#review-view b').count()===0,'Diff not literal');
 assert(await page.locator('#review-into').inputValue()==='feature/other','Into does not default to the current branch');
 await page.locator('#review-into').focus();
 await page.keyboard.press('ArrowDown');
 if(await page.locator('#review-into').inputValue()!=='main')await page.locator('#review-into').selectOption('main');
 for(let i=0;i<8&&await page.evaluate(()=>document.activeElement?.id)!=='review-merge';i++)await page.keyboard.press('Tab');
 assert(await page.evaluate(()=>document.activeElement?.id)==='review-merge','Merge not reachable by Tab');
 await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.querySelector('#review-view .review-result')?.textContent.includes('Merged into main'));
 assert(JSON.stringify(await req('review_merge'))===JSON.stringify([{task_id:'C2',into:'main',expected_head:'2222222222'}]),'review_merge params: '+JSON.stringify(await req('review_merge')));
 const back=page.getByRole('button',{name:'Back to the task',exact:true});
 await back.focus();await page.keyboard.press('Enter');
 await page.waitForFunction(()=>!document.querySelector('#agent-view').hidden);
 assert((await text(page.locator('#heading'))).includes('Add input validation'),'Back did not return to the parent task');
 assert((await text(c2)).includes('Merged into main · abcdef12'),'Merged state missing on the child card: '+await text(c2));
 assert(await page.evaluate(()=>document.activeElement?.getAttribute('aria-label'))==='Review Implementer changes','Focus not returned to Review changes');

 // Back from a subagent names its parent and opens it, with focus on the Open button that led there. A click from a
 // script never focuses the button (as a mouse click in WKWebView does not), and focus sat on another card's button.
 const backButton=page.locator('#agent-back'),focusedId=()=>page.evaluate(()=>document.activeElement?.id||document.activeElement?.tagName);
 const backNames=t=>page.waitForFunction(t=>document.querySelector('#agent-back').textContent===t,t);
 await page.evaluate(()=>document.getElementById('sub-open-C1').click());
 await backNames('← Add input validation');
 await backButton.click();
 assert((await text(page.locator('#heading'))).includes('Add input validation'),'Back did not open the parent: '+await text(page.locator('#heading')));
 assert(await focusedId()==='sub-open-C1','Focus not on the child Open button after Back: '+await focusedId());
 // The same round trip by keyboard.
 await page.locator('#sub-open-C1').focus();await page.keyboard.press('Enter');
 await backNames('← Add input validation');
 await backButton.focus();await page.keyboard.press('Enter');
 await backNames('← Tasks');
 assert(await focusedId()==='sub-open-C1','Focus not on the child Open button after Back by keyboard: '+await focusedId());
 // A child opened from the Running view also goes back to its parent.
 await page.locator('[data-view=running]').click();
 await page.locator('#running-view .child-row[data-child="C1"]').getByRole('button',{name:'Open Researcher subagent',exact:true}).click();
 await backNames('← Add input validation');
 await backButton.click();
 assert((await text(page.locator('#heading'))).includes('Add input validation')&&await page.locator('#agent-view').isVisible(),'Back from a Running view child did not open the parent');

 // Restart: the app quit with a team proposal open and children mid-turn. Everything shows interrupted, nothing resumes.
 await page.evaluate(()=>{const f=window.subFixture;
  f.rows.push({id:'R',mode:'agent',title:'Restarted task',status:'interrupted',provider:'claude',model:null},
   {id:'RC',mode:'agent',title:'Tester',status:'interrupted',provider:'claude',model:null,parent_task_id:'R',role:'tester'});
  f.scheduler={max_running:4,running:[],queued:[]};window.interspaceReceive({type:'state',state:f.state()});});
 await history('R',[status('R',1,'running'),
  ev('R',2,'team_proposed',{team_id:'tA',summary:'Test it',budget:{used:10,budget:250000},members:[{member_id:'t1',role:'tester',brief:'Run tests',provider:'claude',model:null,access:'write',default:true}]}),
  ev('R',3,'team_answered',{team_id:'tA',decision:'approve',members:[],note:null}),
  ev('R',4,'subagent_started',{team_id:'tA',member_id:'t1',task_id:'RC',role:'tester',provider:'claude',model:null,access:'write'}),
  ev('R',5,'subagent_status',{team_id:'tA',member_id:'t1',task_id:'RC',state:'running',tokens_used:40}),
  ev('R',6,'team_proposed',{team_id:'tB',summary:'Second team',budget:{used:50,budget:250000},members:[{member_id:'w1',role:'writer',brief:'Write docs',provider:'claude',model:null,access:'read',default:true}]}),
  status('R',7,'paused_team'),
  ev('R',8,'status',{state:'interrupted',detail:'The app closed while this task was working.',queue_position:null,reason:null},{turn_id:null})]);
 await page.locator('[data-view=tasks]').click();
 assert((await text(page.locator('[data-open-task="R"]'))).includes('interrupted')&&await page.locator('[data-open-task="RC"]').count()===0,'Desk row for the interrupted task wrong');
 await page.locator('[data-open-task="R"]').click();
 await page.waitForFunction(()=>document.querySelectorAll('#agent-view .card.team').length===2);
 const view=page.locator('#agent-view');
 assert((await text(view.locator('.agent-status'))).includes('Interrupted')&&(await text(view.locator('.interrupted-note'))).includes('Nothing resumed'),'Interrupted parent not explained: '+await text(page.locator('#agent-head')));
 const rc=view.locator('.card.subagent[data-child="RC"]');
 assert((await text(rc)).includes('Interrupted')&&!(await text(rc)).includes('Running'),'Interrupted child still shown running: '+await text(rc));
 const second=view.locator('.card.team').nth(1);
 assert((await text(second)).includes('no longer open')&&await second.getByRole('button',{name:'Approve team'}).count()===0,'Interrupted proposal answerable');
 assert(await view.getByRole('button',{name:/resume|retry|continue/i}).count()===0,'A resume button is offered');
 // A new turn on the interrupted task never reopens the old proposal.
 await push([status('R',9,'starting'),status('R',10,'running')]);
 assert(await second.getByRole('button',{name:'Approve team'}).count()===0&&(await text(second)).includes('no longer open'),'Old proposal reopened by a new turn');
 // The interrupted child: its own view says so; Running view shows it under its parent without a resume action.
 await rc.getByRole('button',{name:'Open Tester subagent',exact:true}).click();
 assert((await text(page.locator('#agent-head'))).includes('Interrupted')&&await page.locator('#agent-view').getByRole('button',{name:/resume|retry|continue/i}).count()===0,'Interrupted child view wrong');
 await page.locator('[data-view=running]').click();
 assert((await text(page.locator('#running-view .child-row[data-child="RC"]'))).includes('Interrupted'),'Running view child state wrong');

 // Light/dark, 320-1280 fit for the parent with live children and the review view.
 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:900});
  for(const target of ['agent','review','restart']){
   await page.locator('[data-view=tasks]').click();
   if(target==='restart')await page.locator('[data-open-task="R"]').click();
   else{await page.locator('[data-open-task="T"]').click();if(target==='review'){await page.locator('.card.subagent[data-child="C2"]').getByRole('button',{name:'Review Implementer changes',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#review-merge'));}}
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+target+' '+width+' '+colorScheme);fits.push(fit);
   if(width===390||width===1280&&colorScheme==='light')await page.screenshot({path:'workspace-data/subagents-'+target+'-'+colorScheme+'-'+width+'.png',fullPage:true});
  }
 }}
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'Simple by default: subagent as one line (badge, role, state, Details) that opens to the full card and stays open, Hide details folds it back with focus on Details, ok and waiting orchestration calls hidden, failed one shown, no overflow at 320; Simple | Detailed switch saves Detailed; suggested reason and missing-reason flag, your-change marker, unedited approve exact, two children streaming with state/tokens/latest activity without expanding, literal activity text, duplicate start/seq ignored, expanded child stream ordered under interleaving and gap recovery, unfillable gap noted, focus kept while a sibling streams, Review changes → Merge by keyboard with project and reviewed head, Back returns focus, merged state on the child card, a child\'s Back names its parent and returns to it with focus on its Open button (script click, keyboard, Running view), restart: interrupted parent/child/proposal shown, no resume button, new turn keeps the old proposal closed, Running view child state, light/dark 320-1280 fit',responsiveStates:fits.length};
}
