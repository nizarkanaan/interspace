/* Research tool cards, the citation report, research call counts and the outputs panel, from fixture events only
   (docs/superpowers/specs/research/tools.md, tasks.md): no backend, network or model. All strings are synthetic. */
import {isDeepStrictEqual} from 'node:util';
import {install,requests,push,assert,text,fit,ev,resetSeq} from './research-fixture.mjs';
const XSS='<img src=x onerror="window.pwned=1">';
const paper=(i,extra={})=>({v:1,title:'Synthetic paper '+i,authors:['Ada Example','Bo Sample','Cy Placeholder','Di Fixture'],year:2020+(i%5),venue:'Fixture Conference',doi:'10.5555/fixture.'+i,arxiv_id:null,s2_id:null,openalex_id:null,abstract:null,citation_count:1234+i,url:'https://example.org/paper/'+i,oa_url:null,retracted:false,sources:['semantic_scholar','openalex'],...extra});
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 const papers=[paper(0,{title:XSS+' title',venue:'<script>window.pwned=1</script>',url:'javascript:window.pwned=1'}),paper(1,{retracted:true,oa_url:'http://insecure.example.org/1.pdf'}),paper(2,{oa_url:'https://example.org/open/2.pdf'}),paper(3,{authors:[]}),paper(4),paper(5),paper(6),paper(7)];
 const search={papers,searched:['semantic_scholar','openalex'],skipped:[{source:'unpaywall',reason:'not_configured'}]};
 const report={v:1,checked_at:'2026-11-19T10:05:00Z',summary:{verified:99,mismatch:0,not_found:0,retracted:0,unchecked:0},references:[
  {index:0,input:{title:'Synthetic verified paper',authors:['Ada Example'],year:2021},status:'verified',fields:[],match:paper(10,{title:'Synthetic verified paper'}),similarity:0.99,source:'crossref'},
  {index:1,input:{raw:'Sample, B. (2019). A mismatched '+XSS+' paper.'},status:'mismatch',fields:['year','authors','arxiv_id'],match:paper(11,{url:'javascript:window.pwned=1'}),similarity:0.93,source:'openalex'},
  {index:2,input:{title:'An invented paper that does not exist'},status:'not_found',fields:[],match:null,similarity:0.41,source:null},
  {index:3,input:{title:'A retracted synthetic paper',doi:'10.5555/retracted'},status:'retracted',fields:[],match:paper(12,{retracted:true}),similarity:1,source:'crossref'},
  {index:4,input:{title:'Unchecked synthetic paper'},status:'unchecked',reason:'every_source_skipped',fields:[],match:null,similarity:null,source:null},
  {index:5,input:{title:'Strange status paper'},status:'confirmed',fields:[],match:null},
  ...Array.from({length:6},(_,i)=>({index:6+i,input:{title:'Synthetic extra '+i},status:'verified',fields:[],match:paper(20+i),similarity:0.95,source:'crossref'}))]};
 const call=(id,tool,input)=>ev('r1','tool_call',{call_id:id,category:'research',tool,title:tool,input:{tool,...input},decision:{decision:'allow',rule:'research.allow',scope_version:1}},id);
 const result=(id,data,extra={})=>ev('r1','tool_result',{call_id:id,status:'ok',duration_ms:42,output:{text:typeof data==='string'?data:JSON.stringify(data),truncated:false,blob_id:null},error:null,...extra},id);
 const history=[
  ev('r1','status',{state:'running',detail:'',queue_position:null,reason:null}),
  call('c1','research_search',{query:'synthetic '+XSS+' query'}),result('c1',search),
  call('c2','research_paper',{id:'doi:10.5555/fixture.2'}),result('c2',{paper:paper(2,{abstract:'An abstract with '+XSS+' inside.'}),sources:['crossref']}),
  call('c3','research_bibtex',{id:'10.5555/fixture.2'}),result('c3',{entries:[{id:'10.5555/fixture.2',bibtex:'@article{fixture2, title={'+XSS+'}}',error:null},{id:'arXiv:0000.00000',bibtex:null,error:'not_found'}]}),
  call('c4','research_search',{query:'cut short'}),ev('r1','tool_result',{call_id:'c4',status:'ok',duration_ms:5,output:{text:'{"papers":[{"title":"Synthetic cut',truncated:true,blob_id:'blob-c4'},error:null},'c4'),
  ev('r1','tool_call',{call_id:'c5',category:'research',tool:'research_search',title:'research_search',input:{tool:'research_search',source:'unpaywall',query:'denied query'},decision:{decision:'deny',rule:'research.off',scope_version:1}},'c5'),
  ev('r1','tool_result',{call_id:'c5',status:'denied',output:{text:'',truncated:false,blob_id:null},error:{code:'denied',message:'Unpaywall is off in this task’s scope.'}},'c5'),
  call('c6','research_fulltext',{id:'10.5555/fixture.1'}),result('c6',{oa_url:'https://example.org/open/1.pdf',license:'cc-by',version:'publishedVersion',host_type:'repository',source:'unpaywall'}),
  ev('r1','citation_report',report,'cr1'),
  ev('r1','research_usage',{calls:{semantic_scholar:3,arxiv:1},cached:{semantic_scholar:1}}),
  ev('r1','outputs',{outputs:[{name:'report.md',kind:'report',bytes:2048},{name:'references.bib',kind:'bibtex',bytes:512}]}),
  ev('r1','status',{state:'idle',detail:'',queue_position:null,reason:null})];
 await install(page,url,{display:{v:1,thinking:'full',searches:'full',tools:true,citations:true,plans:true,notes:true},researchRows:[{id:'r1',mode:'agent',kind:'research',project_id:null,title:'Synthetic related work',status:'idle',provider:'codex',model:null}],history:{r1:history},
  scopes:{r1:{v:1,task_id:'r1',version:1,projects:[],network:{default:'deny',allow_hosts:[],deny_hosts:[]},apps:[],web_search:'deny',limits:{token_budget:250000,time_limit_s:3600},research:{sources:{semantic_scholar:'allow',arxiv:'allow',unpaywall:'off'}}}},
  outputs:{r1:[{name:'report.md',kind:'report',bytes:2048},{name:'references.bib',kind:'bibtex',bytes:512}]}});
 await page.evaluate(x=>{window.rFixture.blobs={'blob-c4':JSON.stringify({papers:[{title:'Synthetic full result',authors:[],year:2024,venue:null,citation_count:0,url:null,oa_url:null,sources:['arxiv']}],searched:['arxiv'],skipped:[]})};window.rFixture.readable={r1:{'report.md':'# Related work\n\nA paragraph with **bold**, *care*, `code` and '+x+'.\n\n- First point [a safe link](https://example.org/a)\n- Second point [an unsafe link](javascript:window.pwned=1)\n- Third point [https://doi.org/10.5555/x](https://evil.example/phish)\n\n1. Ordered\n\n> A quote\n\n```\n<script>window.pwned=1</script>\n```','references.bib':'@article{fixture2,\n  title={'+x+'}\n}'}};},XSS);
 await page.locator('[data-view=research]').click();
 // Checking citations is the agents' instruction, not a guarantee: no screen promises that every citation was checked.
 const claims=await page.evaluate(()=>[document.getElementById('heading-note').textContent,document.getElementById('research-empty').textContent,document.querySelector('input[name=new-kind][value=research]')?.closest('label')?.textContent||''].join(' | '));
 assert(!/every citation|check every|every reference/i.test(claims)&&claims.includes('citation report'),'Overclaim: '+claims);
 await page.locator('[data-open-task=r1]').click();
 const stream=page.locator('#agent-stream');
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream .card.research').length===6);
 const card=n=>stream.locator('.card.research').nth(n);

 // Search: paper list with title, authors, year, venue, source badges, citation count; literal text; https links only.
 const c1=await text(card(0));
 assert(c1.includes('Search papers')&&c1.includes('“synthetic '+XSS+' query”')&&c1.includes(XSS+' title'),'Search card text: '+c1);
 assert(c1.includes('Ada Example, Bo Sample, Cy Placeholder et al.')&&c1.includes('Fixture Conference')&&c1.includes('1,236 citations'),'Paper metadata');
 assert(c1.includes('<script>window.pwned=1</script>')&&c1.includes('Searched Semantic Scholar, OpenAlex')&&c1.includes('Skipped: Unpaywall (not set up)'),'Searched/skipped/literal venue');
 assert(await card(0).locator('.source-badge').first().textContent()==='Semantic Scholar','Source badge');
 assert((await text(card(0).locator('.paper').nth(1))).includes('Retracted'),'Retracted flag');
 const links=await stream.locator('a').evaluateAll(as=>as.map(a=>a.getAttribute('href')));
 assert(links.length&&links.every(h=>h.startsWith('https://')),'Non-https link: '+JSON.stringify(links));
 assert(await card(0).locator('.paper').nth(0).locator('a').count()===0&&await card(0).locator('.paper').nth(1).getByRole('link',{name:/Open-access/}).count()===0,'Unsafe paper link shown');
 assert(await card(0).locator('.paper').nth(2).getByRole('link',{name:/Open-access copy of Synthetic paper 2/}).count()===1,'https open-access link missing');
 // Long lists collapse: 5 shown, then all by keyboard, then fewer.
 assert(await card(0).locator('.paper').count()===5,'Not collapsed to 5');
 const more=card(0).getByRole('button',{name:'Show all 8 papers',exact:true});
 assert(await more.getAttribute('aria-expanded')==='false','aria-expanded');
 await more.focus();await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream .card.research')[0].querySelectorAll('.paper').length===8);
 await card(0).getByRole('button',{name:'Show fewer',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream .card.research')[0].querySelectorAll('.paper').length===5);

 // Paper lookup with a collapsible abstract; BibTeX as literal text; a missing entry says so.
 assert((await text(card(1))).includes('Look up a paper')&&await card(1).locator('details.paper-abstract').count()===1,'Paper card');
 assert((await text(card(1).locator('details'))).includes('An abstract with '+XSS),'Abstract literal');
 const c3=await text(card(2));
 assert(c3.includes('@article{fixture2, title={'+XSS+'}}')&&c3.includes('No BibTeX: not found'),'BibTeX card: '+c3);
 // A cut result is shown raw, then the full result from its blob is shown as papers.
 assert((await text(card(3))).includes('cut short, so it is shown as raw text'),'Truncated note');
 await card(3).getByRole('button',{name:'Show full result',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream .card.research')[3].textContent.includes('Synthetic full result'));
 assert(JSON.stringify(await requests(page,'task_blob'))===JSON.stringify([{task_id:'r1',blob_id:'blob-c4'}]),'Blob request');
 // A denied call: its state and reason, no result.
 const c5=await text(card(4));
 assert(c5.includes('Denied')&&c5.includes('Denied by research.off')&&c5.includes('Unpaywall is off'),'Denied card: '+c5);
 assert((await text(card(5))).includes('Find an open copy')&&(await text(card(5))).includes('cc-by · publishedVersion · repository · from Unpaywall'),'Fulltext card');

 // Citation report: counts from the rows (the fixture summary's 99 is ignored); each status in plain words.
 const rep=stream.locator('.card.citation-report');
 const sum=await text(rep.locator('.citation-summary'));
 assert(sum.includes('7 verified')&&sum.includes('1 mismatch')&&sum.includes('1 not found')&&sum.includes('1 retracted')&&sum.includes('1 unchecked')&&sum.includes('1 unknown')&&!sum.includes('99'),'Summary: '+sum);
 assert((await text(rep)).includes('5 references are not verified'),'Not-verified count');
 // Honest scope of "Verified": year and first author count only when the reference gives them.
 const repText=await text(rep);
 assert(repText.includes('Verified means a published record matched: title at least 90% similar, plus the year (within one) and the first author when the reference gives them.')&&!repText.includes('on title, year and first author'),'Verified claim: '+repText);
 assert((await text(rep.locator('.card-head'))).includes('12 references')&&!(await text(rep.locator('.card-head'))).includes('checked'),'Head counts unchecked rows as checked');
 assert((await text(rep.locator('.retracted-alert'))).includes('1 reference is retracted. Do not cite it.'),'Retracted alert');
 // Problem rows come first, so a collapsed report never hides a retracted or unverified reference behind Show all.
 const row=n=>rep.locator('.reference').nth(n);
 const r0=await text(row(0));
 assert(r0.startsWith('Reference 4')&&r0.includes('Retracted: do not cite'),'Retracted row first: '+r0);
 const r1=await text(row(1));
 assert(r1.startsWith('Reference 2')&&r1.includes('Not verified: differs from the published record in year, authors, arXiv ID')&&r1.includes('A mismatched '+XSS+' paper')&&r1.includes('Closest record:'),'Mismatch row: '+r1);
 assert(await row(1).locator('a').count()===0,'Unsafe match link');
 assert((await text(row(2))).includes('Not verified: not found in the sources checked'),'Not found row');
 assert((await text(row(3))).includes('Unknown result (confirmed): not verified'),'Unknown status row');
 assert((await text(row(4))).includes('Not checked: every source skipped'),'Unchecked row');
 const v=await text(row(5));
 assert(v.startsWith('Reference 1')&&v.includes('Verified')&&v.includes('Matched: Synthetic verified paper')&&v.includes('checked with Crossref · title similarity 99%'),'Verified row: '+v);
 for(let i=0;i<5;i++)assert(!(await text(row(i).locator('.reference-status'))).startsWith('Verified'),'Row '+i+' looks verified');
 assert(await rep.locator('.reference').count()===10,'Report not collapsed to 10');
 await rep.getByRole('button',{name:'Show all 12 references',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('#agent-stream .citation-report .reference').length===12);

 // Helpers for Simple's work line and citation pointer (2026-11-27-simple-chat-view-design.md): one-line summaries,
 // counts of what a turn folded, and one shared citation count.
 const same=(got,want,m)=>assert(isDeepStrictEqual(got,want),m+': '+JSON.stringify(got));
 const sq={tool:'research_search',category:'research',input:{tool:'research_search',query:'x'}};
 same(await page.evaluate(c=>window.interspaceResearchCards.summaryText({call:c}),sq),'Searching “x”','Running summary');
 same(await page.evaluate(c=>window.interspaceResearchCards.summaryText({call:c,result:{status:'ok'},output:JSON.stringify({searched:['semantic_scholar'],papers:[{title:'A'},{title:'B'}]})}),sq),'Searched “x” in Semantic Scholar: 2 papers','Done summary');
 same(await page.evaluate(r=>window.interspaceResearchCards.citationCounts(r),report),{total:12,counts:{verified:7,mismatch:1,not_found:1,retracted:1,unchecked:1},other:1,problems:5},'citationCounts');
 same(await page.evaluate(r=>window.interspaceResearchCards.citationPointerText(r),report),'Citations: 7 of 12 verified · 1 mismatch · 1 not found · 1 unchecked · 1 unknown · 1 retracted: do not cite','citationPointerText');
 const ok=(tool,input,data,extra={})=>({call:{tool,category:'research',input:{tool,...input}},result:{status:'ok',output:{text:JSON.stringify(data),truncated:false,blob_id:null,...extra}}});
 const s1=ok('research_search',{query:'a'},{searched:['semantic_scholar','arxiv'],papers:[{doi:'10.1/A',title:'A'},{doi:'10.1/b',title:'B'}]});
 const s2=extra=>ok('research_search',{query:'b'},{searched:['arxiv','openalex'],papers:[{doi:'10.1/a',title:'A again'},{arxiv_id:'2401.1',title:'C'}]},extra);
 const rest=[ok('research_paper',{id:'doi:10.1/a'},{paper:{title:'A'}}),ok('save_report',{},{saved:'report.md',characters:10}),
  {sub:{task_id:'c1',provider:'codex',role:'citation_checker'}},{team:{answered:{decision:'approve'}}},
  {citation:{references:[{status:'verified'},{status:'verified'},{status:'verified'}]}},{reasoning:'x'},{row:'budget',text:'t'}];
 const parts=items=>page.evaluate(list=>window.interspaceResearchCards.workParts(list),items);
 same(await parts([s1,s2(),...rest]),['Team approved','Codex citation checker finished','Searched 3 sources 2 times','3 papers','looked up 1','saved report.md','3 references checked: all verified','9 steps'],'workParts');
 same(await parts([s1,s2({truncated:true}),...rest]),['Team approved','Codex citation checker finished','Searched 3 sources 2 times','looked up 1','saved report.md','3 references checked: all verified','9 steps'],'workParts with a cut search');
 same(await parts([s1]),['Searched 2 sources once','2 papers','1 step'],'workParts with one search');
 same(await parts([ok('record_claim_support',{},{recorded:4}),ok('record_table_cells',{},{recorded:12})]),['recorded 4 claim verdicts','recorded 12 evidence values','2 steps'],'workParts with records');
 same(await page.evaluate(()=>window.interspaceResearchCards.workerName({provider:'codex',role:'citation_checker'})),'Codex citation checker','workerName');
 // The brief card (Simple's Show citation report): counts, the retracted alert and only the problem rows, problems first.
 await page.evaluate(r=>{const box=document.createElement('div');box.id='brief-card';box.className='card';document.body.append(box);const state={};
  const draw=()=>{box.replaceChildren();window.interspaceResearchCards.citationCard(box,r,{state,bump:draw,brief:true});};draw();},report);
 const brief=page.locator('#brief-card');
 assert(await brief.locator('.reference').count()===5,'Brief rows: '+await brief.locator('.reference').count());
 assert((await text(brief.locator('.reference').first())).includes('Retracted: do not cite'),'Brief retracted row first');
 same(await brief.locator(':scope > p.footnote').allTextContents(),['5 references are not verified.'],'Brief footnote');
 assert(!(await text(brief)).includes('Checked at')&&(await text(brief.locator('.retracted-alert'))).includes('1 reference is retracted. Do not cite it.'),'Brief card text: '+await text(brief));
 await brief.getByRole('button',{name:'Show all 12 references',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('#brief-card .reference').length===12);
 await page.evaluate(()=>document.getElementById('brief-card').remove());

 // Research requests per source (Wave 2A: requests sent, and answers from the cache), never money.
 const head=await text(page.locator('#agent-head'));
 assert(head.includes('Research requests: Semantic Scholar 3 sent, 1 answered from cache · arXiv 1 sent')&&!head.includes('calls'),'Usage line: '+head);
 assert(!/[$€£]|cost|price/i.test(head),'Money in header');
 // A research task has no project: no Review changes, and it says so.
 assert(head.includes('Research task: no project')&&await page.locator('#agent-view').getByRole('button',{name:/Review/}).count()===0,'Research header / Review');
 assert((await page.locator('#agent-back').textContent())==='← Research','Back label');

 // Outputs: report as text-safe Markdown, BibTeX as plain text, Save through the save panel.
 const out=page.locator('#agent-outputs');
 assert(await out.isVisible()&&(await text(out)).includes('report.md')&&(await text(out)).includes('Report · 2.0 KB')&&(await text(out)).includes('BibTeX references · 512 bytes'),'Outputs list');
 // The report opens in the Report tab at reading width (2026-11-20-report-reader-design.md).
 await out.getByRole('button',{name:'Read report.md',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-report .report-md'));
 assert((await page.locator('[data-agent-tab=report]').getAttribute('aria-pressed'))==='true'&&await page.locator('#agent-results #agent-report').isVisible(),'Report tab open');
 const md=page.locator('#agent-report .report-md');
 assert(await md.locator('h3').textContent()==='Related work'&&await md.locator('strong').textContent()==='bold'&&await md.locator('em').textContent()==='care'&&await md.locator('li').count()===4,'Markdown structure');
 assert((await text(md)).includes(XSS)&&(await text(md)).includes('<script>window.pwned=1</script>')&&await md.locator('img,script').count()===0,'Markdown not text-safe');
 const mdLinks=await md.locator('a').evaluateAll(as=>as.map(a=>a.getAttribute('href')));
 assert(JSON.stringify(mdLinks)===JSON.stringify(['https://example.org/a','https://evil.example/phish'])&&(await text(md)).includes('an unsafe link (javascript:window.pwned=1)'),'Markdown links: '+JSON.stringify(mdLinks));
 // A link's real host is always visible, so link text that looks like another address cannot hide where it goes.
 assert((await text(md)).includes('a safe link (example.org)')&&(await text(md)).includes('https://doi.org/10.5555/x (evil.example)'),'Link host not shown: '+await text(md));
 assert(await md.locator('a').evaluateAll(as=>as.every(a=>!a.textContent.includes('evil.example')||a.getAttribute('href').includes('evil.example'))),'Host inside link text');
   await page.locator('[data-agent-tab=details]').click(); // Outputs live under Scope and outputs in the split reader.
   await out.getByRole('button',{name:'View references.bib',exact:true}).focus();await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.querySelector('#agent-outputs .output-text'));
 assert((await out.locator('.output-text').textContent()).includes('title={'+XSS+'}'),'BibTeX text');
 assert((await text(out.locator('[data-output="references.bib"]'))).includes('Holds the references the citation checker verified; mismatched ones are marked in a comment, and not-found or retracted ones are left out.'),'BibTeX output note');
 assert(JSON.stringify(await requests(page,'task_output_read'))===JSON.stringify([{task_id:'r1',name:'report.md'},{task_id:'r1',name:'references.bib'}])&&(await requests(page,'task_outputs')).length===0,'task_output_read params');
 assert(await page.evaluate(()=>document.activeElement?.id)==='output-view-references_bib','Focus lost after View');
 await out.getByRole('button',{name:'Save references.bib',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-outputs [data-output="references.bib"]').textContent.includes('Saved.'));
 await page.evaluate(()=>{window.rFixture.saved=false;});
 await out.getByRole('button',{name:'Save report.md',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-outputs [data-output="report.md"]').textContent.includes('Not saved.'));
 assert(JSON.stringify(await requests(page,'task_output_save'))===JSON.stringify([{task_id:'r1',name:'references.bib'},{task_id:'r1',name:'report.md'}]),'Save params');
 assert(await out.locator('.report-md').count()===0,'Report is not shown inside the panel');

 // Live events keep adding cards without losing the open BibTeX view.
 await push(page,[ev('r1','research_usage',{calls:{semantic_scholar:4,arxiv:1},cached:{semantic_scholar:1}})]);
 await page.waitForFunction(()=>document.querySelector('#agent-head').textContent.includes('Semantic Scholar 4 sent'));
 assert(await out.locator('.output-text').count()===1,'Open view lost on update');

 const fits=await fit(page,'research-cards',null,true);
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'research tool cards (search with title/authors/year/venue/source badges/citations/retracted flag, searched and skipped, paper with abstract, BibTeX, open copy, denied call, cut result then full blob), https-only links, collapsible long lists by keyboard, citation report counts from rows with verified/mismatch fields/not found/retracted/unchecked reason/unknown, problem rows first with reference numbers, retracted callout, honest Verified meaning, nothing else looks verified, per-source requests sent and cache answers without money, link host shown after markdown links, BibTeX output note, work-line helpers (summaryText, workParts with distinct papers and a cut search, workerName), citationCounts and the citation pointer text, brief citation card with problem rows only then Show all, no every-citation claim, no Review for research tasks, outputs panel with text-safe Markdown report and plain BibTeX, task_output_read per file, Save and cancelled save, live update keeps open view, literal text everywhere, light/dark 320-1280 fit',responsiveStates:fits.length};
}
