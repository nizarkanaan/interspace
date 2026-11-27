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
 assert(await page.locator('#agent-tabs #agent-focus').count()===1&&await focusButton.isVisible()&&(await text(focusButton))==='Focus'&&await focusButton.getAttribute('aria-pressed')==='false'&&await focusButton.getAttribute('type')==='button','Focus button on the results tab row');
 const open=await store();
 await focusButton.click();
 assert(await focused()&&await page.evaluate(()=>window.interspaceAgent.isFocused())&&(await text(focusButton))==='Exit focus'&&await focusButton.getAttribute('aria-pressed')==='true','Focus on');
 assert(await chat.isHidden()&&await aside.isHidden()&&await reader.isVisible()&&await banner.isHidden(),'Focus hides the conversation and the sidebar');
 {const share=await page.evaluate(()=>document.getElementById('agent-results').getBoundingClientRect().width/innerWidth);assert(share>=0.9,'Results pane share in Focus: '+share);}
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'No sideways scroll in Focus');
 // Every results tab works in Focus.
 await page.locator('[data-agent-tab=corpus]').click();
 assert(await focused()&&await page.locator('#agent-corpus').isVisible(),'Corpus in Focus');
 await page.locator('[data-agent-tab=report]').click();
 await page.keyboard.press('Escape');
 assert(!(await focused())&&!(await page.evaluate(()=>window.interspaceAgent.isFocused()))&&await chat.isVisible()&&await aside.isVisible()&&(await text(focusButton))==='Focus'&&await focusButton.getAttribute('aria-pressed')==='false','Esc exits Focus');
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
 await page.evaluate(()=>{window.rFixture.research[0].status='paused_team';window.rFixture.setState();});
 await banner.waitFor();
 assert(await focused()&&(await text(banner)).includes('Approve the team'),'Banner: '+await text(banner));
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
 await page.waitForFunction(()=>document.getElementById('agent-focus-banner').hidden);
 assert(await focused(),'Focus stays on after the team is answered');
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
 assert(!errors.length,'Page errors: '+errors.join('; '));
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 return {checks:'Read opens the Report tab (no inline report view), verdicts in words from the corpus, summary, literal text, citation links incl. lists and ranges, unknown brackets kept, keyboard jump and Back to text, Save, refetch on change, no sideways scroll; Focus: button on the results tab row only in the split reader, hides the conversation and the sidebar, results at least 90% wide, every tab, Esc and Exit focus, sidebar state kept and nothing saved, needs-you banner with Go to conversation to the team card, leaving the task exits Focus'};
}
