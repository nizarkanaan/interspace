/* Sidebar modes (docs/superpowers/specs/2026-11-20-sidebar-modes-design.md), from fixture rows only: a Research | Code
   switch, the mode's New button, the project picker only in Code, tasks grouped by what they need with their state in
   words, the open task marked, Show all, and literal titles. */
import {install,assert,text,resetSeq} from './research-fixture.mjs';
const XSS='<img src=x onerror="window.pwned=1">';
const r=(id,title,status,extra={})=>({id,mode:'agent',kind:'research',project_id:null,title,status,provider:'codex',model:null,role:'orchestrator',...extra});
const c=(id,title,status,extra={})=>({id,mode:'agent',kind:'project',project_id:'p1',title,status,provider:'claude',model:null,role:'orchestrator',...extra});

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 const research=[r('r1','Emergency call reliability during outages','running'),r('r2','Related work '+XSS,'idle',{has_report:true}),
  r('r3','Fallback for roaming callers','draft',{scope_approved:false}),r('r4','Verify my references','paused_team'),
  r('r1c','Researcher: search','running',{parent_task_id:'r1'}),
  ...Array.from({length:10},(_,i)=>r('d'+i,'Finished question '+i,'idle'))];
 const code=[c('t1','Add input validation','paused_ask'),c('t2','Fix date parsing','idle'),c('t3','Ready to start','draft',{scope_approved:true})];
 await install(page,url,{rows:code,researchRows:research,history:{}});
 const side=page.locator('#sidebar-tasks');

 // Code mode by default: project picker, New code task, the project's tasks grouped.
 assert((await page.locator('[data-view=tasks]').getAttribute('aria-pressed'))==='true','Code mode first');
 assert(await page.locator('.project-nav').isVisible()&&(await text(page.locator('#sidebar-new')))==='New code task','Code controls');
 assert((await text(side.locator('.side-group.needs'))).includes('Add input validation')&&(await text(side.locator('.side-group.needs'))).includes('Answer a question'),'Needs you: question');
 assert((await text(side.locator('[data-sidebar-task=t3]'))).includes('Send the first message'),'Approved draft');
 assert((await text(side.locator('[data-sidebar-task=t2]'))).includes('Waiting for your message'),'Idle code task');

 // Research mode: no project picker, grouped, children left out, literal titles, Show all.
 await page.locator('[data-view=research]').click();
 assert((await page.locator('[data-view=research]').getAttribute('aria-pressed'))==='true'&&(await page.locator('[data-view=tasks]').getAttribute('aria-pressed'))==='false','Research mode pressed');
 assert(await page.locator('.project-nav').isHidden()&&(await text(page.locator('#sidebar-new')))==='New research question','Research controls');
 const groups=await side.locator('.side-group h2').allTextContents();
 assert(JSON.stringify(groups)===JSON.stringify(['Needs you · 2','Working','Done · 11']),'Groups: '+JSON.stringify(groups));
 assert((await text(side.locator('[data-sidebar-task=r3]'))).includes('Approve the scope to start')&&(await text(side.locator('[data-sidebar-task=r4]'))).includes('Approve the team'),'Needs you words');
 assert((await text(side.locator('[data-sidebar-task=r1]'))).includes('Working')&&await side.locator('[data-sidebar-task=r1c]').count()===0,'Working, no subagents');
 assert((await text(side.locator('[data-sidebar-task=r2]'))).includes('Related work '+XSS)&&(await text(side.locator('[data-sidebar-task=r2]'))).includes('Report ready')&&await side.locator('img').count()===0,'Literal title, report ready');
 assert(await side.locator('.side-group.done .side-task').count()===8,'Done shows 8');
 await side.getByRole('button',{name:'Show all 11'}).focus();await page.keyboard.press('Enter');
 assert(await side.locator('.side-group.done .side-task').count()===11&&await page.evaluate(()=>document.activeElement?.textContent)==='Show fewer','Show all by keyboard keeps focus');

 // New research question opens the form with the research kind; opening a task marks it.
 await page.locator('#sidebar-new').click();
 assert(await page.locator('input[name=new-kind][value=research]').isChecked(),'New research question preselects research');
 await side.locator('[data-sidebar-task=r1]').click();
 await page.waitForFunction(()=>!document.getElementById('agent-view').hidden);
 assert((await side.locator('[data-sidebar-task=r1]').getAttribute('aria-current'))==='page'&&(await page.locator('[data-view=research]').getAttribute('aria-pressed'))==='true','Open task marked, mode kept');
 assert(await page.locator('[data-view=running]').isVisible()&&await page.locator('[data-view=settings]').isVisible(),'Running now and Settings');
 // Usage limits: an empty note first, then each provider's reading as reported, warnings in words.
 const usage=page.locator('#sidebar-usage');
 assert((await text(usage)).includes('Usage limits show after an agent runs.'),'Empty usage note');
 await page.evaluate(()=>{const now=Date.now()/1000;window.rFixture.limits={
  codex:{at:new Date().toISOString(),windows:[{label:'5-hour limit',used_percent:42,resets_at:new Date((now+3600)*1000).toISOString()},{label:'Weekly limit',used_percent:86}]},
  claude:{at:new Date().toISOString(),windows:[{label:'5-hour limit',status:'allowed_warning'}]}};window.rFixture.setState();});
 await page.waitForFunction(()=>document.querySelectorAll('#sidebar-usage .usage-provider').length===2);
 const codex=await text(usage.locator('[data-provider=codex]')),claude=await text(usage.locator('[data-provider=claude]'));
 assert(codex.includes('Codex')&&codex.includes('as of')&&codex.includes('5-hour limit · 42% used · resets')&&codex.includes('Weekly limit · 86% used'),'Codex usage: '+codex);
 assert(claude.includes('Claude Code')&&claude.includes('5-hour limit · Near the limit'),'Claude usage: '+claude);
 assert(await usage.locator('.usage-window.high').count()===2&&await usage.locator('.usage-bar').count()===2,'Warnings and bars');
 assert(!/\$|€|£|cost|price/i.test(await text(usage)),'No money in usage');
 // Collapsible sidebar: a thin rail, remembered, with a shortcut that ignores typing.
 {
  const KEY='interspace.sidebarCollapsed',body=page.locator('body'),aside=page.locator('aside'),main=page.locator('main');
  const collapsed=()=>page.evaluate(()=>document.body.classList.contains('sidebar-collapsed'));
  const wide=async loc=>(await loc.boundingBox()).width;
  assert(!(await collapsed())&&await page.locator('#sidebar-expand').isHidden(),'Starts expanded, no rail button');
  assert((await page.locator('#sidebar-collapse').getAttribute('aria-label'))==='Hide sidebar'&&(await text(page.locator('#sidebar-collapse')))==='\u25C0','Collapse button');
  const w0=await wide(main);
  const activeId=()=>page.evaluate(()=>document.activeElement?.id||document.activeElement?.tagName);
  await page.locator('#sidebar-collapse').click();
  assert(await collapsed(),'Click collapses');
  assert(await wide(aside)<=48,'Rail width '+await wide(aside));
  assert(await wide(main)-w0>=150,'Main grows '+(await wide(main)-w0));
  assert((await page.evaluate(k=>localStorage.getItem(k),KEY))==='1','Saved as 1');
  const ex=page.locator('#sidebar-expand');
  // The rail keeps what needs you in view: t1 (a question, Code) and r4 (a team, Research).
  assert(await ex.isVisible()&&(await ex.getAttribute('aria-label'))==='Show sidebar, 2 tasks need you'&&(await text(ex))==='\u2630 2','Expand button with the count: '+await text(ex)+' / '+await ex.getAttribute('aria-label'));
  assert(await page.locator('.mode-switch').isHidden()&&await page.locator('#sidebar-collapse').isHidden(),'Rail hides the rest');
  // Keyboard focus follows the control that replaces the one it was on.
  assert(await activeId()==='sidebar-expand','Collapse moves focus to the rail button: '+await activeId());
  {
   const rail=()=>page.evaluate(()=>{const b=document.getElementById('sidebar-expand');return b.textContent+' | '+b.getAttribute('aria-label');});
   // Another task waits on a team approval; archived tasks and subagents are not counted.
   await page.evaluate(()=>{const f=window.rFixture;f.rows.find(x=>x.id==='t1').status='idle';
    f.research.push({id:'r9',mode:'agent',kind:'research',project_id:null,title:'Archived question',status:'paused_ask',provider:'codex',archived:true},{id:'r4c',mode:'agent',kind:'research',project_id:null,title:'Researcher',status:'paused_team',provider:'codex',parent_task_id:'r4'});f.setState();});
   assert(await rail()==='\u2630 1 | Show sidebar, 1 task needs you','One other task needs you: '+await rail());
   await page.evaluate(()=>{window.rFixture.research.find(x=>x.id==='r4').status='running';window.rFixture.setState();});
   assert(await rail()==='\u2630 | Show sidebar','Nothing needs you: '+await rail());
   await page.evaluate(()=>{const f=window.rFixture;f.research.find(x=>x.id==='r4').status='paused_scope';f.rows.find(x=>x.id==='t1').status='paused_ask';f.setState();});
   assert(await rail()==='\u2630 2 | Show sidebar, 2 tasks need you','A scope change counts too: '+await rail());
  }
  await ex.click();
  assert(!(await collapsed())&&await activeId()==='sidebar-collapse','Expand moves focus to the collapse button: '+await activeId());
  await page.locator('#sidebar-collapse').click();
  assert(await collapsed(),'Collapsed again');
  await page.reload();
  assert(await collapsed(),'Still collapsed after reload');
  await ex.click();
  assert(!(await collapsed())&&(await page.evaluate(k=>localStorage.getItem(k),KEY))==='0','Expand restores and saves 0');
  assert(await page.locator('.mode-switch').isVisible(),'Sidebar back');
  await page.evaluate(()=>document.activeElement?.blur());
  await page.keyboard.press('ControlOrMeta+Backslash');
  assert(await collapsed(),'Shortcut collapses');
  await page.keyboard.press('ControlOrMeta+Backslash');
  assert(!(await collapsed())&&await activeId()==='BODY','Shortcut expands, focus outside the sidebar stays: '+await activeId());
  // The shortcut from a control the rail hides puts focus on the rail button, then back on the collapse button.
  await page.locator('.mode-switch button').first().focus();
  await page.keyboard.press('ControlOrMeta+Backslash');
  assert(await collapsed()&&await activeId()==='sidebar-expand','Shortcut from inside the sidebar: '+await activeId());
  await page.keyboard.press('ControlOrMeta+Backslash');
  assert(!(await collapsed())&&await activeId()==='sidebar-collapse','Shortcut from the rail button: '+await activeId());
  await page.evaluate(()=>document.activeElement?.blur());
  // Typing: the shortcut is ignored in a text field.
  await page.evaluate(()=>{const t=document.createElement('textarea');t.id='agent-message';document.body.append(t);t.focus();});
  await page.keyboard.press('ControlOrMeta+Backslash');
  assert(!(await collapsed()),'Shortcut ignored while typing');
  await page.evaluate(()=>document.getElementById('agent-message').remove());
  // Focus mode hides it without saving.
  await page.evaluate(()=>window.interspaceSidebar.set(true,{persist:false}));
  assert(await collapsed()&&(await page.evaluate(k=>localStorage.getItem(k),KEY))==='0'&&await page.evaluate(()=>window.interspaceSidebar.collapsed()),'set(true,{persist:false}) leaves the saved choice');
  await page.evaluate(()=>window.interspaceSidebar.set(false,{persist:false}));
  assert(!(await collapsed()),'Restored');
  // Narrow layout: no rail controls, sidebar stacks as before even if saved collapsed.
  await page.evaluate(()=>window.interspaceSidebar.set(true));
  await page.setViewportSize({width:390,height:800});
  assert(await page.locator('#sidebar-collapse').isHidden()&&await ex.isHidden(),'No buttons at 390px');
  assert(await page.locator('.mode-switch').isVisible(),'Narrow sidebar content stays');
  await page.setViewportSize({width:1280,height:1000});
  await page.evaluate(()=>window.interspaceSidebar.set(false));
 }
 assert(!errors.length,'Page errors: '+errors.join('; '));
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 return {checks:'Research | Code switch with aria-pressed, mode New button and kind, project picker only in Code, groups Needs you/Working/Done with words, approved draft, children left out, literal titles, Report ready, Show all by keyboard, open task marked'};
}
