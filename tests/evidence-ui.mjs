/* Evidence tab (docs/superpowers/specs/2026-11-20-evidence-table-design.md), from fixture data only: pick columns and
   rows, Fill table starts the table and asks the Orchestrator, the grid says each cell's status in words, a
   disagreement shows both values with their quotes and is resolved by a button or your own value, Needs you filters,
   Export CSV saves, and Start a new table confirms inline. */
import {install,requests,push,assert,text,ev,resetSeq} from './research-fixture.mjs';
const XSS='<img src=x onerror="window.pwned=1">';
const PRESETS=[{id:'design',name:'Study design',instruction:'The kind of study.',numeric:false},{id:'sample',name:'Sample size',instruction:'How many.',numeric:true},
 {id:'setting',name:'Setting or population',instruction:'Where.',numeric:false},{id:'method',name:'Method',instruction:'How.',numeric:false},
 {id:'outcome',name:'Main outcome',instruction:'What.',numeric:false},{id:'finding',name:'Key finding',instruction:'Result.',numeric:false}];
const cell=(status,values,extra={})=>({status,values,resolved:null,...extra});
const v=(value,quote)=>({value,quote,at:'t'});
const STARTED={presets:PRESETS,table:{started_at:'t0',columns:[PRESETS[0],PRESETS[1]],counts:{cells:4,agree:1,check:1,disagree:1,not_reported:1,waiting:0,resolved:0,one_source:0},rows:[
 {id:'r1',paper:{title:'Fallback across operators '+XSS,year:2020},source_kind:'full text',cells:{
  design:cell('disagree',{claude:v('Field study','We studied 40 outages'),codex:v('Observational','observational design')}),
  sample:cell('check',{claude:v('1,200','1,200 calls'),codex:v('1200','1,200 calls')})}},
 {id:'r2',paper:{title:'Recovery timing',year:2021},source_kind:'abstract',cells:{
  design:cell('agree',{claude:v('Simulation','A simulation'),codex:v('simulation','A simulation')}),
  sample:cell('not_reported',{claude:v('Not reported',null),codex:v('Not reported',null)})}}]}};

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 await install(page,url,{researchRows:[{id:'r1',mode:'agent',kind:'research',project_id:null,title:'Fallback review',status:'idle',provider:'claude',model:null}],
  history:{r1:[ev('r1','status',{state:'idle',detail:'',queue_position:null,reason:null})]},tables:{presets:PRESETS,started:STARTED}});
 await page.setViewportSize({width:1440,height:900});
 await page.locator('[data-view=research]').click();await page.locator('[data-sidebar-task=r1]').click();
 await page.locator('[data-agent-tab=details]').click();
 await page.locator('#agent-scope').getByRole('button',{name:'Approve scope',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#agent-scope .primary'));
 await page.locator('[data-agent-tab=evidence]').click();
 const tab=page.locator('#agent-evidence');
 await tab.locator('#ev-fill').waitFor();

 // Picker: four presets on by default, a custom column, rows choice.
 assert(await tab.locator('#ev-col-design').isChecked()&&await tab.locator('#ev-col-sample').isChecked()&&!(await tab.locator('#ev-col-method').isChecked()),'Default columns');
 await tab.locator('#ev-col-setting').uncheck();await tab.locator('#ev-col-finding').uncheck();
 await tab.locator('#ev-add').click();
 await tab.getByLabel('Column 1 name').fill('Country');await tab.getByLabel('Column 1 instruction').fill('Where the study was done.');
 await tab.locator('input[name=ev-rows][value=checked]').check();
 await tab.locator('#ev-fill').click();
 await page.waitForFunction(()=>window.rFixture.requests.some(r=>r.method==='agent_message'));
 const start=(await requests(page,'table_start')).at(-1);
 assert(JSON.stringify(start.columns.map(c=>c.name))===JSON.stringify(['Study design','Sample size','Country'])&&start.rows==='checked','table_start: '+JSON.stringify(start));
 assert((await requests(page,'agent_message')).at(-1).text==='Fill the evidence table.','Orchestrator asked');

 // Grid: words per status, both values for a disagreement, literal titles.
 await page.waitForFunction(()=>document.querySelector('#agent-evidence .ev-table'));
 assert((await text(tab.locator('.claim-summary')))==='4 cells: 2 agree (1 number to check), 1 disagree, 1 not reported.','Summary: '+await text(tab.locator('.claim-summary')));
 const word=async id=>text(tab.locator('[data-cell="'+id+'"] .ev-word'));
 assert(await word('r1:sample')==='Agree, check the number'&&await word('r2:design')==='Agree'&&await word('r2:sample')==='Not reported'&&await word('r1:design')==='Disagree','Status words');
 const dis=await text(tab.locator('[data-cell="r1:design"]'));
 assert(dis.includes('Claude')&&dis.includes('Field study')&&dis.includes('Codex')&&dis.includes('Observational')&&dis.includes('“We studied 40 outages”'),'Disagreement: '+dis);
 assert((await text(tab.locator('tbody th').first())).includes(XSS)&&await tab.locator('img').count()===0,'Literal title');

 // Needs you shows only rows with a disagreement or a number to check.
 await tab.locator('#ev-filter').click();
 assert(await tab.locator('tbody tr').count()===1,'Needs you filter');
 await tab.locator('#ev-filter').click();

 // Resolve by button, undo, then type my own.
 await tab.locator('[data-cell="r1:design"]').getByRole('button',{name:'Use Codex’s'}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-evidence [data-cell="r1:design"]')?.classList.contains('is-resolved'));
 assert(JSON.stringify((await requests(page,'table_resolve')).at(-1))===JSON.stringify({task_id:'r1',row:'r1',column:'design',value:'Observational'}),'Resolve request');
 await tab.locator('[data-cell="r1:design"]').getByRole('button',{name:'Undo'}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-evidence [data-cell="r1:design"]')?.classList.contains('is-disagree'));
 await tab.locator('[data-cell="r1:design"]').getByRole('button',{name:'Type my own'}).click();
 await tab.getByLabel('Your value for Study design').fill('Observational field study');
 await tab.locator('[data-cell="r1:design"]').getByRole('button',{name:'Save'}).click();
 await page.waitForFunction(()=>(document.querySelector('#agent-evidence [data-cell="r1:design"]')?.textContent||'').includes('Observational field study'));

 // Export saves through the save panel; Start a new table asks inline first.
 await tab.locator('#ev-export').click();
 await page.waitForFunction(()=>window.rFixture.requests.some(r=>r.method==='task_output_save'&&r.params.name==='evidence.csv'));
 await tab.locator('#ev-new').click();
 assert(await tab.locator('#ev-new-yes').isVisible()&&await tab.locator('#ev-fill').count()===0,'Inline confirmation');
 await tab.locator('#ev-new-no').click();
 await tab.locator('#ev-new').click();await tab.locator('#ev-new-yes').click();
 assert(await tab.locator('#ev-fill').isVisible(),'Picker again');
 assert(!errors.length,'Page errors: '+errors.join('; '));
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 return {checks:'picker defaults, custom column, rows choice, Fill table starts and asks the Orchestrator, status words, both values and quotes for a disagreement, literal titles, Needs you filter, resolve by button, undo, type my own, export through the save panel, inline new-table confirmation'};
}
