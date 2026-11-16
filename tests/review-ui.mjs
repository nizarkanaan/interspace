/* Review changes view against a fake backend in its own harness page: no app shell, backend or repository. */
import {mkdtempSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
export default async function check(page){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const ui=p=>pathToFileURL(path.resolve('app/ui',p)).href;
 const harness=path.join(mkdtempSync(path.join(tmpdir(),'interspace-review-ui-')),'review.html');
 writeFileSync(harness,`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="${ui('desk.css')}"></head><body><main id="review-view"></main><script src="${ui('review.js')}"></script></body></html>`);
 await page.goto(pathToFileURL(harness).href);
 const HEAD='abc12345'.repeat(5),BASE='0123abcd'.repeat(5);
 const summary={branch:'interspace/task-aaaaaaaa',base_commit:BASE,head_commit:HEAD,truncated:false,files:[
  {path:'src/parser.py',change:'modify',old_path:null,additions:3,deletions:1,binary:false},
  {path:'docs/new.md',change:'rename',old_path:'docs/old.md',additions:0,deletions:0,binary:false},
  {path:'<img src=x onerror="window.pwned=1">.png',change:'add',old_path:null,additions:null,deletions:null,binary:true}],
  patch:'diff --git a/src/parser.py b/src/parser.py\n--- a/src/parser.py\n+++ b/src/parser.py\n@@ -1,2 +1,4 @@\n-old\n+new <script>window.pwned=2</script>\n+two\n+three\n ctx\n'};
 await page.evaluate(({summary})=>{
  const f=window.reviewFixture={requests:[],hold:{},held:[],answers:{review_summary:()=>summary,review_branches:()=>({branches:['dev','interspace/task-aaaaaaaa','main','release'],current:'main'})}};
  window.interspaceReview.init({request(method,params,options){
   f.requests.push({method,params,options});
   return new Promise((resolve,reject)=>{
    const answer=()=>{try{const r=f.answers[method](params);r instanceof Error?reject(r):resolve(r);}catch(e){reject(e);}};
    if(f.hold[method])f.held.push(answer);else queueMicrotask(answer);
   });
  }});
 },{summary});
 const view=page.locator('#review-view');
 const text=async()=>(await view.textContent())||'';
 const req=m=>page.evaluate(m=>window.reviewFixture.requests.filter(r=>r.method===m),m);
 const answer=(method,body)=>page.evaluate(({method,body})=>{window.reviewFixture.answers[method]=()=>body&&body.error?new Error(body.error):body;},{method,body});

 // Opening loads the summary and the branches, then shows files, counts and the diff as text.
 await page.evaluate(()=>window.interspaceReview.open('t1',{project_id:'p1'}));
 await page.locator('#review-merge').waitFor();
 assert((await req('review_summary'))[0].params.task_id==='t1','Summary not requested for t1');
 assert((await req('review_branches'))[0].params.project_id==='p1','Branches not requested for p1');
 const shown=await text();
 for(const part of ['Review changes','interspace/task-aaaaaaaa','src/parser.py','+3','−1','docs/old.md → docs/new.md','binary','3 files changed'])assert(shown.includes(part),'Missing '+part+': '+shown);
 assert(await page.evaluate(()=>document.activeElement?.tagName)==='H2','Heading not focused on open');

 // Backend text is never markup.
 assert(await view.locator('img,script').count()===0,'Backend text became markup');
 assert(await page.evaluate(()=>window.pwned)===undefined,'Injected script ran');
 assert(shown.includes('<img src=x onerror="window.pwned=1">.png')&&shown.includes('<script>window.pwned=2</script>'),'Literal text lost');
 assert(await view.locator('.diff-line.add').count()===3&&await view.locator('.diff-line.del').count()===1&&await view.locator('.diff-line.hunk').count()===1,'Diff lines not classified');

 // Into defaults to the current branch, lists the other local branches and never the task branch itself.
 const options=await page.locator('#review-into option').evaluateAll(list=>list.map(o=>o.value));
 assert(JSON.stringify(options)===JSON.stringify(['dev','main','release']),'Into options wrong: '+options);
 assert(await page.locator('#review-into').inputValue()==='main','Into does not default to current');
 assert((await page.locator('#review-into option[value="main"]').textContent()).includes('(current)'),'Current not marked');

 // Keyboard: pick dev, tab to Merge, press Enter. The request binds the reviewed head.
 await page.locator('#review-into').focus();
 await page.keyboard.press('ArrowDown');
 await page.locator('#review-into').selectOption('dev');
 await page.keyboard.press('Tab');
 assert(await page.evaluate(()=>document.activeElement?.id)==='review-merge','Tab does not reach Merge');
 await page.evaluate(()=>{window.reviewFixture.hold.review_merge=true;});
 await answer('review_merge',{status:'merged',merge_commit:'fedcba98'.repeat(5),conflicts:[],detail:'Merged into dev.'});
 await page.keyboard.press('Enter');
 assert(await page.locator('#review-merge').isDisabled(),'Merge not disabled while merging');
 assert((await page.locator('#review-merge').textContent()).includes('Merging'),'No merging state');
 assert((await view.getAttribute('aria-busy'))==='true','Not busy while merging');
 let merges=await req('review_merge');
 assert(merges.length===1&&merges[0].params.task_id==='t1'&&merges[0].params.into==='dev'&&merges[0].params.expected_head===HEAD,'Merge params wrong: '+JSON.stringify(merges));
 await page.evaluate(()=>{window.reviewFixture.hold.review_merge=false;window.reviewFixture.held.splice(0).forEach(f=>f());});
 await page.locator('.review-result[data-status="merged"]').waitFor();
 assert((await text()).includes('Merged into dev as fedcba98.'),'Merged result missing');
 assert(await page.evaluate(()=>document.activeElement?.classList.contains('review-result')),'Result not focused');

 // Conflict, dirty, stale and errors show inline.
 const runMerge=async body=>{await answer('review_merge',body);await page.locator('#review-merge').click();await page.locator(body.error?'.review-error':'.review-result[data-status="'+body.status+'"]').waitFor();return text();};
 let out=await runMerge({status:'conflict',merge_commit:null,conflicts:['src/parser.py','<b>x</b>'],detail:'The merge into dev conflicts, so nothing was changed.'});
 assert(out.includes('Conflicts. Nothing was changed.')&&out.includes('src/parser.py')&&out.includes('<b>x</b>'),'Conflict result missing: '+out);
 assert(await view.locator('.review-result li').count()===2&&await view.locator('.review-result b').count()===0,'Conflict paths wrong');
 out=await runMerge({status:'dirty',merge_commit:null,conflicts:[],detail:'main is checked out in your working copy, so Interspace leaves it alone.'});
 assert(out.includes('Not merged.')&&out.includes('checked out in your working copy'),'Dirty result missing');
 out=await runMerge({error:'Git failed: something.'});
 assert(out.includes('Git failed: something.')&&await view.locator('[role="alert"]').count()===1,'Error not shown');
 out=await runMerge({status:'stale',merge_commit:null,conflicts:[],detail:'The task branch changed since you reviewed it.'});
 assert(out.includes('The branch changed since you reviewed it.'),'Stale result missing');
 const before=(await req('review_summary')).length;
 await view.getByRole('button',{name:'Review the new changes'}).click();
 await page.locator('#review-merge').waitFor();
 assert((await req('review_summary')).length===before+1,'Stale reload did not refetch the summary');

 // A late reply for an earlier task never overwrites the open one.
 await page.evaluate(()=>{window.reviewFixture.hold.review_summary=true;window.interspaceReview.open('t-old',{project_id:'p1'});});
 await page.evaluate(()=>{window.reviewFixture.hold.review_summary=false;});
 await answer('review_summary',{...summary,branch:'interspace/task-bbbbbbbb',files:[],patch:''});
 await page.evaluate(()=>window.interspaceReview.open('t2',{project_id:'p1'}));
 await page.locator('#review-into').waitFor();
 await answer('review_summary',summary);
 await page.evaluate(()=>window.reviewFixture.held.splice(0).forEach(f=>f()));
 await page.waitForTimeout(50);
 out=await text();
 assert(out.includes('interspace/task-bbbbbbbb')&&out.includes('No changes on this branch.'),'Late reply overwrote the open task: '+out);
 assert(await page.locator('#review-merge').isDisabled(),'Merge enabled with no changes');

 // Load failure is shown, never a blank view.
 await answer('review_summary',{error:'This task has not published a branch yet.'});
 await page.evaluate(()=>window.interspaceReview.open('t3',{project_id:'p1'}));
 await page.locator('.review-error').waitFor();
 assert((await text()).includes('This task has not published a branch yet.'),'Load error missing');

 // Light and dark, 320 to 1280 wide, without horizontal overflow.
 await answer('review_summary',{...summary,files:[...summary.files,{path:'a/very/long/path/'.repeat(12)+'file.py',change:'modify',old_path:null,additions:1,deletions:1,binary:false}],patch:summary.patch+'+'+'x'.repeat(400)+'\n'});
 await page.evaluate(()=>window.interspaceReview.open('t1',{project_id:'p1'}));
 await page.locator('#review-merge').waitFor();
 await answer('review_merge',{status:'conflict',merge_commit:null,conflicts:['a/very/long/path/'.repeat(12)+'file.py'],detail:'Conflicts.'});
 await page.locator('#review-merge').click();await page.locator('.review-result[data-status="conflict"]').waitFor();
 const fits=[],inks=new Set();
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});
  for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:900});
   const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,ink:getComputedStyle(document.querySelector('#review-view h2')).color}));
   assert(fit.scroll<=fit.width,'Overflow at '+width+' '+colorScheme+': '+fit.scroll);fits.push(fit);inks.add(fit.ink);
  }}
 assert(inks.size===2,'Light and dark ink are the same: '+[...inks]);
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'summary and branches requests, file list with +/− rename binary, text-safe diff and paths, Into default current without task branch, keyboard merge bound to reviewed head, merging state, merged/conflict/dirty/stale/error inline, stale reload, late replies ignored, load error, light/dark 320-1280 fit',responsiveStates:fits.length};
}
