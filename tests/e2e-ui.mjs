/* Browser end to end against the real backend (tests/e2e/orchestrated_backend.py) over JSON lines:
   New task → the Orchestrator proposes a team → edit a member's provider → approve → two subagents run at once →
   the writer finishes with a diff → Review changes → Merge into a branch that is not checked out.
   Fake runtimes only: no provider, model call, sign-in or network. The repository is disposable. */
import {spawn,execFileSync} from 'node:child_process';
import {mkdtempSync,rmSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';

// TODO(2A merge): 'Claude' once agent_create without a provider uses routing.orchestrator (see the harness).
const ORCHESTRATOR_TITLE='Codex';

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async loc=>(await loc.textContent())||'';
 const root=mkdtempSync(path.join(tmpdir(),'interspace-e2e-'));
 const child=spawn(process.env.INTERSPACE_PYTHON||'python3',[path.resolve('tests/e2e/orchestrated_backend.py'),root],{cwd:process.cwd(),stdio:['pipe','pipe','pipe']});
 let stderr='';child.stderr.on('data',d=>{stderr+=d;});let exited=null;child.on('exit',code=>{exited=code;});
 const sent=[],received=[];let chain=Promise.resolve(),buffer='';
 child.stdout.on('data',data=>{buffer+=data;let at;while((at=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);if(!line.trim())continue;const message=JSON.parse(line);received.push(message);
  chain=chain.then(()=>page.evaluate(m=>window.interspaceReceive(m),message)).catch(()=>{});}});
 const until=async(predicate,what,ms=20000)=>{const end=Date.now()+ms;while(Date.now()<end){if(exited!==null)throw Error('The backend exited ('+exited+') before '+what+'\n'+stderr.slice(-2000));if(await predicate())return;await page.waitForTimeout(40);}throw Error('Timed out waiting for '+what+(stderr?'\n'+stderr.slice(-2000):''));};
 const repo=path.join(root,'repo');
 const git=(...args)=>execFileSync('git',['-C',repo,...args],{encoding:'utf8'});
 try{
  await page.exposeFunction('interspaceE2EPost',message=>{sent.push(message);child.stdin.write(JSON.stringify(message)+'\n');});
  await page.addInitScript(()=>{window.webkit={messageHandlers:{interspace:{postMessage:m=>window.interspaceE2EPost(m)}}};});
  await page.goto(url);
  await page.evaluate(()=>window.interspaceBoot());
  await until(async()=>(await page.locator('#project-picker option').count())===1,'the real state');
  const calls=method=>sent.filter(m=>m.method===method);
  const reply=m=>received.find(r=>r.id===m.id&&!r.type);
  const events=kind=>received.filter(m=>m.type==='event'&&m.event.kind===kind).map(m=>m.event);

  // New task with the routing defaults, scope approval and the first message.
  await page.getByRole('button',{name:'New task',exact:true}).click();
  await page.locator('#new-title').fill('Validate the parser');
  await page.locator('#new-goal').fill('Add input validation to parse()');
  await page.getByRole('button',{name:'Review scope',exact:true}).click();
  await until(()=>page.locator('#new-agent-scope .scope-editor').isVisible(),'the scope editor');
  await page.getByRole('button',{name:'Create task',exact:true}).click();
  await until(()=>page.locator('#agent-view').isVisible(),'the new task');
  const create=calls('agent_create')[0];
  assert(!('provider' in create.params)&&!('model' in create.params),'Defaults sent as overrides: '+JSON.stringify(create.params));
  const parent=reply(create).result.task_id;
  await until(async()=>(await text(page.locator('#agent-head'))).includes('Orchestrator on '+ORCHESTRATOR_TITLE),'the Orchestrator line');
  await page.getByRole('button',{name:'Approve scope',exact:true}).click();
  await until(async()=>(await text(page.locator('#agent-view .scope-chips'))).includes('Approved'),'scope approval');
  await page.locator('#agent-message').press('Enter');

  // The Orchestrator proposes a team: the default and the suggestion with its reason, as literal text.
  const team=page.locator('#agent-view .card.team');
  await until(()=>team.getByRole('button',{name:'Approve team',exact:true}).isVisible(),'the team proposal');
  assert((await text(page.locator('#agent-view .agent-status'))).includes('Team needs your approval'),'paused_team not shown');
  const member=role=>team.locator('.team-member').filter({has:page.getByRole('heading',{name:role,exact:true})});
  assert((await text(member('Implementer'))).includes('Suggested: Codex <b>already</b> mapped this module')&&await team.locator('b').count()===0,'Suggestion reason: '+await text(member('Implementer')));
  assert((await text(member('Researcher'))).includes('Default'),'Researcher not the default');
  // Edit one member's provider; the edited team is what gets approved.
  await team.getByLabel('Researcher provider').selectOption('claude');
  assert((await text(member('Researcher'))).includes('Your change'),'Edit not marked');
  await team.getByRole('button',{name:'Approve team',exact:true}).focus();
  await page.keyboard.press('Enter');
  const answer=calls('team_answer')[0];
  assert(answer&&answer.params.decision==='approve'&&answer.params.members.map(m=>m.role+':'+m.provider+':'+m.access).join(',')==='researcher:claude:read,implementer:codex:write','team_answer: '+JSON.stringify(answer?.params));

  // Both subagents run at the same time and stream into the parent view without expanding.
  const card=role=>page.locator('#agent-view .card.subagent[aria-label="'+role+' subagent"]');
  await until(async()=>(await text(card('Researcher').locator('.sub-activity')))?.includes('Researcher started')&&(await text(card('Implementer').locator('.sub-activity')))?.includes('Implementer started'),'both subagents streaming');
  assert((await text(card('Researcher'))).includes('Running')&&(await text(card('Implementer'))).includes('Running'),'Subagents not running at once');
  assert(await card('Researcher').locator('.provider-badge[data-provider=claude]').count()===1&&await card('Implementer').locator('.provider-badge[data-provider=codex]').count()===1,'Edited providers not used');
  const running=received.filter(m=>m.type==='state').some(m=>(m.state.scheduler?.running||[]).filter(r=>r.parent_task_id===parent).length===2);
  assert(running,'The scheduler never ran both children at once');
  assert(await page.locator('#agent-view .card.subagent').count()===2,'Duplicate subagent cards');
  child.stdin.write('#release\n');

  // The writer finishes with a diff; the Orchestrator reports; model text stays literal.
  await until(async()=>(await text(card('Implementer'))).includes('1 file changed'),'the diff summary',30000);
  await until(async()=>(await text(page.locator('#agent-view #agent-stream'))).includes('Team finished'),'the Orchestrator summary',30000);
  assert((await text(card('Researcher').locator('.sub-activity'))).includes('parse() is called from <i>cli.py</i> only.')&&await page.locator('#agent-view i').count()===0,'Child text not literal');
  await page.locator('[data-view=tasks]').click();
  assert((await text(page.locator('#task-count')))==='1 tasks','Subagents shown as desk rows: '+await text(page.locator('#desk-tasks')));
  await page.locator('[data-open-task="'+parent+'"]').click();

  // Review changes → Merge into release, which is not checked out, by keyboard.
  const before=git('rev-parse','main').trim();
  await card('Implementer').getByRole('button',{name:'Review Implementer changes',exact:true}).focus();
  await page.keyboard.press('Enter');
  await until(()=>page.locator('#review-merge').isVisible(),'the review view');
  const review=await text(page.locator('#review-view'));
  assert(review.includes('parser.py')&&review.includes('raise ValueError("no input")'),'Review misses the change: '+review);
  await page.locator('#review-into').selectOption('release');
  await page.locator('#review-merge').focus();
  await page.keyboard.press('Enter');
  await until(async()=>(await text(page.locator('#review-view .review-result'))).includes('Merged into release'),'the merge');
  assert(git('show','release:parser.py').includes('raise ValueError("no input")'),'release does not have the change');
  assert(git('log','-1','--format=%s','release').startsWith('Merge interspace task'),'Merge commit message');
  assert(git('rev-parse','main').trim()===before&&!readFileSync(path.join(repo,'parser.py'),'utf8').includes('ValueError')&&git('status','--porcelain')==='','The checked-out branch or files changed');
  await page.getByRole('button',{name:'Back to the task',exact:true}).click();
  await until(async()=>(await text(card('Implementer'))).includes('Merged into release'),'the merged state on the card');

  // Light/dark, 320-1280 fit of the finished task.
  const fits=[];
  for(const colorScheme of ['light','dark'])for(const width of [320,1280]){await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:900});
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+width+' '+colorScheme);fits.push(fit);
   await page.screenshot({path:'workspace-data/e2e-'+colorScheme+'-'+width+'.png',fullPage:true});}
  await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
  assert(!errors.length,'Page errors: '+errors.join(' | '));
  return {checks:'real backend and git: New task with routing defaults omitted, scope approval, team proposal with literal suggested reason, member provider edit, keyboard approve with the edited team, two children running at once streaming into the parent without expanding, diff summary, Orchestrator summary, literal child text, children kept off the desk, Review changes → Merge by keyboard into a non-checked-out branch, checked-out branch and files untouched, merged state on the card, light/dark 320/1280 fit',responsiveStates:fits.length};
 }finally{child.stdin.end();await new Promise(r=>{const t=setTimeout(()=>{child.kill();r();},8000);child.on('exit',()=>{clearTimeout(t);r();});});rmSync(root,{recursive:true,force:true});}
}
