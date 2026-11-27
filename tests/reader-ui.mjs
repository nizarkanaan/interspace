/* Report reader (docs/superpowers/specs/2026-11-20-report-reader-design.md), from fixture data only: Read opens the
   Report tab; [n] citations link to the report's own references; each reference shows the checker's verdict from the
   corpus in words; unmatched references say so; Back to text returns; values stay literal; it refetches on change. */
import {install,requests,push,assert,text,ev,resetSeq} from './research-fixture.mjs';
const XSS='<img src=x onerror="window.pwned=1">';
const REPORT=`# Fallback during outages

Fallback to other networks is described in standards [1] and measured once [2, 3]. Recovery timing is rarely reported [4–5].
A retracted study claimed more [3]. Unrelated brackets stay text: [x] and [99].

## References

1. Example, A. (2019). Emergency call fallback across mobile operators in practice. doi:10.5555/fb.1
2. Sample, B. (2021). Measuring 112 call recovery after network outages. arXiv:2101.00001
3. Wakefield, A. (1998). A retracted study of call routing reliability that was withdrawn. doi:10.5555/retracted
4. Nobody, C. (2031). An invented paper about network fallback timing ${XSS}.
5. Unknown, D. (2015). A paper the agents never searched for at all, about outages.
`;
const rec=(title,extra={})=>({v:1,title,authors:['A'],year:2020,venue:null,doi:null,arxiv_id:null,sources:['crossref'],...extra});
const CORPUS={v:1,full:false,incomplete:0,papers:[
 {paper:rec('Emergency call fallback across mobile operators in practice',{doi:'10.5555/fb.1'}),found:[],check:{status:'verified',by:'orchestrator'}},
 {paper:rec('Measuring 112 call recovery after network outages',{arxiv_id:'2101.00001'}),found:[],check:null},
 {paper:rec('RETRACTED: A retracted study of call routing reliability that was withdrawn',{doi:'10.5555/retracted',retracted:true}),found:[],check:{status:'retracted',by:'orchestrator'}}],
 unverified:[{key:'title:x',reference:{title:'An invented paper about network fallback timing'},status:'not_found',fields:[],closest:null,by:'orchestrator'}]};

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 const history=[ev('r1','message',{role:'assistant',text:'Done.',final:true},'m1'),ev('r1','outputs',{outputs:[{name:'report.md',kind:'report',bytes:900},{name:'references.bib',kind:'bibtex',bytes:100}]}),
  ev('r1','status',{state:'idle',detail:'',queue_position:null,reason:null})];
 await install(page,url,{researchRows:[{id:'r1',mode:'agent',kind:'research',project_id:null,title:'Fallback review',status:'idle',provider:'codex',model:null}],history:{r1:history},corpora:{r1:CORPUS},
  outputs:{r1:[{name:'report.md',kind:'report',bytes:900}]}});
 await page.evaluate(t=>{window.rFixture.readable={r1:{'report.md':t}};},REPORT);
 await page.setViewportSize({width:1440,height:900});
 await page.locator('[data-view=research]').click();await page.locator('[data-open-task=r1]').click();
 await page.locator('#output-read-report_md').waitFor();
 assert(await page.locator('#output-view-report_md').count()===0,'Report has no inline View');
 await page.locator('#output-read-report_md').focus();await page.keyboard.press('Enter');
 const reader=page.locator('#agent-report');
 await page.waitForFunction(()=>document.querySelectorAll('#agent-report .report-reference').length===5);
 assert(await reader.isVisible()&&await page.locator('#agent-stream').isVisible()&&await page.locator('#agent-details').isHidden()&&await page.locator('#agent-results #agent-report').count()===1,'Reader beside the conversation');

 // Verdicts in words, from the corpus.
 const verdict=async n=>text(reader.locator('#report-ref-'+n+' .report-verdict'));
 assert(await verdict(1)==='Verified'&&await verdict(2)==='Not checked'&&await verdict(3)==='Retracted: do not cite'&&await verdict(4)==='Not verified'&&await verdict(5)==='Not found by the agents: possibly cited from memory','Verdicts');
 assert((await text(reader.locator('.reader-summary')))==='5 references: 1 verified, 1 retracted, 1 not verified, 1 not checked, 1 not in the corpus.','Summary: '+await text(reader.locator('.reader-summary')));
 assert((await text(reader.locator('#report-ref-4'))).includes(XSS)&&await reader.locator('img,script').count()===0,'Literal reference text');

 // Citations link to references; unknown numbers and other brackets stay text; ranges link both ends.
 const links=await reader.locator('.cite-link').evaluateAll(as=>as.map(a=>a.textContent));
 assert(JSON.stringify(links)===JSON.stringify(['1','2','3','4','5','3']),'Citation links: '+JSON.stringify(links));
 assert((await text(reader)).includes('[x] and [99]'),'Unknown brackets kept');
 await reader.locator('.cite-link').nth(2).focus();await page.keyboard.press('Enter');
 assert(await page.evaluate(()=>document.activeElement?.id)==='report-ref-3','Citation focuses its reference');
 await reader.locator('#report-ref-3 .report-back').click();
 assert(await page.evaluate(()=>document.activeElement?.classList.contains('cite-link')&&document.activeElement.textContent==='3'),'Back to text');

 // Save from the reader; a changed report is fetched again while the tab is open.
 await page.locator('#reader-save').click();
 await page.waitForFunction(()=>document.querySelector('#agent-report .reader-note')?.textContent==='Saved.');
 const reads=(await requests(page,'task_output_read')).length;
 await page.evaluate(t=>{window.rFixture.readable.r1['report.md']=t+'\nAn added paragraph.';},REPORT);
 await push(page,[ev('r1','outputs',{outputs:[{name:'report.md',kind:'report',bytes:950}]})]);
 await page.waitForFunction(()=>document.querySelector('#agent-report').textContent.includes('An added paragraph.'));
 assert((await requests(page,'task_output_read')).length===reads+1,'Refetched once');
 assert(await reader.locator('.report-reference').count()===5&&(await text(reader.locator('.reader-summary'))).startsWith('5 references'),'A paragraph after the list is not a reference');
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'No sideways scroll');
 await page.setViewportSize({width:390,height:900});
 await page.waitForFunction(()=>!document.querySelector('#agent-view.split'));
 assert(await page.locator('#agent-focus').isHidden(),'Focus offered outside the split reader');
 {const wide=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&e.offsetParent).slice(0,4).map(e=>e.tagName+'#'+e.id+'.'+e.className+':'+Math.round(e.getBoundingClientRect().right)));
  assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'No sideways scroll at 390: '+JSON.stringify(wide));}
 await page.setViewportSize({width:1280,height:1000});
 // Leaving the split reader must free the page: Settings scrolls (the reader's scroll guard once pinned it to the top).
 await page.waitForFunction(()=>document.querySelector('#agent-view.split'));

 // Focus (2026-11-27-readable-workspace-design.md): the results pane takes the whole window; Esc or Exit focus returns.
 const focusButton=page.locator('#agent-focus'),chat=page.locator('#agent-view .agent-main'),aside=page.locator('aside'),banner=page.locator('#agent-focus-banner');
 const focused=()=>page.evaluate(()=>document.getElementById('agent-view').classList.contains('focus'));
 const collapsed=()=>page.evaluate(()=>document.body.classList.contains('sidebar-collapsed'));
 const store=()=>page.evaluate(()=>{const out={};for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);out[k]=localStorage.getItem(k);}return JSON.stringify(Object.entries(out).sort());});
 assert(await page.locator('#agent-tabs #agent-focus').count()===1&&await focusButton.isVisible()&&(await text(focusButton))==='Focus'&&await focusButton.getAttribute('aria-pressed')===null&&await focusButton.getAttribute('type')==='button','Focus button on the results tab row');
 const open=await store();
 await focusButton.click();
 assert(await focused()&&await page.evaluate(()=>window.interspaceAgent.isFocused())&&(await text(focusButton))==='Exit focus'&&await focusButton.getAttribute('aria-pressed')===null,'Focus on: the changing text says it, no aria-pressed');
 assert(await chat.isHidden()&&await aside.isHidden()&&await reader.isVisible()&&await banner.isHidden(),'Focus hides the conversation and the sidebar');
 {const share=await page.evaluate(()=>document.getElementById('agent-results').getBoundingClientRect().width/innerWidth);assert(share>=0.9,'Results pane share in Focus: '+share);}
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'No sideways scroll in Focus');
 // Every results tab works in Focus.
 await page.locator('[data-agent-tab=corpus]').click();
 assert(await focused()&&await page.locator('#agent-corpus').isVisible(),'Corpus in Focus');
 await page.locator('[data-agent-tab=report]').click();
 await page.keyboard.press('Escape');
 assert(!(await focused())&&!(await page.evaluate(()=>window.interspaceAgent.isFocused()))&&await chat.isVisible()&&await aside.isVisible()&&(await text(focusButton))==='Focus'&&await focusButton.getAttribute('aria-pressed')===null,'Esc exits Focus');
 assert(!(await collapsed())&&await store()===open,'Focus leaves an open sidebar open and saves nothing');
 // A collapsed sidebar stays collapsed after Focus, and Focus saves nothing.
 await page.locator('#sidebar-collapse').click();
 const shut=await store();
 assert(await collapsed()&&shut.includes('["interspace.sidebarCollapsed","1"]'),'Sidebar collapsed and saved');
 await focusButton.click();
 assert(await focused()&&await aside.isHidden(),'Focus over a collapsed sidebar');
 // The sidebar shortcut is ignored in Focus: it would change the saved choice with nothing to see.
 await page.keyboard.press('ControlOrMeta+Backslash');
 assert(await focused()&&await collapsed()&&await store()===shut,'Sidebar shortcut changed the sidebar in Focus');
 await focusButton.click();
 assert(!(await focused())&&await collapsed()&&await aside.isVisible()&&await store()===shut,'Collapsed sidebar kept and nothing saved');
 await page.locator('#sidebar-expand').click();
 // Showing or hiding the sidebar fits the saved conversation width to the window again, but never saves what it fitted.
 {
  const before=await page.evaluate(()=>localStorage.getItem('interspace.splitWidth'));
  const width=()=>page.evaluate(()=>parseInt(document.getElementById('agent-view').style.getPropertyValue('--chat-width')));
  await page.evaluate(()=>{localStorage.setItem('interspace.splitWidth','900');dispatchEvent(new Event('resize'));});
  const wide=await width();
  await page.locator('#sidebar-collapse').click();
  const wider=await width();
  await page.locator('#sidebar-expand').click();
  const r={wide,wider,back:await width(),saved:await page.evaluate(()=>localStorage.getItem('interspace.splitWidth'))};
  assert(r.saved==='900'&&r.wide<900&&r.wider>r.wide&&r.back===r.wide,'Sidebar toggle saved a fitted split width: '+JSON.stringify(r));
  await page.evaluate(b=>{if(b==null)localStorage.removeItem('interspace.splitWidth');else localStorage.setItem('interspace.splitWidth',b);dispatchEvent(new Event('resize'));},before);
 }
 // Something that needs you while in Focus: Focus stays on, a banner names it, Go to conversation exits and shows it.
 const said=(tag,n)=>Array.from({length:n},(_,i)=>ev('r1','message',{role:'assistant',text:'Progress note '+tag+i+'. '+'Searching more sources about outage fallback. '.repeat(4),final:false},tag+i));
 await push(page,[...said('a',20),ev('r1','team_proposed',{team_id:'tm1',summary:'Check every reference.',budget:null,members:[{member_id:'m1',role:'citation_checker',brief:'Check every reference.',provider:'codex',model:null,access:'read',default:true}]}),...said('b',20)]);
 await page.waitForFunction(()=>document.querySelector('#agent-stream .card.team'));
 await focusButton.click();
 assert(await focused()&&await banner.isHidden(),'No banner while nothing needs you');
 // The banner follows the task's live state (its status events), as the sidebar does.
 await page.evaluate(()=>{window.rFixture.research[0].status='paused_team';window.rFixture.setState();});
 await push(page,[ev('r1','status',{state:'paused_team',detail:'',queue_position:null,reason:null})]);
 await banner.waitFor();
 assert(await focused()&&(await text(banner)).includes('Approve the team'),'Banner: '+await text(banner));
 {const live=await page.evaluate(()=>{const l=document.getElementById('agent-focus-live'),b=document.getElementById('agent-focus-banner');
   return l?{text:l.textContent,role:l.getAttribute('role'),need:document.getElementById('agent-focus-need').textContent,shown:!l.hidden&&!l.closest('[hidden]'),bannerRole:b.getAttribute('role')}:null;});
  assert(live&&live.role==='status'&&live.text==='Needs you: Approve the team'&&live.text===live.need&&live.shown&&live.bannerRole===null,'Live region for the banner: '+JSON.stringify(live));}
 // Scrolled down a long report, the banner and the whole tab row (Exit focus too) stay reachable, one under the other.
 await page.setViewportSize({width:1280,height:600});
 {const r=await page.evaluate(()=>{const x=document.getElementById('agent-results');x.scrollTop=x.scrollHeight;return {scroll:x.scrollHeight-x.clientHeight,top:x.scrollTop};});
  assert(r.scroll>200&&r.top>200,'Report too short to scroll: '+JSON.stringify(r));}
 {const hit=await page.evaluate(()=>{const at=e=>{const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!h&&(h===e||e.contains(h));};
   const b=document.getElementById('agent-focus-banner').getBoundingClientRect(),t=document.getElementById('agent-tabs').getBoundingClientRect(),x=document.getElementById('agent-results').getBoundingClientRect();
   return {exit:at(document.getElementById('agent-focus')),tab:at(document.querySelector('[data-agent-tab=corpus]')),go:at(document.getElementById('agent-focus-go')),bannerTop:Math.round(b.top),bannerBottom:Math.round(b.bottom),tabsTop:Math.round(t.top),pane:Math.round(x.top)};});
  assert(hit.exit&&hit.tab&&hit.go&&hit.bannerBottom<=hit.tabsTop&&hit.bannerTop>=hit.pane,'Banner covers the tab row when scrolled: '+JSON.stringify(hit));}
 await focusButton.click();
 assert(!(await focused()),'Exit focus after scrolling');
 await focusButton.click();
 await page.setViewportSize({width:1280,height:1000});
 assert(await focused()&&await banner.isVisible(),'Banner again in Focus');
 // Go to conversation moves keyboard focus once, to the team card, never through the Focus button.
 await page.evaluate(()=>{window.focusHops=0;document.getElementById('agent-focus').addEventListener('focus',()=>{window.focusHops++;});});
 await banner.getByRole('button',{name:'Go to conversation',exact:true}).click();
 assert(await page.evaluate(()=>window.focusHops)===0,'Go to conversation focused the Focus button on the way');
 assert(!(await focused())&&await chat.isVisible()&&await banner.isHidden(),'Go to conversation exits Focus');
 {const seen=await page.evaluate(()=>{const c=document.querySelector('#agent-view .agent-main').getBoundingClientRect(),t=[...document.querySelectorAll('#agent-stream .card.team')].pop(),r=t.getBoundingClientRect();
   return {top:Math.round(r.top),chat:[Math.round(c.top),Math.round(c.bottom)],focus:document.activeElement===t||t.contains(document.activeElement)};});
  assert(seen.top>=seen.chat[0]-1&&seen.top<seen.chat[1]&&seen.focus,'Team card shown and focused: '+JSON.stringify(seen));}
 await focusButton.click();
 assert(await banner.isVisible(),'Banner when Focus starts while the team waits');
 await page.evaluate(()=>{window.rFixture.research[0].status='idle';window.rFixture.setState();});
 await push(page,[ev('r1','status',{state:'running',detail:'',queue_position:null,reason:null})]);
 await page.waitForFunction(()=>document.getElementById('agent-focus-banner').hidden);
 assert(await focused(),'Focus stays on after the team is answered');
 assert(await page.evaluate(()=>document.getElementById('agent-focus-live').textContent)==='','Live region cleared with the banner');
 // A question arrives as a status event while the task row still says idle: the banner names it.
 await push(page,[ev('r1','status',{state:'paused_ask',detail:'',queue_position:null,reason:null})]);
 await banner.waitFor();
 assert((await text(banner)).includes('Answer a question')&&await page.evaluate(()=>document.getElementById('agent-focus-live').textContent)==='Needs you: Answer a question','Banner from the live state: '+await text(banner));
 await push(page,[ev('r1','status',{state:'running',detail:'',queue_position:null,reason:null})]);
 await page.waitForFunction(()=>document.getElementById('agent-focus-banner').hidden);
 // Leaving the task (to Settings, from the app menu while the sidebar is hidden) exits Focus and restores the sidebar.
 await page.evaluate(()=>document.querySelector('aside [data-view=settings]').click());
 await page.waitForFunction(()=>document.getElementById('agent-view').hidden);
 assert(!(await focused())&&!(await page.evaluate(()=>window.interspaceAgent.isFocused()))&&!(await collapsed())&&await aside.isVisible(),'Leaving the task exits Focus');
 await page.locator('[data-view=research]').click();await page.locator('[data-open-task=r1]').click();
 await page.waitForFunction(()=>document.querySelector('#agent-view.split'));
 assert(!(await focused())&&(await text(focusButton))==='Focus','Back in the task without Focus');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('agent-view').hidden);
 await page.evaluate(()=>scrollTo(0,400));
 assert(await page.evaluate(()=>scrollY)>0,'Settings scrolls after leaving the split reader');
 assert(!(await page.evaluate(()=>document.getElementById('agent-view').classList.contains('split'))),'Hidden reader keeps no split');

 // A report with a Markdown table: citations in its cells, the first column's included, link to the report's own
 // references in reading order; the reference list, its verdicts and the claims to look at work as in running text.
 // At 1440x900 the four long columns wrap inside the reader's measure, so the table needs no sideways scroll.
 const TABLE_REPORT='# Gains as reported\n\nThe gains below are as the authors state them [1].\n\n| Ref | Method | Evaluation | Headline result |\n|---|---|---|---|\n'+
  '| [2] | Federated deep reinforcement learning that coordinates two xApps across the slices of one cell | Simulation with synthetic traffic | Higher throughput and lower delay than a conventional single-agent baseline in every scenario tried |\n'+
  '| [3] | Transfer learning between slices that reuses the action-selection policy | Simulation | Lower delay for the low-latency slice and higher throughput for the broadband slice, as in [2] |\n'+
  '| [4], [5] | Two constrained multi-agent methods compared on one testbed | Testbed with ten handsets | Fewer agreement violations for a small extra cost in resources |\n\n'+REPORT.slice(REPORT.indexOf('## References'));
 const TABLE_CLAIMS={started_at:'t0',counts:{claims:1,pending:0,supported:0,partly:0,not_supported:1,cannot_tell:0},claims:[{id:'3:1',n:3,k:1,sentence:'Transfer learning between slices [3].',reference:'Ref 3',paper:null,
  status:'judged',by:'codex Citation checker',at:'2026-11-27T10:00:00Z',verdict:'not_supported',reason:'The source reports no delay figure.',quote:'throughput only'}]};
 await page.setViewportSize({width:1440,height:900});
 await page.locator('[data-view=research]').click();await page.locator('[data-open-task=r1]').click();
 await page.waitForFunction(()=>document.querySelector('#agent-view.split'));
 await page.locator('[data-agent-tab=report]').click();
 await page.evaluate(([t,c])=>{window.rFixture.readable.r1['report.md']=t;window.rFixture.claimsNow=c;},[TABLE_REPORT,TABLE_CLAIMS]);
 await push(page,[ev('r1','outputs',{outputs:[{name:'report.md',kind:'report',bytes:1400}]}),ev('r1','claims',TABLE_CLAIMS.counts)]);
 await page.waitForFunction(()=>document.querySelector('#agent-report .md-table')&&document.querySelector('#agent-report .claim-item'));
 {const first=await reader.locator('.md-table').evaluate(t=>[...t.tBodies[0].rows].map(r=>[...r.cells[0].querySelectorAll('.cite-link')].map(a=>[a.textContent,a.getAttribute('href'),a.dataset.claim])));
  assert(JSON.stringify(first)===JSON.stringify([[['2','#report-ref-2','2:1']],[['3','#report-ref-3','3:1']],[['4','#report-ref-4','4:1'],['5','#report-ref-5','5:1']]]),'Citations in the first column: '+JSON.stringify(first));}
 {const all=await reader.locator('.cite-link').evaluateAll(as=>as.map(a=>a.textContent+'='+a.dataset.claim));
  assert(JSON.stringify(all)===JSON.stringify(['1=1:1','2=2:1','3=3:1','2=2:2','4=4:1','5=5:1']),'Citations in reading order: '+JSON.stringify(all));}
 assert(await reader.locator('.report-reference').count()===5&&(await text(reader.locator('.reader-summary')))==='5 references: 1 verified, 1 retracted, 1 not verified, 1 not checked, 1 not in the corpus.','References with a table: '+await text(reader.locator('.reader-summary')));
 assert(await reader.locator('.md-table [data-claim="3:1"]').evaluate(a=>a.classList.contains('claim-not_supported')&&a.getAttribute('aria-label')==='Reference 3, not supported'),'Claim verdict on a cell citation');
 assert(await reader.locator('.claim-item').count()===1&&(await text(reader.locator('.claim-item'))).includes('Transfer learning between slices [3].'),'Claims to look at with a table: '+await text(reader.locator('.claim-list')));
 await reader.locator('.claim-item').getByRole('link',{name:'Show in text'}).click();
 assert(await page.evaluate(()=>document.activeElement?.dataset.claim==='3:1'&&!!document.activeElement.closest('td')),'Show in text to a cell citation');
 await reader.locator('.md-table .cite-link').filter({hasText:'4'}).focus();await page.keyboard.press('Enter');
 assert(await page.evaluate(()=>document.activeElement?.id)==='report-ref-4','Cell citation focuses its reference');
 await reader.locator('#report-ref-4 .report-back').click();
 assert(await page.evaluate(()=>document.activeElement?.dataset.claim==='4:1'),'Back to the cell citation');
 {const t=await page.evaluate(()=>{const w=document.querySelector('#agent-report .table-wrap'),t=w.querySelector('table'),text=document.querySelector('#agent-report .reader-text');
   return {wrap:[w.scrollWidth,w.clientWidth],table:Math.round(t.getBoundingClientRect().width),text:Math.round(text.getBoundingClientRect().width),rows:Math.round(t.tBodies[0].rows[0].getBoundingClientRect().height),page:document.documentElement.scrollWidth<=innerWidth};});
  assert(t.wrap[0]<=t.wrap[1]&&t.table<=t.text&&t.rows>40&&t.page,'Table at 1440x900 needs a sideways scroll or does not wrap: '+JSON.stringify(t));}
 // Words in table cells that wrap across two lines (ordinary words only: a token over 24 characters may break).
 const brokenWords=()=>page.evaluate(()=>{const out=[];for(const c of document.querySelectorAll('#agent-report .md-table th,#agent-report .md-table td')){
  const w=document.createTreeWalker(c,NodeFilter.SHOW_TEXT);while(w.nextNode()){const n=w.currentNode;for(const m of n.nodeValue.matchAll(/\S+/g)){if(m[0].length>24)continue;
   const r=document.createRange();r.setStart(n,m.index);r.setEnd(n,m.index+m[0].length);if(new Set([...r.getClientRects()].map(x=>Math.round(x.top))).size>1)out.push(m[0]);}}}return out;});
 assert(!(await brokenWords()).length,'Words broken inside table cells at 1440x900: '+JSON.stringify(await brokenWords()));
 for(const width of [320,390,600]){await page.setViewportSize({width,height:900});await page.waitForFunction(()=>!document.querySelector('#agent-view.split'));
  const r=await page.evaluate(()=>({shown:!!document.querySelector('#agent-report .table-wrap')?.getClientRects().length,page:document.documentElement.scrollWidth,width:innerWidth}));
  assert(r.shown&&r.page<=r.width,'Table report overflows at '+width+': '+JSON.stringify(r));}

 // References written as numbered lines with no blank line between them ("[1] …\n[2] …", as agents write them) are one
 // reference each, so every citation links, those in a table's first column too, and Show in text finds them; a
 // wrapped entry's next line stays with its entry. A long unbroken token in a cell (a DOI) wraps inside its column, so at
 // 1440x900 the table still needs no sideways scroll.
 const LONG_DOI='10.5555/'+'x'.repeat(192);
 const LINES_REPORT='# Gains as reported\n\nThe gains below are as the authors state them [1].\n\n| Ref | Method | Source |\n|---|---|---|\n'+
  '| [3] | Transfer learning between slices | '+LONG_DOI+' |\n| [2] | Federated learning across two xApps | arXiv |\n| [5] | A method nobody checked | none |\n\n## References\n'+
  ['[1] Example, A. (2019). Emergency call fallback across mobile operators in practice. doi:10.5555/fb.1',
   '[2] Sample, B. (2021). Measuring 112 call recovery after network outages.','    arXiv:2101.00001',
   '[3] Wakefield, A. (1998). A retracted study of call routing reliability that was withdrawn. doi:10.5555/retracted',
   '[4] Nobody, C. (2031). An invented paper about network fallback timing.',
   '[5] Unknown, D. (2015). A paper the agents never searched for at all, about outages.'].join('\n')+'\n';
 await page.setViewportSize({width:1440,height:900});
 await page.waitForFunction(()=>document.querySelector('#agent-view.split'));
 await page.evaluate(t=>{window.rFixture.readable.r1['report.md']=t;},LINES_REPORT);
 await push(page,[ev('r1','outputs',{outputs:[{name:'report.md',kind:'report',bytes:1500}]})]);
 await page.waitForFunction(()=>document.querySelector('#agent-report .reader-text')?.textContent.includes('A method nobody checked'));
 assert(await reader.locator('.report-reference').count()===5&&(await text(reader.locator('.reader-summary')))==='5 references: 1 verified, 1 retracted, 1 not verified, 1 not checked, 1 not in the corpus.','Numbered reference lines: '+await text(reader.locator('.reader-summary')));
 assert((await text(reader.locator('#report-ref-2'))).includes('arXiv:2101.00001')&&!(await text(reader.locator('#report-ref-1'))).includes('Sample, B.'),'Wrapped reference line: '+await text(reader.locator('#report-ref-2')));
 {const first=await reader.locator('.md-table').evaluate(t=>[...t.tBodies[0].rows].map(r=>[...r.cells[0].querySelectorAll('.cite-link')].map(a=>[a.textContent,a.getAttribute('href'),a.dataset.claim])));
  assert(JSON.stringify(first)===JSON.stringify([[['3','#report-ref-3','3:1']],[['2','#report-ref-2','2:1']],[['5','#report-ref-5','5:1']]]),'Citations in the first column with line references: '+JSON.stringify(first));}
 await reader.locator('.claim-item').getByRole('link',{name:'Show in text'}).click();
 assert(await page.evaluate(()=>document.activeElement?.dataset.claim==='3:1'&&!!document.activeElement.closest('td')),'Show in text with line references');
 {const t=await page.evaluate(()=>{const w=document.querySelector('#agent-report .table-wrap'),cols=[...w.querySelector('tbody tr').cells].map(c=>Math.round(c.getBoundingClientRect().width));
   return {wrap:[w.scrollWidth,w.clientWidth],cols,page:document.documentElement.scrollWidth<=innerWidth};});
  assert(t.wrap[0]<=t.wrap[1]&&Math.min(...t.cols)>=40&&t.page,'A long DOI in a cell needs a sideways scroll at 1440x900: '+JSON.stringify(t));}
 await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join('; '));
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 return {checks:'Read opens the Report tab (no inline report view), verdicts in words from the corpus, summary, literal text, citation links incl. lists and ranges, unknown brackets kept, keyboard jump and Back to text, Save, refetch on change, no sideways scroll; Focus: button on the results tab row only in the split reader, hides the conversation and the sidebar, results at least 90% wide, every tab, Esc and Exit focus, sidebar state kept and nothing saved, needs-you banner from the live task state with an always-present live region and Go to conversation to the team card, sidebar toggle never saves a fitted split width, leaving the task exits Focus; a report with a Markdown table: citations in its cells (first column included) linked in reading order with claim ids, references, verdicts and summary unchanged, a claim verdict on a cell citation, Show in text and Back to text to a cell, four long columns wrapping between words without a sideways scroll at 1440x900, no page overflow at 320/390/600; references as numbered [n] lines with no blank line between them each a reference (a wrapped line kept with its entry), linking the first column’s citations, Show in text to a cell, and a long DOI in a cell wrapping with no sideways scroll at 1440x900'};
}
