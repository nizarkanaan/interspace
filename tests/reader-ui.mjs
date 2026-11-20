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
 assert(await verdict(1)==='Verified'&&await verdict(2)==='Not checked'&&await verdict(3)==='Retracted: do not cite'&&await verdict(4)==='Not verified'&&await verdict(5)==='Not in the corpus','Verdicts');
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
 {const wide=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&e.offsetParent).slice(0,4).map(e=>e.tagName+'#'+e.id+'.'+e.className+':'+Math.round(e.getBoundingClientRect().right)));
  assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'No sideways scroll at 390: '+JSON.stringify(wide));}
 await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join('; '));
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 return {checks:'Read opens the Report tab (no inline report view), verdicts in words from the corpus, summary, literal text, citation links incl. lists and ranges, unknown brackets kept, keyboard jump and Back to text, Save, refetch on change, no sideways scroll'};
}
