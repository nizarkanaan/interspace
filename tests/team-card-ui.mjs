/* Team proposals, subagent cards and the grouped Running view against fixture events and a fake bridge only
   (docs/superpowers/specs/multi-provider/orchestration.md): no backend, runtime or provider. */
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async loc=>(await loc.textContent())||'';
 await page.goto(url);
 await page.evaluate(()=>{
  const project={id:'p1',name:'Fixture project',brief:'',priority:'normal',next_action:''};
  const rows=[{id:'T',mode:'agent',title:'Add input validation',status:'running',provider:'claude',model:null},
   {id:'C1',mode:'agent',title:'Researcher',status:'running',provider:'codex',model:null,parent_task_id:'T',role:'researcher'},
   {id:'U',mode:'agent',title:'Unrelated task',status:'idle',provider:'codex',model:'gpt-fixture'}];
  const scheduler={max_running:4,running:[{task_id:'T',project_id:'p1',state:'running',parent_task_id:null,role:'orchestrator',provider:'claude',tokens:{used:1200,budget:250000},lock:null},
   {task_id:'C1',project_id:'p1',state:'running',parent_task_id:'T',role:'researcher',provider:'codex',tokens:{used:300,budget:250000},lock:null}],
   queued:[{task_id:'C2',project_id:'p1',state:'queued',position:1,parent_task_id:'T',role:'implementer',provider:'claude'}]};
  // No saved display at first, so the conversation starts Simple; the header toggle saves Detailed through display_update.
  const state=()=>({version:4,projects:[project],project_id:'p1',project:'Fixture project',task_id:null,task:null,tasks:rows,active:null,error:'',scheduler,display:window.teamFixture.display});
  const providers={providers:[
   {name:'claude',title:'Claude',models:['claude-sonnet-5-5','claude-opus-5-5','claude-haiku-5-5'],default_model:'claude-sonnet-5-5',capabilities:{write:true,web_search:true,approvals:true}},
   {name:'codex',title:'Codex',models:[],default_model:null,capabilities:{write:true,web_search:true,approvals:true}},
   {name:'gemini',title:'Gemini',models:[],default_model:null,capabilities:{write:false,web_search:true,approvals:false}}],
   status:[],routing:{v:1,orchestrator:{provider:'claude',model:null},roles:{researcher:{provider:'codex',model:null},implementer:{provider:'claude',model:null},reviewer:{provider:'codex',model:null},tester:{provider:'claude',model:null},writer:{provider:'claude',model:null}}}};
  const scope={v:1,task_id:'T',version:1,projects:[{project_id:'p1',access:'write',read:['**'],write:['**'],deny:[]}],commands:{workspace:'allow',allow:[],deny:[]},network:{default:'deny',allow_hosts:[],deny_hosts:[]},apps:[],web_search:'deny',limits:{token_budget:250000,time_limit_s:3600}};
  const f=window.teamFixture={requests:[],history:{},hold:{},held:[],reviewOpened:[],display:undefined,
   respond(r,result){window.interspaceReceive({id:r.id,result});},fail(r,error){window.interspaceReceive({id:r.id,error});}};
  window.interspaceReview={open(id){f.reviewOpened.push(id);}};
  window.webkit={messageHandlers:{interspace:{postMessage(r){
   f.requests.push(r);const p=r.params||{};if(f.hold[r.method]){f.held.push(r);return;}
   let result={};
   if(r.method==='state')result=state();
   else if(r.method==='providers_list')result=providers;
   else if(r.method==='provider_models'){const eff=['low','medium','high','xhigh','max'],m={claude:['claude-sonnet-5-5','claude-opus-5-5','claude-haiku-5-5'],codex:['codex-fixture-1','codex-fixture-2']}[p.provider]||[];result={provider:p.provider,models:m.map((id,i)=>({id,is_default:i===0,default_effort:'low',efforts:eff})),error:m.length?'':'Models are not listed for this provider.'};}
   else if(r.method==='task_events'){const events=(f.history[p.task_id]||[]).filter(e=>e.seq>p.after_seq);result={events,last_seq:events.length?events.at(-1).seq:p.after_seq,complete:true};}
   else if(r.method==='scope_get')result={scope:{...scope,task_id:p.task_id},scope_digest:'sha256:aa',scope_approval:{v:1,scope_version:1,scope_digest:'sha256:aa',approved_at:'2026-11-15T09:00:00.000Z',by:'user'}};
   else if(r.method==='team_answer')result={status:p.decision==='approve'?'approved':'declined'};
   else if(r.method==='display_update'){f.display=p.display;result=p.display;}
   queueMicrotask(()=>f.respond(r,result));
  }}}};
  window.interspaceReceive({type:'state',state:state()});
  window.interspaceProviders.load();
 });
 const ev=(task,seq,kind,data,extra={})=>({v:1,task_id:task,project_id:'p1',seq,at:'2026-11-15T10:00:00.000Z',kind,turn_id:'u1',item_id:null,data,...extra});
 const push=events=>page.evaluate(list=>{for(const event of list)window.interspaceReceive({type:'event',event});},events);
 const req=method=>page.evaluate(m=>window.teamFixture.requests.filter(r=>r.method===m).map(r=>r.params),method);
 const stream=page.locator('#agent-view #agent-stream');

 // Desk: subagents are not desk rows; the parent row names its provider with a badge.
 const desk=await text(page.locator('#desk-tasks'));
 assert(!desk.includes('Researcher')&&(await page.locator('[data-open-task="C1"]').count())===0,'Child task shown as a desk row: '+desk);
 assert((await text(page.locator('#task-count')))==='2 tasks','Child counted on the desk');

 // Simple (the default, 2026-11-27-readable-workspace-design.md): a proposal is a short card that approves exactly as
 // the Detailed one does; Edit team opens today's editors; the answered team and orchestration calls fold away.
 await page.locator('[data-open-task="U"]').click();
 const toggle=page.locator('#agent-detail-toggle'),uStream=page.locator('#agent-view #agent-stream');
 const simpleBtn=toggle.getByRole('button',{name:'Simple',exact:true}),detailedBtn=toggle.getByRole('button',{name:'Detailed',exact:true});
 assert(await toggle.isVisible()&&await toggle.getAttribute('role')==='group'&&await toggle.getAttribute('aria-label')==='Conversation view'&&await simpleBtn.getAttribute('aria-pressed')==='true'&&await detailedBtn.getAttribute('aria-pressed')==='false','Header switch does not show Simple as the current view ('+await toggle.count()+' found)');
 const sMembers=[{member_id:'s1',role:'researcher',brief:'Read the docs folder',provider:'codex',model:null,access:'read',default:true},
  {member_id:'s2',role:'implementer',brief:'Fix the typo',provider:'claude',model:null,access:'write',default:true}];
 const sTeam=id=>({team_id:id,summary:'Check the docs <b>first</b>.',budget:{used:10,budget:250000},members:sMembers});
 const sRunning=seq=>ev('U',seq,'status',{state:'running',detail:'',queue_position:null,reason:null},{turn_id:null});
 const sPaused=seq=>ev('U',seq,'status',{state:'paused_team',detail:'',queue_position:null,reason:null},{turn_id:null});
 await push([sRunning(1),
  ev('U',2,'tool_call',{call_id:'u2',category:'orchestrate',tool:'propose_team',title:'propose_team',input:{},decision:null},{item_id:'u2'}),
  ev('U',3,'tool_result',{call_id:'u2',status:'ok',output:{text:'{"members": []}',truncated:false}},{item_id:'u2'}),
  ev('U',4,'team_proposed',sTeam('teamS1')),sPaused(5)]);
 const sCard=uStream.locator('.card.team');
 assert(await sCard.count()===1&&await sCard.evaluate(n=>n.classList.contains('is-simple')),'Simple team card missing');
 const sText=await text(sCard);
 for(const part of ['Proposed team','Check the docs <b>first</b>.','Codex researcher · reads','Claude implementer · writes'])assert(sText.includes(part),'Simple team card misses '+part+': '+sText);
 assert(await sCard.locator('li').count()===2&&await sCard.locator('b').count()===0,'One line per member, literal summary');
 assert(!sText.includes('Read the docs folder')&&await sCard.locator('textarea,select,input').count()===0,'Member editors shown in Simple: '+sText);
 assert(await sCard.getByRole('button',{name:'Approve team',exact:true}).isVisible()&&await sCard.getByRole('button',{name:'Decline',exact:true}).isVisible(),'Approve or Decline missing in Simple');
 assert(!(await text(uStream)).includes('Orchestration'),'Orchestration call shown in Simple');
 await sCard.getByRole('button',{name:'Approve team',exact:true}).click();
 const simpleAnswer=(await req('team_answer')).at(-1);
 assert(JSON.stringify(simpleAnswer)===JSON.stringify({task_id:'U',team_id:'teamS1',decision:'approve'}),'Simple approve not exact: '+JSON.stringify(simpleAnswer));
 assert((await text(sCard)).includes('Approved. Waiting for the Orchestrator.')&&await sCard.getByRole('button',{name:'Approve team'}).count()===0,'Simple card still answerable after approval');
 await push([ev('U',6,'team_answered',{team_id:'teamS1',decision:'approve',members:[],note:null}),sRunning(7)]);
 const sLine=uStream.locator('.card.team').first();
 assert(await sLine.evaluate(n=>n.classList.contains('is-line'))&&(await text(sLine)).startsWith('Team approved · Codex researcher, Claude implementer'),'Answered team not one line: '+await text(sLine));
 const teamDetails=sLine.locator('button.team-details');
 assert((await text(teamDetails))==='Details ▸'&&await teamDetails.getAttribute('aria-expanded')==='false','Answered line has no Details');
 assert(await teamDetails.getAttribute('aria-label')==='Team details'&&await teamDetails.locator('span[aria-hidden=true]').textContent()==='▸','Answered line Details is not named for the team: '+await teamDetails.getAttribute('aria-label'));
 // Edit team reveals today's member editors in the same card; the untouched proposal still approves the same way.
 await push([ev('U',8,'team_proposed',sTeam('teamS2')),sPaused(9)]);
 const sCard2=uStream.locator('.card.team').nth(1),edit=sCard2.locator('button.team-edit');
 assert(await sCard2.evaluate(n=>n.classList.contains('is-simple'))&&(await text(edit))==='Edit team'&&await edit.getAttribute('aria-expanded')==='false','Edit team missing');
 await edit.click();
 assert(await sCard2.getByLabel('Researcher brief').inputValue()==='Read the docs folder'&&await sCard2.getByLabel('Implementer provider').isVisible()&&await sCard2.getByRole('button',{name:'Remove Researcher',exact:true}).isVisible(),'Edit team did not show the member editors');
 assert(await sCard2.getByRole('button',{name:'Approve team',exact:true}).isVisible(),'Approve gone after Edit team');
 // Hide details folds the untouched editors back to the short card, and focus returns to Edit team.
 const editHide=sCard2.locator('button.team-details.is-open');
 assert((await text(editHide))==='Hide details ▾'&&await editHide.getAttribute('aria-label')==='Hide Proposed team details'&&await editHide.getAttribute('aria-expanded')==='true','Edit team has no Hide details');
 await editHide.click();
 assert(await sCard2.locator('textarea,select,input').count()===0&&await sCard2.locator('.team-lines').count()===1,'Hide details did not fold the editors: '+await text(sCard2));
 assert(await page.evaluate(()=>document.activeElement?.matches('.card.team button.team-edit')),'Focus not back on Edit team');
 await edit.click();
 // Details opens today's answered card in place, and it stays open as events arrive.
 await teamDetails.click();
 assert((await text(sLine)).includes('You approved this team.')&&!(await sLine.evaluate(n=>n.classList.contains('is-line'))),'Details did not open the answered card');
 await push([ev('U',10,'message',{role:'assistant',text:'Waiting for the team.',final:true},{item_id:'u10'})]);
 assert((await text(sLine)).includes('You approved this team.'),'Opened answered card folded again');
 // Hide details folds the answered card back to its line, and focus returns to Details.
 const teamHide=sLine.locator('button.team-details.is-open');
 assert((await text(teamHide))==='Hide details ▾'&&await teamHide.getAttribute('aria-label')==='Hide Team details'&&await teamHide.getAttribute('aria-expanded')==='true','Opened team card has no Hide details');
 await teamHide.click();
 assert(await sLine.evaluate(n=>n.classList.contains('is-line'))&&!(await text(sLine)).includes('You approved this team.'),'Hide details did not fold the answered team');
 assert(await page.evaluate(()=>document.activeElement?.matches('.card.team button.team-details:not(.is-open)')),'Focus not back on team Details');
 // Clicking the view already shown changes nothing; Detailed switches every card to full (saved with display_update).
 await simpleBtn.click();
 // The header toggle switches to Detailed (saved with display_update): every card is in full again.
 await detailedBtn.click();
 await page.waitForFunction(()=>window.teamFixture.requests.some(r=>r.method==='display_update'));
 const updates=await req('display_update');
 assert(updates.length===1&&updates[0].display.detail==='detailed','Toggle did not save Detailed: '+JSON.stringify(updates));
 await page.waitForFunction(()=>document.querySelector('#agent-detail-toggle [data-detail=detailed]')?.getAttribute('aria-pressed')==='true');
 assert(await simpleBtn.getAttribute('aria-pressed')==='false','Simple still marked as the current view in Detailed');
 assert(await uStream.locator('button.is-open').count()===0,'Hide details shown in Detailed');
 assert((await text(uStream)).includes('Orchestration')&&await uStream.locator('.card.team.is-line,.card.team.is-simple').count()===0,'Detailed did not restore the full cards');
 await sCard2.getByRole('button',{name:'Approve team',exact:true}).click();
 const detailedAnswer=(await req('team_answer')).at(-1);
 assert(JSON.stringify(detailedAnswer)===JSON.stringify({...simpleAnswer,team_id:'teamS2'}),'Simple and Detailed approve differ: '+JSON.stringify([simpleAnswer,detailedAnswer]));
 await page.locator('[data-view=tasks]').click();
 await page.locator('[data-open-task="T"]').click();
 assert((await text(page.locator('#agent-head'))).includes('Orchestrator on Claude · default model'),'Orchestrator line missing: '+await text(page.locator('#agent-head')));
 assert(await page.locator('#agent-head .provider-badge[data-provider=claude]').count()===1,'Header provider badge missing');

 // A proposed team: roles, briefs, providers, models, access, default vs suggested, budget; text stays literal.
 const team1={team_id:'team1',summary:'Literal <img src=x onerror="window.pwned=1"> plan: research, build, review.',budget:{used:1200,budget:250000},members:[
  {member_id:'m1',role:'researcher',brief:'Map the parser code',provider:'codex',model:null,access:'read',default:true},
  {member_id:'m2',role:'implementer',brief:'Add input validation',provider:'claude',model:'claude-sonnet-5-5',access:'write',default:true},
  {member_id:'m3',role:'reviewer',brief:'Review the change',provider:'gemini',model:null,access:'read',default:false,reason:'A second model family <b>catches</b> different issues'}]};
 await push([ev('T',1,'status',{state:'running',detail:'',queue_position:null,reason:null},{turn_id:null}),
  ev('T',2,'message',{role:'assistant',text:'I will propose a team.',final:true},{item_id:'o1'}),
  ev('T',3,'tool_call',{call_id:'o2',category:'orchestrate',tool:'propose_team',title:'propose_team',input:{},decision:null},{item_id:'o2'}),
  ev('T',4,'team_proposed',team1),
  ev('T',5,'status',{state:'paused_team',detail:'Approve the team',queue_position:null,reason:null},{turn_id:null})]);
 const card=page.locator('#agent-view .card.team');
 assert(await card.count()===1,'Team card missing');
 const cardText=await text(card);
 for(const part of ['Proposed team','Needs your approval','Researcher','Implementer','Reviewer','Default','Suggested: A second model family <b>catches</b> different issues','1,200 / 250,000'])assert(cardText.includes(part),'Team card misses '+part+': '+cardText);
 assert(cardText.includes('Literal <img src=x onerror="window.pwned=1"> plan'),'Summary not literal');
 assert(await card.locator('img,b').count()===0&&!(await page.evaluate(()=>window.pwned)),'Model text inserted as markup');
 for(const name of ['codex','claude','gemini'])assert(await card.locator('.provider-badge[data-provider='+name+']').count()===1,'Member badge missing: '+name);
 assert((await text(page.locator('#agent-view .agent-status'))).includes('Team needs your approval'),'paused_team status missing');
 assert((await text(page.locator('#agent-view .runtime-line'))).length>0&&await page.locator('#agent-send').isDisabled()&&(await text(page.locator('#agent-note'))).includes('Approve or decline the proposed team first.'),'Composer not gated by the team');
 assert((await text(stream)).includes('Orchestration'),'Orchestrate tool category not labelled');
 // Field values and the write gate for a provider without write.
 assert(await card.getByLabel('Researcher brief').inputValue()==='Map the parser code','Brief not shown');
 assert(await card.getByLabel('Implementer model').inputValue()==='claude-sonnet-5-5'&&await card.getByLabel('Researcher provider').inputValue()==='codex','Member fields not filled');
 assert(await card.getByLabel('Reviewer access').locator('option[value=write]').isDisabled(),'Write offered on a provider without write');
 await card.getByLabel('Implementer provider').selectOption('gemini');
 assert(await card.getByLabel('Implementer access').inputValue()==='read'&&await card.getByLabel('Implementer access').locator('option[value=write]').isDisabled(),'Write kept after switching to a read-only provider');
 await card.getByLabel('Implementer provider').selectOption('claude');
 await card.getByLabel('Implementer access').selectOption('write');

 // Model dropdowns: Default plus the provider's own models, refilled when the provider changes, and no effort control.
 const options=async label=>card.getByLabel(label).locator('option').evaluateAll(o=>o.map(x=>x.value));
 assert(await card.locator('select.member-model').count()===2,'Member models are not dropdowns: '+await card.locator('select.member-model').count());
 assert(JSON.stringify(await options('Implementer model'))===JSON.stringify(['','claude-sonnet-5-5','claude-opus-5-5','claude-haiku-5-5']),'Claude list wrong: '+await options('Implementer model'));
 assert(JSON.stringify(await options('Researcher model'))===JSON.stringify(['','codex-fixture-1','codex-fixture-2']),'Codex list wrong: '+await options('Researcher model'));
 assert(await card.locator('input.member-model').count()===1,'Provider without a list does not keep the typed box');
 assert(await card.locator('.team-member [id$=-effort],.team-member label:text-matches("effort","i")').count()===0,'Effort control on the team card');
 // Edits: provider, model and brief, and a removed member. A provider change clears the model.
 await card.getByLabel('Implementer model').selectOption('claude-haiku-5-5');
 await card.getByLabel('Implementer provider').selectOption('codex');
 await page.waitForFunction(()=>[...document.querySelectorAll('#agent-view select.member-model')].some(s=>s.id.endsWith('-model')&&[...s.options].some(o=>o.value==='codex-fixture-2')&&s.value===''));
 assert(await card.getByLabel('Implementer model').inputValue()===''&&!(await card.getByLabel('Implementer model').locator('option:checked').textContent()).includes('not available'),'Model kept across a provider change');
 await card.getByLabel('Implementer provider').selectOption('claude');
 await page.waitForFunction(()=>[...document.querySelectorAll('#agent-view select.member-model')].some(s=>[...s.options].some(o=>o.value==='claude-haiku-5-5')));
 await card.getByLabel('Implementer model').selectOption('claude-sonnet-5-5');
 await card.getByLabel('Researcher provider').selectOption('claude');
 await page.waitForFunction(()=>[...document.querySelectorAll('#agent-view select.member-model')].filter(s=>[...s.options].some(o=>o.value==='claude-haiku-5-5')).length===2);
 assert(await card.getByLabel('Researcher model').inputValue()==='','Researcher model not reset to Default');
 await card.getByLabel('Implementer brief').fill('Add input validation to parse()\nwith tests');
 await card.getByRole('button',{name:'Remove Reviewer',exact:true}).click();
 assert((await text(card)).includes('Removed')&&await card.getByRole('button',{name:'Keep Reviewer',exact:true}).count()===1,'Removed member not marked');
 assert(await card.getByLabel('Implementer brief').inputValue()==='Add input validation to parse()\nwith tests','Edit lost after a rebuild');
 // Edits made in Detailed stay in view in Simple: the edited proposal keeps its editors and says it was changed.
 await simpleBtn.click();
 await page.waitForFunction(()=>document.querySelector('#agent-detail-toggle [data-detail=simple]')?.getAttribute('aria-pressed')==='true');
 assert(await card.getByLabel('Implementer brief').inputValue()==='Add input validation to parse()\nwith tests'&&await card.locator('.team-lines').count()===0&&(await text(card)).includes('You changed this team'),'Simple folded an edited team: '+await text(card));
 await detailedBtn.click();
 await page.waitForFunction(()=>document.querySelector('#agent-detail-toggle [data-detail=detailed]')?.getAttribute('aria-pressed')==='true');
 await card.getByLabel('Researcher model').selectOption('claude-haiku-5-5');
 await card.getByRole('button',{name:'Approve team',exact:true}).click();
 const answers=(await req('team_answer')).filter(p=>p.task_id==='T');
 const expected={task_id:'T',team_id:'team1',decision:'approve',members:[{member_id:'m1',role:'researcher',brief:'Map the parser code',provider:'claude',model:'claude-haiku-5-5',access:'read'},{member_id:'m2',role:'implementer',brief:'Add input validation to parse()\nwith tests',provider:'claude',model:'claude-sonnet-5-5',access:'write'}]};
 assert(answers.length===1&&JSON.stringify(answers[0])===JSON.stringify(expected),'team_answer not exact: '+JSON.stringify(answers));
 assert((await text(card)).includes('Waiting for the Orchestrator')&&await card.getByRole('button',{name:'Approve team'}).count()===0&&await card.getByLabel('Implementer brief').isDisabled(),'Team still editable after approval');

 // Answered, then subagents start: provider badge, role, state and tokens per child.
 await push([ev('T',6,'team_answered',{team_id:'team1',decision:'approve',members:expected.members,note:null}),
  ev('T',7,'subagent_started',{team_id:'team1',member_id:'m1',task_id:'C1',role:'researcher',provider:'codex',model:null,access:'read'}),
  ev('T',8,'subagent_started',{team_id:'team1',member_id:'m2',task_id:'C2',role:'implementer',provider:'claude',model:'claude-sonnet-5-5',access:'write'}),
  ev('T',9,'subagent_status',{team_id:'team1',member_id:'m1',task_id:'C1',state:'running',tokens_used:300}),
  ev('T',10,'subagent_status',{team_id:'team1',member_id:'m2',task_id:'C2',state:'queued',tokens_used:0}),
  ev('T',11,'status',{state:'running',detail:'',queue_position:null,reason:null},{turn_id:null})]);
 assert((await text(card)).includes('You approved this team.')&&await card.locator('textarea,select,input').count()===0,'Answered card still editable');
 const c1=page.locator('#agent-view .card.subagent[aria-label="Researcher subagent"]'),c2=page.locator('#agent-view .card.subagent[aria-label="Implementer subagent"]');
 const c1Text=await text(c1);
 assert(c1Text.includes('Codex')&&c1Text.includes('Running')&&c1Text.includes('300 tokens')&&c1Text.includes('Read only'),'Researcher card incomplete: '+c1Text);
 assert(await c1.locator('.provider-badge[data-provider=codex]').count()===1&&(await text(c2)).includes('Queued')&&(await text(c2)).includes('Can write'),'Implementer card incomplete');
 assert(await c1.getByRole('button',{name:/Review/}).count()===0,'Review offered for a read-only member without changes');

 // Expanding a child loads its own stream with task_events and follows its live events.
 await page.evaluate(ev=>{window.teamFixture.history.C1=ev;},[ev('C1',1,'message',{role:'assistant',text:'Child found <b>three</b> call sites',final:true},{item_id:'k1'}),
  ev('C1',2,'tool_call',{call_id:'k2',category:'file_read',tool:'read',title:'Read parser.py',input:{path:'src/parser.py'},decision:null},{item_id:'k2'})]);
 await c1.getByRole('button',{name:'Show Researcher activity',exact:true}).click();
 const childEvents=(await req('task_events')).filter(p=>p.task_id==='C1');
 assert(childEvents.length===1&&childEvents[0].after_seq===0,'Child stream not loaded: '+JSON.stringify(childEvents));
 const nested=c1.locator('.stream.nested');
 await page.waitForFunction(()=>document.querySelector('.card.subagent .stream.nested')?.textContent.includes('three'));
 assert((await text(nested)).includes('Child found <b>three</b> call sites')&&await nested.locator('b').count()===0,'Child stream not literal');
 assert(await c1.getByRole('button',{name:'Hide Researcher activity',exact:true}).getAttribute('aria-expanded')==='true','Expanded state not exposed');
 await push([ev('C1',3,'message',{role:'assistant',text:'Child live update',final:true},{item_id:'k3'})]);
 assert((await text(nested)).includes('Child live update'),'Live child event not shown in the nested stream');
 assert(!(await text(page.locator('#agent-view #agent-stream > .message'))).includes('Child live update'),'Child event leaked into the parent stream');

 // A finished writer child: diff summary, report and Review changes.
 await push([ev('T',12,'subagent_finished',{team_id:'team1',member_id:'m2',task_id:'C2',state:'completed',report_excerpt:'Added **validation**.\nLiteral <script>window.pwned=2</script>',diff_summary:{branch:'interspace/task-c2c2c2c2',files:[{path:'src/parser.py',change:'modified',additions:12,deletions:3},{path:'tests/test_parser.py',change:'added',additions:20,deletions:0}]}})]);
 const c2Text=await text(c2);
 assert(c2Text.includes('Completed')&&c2Text.includes('2 files changed · +32 −3 · interspace/task-c2c2c2c2'),'Finished card incomplete: '+c2Text);
 assert(c2Text.includes('Literal <script>window.pwned=2</script>')&&!(await page.evaluate(()=>window.pwned)),'Report not literal');
 await c2.getByRole('button',{name:'Review Implementer changes',exact:true}).click();
 assert(JSON.stringify(await page.evaluate(()=>window.teamFixture.reviewOpened))==='["C2"]','Review changes did not open the child');

 // Running view: one column per task, children as rows under it.
 await page.locator('[data-view=running]').click();
 const running=page.locator('#running-view');
 assert(await running.locator('.task-column[data-task="T"]').count()===1&&await running.locator('.task-column[data-task="C1"],.task-column[data-task="C2"]').count()===0,'Children shown as their own columns');
 const rowsT=running.locator('.task-column[data-task="T"] .child-row');
 assert(await rowsT.count()===2,'Child rows missing: '+await rowsT.count());
 const r1=await text(running.locator('.child-row[data-child="C1"]')),r2=await text(running.locator('.child-row[data-child="C2"]'));
 assert(r1.includes('Codex')&&r1.includes('Researcher')&&r1.includes('Running')&&r2.includes('Implementer')&&r2.includes('Claude'),'Child rows incomplete: '+r1+' | '+r2);
 assert((await text(running.locator('.task-column[data-task="T"] .column-status'))).includes('Orchestrator on Claude'),'Column header misses the provider');
 assert((await text(page.locator('#running-note'))).startsWith('2 running of 4 at once · 1 queued'),'Running note wrong');
 // Open a child from its row: its header names the role, provider and parent.
 await running.locator('.child-row[data-child="C1"]').getByRole('button',{name:'Open Researcher subagent',exact:true}).click();
 assert(await page.locator('#agent-view').isVisible()&&(await text(page.locator('#agent-head'))).includes('Researcher subagent on Codex'),'Child header wrong: '+await text(page.locator('#agent-head')));
 await page.getByRole('button',{name:'Part of “Add input validation”',exact:true}).click();
 assert((await text(page.locator('#heading'))).includes('Add input validation'),'Parent link did not open the parent');

 // A second proposal: Decline with a note by keyboard; a failed answer is recoverable.
 await push([ev('T',13,'team_proposed',{team_id:'team2',summary:'Follow-up: docs',budget:{used:9000,budget:250000},members:[{member_id:'w1',role:'writer',brief:'Update the README',provider:'claude',model:null,access:'read',default:true}]}),
  ev('T',14,'status',{state:'paused_team',detail:'',queue_position:null,reason:null},{turn_id:null})]);
 const card2=page.locator('#agent-view .card.team').nth(1);
 await card2.getByRole('button',{name:'Decline',exact:true}).focus();
 await page.keyboard.press('Enter');
 const note=card2.getByLabel('Note for the Orchestrator (optional)');
 assert(await note.isVisible(),'Decline note not shown');
 await note.fill('Not needed yet');
 await page.evaluate(()=>{window.teamFixture.hold.team_answer=true;});
 await card2.getByRole('button',{name:'Decline team',exact:true}).click();
 await page.evaluate(()=>{const f=window.teamFixture;f.fail(f.held.pop(),'The team is no longer waiting.');f.hold.team_answer=false;});
 assert((await text(card2)).includes('The team is no longer waiting.')&&await card2.getByRole('button',{name:'Decline team',exact:true}).isEnabled(),'Failed answer not recoverable');
 await card2.getByRole('button',{name:'Decline team',exact:true}).click();
 const declines=(await req('team_answer')).filter(p=>p.team_id==='team2');
 assert(declines.length===2&&JSON.stringify(declines[1])===JSON.stringify({task_id:'T',team_id:'team2',decision:'decline',note:'Not needed yet'}),'Decline not exact: '+JSON.stringify(declines));
 await push([ev('T',15,'team_answered',{team_id:'team2',decision:'decline',members:[],note:'Not needed yet'})]);
 assert((await text(card2)).includes('You declined this team: Not needed yet'),'Declined answer not shown');

 // A proposal left open when the task ends cannot be answered.
 await push([ev('T',16,'team_proposed',{team_id:'team3',summary:'Late team',budget:{used:9000,budget:250000},members:[{member_id:'x1',role:'tester',brief:'Run the tests',provider:'claude',model:null,access:'write',default:true}]}),
  ev('T',17,'status',{state:'interrupted',detail:'',queue_position:null,reason:null},{turn_id:null})]);
 const card3=page.locator('#agent-view .card.team').nth(2);
 assert((await text(card3)).includes('no longer open')&&await card3.getByRole('button',{name:'Approve team'}).count()===0,'Closed proposal still answerable');

 // Light/dark, 320-1280 fit for the agent view with team and subagent cards, and the grouped Running view.
 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:900});
  for(const target of ['agent','running']){
   if(target==='agent'){await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task="T"]').click();assert(await page.locator('#agent-detail-toggle').isVisible(),'Header toggle hidden at '+width);}else await page.locator('[data-view=running]').click();
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+target+' '+width+' '+colorScheme);fits.push(fit);
   if(width===390||width===1280&&colorScheme==='light')await page.screenshot({path:'workspace-data/team-'+target+'-'+colorScheme+'-'+width+'.png',fullPage:true});
  }
 }}
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'Simple by default: short team card (one line per member, literal summary, no editors) whose approve equals the Detailed one, Edit team opens the editors and Hide details folds them, answered team as one line with Details kept open until Hide details, orchestration calls hidden; Simple | Detailed switch saves Detailed and restores full cards, visible at every width; child rows hidden from the desk, header provider badge, team_proposed card (roles, briefs, badges, default vs suggested reason, budget, literal text), paused_team gate, write disabled for providers without write, edits (provider/model/brief/remove) with model validation, exact team_answer approve and decline-with-note by keyboard, failed answer recovery, closed proposal, subagent cards (badge/role/state/tokens), child stream via task_events with live events, finished diff summary and literal report, Review changes hook, Running view grouped by parent with child rows and parent link, light/dark 320-1280 fit',responsiveStates:fits.length};
}
