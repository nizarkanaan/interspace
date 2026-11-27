/* Task details panel and conversation display (docs/superpowers/specs/2026-11-20-details-panel-and-display-design.md),
   from fixture events only: the panel holds status, scope and outputs beside the conversation (a Details tab when
   narrow); searches and reasoning show as summaries by default; Settings → Conversation display hides kinds of output,
   but replies, questions and failed calls always show. */
import {install,requests,assert,text,ev,resetSeq} from './research-fixture.mjs';
const XSS='<img src=x onerror="window.pwned=1">';
const LONG='First I will search OpenAlex and Crossref for fallback studies. '.repeat(8)+'\n\nThen I will check every reference.';
const call=(id,tool,input)=>ev('r1','tool_call',{call_id:id,category:'research',tool,title:tool,input:{tool,...input},decision:{decision:'allow',rule:'research.allow',scope_version:1}},id);
const result=(id,data,status='ok')=>ev('r1','tool_result',{call_id:id,status,duration_ms:5,output:{text:JSON.stringify(data),truncated:false,blob_id:null},error:status==='ok'?null:{code:'unavailable',message:'Crossref did not answer.'}},id);
const paper=i=>({v:1,title:'Fallback paper '+i,authors:['Ada Example'],year:2020,venue:'Fixture',doi:'10.5555/fb.'+i,sources:['openalex']});

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 const history=[
  ev('r1','scope',{scope_version:1,scope_digest:'sha256:aa',change:'approved',summary:'Scope approved.'}),
  ev('r1','message',{role:'user',text:'Review fallback evidence',final:true},'u1'),
  ev('r1','reasoning',{text:LONG},'think1'),
  call('s1','research_search',{query:'fallback '+XSS}),result('s1',{papers:[paper(1),paper(2),paper(3)],searched:['openalex','crossref'],skipped:[]}),
  call('s2','research_paper',{id:'doi:10.5555/fb.1'}),result('s2',{paper:paper(1)}),
  call('s3','research_search',{query:'failing search'}),result('s3',{},'error'),
  call('s5','save_report',{}),result('s5',{saved:'report.md',characters:1234}),
  call('s4','research_corpus',{status:'unchecked'}),result('s4',{counts:{papers:3,checked:1,unchecked:2,unverified:0},status:'unchecked',matched:2,offset:0,papers:[paper(2),paper(3)]}),
  ev('r1','plan_update',{steps:[{text:'Search',status:'completed'}]},'plan1'),
  ev('r1','message',{role:'assistant',text:'The evidence on fallback is thin.',final:true},'m1'),
  ev('r1','outputs',{outputs:[{name:'report.md',kind:'report',bytes:100}]}),
  ev('r1','status',{state:'idle',detail:'',queue_position:null,reason:null})];
 await install(page,url,{researchRows:[{id:'r1',mode:'agent',kind:'research',project_id:null,title:'Fallback review',status:'idle',provider:'codex',model:null}],history:{r1:history},
  outputs:{r1:[{name:'report.md',kind:'report',bytes:100}]}});
 await page.setViewportSize({width:1440,height:900});
 await page.locator('[data-view=research]').click();
 await page.locator('[data-open-task=r1]').click();
 const stream=page.locator('#agent-stream');
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream .message').length===2);

 // Split reader (wide research task): the conversation on the left, results on the right. While the scope waits for
 // approval the results open on Scope and outputs, which holds status, scope and outputs.
 const panel=page.locator('#agent-details');
 assert(await page.locator('#agent-view.split').count()===1&&await page.locator('#agent-topbar').isVisible(),'Split reader with a top bar');
 assert(await page.locator('#agent-topbar #agent-detail-toggle').isVisible()&&await page.locator('#agent-detail-toggle [data-detail=simple]').getAttribute('aria-pressed')==='true'&&await page.locator('#agent-detail-toggle [data-detail=detailed]').getAttribute('aria-pressed')==='false','Simple | Detailed switch in the top bar, Simple marked current');
 assert(await panel.isVisible()&&(await text(page.locator('[data-agent-tab=details]')))==='Scope and outputs'&&(await page.locator('[data-agent-tab=details]').getAttribute('aria-pressed'))==='true','Scope and outputs open first');
 for(const id of ['agent-head','agent-scope'])assert(await panel.locator('#'+id).count()===1,id+' in the panel');
 assert(await page.locator('[data-agent-tab=conversation]').isHidden(),'No Conversation tab beside the conversation');
 const side=await page.evaluate(()=>{const s=document.getElementById('agent-stream').getBoundingClientRect(),p=document.getElementById('agent-results').getBoundingClientRect();return p.left>=s.right;});
 assert(side,'Results are to the right of the conversation');
 assert((await text(page.locator('#agent-topbar-scope')))==='Scope needs approval'&&await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight+1),'Top bar scope, page does not scroll');

 // Resizable split: drag the divider, arrow keys move it, limits hold, double-click resets.
 const handle=page.locator('#split-handle'),chatW=()=>page.evaluate(()=>Math.round(document.getElementById('agent-stream').closest('.agent-main').getBoundingClientRect().width));
 assert(await handle.evaluate(h=>!h.hidden)&&(await handle.getAttribute('role'))==='separator','Divider shown');
 const start=await chatW(),box=await handle.boundingBox();
 await page.mouse.move(box.x+box.width/2,box.y+200);await page.mouse.down();await page.mouse.move(box.x+180,box.y+200,{steps:5});await page.mouse.up();
 const dragged=await chatW();
 assert(dragged>start+150,'Drag widens the conversation: '+start+' -> '+dragged);
 await handle.focus();await page.keyboard.press('ArrowLeft');
 assert(await chatW()===dragged-24,'Arrow key moves it');
 await page.keyboard.press('Home');assert(await chatW()===300,'Home is the narrowest');
 await page.keyboard.press('End');const widest=await chatW();
 assert(widest===Math.round(await page.evaluate(()=>document.querySelector('#agent-view .agent-layout').getBoundingClientRect().width))-420,'End leaves the results 420px');
 assert(await page.evaluate(()=>localStorage.getItem('interspace.splitWidth'))===String(widest),'Width remembered');
 {const r=await handle.evaluate(h=>{const b=h.getBoundingClientRect();return {x:b.left,y:b.top+200};});await page.mouse.dblclick(r.x,r.y);}
 assert(await chatW()===420,'Double-click resets');

 // The page itself never scrolls in the split reader, even when something asks to scroll an element into view.
 await page.evaluate(()=>{document.getElementById('agent-message').scrollIntoView({block:'end'});document.documentElement.scrollTop=300;window.scrollTo(0,400);});
 await page.waitForFunction(()=>window.scrollY===0);
 assert(await page.evaluate(()=>document.getElementById('agent-topbar').getBoundingClientRect().top>=0),'Top bar stays in view');

 // Default display: one-line search summaries, reasoning summary, failed call in full.
 const s1=await text(stream.locator('[data-item=s1]'));
 assert(s1.startsWith('Searched “fallback '+XSS+'” in OpenAlex, Crossref: 3 papers'),'Search summary: '+s1);
 assert((await text(stream.locator('[data-item=s2]'))).includes('Looked up doi:10.5555/fb.1: found “Fallback paper 1”'),'Lookup summary');
 assert((await text(stream.locator('[data-item=s5]'))).startsWith('Saved the report as report.md (1,234 characters).'),'Save summary');
 assert((await text(stream.locator('[data-item=s4]'))).startsWith('Read the corpus: 2 not checked papers'),'Corpus summary: '+await text(stream.locator('[data-item=s4]')));
 assert(await stream.locator('[data-item=s1] .paper').count()===0,'Summary has no paper list');
 assert((await text(stream.locator('[data-item=s3]'))).includes('Crossref did not answer.'),'Failed call shown in full');
 const think=await text(stream.locator('[data-item=think1] .reasoning-summary'));
 assert(think.startsWith('Reasoning')&&think.endsWith('…')&&!think.includes('check every reference')&&await stream.locator('[data-item=think1] details').evaluate(d=>!d.open),'Reasoning summary: '+think);
 // Show details expands one search in place, by keyboard.
 await stream.locator('[data-item=s1]').getByRole('button',{name:'Show details'}).focus();await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream [data-item=s1] .paper').length===3);
 await stream.locator('[data-item=s1]').getByRole('button',{name:'Show less'}).click();
 assert(await stream.locator('[data-item=s1] .paper').count()===0,'Show less');

 // Conversation detail: Simple by default (also when the saved display has no `detail`), Detailed saves.
 assert(await page.evaluate(()=>window.interspaceDisplay.get().detail)==='simple','Detail defaults to simple');
 await page.locator('[data-view=settings]').click();
 const detail=page.locator('#display-settings fieldset',{hasText:'Conversation detail'});
 assert(await detail.count()===1&&(await detail.getByLabel('Simple').isChecked())&&!(await detail.getByLabel('Detailed').isChecked()),'Simple checked by default');
 assert((await text(detail)).includes('Simple folds team and subagent details into one line you can open. Detailed shows everything.'),'Detail help text');
 await detail.getByLabel('Detailed').check();
 await page.waitForFunction(()=>window.rFixture.requests.some(r=>r.method==='display_update'&&r.params.display.detail==='detailed'));
 assert((await requests(page,'display_update')).at(-1).display.detail==='detailed','Detailed sent');
 await page.evaluate(()=>window.interspaceDisplay.setDetail('simple'));
 await page.waitForFunction(()=>window.rFixture.requests.filter(r=>r.method==='display_update').at(-1).params.display.detail==='simple');
 await page.locator('[data-view=research]').click();await page.locator('[data-open-task=r1]').click();
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream .message').length===2);

 // Settings: hide searches, thinking, plans and notes; replies and the failed call stay.
 await page.locator('[data-view=settings]').click();
 const settings=page.locator('#display-settings');
 await settings.getByLabel('Hidden').first().check();
 await page.waitForFunction(()=>window.rFixture.requests.some(r=>r.method==='display_update'));
 for(const label of ['Plans','Status notes (scope, token and status lines)'])await settings.getByLabel(label).uncheck();
 await settings.locator('#display-searches-hidden').check();
 await page.waitForFunction(()=>document.querySelector('#display-settings .display-status')?.textContent==='Saved.');
 const sent=(await requests(page,'display_update')).at(-1).display;
 assert(sent.thinking==='hidden'&&sent.searches==='hidden'&&sent.plans===false&&sent.notes===false&&sent.tools===true,'Sent: '+JSON.stringify(sent));
 await page.locator('[data-view=research]').click();await page.locator('[data-open-task=r1]').click();
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream .message').length===2);
 for(const key of ['s1','s2','think1','plan1'])assert(await stream.locator('[data-item='+key+']').count()===0,key+' hidden');
 assert(await stream.locator('.row-event').count()===0,'Status notes hidden');
 assert(await stream.locator('[data-item=s3]').count()===1,'Failed call still shown');
 assert((await text(stream)).includes('The evidence on fallback is thin.'),'Reply still shown');

 // Full: whole reasoning, whole search cards.
 await page.locator('[data-view=settings]').click();await page.locator('#display-thinking-full').check();await page.locator('#display-searches-full').check();
 await page.waitForFunction(()=>window.rFixture.requests.filter(r=>r.method==='display_update').at(-1)?.params.display.searches==='full');
 await page.locator('[data-view=research]').click();await page.locator('[data-open-task=r1]').click();
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream [data-item=s1] .paper').length===3);
 assert((await text(stream.locator('[data-item=think1]'))).includes('check every reference'),'Full reasoning');

 // Narrow: the panel is the Details tab.
 await page.setViewportSize({width:800,height:900});
 await page.waitForFunction(()=>!document.querySelector('#agent-view.split')); // The split reader leaves on the next frame.
 const details=page.locator('[data-agent-tab=details]');
 await details.waitFor();
 assert(await panel.isHidden(),'Panel hidden on Conversation when narrow');
 await details.click();
 assert(await panel.isVisible()&&await stream.isHidden()&&await page.locator('#agent-detail-toggle').isHidden(),'Details tab shows the panel');
 assert((await text(panel)).includes('report.md'),'Outputs in Details');
 await page.locator('[data-agent-tab=conversation]').click();
 assert(await stream.isVisible()&&await panel.isHidden()&&await page.locator('.agent-main #agent-detail-toggle').isVisible(),'Back to Conversation, with the Simple/Detailed toggle above it');
 const fit=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);
 assert(fit,'No sideways scroll when narrow');
 await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join('; '));
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 return {checks:'Simple | Detailed switch (current view pressed) in the split top bar and above the narrow conversation, details panel beside the conversation (Details tab when narrow), one-line search summaries with Show details/less by keyboard, reasoning summary, failed calls always shown, settings hide searches/thinking/plans/notes with replies kept, full mode, literal text, no sideways scroll'};
}
