/* Research browser end to end against the real backend (tests/e2e/research_backend.py) over JSON lines.
   This file also plays the Swift shell's part of the bridge: it sends `bridge_hello`, keeps a fake Keychain and answers
   `keychain` and `save_panel` lines, which never reach the page (research/credentials.md). Research HTTP is answered
   from tests/research/fixtures/; runtimes are fakes. No provider, model call, sign-in, Keychain or network.
   1. Settings → Research sources: save a key and an email (never shown back), Test, Remove.
   2. A no-project Literature review: research scope, research tool cards, a researcher and a citation_checker team,
      both running live, the citation report, report.md and references.bib in Outputs, Save through the save panel,
      research call counts, no Review/Merge, listed under Research.
   3. Verify my references: a pasted bibliography gets a citation report.
   4. A project task keeps the coding flow: team card and Review changes. */
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync,mkdirSync,realpathSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';

// Fake values only, distinctive so the test can look for them anywhere they must never appear.
const FAKE_KEY='S2-E2E-fake-key-0123456789';
const FAKE_EMAIL='e2e.contact@example.invalid';
const SHOTS=process.env.INTERSPACE_SHOTS||'workspace-data/research-e2e';

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async loc=>(await loc.textContent())||'';
 const root=mkdtempSync(path.join(tmpdir(),'interspace-research-e2e-'));
 mkdirSync(SHOTS,{recursive:true});
 const child=spawn(process.env.INTERSPACE_PYTHON||'python3',[path.resolve('tests/e2e/research_backend.py'),root],{cwd:process.cwd(),stdio:['pipe','pipe','pipe']});
 let stderr='';child.stderr.on('data',d=>{stderr+=d;});let exited=null;child.on('exit',code=>{exited=code;});
 const write=m=>child.stdin.write((typeof m==='string'?m:JSON.stringify(m))+'\n');
 // The fake Swift side: a Keychain held in memory here, and a save panel that "saves" without a real file dialog.
 const keychain=new Map(),bridge=[],saves=[],toPage=[],received=[];
 let chain=Promise.resolve(),buffer='';
 const swift=m=>{
  bridge.push({type:m.type,op:m.op,account:m.account});
  if(m.type==='keychain'){
   if(m.op==='write'){keychain.set(m.account,m.secret);write({type:'keychain_reply',id:m.id,ok:true});}
   else if(m.op==='delete'){keychain.delete(m.account);write({type:'keychain_reply',id:m.id,ok:true});}
   else if(keychain.has(m.account))write({type:'keychain_reply',id:m.id,ok:true,secret:keychain.get(m.account)});
   else write({type:'keychain_reply',id:m.id,ok:false,error:'not_found'});
  }else if(m.type==='save_panel'){saves.push({suggested_name:m.suggested_name,path:m.path});write({type:'save_panel_reply',id:m.id,ok:true});}
 };
 child.stdout.on('data',data=>{buffer+=data;let at;while((at=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);if(!line.trim())continue;const message=JSON.parse(line);received.push(message);
  if(message.type==='keychain'||message.type==='save_panel'){swift(message);continue;}
  toPage.push(line);
  chain=chain.then(()=>page.evaluate(m=>window.interspaceReceive(m),message)).catch(()=>{});}});
 const until=async(predicate,what,ms=20000)=>{const end=Date.now()+ms;while(Date.now()<end){if(exited!==null)throw Error('The backend exited ('+exited+') before '+what+'\n'+stderr.slice(-2000));if(await predicate())return;await page.waitForTimeout(40);}throw Error('Timed out waiting for '+what+(stderr?'\n'+stderr.slice(-3000):''));};
 const sent=[];
 const calls=method=>sent.filter(m=>m.method===method);
 const reply=m=>received.find(r=>r.id===m.id&&!r.type);
 const events=(kind,task)=>received.filter(m=>m.type==='event'&&m.event.kind===kind&&(!task||m.event.task_id===task)).map(m=>m.event);
 const shot=async name=>page.screenshot({path:path.join(SHOTS,name+'.png'),fullPage:true});
 let harnessSeq=0;
 const harness=async method=>{const id='h-'+(++harnessSeq);write({id,method,params:{}});await until(()=>received.some(r=>r.id===id),method);return received.find(r=>r.id===id).result;};
 try{
  write({type:'bridge_hello',keychain:1,save_panel:1});
  await page.exposeFunction('interspaceE2EPost',message=>{
   // The WebView may never send bridge types; Swift would drop them. Fail loudly instead.
   if(['keychain','keychain_reply','bridge_hello','save_panel_reply'].includes(message?.type))throw Error('The page sent a bridge message');
   sent.push(message);write(message);});
  await page.addInitScript(()=>{window.webkit={messageHandlers:{interspace:{postMessage:m=>window.interspaceE2EPost(m)}}};});
  await page.goto(url);
  await page.evaluate(()=>window.interspaceBoot());
  await until(async()=>(await page.locator('#project-picker option').count())===1,'the real state');

  // 1. Settings → Research sources ------------------------------------------------------------------------
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  const settings=page.locator('#research-settings');
  const item=name=>settings.locator('.research-source[data-source='+name+']');
  await until(async()=>await settings.locator('.research-source').count()===5,'five research sources');
  assert((await text(item('unpaywall'))).includes('Needs your email address'),'Unpaywall before: '+await text(item('unpaywall')));
  await shot('settings-before');
  const key=item('semantic_scholar').locator('input');
  await key.fill(FAKE_KEY);await key.press('Enter');
  await until(async()=>(await text(item('semantic_scholar'))).includes('Saved in your Keychain'),'the key saved');
  assert(await key.inputValue()===''&&keychain.get('semantic_scholar')===FAKE_KEY,'Key not stored through the bridge');
  assert((await key.getAttribute('placeholder')).startsWith('Saved.'),'Saved key placeholder');
  const email=item('unpaywall').locator('input');
  await email.fill(FAKE_EMAIL);
  await item('unpaywall').getByRole('button',{name:'Save',exact:true}).click();
  await until(async()=>(await text(item('unpaywall'))).includes('Saved in your Keychain'),'the email saved');
  assert(keychain.get('unpaywall_email')===FAKE_EMAIL&&(await text(item('unpaywall'))).includes('Your email address is saved')&&!(await text(item('unpaywall'))).includes('Needs your'),'Unpaywall after: '+await text(item('unpaywall')));
  // Test sources: a fixed free lookup answered by the fixtures.
  await item('unpaywall').getByRole('button',{name:'Test Unpaywall',exact:true}).click();
  await until(async()=>/Test call succeeded|Test:/.test(await text(item('unpaywall'))),'the Unpaywall test');
  assert((await text(item('unpaywall'))).includes('Test call succeeded')&&(await text(item('unpaywall'))).includes('Ready'),'Unpaywall test: '+await text(item('unpaywall')));
  await item('crossref').getByRole('button',{name:'Test Crossref',exact:true}).click();
  await until(async()=>/Test call succeeded|Test:/.test(await text(item('crossref'))),'the Crossref test');
  assert((await text(item('crossref'))).includes('Test call succeeded'),'Crossref test: '+await text(item('crossref')));
  // Save a Crossref email too, then Remove it (with its confirmation): the store forgets it.
  await item('crossref').locator('input').fill('remove.me@example.invalid');await item('crossref').locator('input').press('Enter');
  await until(()=>keychain.has('crossref_email'),'the Crossref email saved');
  await until(()=>item('crossref').getByRole('button',{name:'Remove your Crossref email address',exact:true}).isVisible(),'the Remove button');
  await item('crossref').getByRole('button',{name:'Remove your Crossref email address',exact:true}).click();
  await page.locator('#research-remove-confirm-crossref').click();
  await until(async()=>(await text(item('crossref'))).includes('Removed from your Keychain'),'the email removed');
  assert(!keychain.has('crossref_email'),'Crossref email still stored');
  const settingsText=await text(settings);
  assert(!settingsText.includes(FAKE_KEY)&&!settingsText.includes(FAKE_EMAIL)&&!(await settings.locator('input').evaluateAll(is=>is.map(i=>i.value))).some(Boolean),'A secret is shown back');
  await shot('settings-after');

  // 2. Literature review, no project -------------------------------------------------------------------------
  await page.locator('[data-view=research]').click();
  assert((await text(page.locator('#research-empty'))).includes('No research tasks yet'),'Research empty state');
  await shot('research-empty');
  await page.locator('#new-task').click();
  assert(await page.locator('input[name=new-kind][value=research]').isChecked(),'Research kind preselected');
  await page.locator('input[name=new-preset][value=literature_review]').check();
  await page.locator('#new-goal').fill('attention-based sequence models');
  await shot('new-literature-review');
  await page.getByRole('button',{name:'Review scope',exact:true}).click();
  await until(()=>page.locator('#new-agent-scope .scope-editor').isVisible(),'the research scope editor');
  for(const [label,value] of [['Semantic Scholar','allow'],['OpenAlex','allow'],['arXiv','allow'],['Crossref','allow'],['Unpaywall','allow']])
   assert(await page.locator('#new-agent-scope').getByLabel(label,{exact:true}).inputValue()===value,label+' default');
  // Each source offers allow / ask / off.
  assert(JSON.stringify(await page.locator('#new-agent-scope').getByLabel('arXiv',{exact:true}).locator('option').evaluateAll(o=>o.map(x=>x.value)))===JSON.stringify(['allow','ask','off']),'Source choices');
  await shot('new-research-scope');
  await page.getByRole('button',{name:'Create task',exact:true}).click();
  await until(()=>page.locator('#agent-view').isVisible(),'the research task');
  const create=calls('agent_create')[0];
  assert(create.params.project_id===null&&create.params.kind==='research','agent_create: '+JSON.stringify(create.params));
  const review=reply(create).result.task_id;
  await page.getByRole('button',{name:'Approve scope',exact:true}).click();
  await until(async()=>(await text(page.locator('#agent-view .scope-chips'))).includes('Approved'),'scope approval');
  await page.locator('#agent-message').press('Enter');

  // The Orchestrator's own research calls stream in as paper cards with source badges and https links only.
  const stream=page.locator('#agent-stream');
  const team=page.locator('#agent-view .card.team');
  await until(()=>team.getByRole('button',{name:'Approve team',exact:true}).isVisible(),'the research team proposal',30000);
  const toolCards=stream.locator('.card.tool.research');
  assert(await toolCards.count()>=2,'Research tool cards: '+await toolCards.count());
  const search=toolCards.filter({hasText:'Search papers'}).first();
  assert(await search.locator('.paper').count()>0&&await search.locator('.source-badge').count()>0,'Paper list: '+await text(search));
  const hrefs=await stream.locator('a').evaluateAll(as=>as.map(a=>a.getAttribute('href')));
  assert(hrefs.length>0&&hrefs.every(h=>h.startsWith('https://')),'Links: '+JSON.stringify(hrefs));
  const member=role=>team.locator('.team-member').filter({has:page.getByRole('heading',{name:role,exact:true})});
  assert(await member('Researcher').count()===1&&await member('Citation checker').count()===1,'Team: '+await text(team));
  await shot('research-team');
  await team.getByRole('button',{name:'Approve team',exact:true}).click();
  const answer=calls('team_answer')[0];
  const proposed=events('team_proposed',review)[0];
  assert(answer.params.decision==='approve'&&proposed.data.members.every(m=>m.access==='read'),'Research members: '+JSON.stringify(proposed.data.members));

  // Both subagents run at once, live in the parent view.
  const card=role=>page.locator('#agent-view .card.subagent[aria-label="'+role+' subagent"]');
  await until(async()=>(await text(card('Researcher').locator('.sub-activity'))).includes('Researcher started')&&(await text(card('Citation checker').locator('.sub-activity'))).includes('Citation checker started'),'both research subagents streaming');
  assert((await text(card('Researcher'))).includes('Running')&&(await text(card('Citation checker'))).includes('Running'),'Research subagents not running at once');
  await shot('research-subagents-running');
  write('#release-research');

  // The citation report: one row per status, never "verified" for the ones the checker did not verify.
  const report=stream.locator('.citation-report').first();
  await until(()=>report.isVisible(),'the citation report',30000);
  for(const cls of ['verified','mismatch','not-found','retracted'])assert(await report.locator('.reference.'+cls).count()===1,'Row '+cls+': '+await text(report));
  assert((await text(report.locator('.reference.mismatch'))).includes('Not verified')&&(await text(report.locator('.reference.retracted'))).includes('Retracted'),'Row wording');
  // The checker's report sits on its subagent card in the parent view; finished children read Finished.
  assert(await card('Citation checker').locator('.citation-report').count()===1,'Citation report not on the checker card');
  await until(async()=>(await text(card('Citation checker'))).includes('Finished')&&(await text(card('Researcher'))).includes('Finished'),'finished subagents');
  assert((await text(card('Citation checker').locator('.sub-activity'))).includes('Research: Check citations'),'Activity: '+await text(card('Citation checker').locator('.sub-activity')));
  // The final report and outputs.
  await until(async()=>(await text(stream)).includes('Attention-based sequence models'),'the final report',30000);
  // A research answer reads as a document: headings, lists and https links, all as text.
  const final=stream.locator('.message.assistant').filter({hasText:'short review'});
  assert(await final.getByRole('heading',{name:'Findings'}).count()===1&&await final.locator('li').count()>=4&&await final.locator('a[href="https://arxiv.org/abs/1706.03762"]').count()===1,'Final answer not rendered as a document');
  const outputs=page.locator('#agent-outputs');
  await until(async()=>await outputs.isVisible()&&await outputs.locator('.output-item').count()===2,'report.md and references.bib',30000);
  await page.locator('#output-view-report_md').click();
  await until(async()=>(await text(outputs.locator('#output-body-report_md'))).includes('short review'),'report.md text');
  assert(await outputs.locator('#output-body-report_md h3, #output-body-report_md h2').count()>0,'Report not rendered as Markdown');
  await page.locator('#output-view-references_bib').click();
  await until(async()=>(await text(outputs.locator('#output-body-references_bib'))).includes('@'),'references.bib text');
  const bib=await text(outputs.locator('#output-body-references_bib'));
  assert(bib.includes('Left out, retracted')&&bib.includes('mismatch'),'BibTeX header: '+bib.slice(0,600));
  await page.locator('#output-save-references_bib').click();
  await until(async()=>(await text(outputs.locator('[data-output="references.bib"]'))).includes('Saved.'),'the save panel reply');
  assert(saves.length===1&&saves[0].suggested_name.endsWith('.bib')&&saves[0].path.startsWith(path.join(realpathSync(root),'data','tasks',review,'outputs')+path.sep),'Save panel: '+JSON.stringify(saves));
  // Research call counts, never money; no Review/Merge anywhere for this task.
  await until(async()=>/Research calls:.*Crossref/.test(await text(page.locator('#agent-view .research-usage'))),'research usage for every source used');
  const usage=await text(page.locator('#agent-view .research-usage'));
  assert(/Semantic Scholar \d+ call/.test(usage)&&!/\$|€|£|cost|price/i.test(usage),'Usage: '+usage);
  assert(await page.locator('#agent-view').getByRole('button',{name:/Review|Merge/}).count()===0,'Review/Merge offered for research');
  await shot('research-report');
  await outputs.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(SHOTS,'research-outputs.png')});
  await report.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(SHOTS,'citation-report.png')});
  // Listed under Research, not on the project desk.
  await page.locator('#agent-back').click();
  await until(async()=>(await text(page.locator('#research-tasks'))).includes('Literature review: attention-based'),'the Research list');
  await page.locator('[data-view=tasks]').click();
  assert(!(await text(page.locator('#desk-tasks'))).includes('Literature review'),'Research task on the project desk');

  // 3. Verify my references ------------------------------------------------------------------------------------
  await page.locator('[data-view=research]').click();
  await page.locator('#new-task').click();
  await page.locator('input[name=new-preset][value=verify_references]').check();
  await page.locator('#new-bib').fill(['Vaswani, A., et al. (2017). Attention Is All You Need. arXiv:1706.03762',
   'LeCun, Y., Bengio, Y., Hinton, G. (2012). Deep learning. Nature. doi:10.1038/nature14539',
   'Wakefield, A. J., et al. (1998). Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children. The Lancet. doi:10.1016/S0140-6736(97)11096-0',
   'Placeholder, J. (2020). "A synthetic survey of imaginary retrieval transformers". Journal of Nowhere.'].join('\n'));
  await page.getByRole('button',{name:'Review scope',exact:true}).click();
  await until(()=>page.locator('#new-agent-scope .scope-editor').isVisible(),'the verify scope editor');
  await page.getByRole('button',{name:'Create task',exact:true}).click();
  await until(async()=>calls('agent_create').length===2&&await page.locator('#agent-view').isVisible(),'the verify task');
  const verify=reply(calls('agent_create')[1]).result.task_id;
  await page.getByRole('button',{name:'Approve scope',exact:true}).click();
  await until(async()=>(await text(page.locator('#agent-view .scope-chips'))).includes('Approved'),'verify scope approval');
  await page.locator('#agent-message').press('Enter');
  const vreport=page.locator('#agent-stream .citation-report').first();
  await until(()=>vreport.isVisible(),'the verify citation report',30000);
  assert(await vreport.locator('.reference').count()===4,'Verify rows: '+await text(vreport));
  await until(async()=>await page.locator('#agent-outputs .output-item').count()>=1,'the verify outputs',30000);
  await vreport.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(SHOTS,'verify-references.png')});
  const vrows=await vreport.locator('.reference').evaluateAll(ls=>ls.map(l=>l.className));

  // 4. A project task keeps the coding flow ----------------------------------------------------------------------
  await page.locator('[data-view=tasks]').click();
  await page.locator('#new-task').click();
  assert(await page.locator('input[name=new-kind][value=project]').isChecked(),'Project kind from the desk');
  await page.locator('#new-title').fill('Validate the parser');
  await page.locator('#new-goal').fill('Add input validation to parse()');
  await page.getByRole('button',{name:'Review scope',exact:true}).click();
  await until(()=>page.locator('#new-agent-scope .scope-editor').isVisible(),'the project scope editor');
  await page.getByRole('button',{name:'Create task',exact:true}).click();
  await until(async()=>calls('agent_create').length===3&&await page.locator('#agent-view').isVisible(),'the project task');
  assert(!('kind' in calls('agent_create')[2].params),'Project task sent a kind');
  await page.getByRole('button',{name:'Approve scope',exact:true}).click();
  await until(async()=>(await text(page.locator('#agent-view .scope-chips'))).includes('Approved'),'project scope approval');
  await page.locator('#agent-message').press('Enter');
  await until(()=>team.getByRole('button',{name:'Approve team',exact:true}).isVisible(),'the project team proposal');
  await team.getByRole('button',{name:'Approve team',exact:true}).click();
  await until(async()=>(await text(card('Implementer').locator('.sub-activity'))).includes('Implementer started'),'the implementer');
  write('#release');
  await until(async()=>(await text(card('Implementer'))).includes('1 file changed'),'the diff summary',30000);
  assert(await card('Implementer').getByRole('button',{name:'Review Implementer changes',exact:true}).count()===1,'Review changes missing on the project task');

  // Nothing secret left the backend for the page, and research HTTP only went to the sources' own hosts.
  const leaked=toPage.filter(l=>l.includes(FAKE_KEY)||l.includes(FAKE_EMAIL));
  assert(!leaked.length,'A secret reached the page: '+leaked[0]?.slice(0,200));
  const urls=(await harness('harness_urls')).urls;
  const hosts=[...new Set(urls.map(u=>new URL(u).hostname))];
  assert(urls.length>0&&urls.every(u=>u.startsWith('https://'))&&hosts.every(h=>['api.semanticscholar.org','api.openalex.org','export.arxiv.org','arxiv.org','api.crossref.org','api.unpaywall.org'].includes(h)),'Hosts: '+hosts);
  assert(!urls.some(u=>u.includes(FAKE_KEY)),'The key went into a URL');
  assert(events('research_usage',review).length>0&&events('outputs',review).length>0&&events('citation_report').length>=2,'Research events missing');

  // Light/dark, 320–1280 fit of the research task.
  await page.locator('[data-view=research]').click();await page.locator('[data-open-task="'+review+'"]').click();
  await until(()=>page.locator('#agent-stream .citation-report').first().isVisible(),'the reopened research task');
  const fits=[];
  for(const colorScheme of ['light','dark'])for(const width of [320,768,1280]){await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:900});
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+width+' '+colorScheme);fits.push(fit);
   await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(SHOTS,'research-task-'+colorScheme+'-'+width+'.png')});
   const cite=page.locator('#agent-stream .card.subagent .sub-citation').first();await cite.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(SHOTS,'citation-'+colorScheme+'-'+width+'.png')});}
  await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
  assert(!errors.length,'Page errors: '+errors.join(' | '));
  return {checks:'real backend, fake Swift bridge (Keychain, save panel), fixture HTTP: research key and email saved write-only and never shown back, Test, Remove with confirmation; Literature review with no project, research scope allow/ask/off, research tool cards with source badges and https links, researcher + citation_checker team approved read-only, both running live, citation report verified/mismatch/not found/retracted, report.md and references.bib viewed, Save through the save panel, research call counts, no Review/Merge, listed under Research only; Verify my references ('+vrows.join(',')+'); project task team and Review changes; no secret reached the page or a URL; only source hosts over https; light/dark 320/768/1280 fit',responsiveStates:fits.length,researchUrls:urls.length};
 }catch(error){
  try{await shot('failure');}catch{}
  throw error;
 }finally{child.stdin.end();await new Promise(r=>{const t=setTimeout(()=>{child.kill();r();},8000);child.on('exit',()=>{clearTimeout(t);r();});});rmSync(root,{recursive:true,force:true});}
}
