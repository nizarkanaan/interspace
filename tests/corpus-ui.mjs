/* Corpus tab (docs/superpowers/specs/2026-11-20-task-corpus-design.md), from fixture data only: the tab shows on root
   research tasks, unverified references come first, papers carry their verdict in words, search, filters and sort
   work by keyboard, values stay literal and links https only, and it refetches after a `corpus` event. */
import {install,requests,push,assert,text,fit,ev,resetSeq} from './research-fixture.mjs';
const XSS='<img src=x onerror="window.pwned=1">';
const rec=(i,extra={})=>({v:1,title:'Corpus paper '+i,authors:['Ada Example','Bo Sample'],year:2010+i,venue:'Fixture Journal',doi:'10.5555/corpus.'+i,arxiv_id:null,abstract:null,citation_count:i*10,url:'https://example.org/p/'+i,oa_url:null,retracted:false,sources:['crossref'],...extra});
const entry=(i,check=null,extra={})=>({paper:rec(i,extra),found:[{tool:'research_search',query:'query '+i,member:i%2?'Researcher':'Orchestrator',at:'2026-11-20T10:00:00Z'}],check});
const CORPUS={v:1,updated_at:'2026-11-20T10:00:00Z',full:false,incomplete:1,
 papers:[entry(0,{status:'verified',by:'orchestrator'}),entry(1,null,{title:XSS+' title',url:'javascript:window.pwned=1',oa_url:'https://example.org/oa/1.pdf'}),
  entry(2,{status:'retracted',by:'orchestrator'},{retracted:true}),...Array.from({length:55},(_,i)=>entry(3+i))],
 unverified:[{key:'title:x',reference:{title:'A mismatched '+XSS+' reference',authors:['Bo Sample'],year:2012},status:'mismatch',fields:['year'],closest:rec(90,{year:2015,url:'javascript:window.pwned=1'}),by:'orchestrator'},
  {key:'title:y',reference:{raw:'Nobody, A. (2031). An invented paper.'},status:'not_found',fields:[],closest:null,by:'member'}]};

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 const history=[ev('r1','status',{state:'idle',detail:'',queue_position:null,reason:null}),ev('r1','message',{role:'assistant',text:'Done.',final:true},'m1')];
 await install(page,url,{researchRows:[{id:'r1',mode:'agent',kind:'research',project_id:null,title:'Synthetic corpus task',status:'idle',provider:'codex',model:null}],history:{r1:history},corpora:{r1:CORPUS}});
 // Tabs are tested in a narrow window; wide windows show the split reader (display-ui, reader-ui).
 await page.setViewportSize({width:1000,height:900});
 await page.locator('[data-view=research]').click();
 await page.locator('[data-open-task=r1]').click();
 const tabs=page.locator('#agent-tabs');
 await tabs.waitFor();
 assert(await tabs.isVisible(),'Corpus tabs on a research task');
 assert((await page.locator('[data-agent-tab=conversation]').getAttribute('aria-pressed'))==='true','Conversation first');
 assert((await requests(page,'task_corpus')).length===0,'Corpus fetched before the tab opened');

 // Keyboard: open the Corpus tab.
 await page.locator('[data-agent-tab=corpus]').focus();await page.keyboard.press('Enter');
 const box=page.locator('#agent-corpus');
 await page.waitForFunction(()=>document.querySelectorAll('#agent-corpus .corpus-paper').length>0);
 assert(await page.locator('#agent-stream').isHidden()&&await page.locator('#agent-composer').isHidden(),'Conversation hidden on Corpus');
 const summary=await text(box.locator('.corpus-summary'));
 assert(summary==='58 papers · 1 verified · 2 references not verified','Summary: '+summary);
 assert((await text(box)).includes('Some earlier results could not be read'),'Incomplete note');

 // Unverified references come first, status in words, values literal, closest record never verified.
 assert(await page.evaluate(()=>{const u=document.querySelector('#agent-corpus .corpus-unverified'),l=document.querySelector('#agent-corpus .corpus-list');return !!(u&&l&&u.compareDocumentPosition(l)&Node.DOCUMENT_POSITION_FOLLOWING);}),'Unverified first');
 const u=await text(box.locator('.corpus-unverified'));
 assert(u.includes('References not verified (2)')&&u.includes('Not verified: differs from the published record in year')&&u.includes('A mismatched '+XSS+' reference')&&u.includes('Closest record: Corpus paper 90')&&u.includes('Not verified: not found in the sources checked')&&u.includes('Nobody, A. (2031). An invented paper.'),'Unverified text: '+u);

 // Papers: verdict words, provenance, literal text, https-only links, 50 shown then all.
 const papers=box.locator('.corpus-paper');
 assert(await papers.count()===50,'Collapsed to 50');
 assert((await text(papers.nth(0))).includes('Verified')&&(await text(papers.nth(0))).includes('Found by Orchestrator (search “query 0”).'),'Verified paper');
 assert((await text(papers.nth(1))).includes(XSS+' title')&&(await text(papers.nth(1))).includes('Not checked'),'Literal unchecked paper');
 assert((await text(papers.nth(2))).includes('Retracted: do not cite'),'Retracted paper');
 const links=await box.locator('a').evaluateAll(as=>as.map(a=>a.getAttribute('href')));
 assert(links.length&&links.every(h=>h.startsWith('https://')),'Non-https link: '+JSON.stringify(links));
 await page.locator('#corpus-more').click();
 assert(await papers.count()===58,'Show all');

 // Filters are toggle buttons with counts.
 assert((await text(page.locator('#corpus-filter-verified')))==='Checked 2','Checked filter count');
 await page.locator('#corpus-filter-verified').click();
 assert((await page.locator('#corpus-filter-verified').getAttribute('aria-pressed'))==='true','Filter pressed');
 assert(await papers.count()===2&&(await text(box.locator('.corpus-count')))==='Showing 2 of 58 papers','Checked filter');
 await page.locator('#corpus-filter-open').click();
 assert(await papers.count()===1,'Open access filter');
 await page.locator('#corpus-filter-all').click();

 // Search keeps focus while typing; sort by most cited.
 await page.locator('#corpus-search').focus();await page.keyboard.type('paper 5');
 assert(await page.evaluate(()=>document.activeElement?.id)==='corpus-search','Search keeps focus');
 const found=await papers.count();
 assert(found===9&&(await text(box.locator('.corpus-count')))==='Showing 9 of 58 papers','Search results: '+found);
 await page.locator('#corpus-search').fill('');
 await page.locator('#corpus-sort').selectOption('cited');
 assert((await text(papers.nth(0).locator('.paper-title'))).includes('Corpus paper 57'),'Most cited first');
 await page.locator('#corpus-search').fill('no such paper');
 assert((await text(box)).includes('No papers match.'),'No match message');
 await page.locator('#corpus-search').fill('');

 // A corpus event refetches (debounced) while the tab is open.
 const before=(await requests(page,'task_corpus')).length;
 await push(page,[ev('r1','corpus',{papers:59,unverified:2})]);
 await page.waitForFunction(n=>window.rFixture.requests.filter(r=>r.method==='task_corpus').length>n,before,{timeout:5000});

 // A corpus event that lands while a fetch is still out triggers a fresh fetch afterwards (the live run showed 0 papers).
 {const n=(await requests(page,'task_corpus')).length;
  await page.evaluate(()=>{window.rFixture.hold.task_corpus=true;});
  await push(page,[ev('r1','corpus',{papers:60,unverified:2})]);
  await page.waitForFunction(k=>window.rFixture.requests.filter(r=>r.method==='task_corpus').length>k,n,{timeout:5000});
  await push(page,[ev('r1','corpus',{papers:61,unverified:2})]);
  await page.waitForTimeout(1500);
  await page.evaluate(()=>{const f=window.rFixture;f.hold.task_corpus=false;for(const r of f.held.splice(0))f.respond(r,{v:1,papers:[],unverified:0,full:[]});});
  await page.waitForFunction(k=>window.rFixture.requests.filter(r=>r.method==='task_corpus').length>k+1,n,{timeout:5000});}
 // The tab row stays pinned while the list scrolls, and a switch made there starts the new tab at its top.
 await page.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));
 assert(Math.abs(await page.evaluate(()=>document.getElementById('agent-tabs').getBoundingClientRect().top))<=1,'Tabs pinned');
 // Back to Conversation; the tab row is not shown for a project task's view.
 await page.locator('[data-agent-tab=conversation]').click();
 assert(await page.locator('#agent-stream').isVisible()&&await box.isHidden(),'Conversation again');
 assert(await page.evaluate(()=>innerHeight+scrollY>=document.documentElement.scrollHeight-2),'Conversation opens at its end');

 await page.locator('[data-agent-tab=corpus]').click();
 const fits=await fit(page,'corpus',null,process.env.INTERSPACE_SHOTS?true:false);
 assert(!errors.length,'Page errors: '+errors.join('; '));
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 return {checks:'corpus tab on research tasks only when opened, unverified first, verdict words, provenance, literal text, https links, 50 then all, filters with counts and aria-pressed, search keeps focus, sort, empty match, corpus event refetch, fit',fits:fits.length};
}
