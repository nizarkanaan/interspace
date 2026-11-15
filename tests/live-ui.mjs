/* Agent UI against the real backend: service.Router and Application with the real scope engine and audit log,
   over the same JSON-lines protocol the Swift shell carries. The runtime is a fake:
   no provider, model call, sign-in or network. */
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';

const HARNESS=String.raw`
import json, subprocess, sys, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(Path.cwd() / 'app/backend'))
sys.path.insert(0, str(Path.cwd() / 'tests'))
import service, projects
from agent_fakes import FakeRuntime

out_lock = threading.Lock()
def emit(message):
    line = json.dumps(message)
    with out_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()

repo = root / 'repo'
repo.mkdir()
git = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
subprocess.run(git + ['init', '-q', '-b', 'main', str(repo)], check=True)
(repo / 'parser.py').write_text('def parse(x):\n    return x\n')
subprocess.run(git + ['-C', str(repo), 'add', '.'], check=True)
subprocess.run(git + ['-C', str(repo), 'commit', '-qm', 'base'], check=True)

class Provider:
    def status(self):
        return {'ready': True, 'message': 'Live harness (fake runtime)'}
    def sign_in(self, cancel, emit):
        pass

def script(session, text, ctx):
    item = 'm-' + ctx.turn_id[:12]
    if 'wait' in text:
        ctx.emit('message', {'role': 'assistant', 'text': 'Working: ' + text, 'final': True}, item_id=item)
        session.interrupted.wait(30)
        return {'status': 'cancelled', 'usage': None, 'error': None}
    ctx.emit('message_delta', {'role': 'assistant', 'text_delta': 'Looking at '}, item_id=item)
    if 'ask' in text:
        decision = ctx.authorize({'category': 'file_read', 'project_id': ctx.project_ids[0], 'path': 'parser.py'},
                                 'call-' + ctx.turn_id[:12])
        ctx.emit('message', {'role': 'assistant', 'text': 'File read ' + decision['decision'] + ' (' + decision['rule'] + ')',
                             'final': True}, item_id=item)
    else:
        ctx.emit('message', {'role': 'assistant', 'text': 'Done: ' + text, 'final': True}, item_id=item)
    return {'status': 'completed', 'usage': {'input_tokens': 900, 'output_tokens': 100}, 'error': None}

runtime = FakeRuntime(script)
app = service.Application(root / 'data', provider=Provider(), emit=emit, runtime_factory=lambda task_id: runtime,
                          interrupt_grace_s=0.5)
project = projects.new_project(repo)
with app.lock:
    app.state['projects'][project['id']] = project
    app.state['selected_project_id'] = project['id']
    app.persist()
router = service.Router(app, emit)
for line in sys.stdin:
    router.route(line)
router.close(5)
app.scheduler.shutdown(5)
`;

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async loc=>(await loc.textContent())||'';
 const root=mkdtempSync(path.join(tmpdir(),'interspace-live-'));
 const child=spawn(process.env.INTERSPACE_PYTHON||'python3',['-c',HARNESS,root],{cwd:process.cwd(),stdio:['pipe','pipe','pipe']});
 let stderr='';child.stderr.on('data',d=>{stderr+=d;});
 const sent=[],received=[];let drop=null,chain=Promise.resolve(),buffer='';
 child.stdout.on('data',data=>{buffer+=data;let at;while((at=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);if(!line.trim())continue;const message=JSON.parse(line);received.push(message);
  if(message.type==='event'&&drop&&drop(message.event))continue;
  chain=chain.then(()=>page.evaluate(m=>window.interspaceReceive(m),message)).catch(()=>{});}});
 const until=async(predicate,what,ms=15000)=>{const end=Date.now()+ms;while(Date.now()<end){if(await predicate())return;await page.waitForTimeout(40);}throw Error('Timed out waiting for '+what+(stderr?'\n'+stderr.slice(-2000):''));};
 try{
  await page.exposeFunction('interspaceLivePost',message=>{sent.push(message);child.stdin.write(JSON.stringify(message)+'\n');});
  await page.addInitScript(()=>{window.webkit={messageHandlers:{interspace:{postMessage:m=>window.interspaceLivePost(m)}}};});
  await page.goto(url);
  if(!await page.evaluate(()=>!!document.getElementById('ispace').interspaceLab))await page.addScriptTag({path:'design/scene/lab-scene.js'});
  await page.evaluate(()=>window.interspaceBoot());
  await until(async()=>(await page.locator('#project-picker option').count())===1,'the real state');
  const calls=method=>sent.filter(m=>m.method===method);
  const reply=m=>received.find(r=>r.id===m.id&&!r.type);

  // New agent task form: title, project, runtime and model, then the real default scope in the editor.
  const newAgent=async(title,provider,model,goal)=>{
   await page.getByRole('button',{name:'New task',exact:true}).click();
   await page.locator('#new-mode').selectOption('agent');
   assert(await page.locator('#new-agent-fields').isVisible()&&await page.locator('#new-legacy-fields').isHidden(),'Agent fields not shown');
   assert(await page.locator('#create-draft').isHidden(),'Legacy draft button shown for agent mode');
   await page.locator('#new-title').fill(title);await page.locator('#new-runtime').selectOption(provider);await page.locator('#new-model').fill(model);
   if(goal)await page.locator('#new-goal').fill(goal);
   await page.getByRole('button',{name:'Review scope',exact:true}).click();
   await until(()=>page.locator('#new-agent-scope .scope-editor').isVisible(),'the scope editor');
   assert(await page.locator('#new-task-form').isHidden(),'Form still shown during scope review');
  };
  await page.getByRole('button',{name:'New task',exact:true}).click();
  await page.locator('#new-mode').selectOption('agent');
  await page.locator('#new-model').fill('bad model');await page.locator('#new-title').fill('Bad');
  await page.getByRole('button',{name:'Review scope',exact:true}).click();
  assert(calls('scope_default').length===0,'Invalid model reached the backend');
  await page.getByRole('button',{name:'Tasks',exact:true}).click();

  await newAgent('Fix the parser','codex','','Please ask before reading parser.py');
  const defaults=reply(calls('scope_default')[0]).result.scope;
  assert(defaults.network.default==='deny'&&defaults.apps.length===0&&defaults.web_search==='deny'&&defaults.projects[0].access==='write','Unexpected default scope '+JSON.stringify(defaults));
  assert((await page.locator('#new-agent-scope select').first().inputValue())==='write','Editor does not show the default scope');
  assert((await text(page.locator('#new-agent-scope-note'))).includes('Fix the parser'),'Scope review does not name the task');
  // Back keeps the draft; editing the scope before creation is sent as edited.
  await page.getByRole('button',{name:'Back',exact:true}).click();
  assert(await page.locator('#new-task-form').isVisible()&&(await page.locator('#new-title').inputValue())==='Fix the parser','Back lost the draft');
  await page.getByRole('button',{name:'Review scope',exact:true}).click();
  await until(()=>page.locator('#new-agent-scope .scope-editor').isVisible(),'the scope editor again');
  await page.locator('#new-agent-scope textarea').nth(0).fill('src/**');
  await page.locator('#new-agent-scope textarea').nth(2).fill('secrets/**');
  assert(calls('agent_create').length===0,'Task created before Create task');
  await page.getByRole('button',{name:'Create task',exact:true}).click();
  await until(()=>page.locator('#agent-view').isVisible(),'the new agent task');
  const create1=calls('agent_create')[0];
  assert(create1.params.provider==='codex'&&create1.params.model===null&&create1.params.scope.projects[0].deny[0]==='secrets/**'&&create1.params.scope.projects[0].read[0]==='src/**','agent_create params '+JSON.stringify(create1.params));
  const taskA=reply(create1).result.task_id;
  await until(async()=>(await text(page.locator('#agent-view .scope-chips'))).includes('Needs approval'),'unapproved scope chips');
  assert((await text(page.locator('#agent-view .scope-chips'))).includes('Network: off'),'Network chip missing');
  assert((await page.locator('#agent-message').inputValue())==='Please ask before reading parser.py','First message not waiting in the composer');
  assert(await page.locator('#agent-send').isDisabled(),'Send enabled before approval');
  assert((await text(page.locator('#agent-head'))).includes('Runtime Codex · default model'),'Runtime line missing');
  // Approval binds the digest the backend returned.
  await page.getByRole('button',{name:'Approve scope',exact:true}).click();
  await until(async()=>(await text(page.locator('#agent-view .scope-chips'))).includes('Approved'),'approval');
  const approve=calls('scope_approve')[0];
  assert(approve.params.scope_digest===reply(calls('scope_get').find(c=>c.params.task_id===taskA)).result.scope_digest&&!reply(approve).error,'Approval digest mismatch');

  // Ask prompt through policy: Add to scope sends the exact patched digest; the real scope engine amends.
  await page.locator('#agent-message').press('Enter');
  await until(()=>page.locator('#agent-view .card.ask').isVisible(),'the ask prompt');
  const askCard=page.locator('#agent-view .card.ask');
  assert((await text(askCard)).includes('parser.py')&&(await text(askCard)).includes('Outside the task scope'),'Ask card incomplete');
  assert((await text(page.locator('#agent-view .agent-status'))).includes('Needs your answer'),'paused_ask status missing');
  await askCard.getByRole('button',{name:'Add to scope',exact:true}).click();
  await until(async()=>(await text(page.locator('#agent-view .stream'))).includes('File read allow (ask.add_to_scope)'),'the amended turn to finish');
  const answer=calls('agent_answer')[0],askEvent=received.find(m=>m.type==='event'&&m.event.kind==='ask').event.data;
  assert(answer.params.request_digest===askEvent.request_digest&&answer.params.scope_digest===askEvent.patched_scope_digest&&answer.params.ask_id===askEvent.ask_id,'Answer digests not exact');
  await until(async()=>(await text(page.locator('#agent-view .scope-chips'))).includes('Approved · v2'),'the amended scope to reload');
  await until(async()=>(await text(page.locator('#agent-view .agent-status'))).includes('Waiting for your message'),'idle status');

  // A second task on Claude Code with a model.
  await newAgent('Tidy notes','claude','claude-opus-5-5','');
  await page.getByRole('button',{name:'Create task',exact:true}).click();
  await until(()=>page.locator('#agent-view').isVisible(),'the second task');
  const create2=calls('agent_create')[1],taskB=reply(create2).result.task_id;
  assert(create2.params.provider==='claude'&&create2.params.model==='claude-opus-5-5','Second create params');
  assert((await text(page.locator('#agent-head'))).includes('Runtime Claude Code · claude-opus-5-5'),'Claude runtime line missing');
  await page.getByRole('button',{name:'Approve scope',exact:true}).click();
  await until(async()=>(await text(page.locator('#agent-view .scope-chips'))).includes('Approved'),'second approval');
  await page.getByRole('button',{name:'Tasks',exact:true}).click();
  const rows=await text(page.locator('#desk-tasks'));
  assert(rows.includes('Agent task · Claude Code · claude-opus-5-5')&&rows.includes('Agent task · Codex'),'Desk rows miss the runtime: '+rows);

  // Several tasks at once: both wait inside their turns; each stream stays its own.
  const send=async(id,message)=>{await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.locator('[data-open-task="'+id+'"]').click();await until(()=>page.locator('#agent-view').isVisible(),'agent view');await page.locator('#agent-message').fill(message);await page.locator('#agent-message').press('Enter');};
  await send(taskA,'wait for A');
  await send(taskB,'wait for B');
  await page.getByRole('button',{name:'Running',exact:true}).click();
  await until(async()=>(await text(page.locator('#running-note'))).startsWith('2 running'),'two running tasks');
  const colA=page.locator('#running-grid [data-task="'+taskA+'"]'),colB=page.locator('#running-grid [data-task="'+taskB+'"]');
  await until(async()=>(await text(colA)).includes('Working: wait for A')&&(await text(colB)).includes('Working: wait for B'),'both streams');
  assert(!(await text(colA)).includes('wait for B')&&!(await text(colB)).includes('wait for A'),'Streams mixed between tasks');

  // Cancel one: the other keeps running.
  await colB.getByRole('button',{name:'Stop',exact:true}).click();
  await until(async()=>(await text(colB.locator('.column-status'))).includes('Cancelled'),'task B cancelled');
  assert((await text(colA.locator('.column-status'))).includes('Running'),'Cancelling B stopped A');
  assert(calls('agent_cancel').length===1&&calls('agent_cancel')[0].params.task_id===taskB,'Cancel params');
  await colA.getByRole('button',{name:'Stop',exact:true}).click();
  await until(async()=>(await text(colA.locator('.column-status'))).includes('Cancelled'),'task A cancelled');

  // Gap recovery from task_events: drop live events for task A, then the next one triggers a replay.
  let dropped=0;drop=e=>e.task_id===taskA&&dropped<3&&++dropped>0;
  await send(taskA,'second pass');
  await until(async()=>(await text(page.locator('#agent-view .stream'))).includes('Done: second pass'),'the recovered stream');
  assert(dropped===3,'Nothing was dropped');
  const replays=calls('task_events').filter(c=>c.params.task_id===taskA&&c.params.after_seq>0);
  assert(replays.length>=1,'No gap replay requested');
  assert(!(await text(page.locator('#agent-view .stream'))).includes('could not be loaded'),'Gap left unfilled');
  drop=null;

  // Fit, light and dark, for the new form and the live views.
  const fits=[];
  for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:900});
   for(const target of ['new','agent','running']){
    if(target==='new'){await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.getByRole('button',{name:'New task',exact:true}).click();await page.locator('#new-mode').selectOption('agent');}
    if(target==='agent'){await page.getByRole('button',{name:'Tasks',exact:true}).click();await page.locator('[data-open-task="'+taskA+'"]').click();}
    if(target==='running')await page.getByRole('button',{name:'Running',exact:true}).click();
    const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+target+' '+width+' '+colorScheme);fits.push(fit);
   }}}
  await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
  assert(!errors.length,'Page errors: '+errors.join('; '));
  return {checks:'real backend over JSON lines: new agent task form (title, project, runtime, model, validation), scope_default in the editor, edited scope on create, digest approval, ask answered through the real scope engine with Add to scope, several tasks running at once with separate streams, per-task cancel, gap recovery from task_events, light/dark 320-1280 fit',responsiveStates:fits.length,requests:sent.length};
 }finally{
  child.stdin.end();await new Promise(resolve=>{const t=setTimeout(()=>{child.kill();resolve();},8000);child.on('exit',()=>{clearTimeout(t);resolve();});});
  rmSync(root,{recursive:true,force:true});
 }
}
