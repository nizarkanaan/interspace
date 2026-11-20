/* Archive and delete (docs/superpowers/specs/2026-11-20-archive-delete-design.md), from fixture data only: archive
   moves a task to the sidebar's Archived list and Restore brings it back; delete asks first, says what goes, offers
   Review and merge for unmerged work, says whether the branch is deleted, and lands on the list with a note; a working
   task cannot be archived or deleted. */
import {install,requests,assert,text,resetSeq} from './research-fixture.mjs';
const r=(id,title,status,extra={})=>({id,mode:'agent',kind:'research',project_id:null,title,status,provider:'codex',model:null,role:'orchestrator',...extra});
const c=(id,title,status,extra={})=>({id,mode:'agent',kind:'project',project_id:'p1',title,status,provider:'claude',model:null,role:'orchestrator',...extra});

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 await install(page,url,{rows:[c('t1','Add input validation','idle'),c('t2','Merged work','idle'),c('t3','Busy task','running')],
  researchRows:[r('q1','Fallback evidence','idle')],history:{},
  deleteChecks:{t1:{working:false,subagents:2,kind:'project',branches:[{project_id:'p1',name:'interspace/task-t1',exists:true,ahead:3,into:'main',checked_out:false}]},
   t2:{working:false,subagents:0,kind:'project',branches:[{project_id:'p1',name:'interspace/task-t2',exists:true,ahead:0,into:'main',checked_out:false}]}}});
 const side=page.locator('#sidebar-tasks'),menu=page.locator('.task-menu'),dialog=page.locator('#delete-dialog');
 const openMenu=async id=>{await side.locator('[data-sidebar-task='+id+']').click({button:'right'});await menu.waitFor();};

 // The details panel has no archive or delete controls.
 await page.locator('[data-view=research]').click();
 await side.locator('[data-sidebar-task=q1]').click();
 assert(await page.locator('#agent-manage').count()===0&&await page.locator('#task-delete').count()===0,'No controls in the panel');

 // Right-click: Open, Archive, Delete; Archive moves the task to the Archived list; Restore from its menu.
 await openMenu('q1');
 assert(JSON.stringify(await menu.locator('[role=menuitem]').allTextContents())===JSON.stringify(['Open','Archive','Delete…']),'Menu items');
 await menu.locator('[data-action=archive]').click();
 await page.waitForFunction(()=>document.querySelector('#sidebar-tasks .side-archived-toggle'));
 assert(JSON.stringify((await requests(page,'task_archive')).at(-1))===JSON.stringify({task_id:'q1',archived:true}),'Archive request');
 assert((await text(page.locator('#info'))).includes('Archived “Fallback evidence”'),'Archive note');
 assert((await text(side.locator('[data-sidebar-task=q1]'))).includes('Archived')&&await side.locator('.side-group.done').count()===0,'In the Archived list');
 // Keyboard: Shift+F10 on the focused task, arrows, Enter.
 await side.locator('[data-sidebar-task=q1]').focus();await page.keyboard.press('Shift+F10');await menu.waitFor();
 assert(await page.evaluate(()=>document.activeElement?.dataset.action)==='open','Menu focuses its first item');
 await page.keyboard.press('ArrowDown');assert((await page.evaluate(()=>document.activeElement?.textContent))==='Restore','Arrow moves');
 await page.keyboard.press('Enter');
 await page.waitForFunction(()=>!document.querySelector('#sidebar-tasks .side-archived-toggle'));
 await openMenu('q1');await page.keyboard.press('Escape');
 assert(await menu.count()===0&&await page.evaluate(()=>document.activeElement?.dataset.sidebarTask)==='q1','Escape closes and returns focus');

 // A working task: Stop is offered; Archive and Delete are disabled.
 await page.locator('[data-view=tasks]').click();
 await openMenu('t3');
 assert(JSON.stringify(await menu.locator('[role=menuitem]').allTextContents())===JSON.stringify(['Open','Stop','Archive','Delete…']),'Working menu');
 assert((await menu.locator('[data-action=delete]').getAttribute('aria-disabled'))==='true'&&(await text(menu)).includes('Stop this task to archive or delete it.'),'Working locked');
 await menu.locator('[data-action=delete]').click({force:true});
 assert(await dialog.evaluate(d=>!d.open),'Disabled delete does nothing');
 await page.mouse.click(900,600);

 // Unmerged branch: the dialog warns, offers Review and merge, and focuses Cancel.
 await openMenu('t1');await menu.locator('[data-action=delete]').click();
 await page.waitForFunction(()=>document.querySelector('#delete-dialog .delete-branch'));
 const card=await text(dialog);
 assert(card.includes('Delete “Add input validation”?')&&card.includes('its private copy of the project and 2 subagents')&&card.includes('cannot be undone'),'What goes: '+card);
 assert(card.includes('interspace/task-t1 has 3 commits not merged into main')&&card.includes('loses them unless you merge first'),'Unmerged warning');
 assert(JSON.stringify(await dialog.locator('button').allTextContents())===JSON.stringify(['Review and merge first','Delete task and branch','Delete task, keep branch','Cancel']),'Buttons');
 assert(await page.evaluate(()=>document.activeElement?.id)==='delete-cancel','Cancel focused');
 await page.keyboard.press('Enter');
 assert(await dialog.evaluate(d=>!d.open)&&(await requests(page,'task_delete')).length===0,'Cancel deletes nothing');

 // Keep the branch; the note names it and the task leaves the sidebar.
 await openMenu('t1');await menu.locator('[data-action=delete]').click();
 await dialog.locator('#delete-keep').click();
 await page.waitForFunction(()=>(document.getElementById('info').textContent||'').includes('Deleted'));
 assert(JSON.stringify((await requests(page,'task_delete')).at(-1))===JSON.stringify({task_id:'t1',branches:'keep'}),'Keep request');
 assert((await text(page.locator('#info'))).includes('Deleted “Add input validation”.')&&(await text(page.locator('#info'))).includes('Kept branch interspace/task-t1'),'Note');
 await page.waitForFunction(()=>!document.querySelector('[data-sidebar-task=t1]'));

 // A merged branch is said to be deleted with the task.
 await openMenu('t2');await menu.locator('[data-action=delete]').click();
 await page.waitForFunction(()=>document.querySelector('#delete-dialog .delete-branch'));
 assert((await text(dialog)).includes('interspace/task-t2 is fully merged into main and will be deleted with the task.'),'Merged note');
 assert(JSON.stringify(await dialog.locator('button').allTextContents())===JSON.stringify(['Delete task and branch','Cancel']),'Merged buttons');
 await dialog.locator('#delete-confirm').click();
 await page.waitForFunction(()=>(document.getElementById('info').textContent||'').includes('Deleted branch interspace/task-t2'));
 assert(!errors.length,'Page errors: '+errors.join('; '));
 return {checks:'no controls in the panel; right-click menu Open/Archive/Delete; archive to the Archived list and restore by keyboard (Shift+F10, arrows, Enter); Escape returns focus; working task offers Stop and disables Archive/Delete; delete dialog lists what goes, unmerged branch warning with Review and merge / delete / keep / cancel, Cancel focused and deletes nothing; keep and delete requests; notes naming branches'};
}
