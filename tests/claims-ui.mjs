/* Claim check in the Report tab (docs/superpowers/specs/2026-11-20-claim-check-design.md), from fixture data only:
   Check claims starts a check and asks the Orchestrator in the conversation without touching a draft; verdicts
   colour the citation links (words in their accessible names), a summary counts them, and Claims to look at lists
   problems first with reason, quote and Show in text. */
import {install,requests,push,assert,text,ev,resetSeq} from './research-fixture.mjs';
const XSS='<img src=x onerror="window.pwned=1">';
const REPORT=`# Fallback during outages

Fallback is described in standards [1]. Two reports measured it [2]. Recovery timing is rare [1].

## References

1. Example, A. (2020). Emergency call fallback across mobile operators. doi:10.5555/fb.1
2. Sample, B. (2021). Measuring call recovery after outages. arXiv:2101.00001
`;
const claim=(id,n,sentence,extra)=>({id,n,k:Number(id.split(':')[1]),sentence,reference:'Ref '+n,paper:null,status:'judged',by:'codex Citation checker',at:'2026-11-20T10:00:00Z',...extra});
const START={started_at:'t0',counts:{claims:3,pending:3,supported:0,partly:0,not_supported:0,cannot_tell:0},claims:[]};
const DONE={started_at:'t0',counts:{claims:3,pending:0,supported:1,partly:1,not_supported:1,cannot_tell:0},claims:[
 claim('1:1',1,'Fallback is described in standards [1].',{verdict:'supported',reason:'Stated.',quote:'fallback is described'}),
 claim('2:1',2,'Two reports measured it [2].',{verdict:'partly',reason:'Only one report.',quote:'one operator report'}),
 claim('1:2',1,'Recovery timing is rare [1].',{verdict:'not_supported',reason:'The abstract reports timing '+XSS,quote:'median of 40 minutes',source_kind:'full text'})]};

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 const history=[ev('r1','outputs',{outputs:[{name:'report.md',kind:'report',bytes:400}]}),ev('r1','status',{state:'idle',detail:'',queue_position:null,reason:null})];
 await install(page,url,{researchRows:[{id:'r1',mode:'agent',kind:'research',project_id:null,title:'Fallback review',status:'idle',provider:'claude',model:null}],history:{r1:history},
  outputs:{r1:[{name:'report.md',kind:'report',bytes:400}]},claims:{r1:{start:START}}});
 await page.evaluate(t=>{window.rFixture.readable={r1:{'report.md':t}};window.rFixture.scopes.r1={...window.rFixture.scopes.r1};},REPORT);
 await page.setViewportSize({width:1440,height:900});
 await page.locator('[data-view=research]').click();await page.locator('[data-sidebar-task=r1]').click();
 // A finished research task has an approved scope; approve the fixture's first.
 await page.locator('[data-agent-tab=details]').click();
 await page.locator('#agent-scope').getByRole('button',{name:'Approve scope',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#agent-scope .primary'));
 await page.locator('[data-agent-tab=report]').click();
 const reader=page.locator('#agent-report');
 await page.waitForFunction(()=>document.querySelectorAll('#agent-report .cite-link').length===3);
 assert(JSON.stringify(await reader.locator('.cite-link').evaluateAll(a=>a.map(x=>x.dataset.claim)))===JSON.stringify(['1:1','2:1','1:2']),'Claim ids in reading order');

 // Check claims: starts the check, then asks the Orchestrator; a draft in the composer is left alone.
 await page.locator('#agent-message').fill('my unsent draft');
 await reader.locator('#reader-check').click();
 await page.waitForFunction(()=>window.rFixture.requests.some(r=>r.method==='agent_message'));
 assert(JSON.stringify((await requests(page,'claims_start')).at(-1))===JSON.stringify({task_id:'r1'}),'claims_start');
 assert((await requests(page,'agent_message')).at(-1).text==='Check the claims in the saved report.','Orchestrator asked');
 assert((await page.locator('#agent-message').inputValue())==='my unsent draft','Draft kept');
 await page.waitForFunction(()=>(document.querySelector('#agent-report .claim-summary')?.textContent||'').includes('Checking claims: 0 of 3 done'));

 // Verdicts arrive: summary, link colours and accessible names, problems listed first.
 await page.evaluate(d=>{window.rFixture.claimsNow=d;},DONE);
 await push(page,[ev('r1','claims',DONE.counts)]);
 await page.waitForFunction(()=>(document.querySelector('#agent-report .claim-summary')?.textContent||'').startsWith('3 claims:'));
 assert((await text(reader.locator('.claim-summary')))==='3 claims: 1 supported, 1 partly, 1 not supported.','Summary');
 assert((await reader.locator('[data-claim="1:2"]').getAttribute('aria-label'))==='Reference 1, not supported'&&await reader.locator('.cite-link.claim-supported').count()===1,'Link verdicts');
 const items=await reader.locator('.claim-item .claim-verdict').allTextContents();
 assert(JSON.stringify(items)===JSON.stringify(['Not supported','Partly supported']),'Problems first: '+JSON.stringify(items));
 const first=await text(reader.locator('.claim-item').first());
 assert(first.includes('Recovery timing is rare [1].')&&first.includes(XSS)&&first.includes('median of 40 minutes')&&first.includes('Judged from the full text'),'Literal reason, quote and source kind');
 await reader.locator('.claim-item').first().getByRole('link',{name:'Show in text'}).click();
 assert(await page.evaluate(()=>document.activeElement?.dataset.claim)==='1:2','Show in text focuses the citation');
 assert(!errors.length,'Page errors: '+errors.join('; '));
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 return {checks:'claim ids in reading order, Check claims starts and asks the Orchestrator without touching a draft, progress line, verdict summary, link colours with words in accessible names, problems listed first with literal reason and quote, Show in text'};
}
