/* Evidence tab (docs/superpowers/specs/2026-11-20-evidence-table-design.md and 2026-11-27-readable-workspace-design.md),
   from fixture data only: pick columns and rows, Fill table starts the table and asks the Orchestrator, the note about it
   clears once a cell has a value, the grid is compact (a short paper label, a status word and the value, both values on
   two lines for a disagreement, no quotes or buttons), a cell opens a drawer with the quotes and the resolve buttons, the
   drawer follows its cell through re-renders and closes with ×, Esc (before Focus) or when its row is gone, arrow keys
   move between cells, the table fills the pane, Needs you filters, Export CSV saves, and Start a new table confirms. */
import {install,requests,push,assert,text,ev,resetSeq} from './research-fixture.mjs';
const XSS='<img src=x onerror="window.pwned=1">';
const TITLE1='Fallback across operators '+XSS;
const AUTHORS=['Han Zhang','Hao Zhou','Melike Erol-Kantarci'];
const LONG='A discrete-event simulation of a regional network with three operators, five fallback policies and twelve months of outage traces';
const PRESETS=[{id:'design',name:'Study design',instruction:'The kind of study.',numeric:false},{id:'sample',name:'Sample size',instruction:'How many.',numeric:true},
 {id:'setting',name:'Setting or population',instruction:'Where.',numeric:false},{id:'method',name:'Method',instruction:'How.',numeric:false},
 {id:'outcome',name:'Main outcome',instruction:'What.',numeric:false},{id:'finding',name:'Key finding',instruction:'Result.',numeric:false}];
const cell=(status,values,extra={})=>({status,values,resolved:null,...extra});
const v=(value,quote)=>({value,quote,at:'t'});
const PAPER1={title:TITLE1,year:2020,authors:AUTHORS},PAPER2={title:'Recovery timing',year:2021,authors:[]};
// Fill table returns every cell waiting; the agents' values arrive later with an `evidence` event.
const WAITING={presets:PRESETS,table:{started_at:'t0',columns:[PRESETS[0],PRESETS[1]],counts:{cells:4,agree:0,check:0,disagree:0,not_reported:0,waiting:4,resolved:0,one_source:0},rows:[
 {id:'r1',paper:PAPER1,source_kind:'full text',cells:{design:cell('waiting',{}),sample:cell('waiting',{})}},
 {id:'r2',paper:PAPER2,source_kind:'abstract',cells:{design:cell('waiting',{}),sample:cell('waiting',{})}}]}};
const FILLED={presets:PRESETS,table:{started_at:'t0',columns:[PRESETS[0],PRESETS[1]],counts:{cells:4,agree:1,check:1,disagree:1,not_reported:1,waiting:0,resolved:0,one_source:0},rows:[
 {id:'r1',paper:PAPER1,source_kind:'full text',cells:{
  design:cell('disagree',{claude:v('Field study','We studied 40 outages'),codex:v('Observational','observational design')}),
  sample:cell('check',{claude:v('1,200','1,200 calls'),codex:v('1200','1,200 calls')})}},
 {id:'r2',paper:PAPER2,source_kind:'abstract',cells:{
  design:cell('agree',{claude:v(LONG,'A simulation'),codex:v(LONG,'A simulation')}),
  sample:cell('not_reported',{claude:v('Not reported',null),codex:v('Not reported',null)})}}]}};

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 await install(page,url,{researchRows:[{id:'r1',mode:'agent',kind:'research',project_id:null,title:'Fallback review',status:'idle',provider:'claude',model:null}],
  history:{r1:[ev('r1','status',{state:'idle',detail:'',queue_position:null,reason:null})]},tables:{presets:PRESETS,started:WAITING}});
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

 // The note about the Orchestrator shows while no cell has a value, and clears once one has.
 await page.waitForFunction(()=>document.querySelector('#agent-evidence .ev-table'));
 assert((await text(tab)).includes('Asked the Orchestrator to fill the table'),'Note while every cell waits');
 await page.evaluate(t=>{window.rFixture.tableNow=t;},FILLED);
 await push(page,[ev('r1','evidence',{rev:1})]);
 await page.waitForFunction(()=>document.querySelector('#agent-evidence [data-cell="r1:design"]')?.classList.contains('is-disagree'));
 assert(!(await text(tab)).includes('Asked the Orchestrator'),'Note cleared once a cell has a value: '+await text(tab));

 // Short paper labels.
 const labels=await page.evaluate(()=>{const L=window.interspaceEvidence.paperLabel;return [
  L({authors:['Han Zhang'],year:2022}),L({authors:['Han Zhang','Hao Zhou'],year:2022}),L({authors:['Han Zhang','Hao Zhou','Melike Erol-Kantarci'],year:2022}),
  L({authors:['Zhang, Han','Zhou, Hao','X Y'],year:2022}),L({authors:'Han Zhang',title:'T'}),L({authors:['',''],title:'T',year:null})];});
 const want=[{label:'Zhang 2022',clamp:false},{label:'Zhang & Zhou 2022',clamp:false},{label:'Zhang et al. 2022',clamp:false},{label:'Zhang et al. 2022',clamp:false},{label:'T',clamp:true},{label:'T',clamp:true}];
 assert(JSON.stringify(labels)===JSON.stringify(want),'paperLabel: '+JSON.stringify(labels));
 const paper=await page.evaluate(()=>[...document.querySelectorAll('#agent-evidence tbody th')].map(th=>{const p=th.querySelector('.ev-paper');return {label:p.textContent,lines:getComputedStyle(p).webkitLineClamp,title:th.title};}));
 assert(paper[0].label==='Zhang et al. 2020'&&paper[0].title===TITLE1&&paper[1].label==='Recovery timing'&&paper[1].lines==='2'&&paper[1].title==='Recovery timing','Paper labels: '+JSON.stringify(paper));
 assert(await tab.locator('img').count()===0,'Literal title');

 // Compact grid: a status word and the value; a disagreement shows both values on two lines, with no quotes or buttons.
 assert((await text(tab.locator('.claim-summary')))==='4 cells: 2 agree (1 number to check), 1 disagree, 1 not reported.','Summary: '+await text(tab.locator('.claim-summary')));
 const word=async id=>text(tab.locator('[data-cell="'+id+'"] .ev-word'));
 assert(await word('r1:sample')==='Check'&&await word('r2:design')==='Agree'&&await word('r2:sample')==='Not reported'&&await word('r1:design')==='Disagree','Status words');
 const dis=tab.locator('[data-cell="r1:design"]');
 const pairs=await dis.locator('.ev-pair').allTextContents();
 assert(JSON.stringify(pairs)===JSON.stringify(['Claude: Field study','Codex: Observational']),'Disagreement pairs: '+JSON.stringify(pairs));
 assert(await tab.locator('.ev-table blockquote, .ev-table button, .ev-table details').count()===0,'No quotes or buttons in cells');
 assert(await page.evaluate(()=>[...document.querySelectorAll('#agent-evidence td.ev-cell')].every(td=>td.tabIndex===0)),'Every cell is focusable');
 const size=await page.evaluate(()=>{const w=[...document.querySelectorAll('#agent-evidence thead th')].map(th=>Math.round(th.getBoundingClientRect().width));const long=document.querySelector('#agent-evidence [data-cell="r2:design"] .ev-value');return {w,lines:getComputedStyle(long).webkitLineClamp,clipped:long.scrollHeight>long.clientHeight};});
 assert(size.w[0]===170&&size.w.slice(1).every(x=>x>=120&&x<=220)&&size.lines==='3'&&size.clipped,'Column widths and clamp: '+JSON.stringify(size));

 // Needs you shows only rows with a disagreement or a number to check.
 await tab.locator('#ev-filter').click();
 assert(await tab.locator('tbody tr').count()===1,'Needs you filter');
 await tab.locator('#ev-filter').click();

 // A cell opens the drawer: paper, column, both values with their quotes; resolve and undo from it.
 await dis.click();
 const drawer=tab.locator('#ev-drawer');
 await drawer.waitFor();
 assert(await drawer.getAttribute('role')==='region'&&await drawer.getAttribute('aria-label')==='Cell details'&&await drawer.getAttribute('data-for')==='r1:design','Drawer region');
 assert(await drawer.locator('button.ev-drawer-close').count()===1&&await page.evaluate(()=>!!document.querySelector('#agent-evidence .ev-body #ev-drawer')),'Close button, inside the evidence area');
 const dt=await text(drawer);
 assert(dt.includes(TITLE1)&&dt.includes('2020')&&dt.includes('Study design')&&dt.includes('The kind of study.')&&dt.includes('Field study')&&dt.includes('“We studied 40 outages”')&&dt.includes('Observational')&&dt.includes('“observational design”'),'Drawer: '+dt);
 assert(await tab.locator('img').count()===0,'Literal title in the drawer');
 // The drawer's buttons look like buttons: the sidebar's rules (transparent buttons, hidden scrollbar) stay in the sidebar.
 {const bg=await page.evaluate(()=>getComputedStyle(document.getElementById('ev-use-claude')).backgroundColor);
  assert(bg!=='rgba(0, 0, 0, 0)'&&bg!=='transparent','Use button background: '+bg);}
 // Keyboard focus stays in the drawer when the button that was used is gone after the update.
 const inDrawer=()=>page.evaluate(()=>{const a=document.activeElement,d=document.getElementById('ev-drawer');return d&&d.contains(a)?a.id||'ev-drawer':a?.dataset?.cell||a?.tagName;});
 await drawer.getByRole('button',{name:'Use Claude’s'}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-evidence [data-cell="r1:design"]')?.classList.contains('is-resolved'));
 assert(JSON.stringify((await requests(page,'table_resolve')).at(-1))===JSON.stringify({task_id:'r1',row:'r1',column:'design',value:'Field study'}),'Resolve request');
 assert(await word('r1:design')==='Decided'&&await drawer.getByRole('button',{name:'Undo'}).isVisible(),'Decided, with Undo in the drawer');
 assert(await inDrawer()==='ev-undo','Focus after Use Claude’s: '+await inDrawer());
 await drawer.getByRole('button',{name:'Undo'}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-evidence [data-cell="r1:design"]')?.classList.contains('is-disagree'));
 assert(await inDrawer()==='ev-use-claude','Focus after Undo: '+await inDrawer());

 // A pushed table update re-renders and the drawer stays on its cell, with the new data.
 await page.evaluate(()=>{window.rFixture.tableNow.table.rows[0].cells.design.values.codex.quote='an observational design, revised';});
 await push(page,[ev('r1','evidence',{rev:2})]);
 await page.waitForFunction(()=>(document.querySelector('#ev-drawer')?.textContent||'').includes('revised'));
 assert(await drawer.getAttribute('data-for')==='r1:design','Drawer follows its cell');
 // A choice made after an update uses the updated value.
 await page.evaluate(()=>{window.rFixture.tableNow.table.rows[0].cells.design.values.claude.value='Field trial';});
 await push(page,[ev('r1','evidence',{rev:3})]);
 await page.waitForFunction(()=>(document.querySelector('#ev-drawer')?.textContent||'').includes('Field trial'));
 await drawer.getByRole('button',{name:'Use Claude’s'}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-evidence [data-cell="r1:design"]')?.classList.contains('is-resolved'));
 {const r=(await requests(page,'table_resolve')).at(-1);
  assert(r.row==='r1'&&r.column==='design'&&r.value==='Field trial','Resolve after an update: '+JSON.stringify(r));}
 await drawer.getByRole('button',{name:'Undo'}).click();
 await page.waitForFunction(()=>document.querySelector('#agent-evidence [data-cell="r1:design"]')?.classList.contains('is-disagree'));

 // Esc in another window's dialog closes only that dialog, never the drawer behind it.
 await page.evaluate(()=>{const d=document.getElementById('delete-dialog');d.replaceChildren();const b=document.createElement('button');b.type='button';b.textContent='Keep';d.append(b);d.showModal();b.focus();});
 await page.keyboard.press('Escape');
 assert(await page.evaluate(()=>!document.getElementById('delete-dialog').open)&&await drawer.count()===1,'Esc in a dialog: dialog closed, drawer kept');
 await page.evaluate(()=>document.getElementById('delete-dialog').replaceChildren());

 // Type my own, from the drawer. Esc in the field stops typing and keeps the drawer open.
 await drawer.getByRole('button',{name:'Type my own'}).click();
 await tab.getByLabel('Your value for Study design').fill('Half typed');
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!document.getElementById('ev-own-value'));
 assert(await drawer.count()===1&&await page.evaluate(()=>document.activeElement?.id)==='ev-own','Esc in the field cancels typing: '+await page.evaluate(()=>document.activeElement?.id||document.activeElement?.tagName));
 await drawer.getByRole('button',{name:'Type my own'}).click();
 assert(await tab.getByLabel('Your value for Study design').inputValue()==='','The cancelled value is gone');
 await tab.getByLabel('Your value for Study design').fill('Observational field study');
 await drawer.getByRole('button',{name:'Save'}).click();
 await page.waitForFunction(()=>(document.querySelector('#agent-evidence [data-cell="r1:design"]')?.textContent||'').includes('Observational field study'));
 assert((await requests(page,'table_resolve')).at(-1).value==='Observational field study','Own value');

 // Esc and × close it.
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!document.querySelector('#ev-drawer'));
 await tab.locator('[data-cell="r2:design"]').click();await drawer.waitFor();
 assert((await text(drawer)).includes(LONG),'Full value in the drawer');
 await drawer.locator('button.ev-drawer-close').click();
 await page.waitForFunction(()=>!document.querySelector('#ev-drawer'));

 // Arrow keys move between cells; Enter opens the drawer and moves into it; Esc returns to the cell.
 await tab.locator('[data-cell="r1:design"]').focus();
 const at=()=>page.evaluate(()=>document.activeElement?.dataset?.cell||document.activeElement?.id||null);
 const steps=[];for(const k of ['ArrowRight','ArrowDown','ArrowLeft','ArrowLeft','ArrowUp']){await page.keyboard.press(k);steps.push(await at());}
 assert(JSON.stringify(steps)===JSON.stringify(['r1:sample','r2:sample','r2:design','r2:design','r1:design']),'Arrow keys: '+JSON.stringify(steps));
 await page.keyboard.press('Enter');await drawer.waitFor();
 assert(await drawer.getAttribute('data-for')==='r1:design'&&await page.evaluate(()=>document.getElementById('ev-drawer').contains(document.activeElement)),'Enter opens the drawer and moves into it');
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!document.querySelector('#ev-drawer'));
 assert(await at()==='r1:design','Esc returns to the cell');

 // In Focus, the first Esc closes the drawer and the second leaves Focus.
 await page.locator('#agent-focus').click();
 await page.waitForFunction(()=>document.getElementById('agent-view').classList.contains('focus'));
 await tab.locator('[data-cell="r1:sample"]').click();await drawer.waitFor();
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!document.querySelector('#ev-drawer'));
 assert(await page.evaluate(()=>document.getElementById('agent-view').classList.contains('focus')),'First Esc closes only the drawer');
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!document.getElementById('agent-view').classList.contains('focus'));

 // The drawer closes when its row is gone.
 await tab.locator('[data-cell="r2:sample"]').click();await drawer.waitFor();
 await page.evaluate(()=>{window.rFixture.tableNow.table.rows.pop();});
 await push(page,[ev('r1','evidence',{rev:4})]);
 await page.waitForFunction(()=>document.querySelectorAll('#agent-evidence tbody tr').length===1);
 assert(await drawer.count()===0,'Drawer closes when its row is gone');

 // A long table fills the pane, not a fixed 70vh, so its sideways scrollbar stays on screen.
 await page.setViewportSize({width:1280,height:800});
 await page.evaluate(()=>{const t=window.rFixture.tableNow.table;for(let i=0;i<30;i++)t.rows.push({...JSON.parse(JSON.stringify(t.rows[0])),id:'x'+i});});
 await push(page,[ev('r1','evidence',{rev:5})]);
 await page.waitForFunction(()=>document.querySelectorAll('#agent-evidence tbody tr').length===31);
 const box=await page.evaluate(()=>{const w=document.querySelector('#agent-evidence .ev-wrap'),r=w.getBoundingClientRect();return {bottom:Math.round(r.bottom),height:innerHeight,max:getComputedStyle(w).maxHeight,scrolls:w.scrollHeight>w.clientHeight,split:document.getElementById('agent-view').classList.contains('split')};});
 assert(box.split&&box.max!=='560px'&&box.bottom<=box.height&&box.scrolls,'Table fills the pane: '+JSON.stringify(box));
 // A short conversation keeps each message as tall as its text; it does not stretch to fill the column.
 const slack=await page.evaluate(()=>[...document.querySelectorAll('#agent-stream>*')].filter(el=>el.offsetParent&&el.children.length).map(el=>{const kids=[...el.children].filter(k=>k.offsetParent).map(k=>k.getBoundingClientRect());return Math.round(el.getBoundingClientRect().height-(Math.max(...kids.map(k=>k.bottom))-Math.min(...kids.map(k=>k.top))));}));
 assert(slack.length&&slack.every(s=>s<=40),'Messages are not stretched: '+JSON.stringify(slack));
 await tab.locator('[data-cell="x0:design"]').click();await drawer.waitFor();
 const side=await page.evaluate(()=>{const w=document.querySelector('#agent-evidence .ev-wrap').getBoundingClientRect(),d=document.getElementById('ev-drawer').getBoundingClientRect();return {wrap:Math.round(w.right),drawer:Math.round(d.left),bottom:Math.round(d.bottom),height:innerHeight};});
 assert(side.drawer>=side.wrap&&side.bottom<=side.height,'Drawer on the right of the table: '+JSON.stringify(side));

 // Narrow window: the drawer is full width and nothing scrolls sideways.
 await page.setViewportSize({width:390,height:800});
 await page.waitForFunction(()=>!document.getElementById('agent-view').classList.contains('split'));
 await drawer.waitFor();
 const narrow=await page.evaluate(()=>({drawer:Math.round(document.getElementById('ev-drawer').getBoundingClientRect().width),area:Math.round(document.getElementById('agent-evidence').getBoundingClientRect().width),scroll:document.documentElement.scrollWidth,width:innerWidth}));
 assert(Math.abs(narrow.drawer-narrow.area)<=2&&narrow.scroll<=narrow.width,'Narrow drawer: '+JSON.stringify(narrow));
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!document.querySelector('#ev-drawer'));
 await page.setViewportSize({width:1440,height:900});

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
 return {checks:'picker defaults, custom column, rows choice, Fill table starts and asks the Orchestrator, the note clears once a cell has a value, short paper labels with the title as tooltip, status words, two-line disagreement without quotes or buttons, 170px paper column, 120–220px value columns clamped to 3 lines, Needs you filter, drawer with paper, column and quotes, resolve and undo from the drawer, drawer follows its cell through a pushed update, a choice after an update sends the new value, focus stays in the drawer after a choice, Esc in a dialog leaves the drawer, type my own with Esc to cancel typing, Esc and × close, arrow keys and Enter, Esc closes the drawer before Focus, drawer closes when its row is gone, table fills the pane at 1280×800 with the drawer beside it, short messages keep their own height, full-width drawer at 390px, export through the save panel, inline new-table confirmation'};
}
