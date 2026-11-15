/* Spaces sidebar frame with fake panels: no connector, Keychain or network. */
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,m)=>{if(!v)throw Error(m);};
 const text=async loc=>(await loc.textContent())||'';
 await page.goto(url);
 if(!await page.evaluate(()=>!!document.getElementById('ispace').interspaceLab))await page.addScriptTag({path:'design/scene/lab-scene.js'});

 // The frame exists before the panel scripts, which are tagged for all four apps.
 const scripts=await page.evaluate(()=>[...document.scripts].map(s=>s.getAttribute('src')));
 const frame=scripts.indexOf('spaces.js');
 assert(frame>=0,'Spaces frame script missing');
 for(const app of ['notion','github','gdrive','zotero']){const at=scripts.indexOf('spaces/'+app+'.js');assert(at>frame,'Panel script for '+app+' missing or before the frame');}
 assert(await page.evaluate(()=>typeof window.interspaceSpaces?.register==='function'),'register not defined');

 await page.evaluate(()=>{
  const f=window.spacesFixture={requests:[]};
  const state={version:3,projects:[{id:'p1',name:'Fixture project',brief:'',priority:'normal',next_action:''}],project_id:'p1',project:'Fixture project',task_id:null,task:null,tasks:[{id:'t1',mode:'agent',title:'Fix the date parser',status:'idle',run_count:0,specialist_limit:1}],threads:{workspace:[],project:[],task:[]},pending:null,run:null,runs:[],active:null,error:'',connection:{message:'Synthetic fixture'},usage:[],source_selection:{mode:'selected',selection_version:1,revision:'r',paths:['README.md']},source_error:'',spaces:{apps:{github:{v:1,app:'github',state:'signed_in',account:{label:'octocat',id:'1'},granted:[],detail:'',checked_at:'2026-11-11T09:30:00.000Z'},zotero:{v:1,app:'zotero',state:'unavailable',account:null,granted:[],detail:'Open Zotero.',checked_at:'2026-11-11T09:30:00.000Z'}}}};
  window.webkit={messageHandlers:{interspace:{postMessage(r){f.requests.push(r);const p=r.params||{};let result={};
   if(r.method==='select_task')result={...state,task_id:p.task_id,task:{id:p.task_id,title:'Fix the date parser',specialist_limit:1,draft:'',mode:'agent'}};
   else if(r.method==='task_events')result={events:[],last_seq:0,complete:true};
   else if(r.method==='scope_get')result={scope:null,scope_digest:null,scope_approval:null};
   else if(r.method==='spaces_browse')result={v:1,items:[{ref:'github:repo:octo/notes',kind:'repo',title:'<b>octo/notes</b>',parent:null,url:null,updated_at:null,has_children:true,meta:{}}],next_cursor:null};
   queueMicrotask(()=>window.interspaceReceive({id:r.id,result}));}}}};
  window.interspaceReceive({type:'state',state});
 });

 // Missing panel files leave each entry showing "Not available yet".
 const nav=page.locator('nav[aria-label="Spaces"]');
 for(const name of ['Notion','GitHub','Google Drive','Zotero'])assert(await nav.getByRole('button',{name:new RegExp('^'+name)}).count()===1,'Sidebar entry missing: '+name);
 assert((await text(nav)).includes('octocat'),'Signed-in account label missing');
 for(const name of ['Notion','GitHub','Google Drive','Zotero']){
  await nav.getByRole('button',{name:new RegExp('^'+name)}).click();
  assert(await page.locator('#spaces-view').isVisible(),'Spaces view hidden for '+name);
  assert((await text(page.locator('#heading'))).includes(name),'Heading wrong for '+name);
  // Panels merged so far register themselves; the rest still show the placeholder.
  const placeholder=(await text(page.locator('#space-panel'))).includes('Not available yet');
  if(name==='Notion')assert(!placeholder,'Merged Notion panel did not register');
  else if(name==='GitHub')assert(!placeholder&&(await text(page.locator('#space-panel'))).includes('Connect GitHub'),'GitHub panel did not register');
  else if(name==='Google Drive')assert(!placeholder,'Merged Google Drive panel did not register');
  else if(name==='Zotero')assert(!placeholder,'Zotero panel did not register');
  else assert(placeholder,'Missing panel not reported for '+name);
 }

 // Zotero panel: unavailable instructions, then a read-only listing and read with literal remote text.
 await page.evaluate(()=>{
  const handler=window.webkit.messageHandlers.interspace,original=handler.postMessage.bind(handler);
  const z=window.zoteroFixture={state:'unavailable',requests:[]};
  handler.postMessage=r=>{
   const p=r.params||{};if(p.app!=='zotero')return original(r);
   z.requests.push(r);let result={};
   const signedIn=z.state==='signed_in';
   if(r.method==='spaces_status')result={apps:[{v:1,app:'zotero',state:z.state,account:signedIn?{label:'My Library',id:'local'}:null,granted:signedIn?['library:read']:[],detail:signedIn?'':'Zotero is not running. Open Zotero on this Mac, then try again.',checked_at:'2026-11-11T09:30:00.000Z'}]};
   else if(r.method==='spaces_browse')result={v:1,items:[{ref:'zotero:library:users/0',kind:'library',title:'My Library',parent:null,url:null,updated_at:null,has_children:true,meta:{type:'user'}},{ref:'zotero:item:users/0/items/ITEM2222',kind:'item',title:'<img src=x onerror=alert(1)>Attention',parent:'zotero:library:users/0',url:null,updated_at:'2026-11-10T18:02:11.000Z',has_children:false,meta:{type:'journalArticle',creators:'Vaswani et al.',date:'2017'}}],next_cursor:null};
   else if(r.method==='spaces_read')result={v:1,ref:p.ref,title:'Attention',format:'json',text:'{"title": "<b>Attention</b>"}',truncated:false,next_cursor:null,version:'1203',url:null,meta:{type:'journalArticle'},parent:null};
   queueMicrotask(()=>window.interspaceReceive({id:r.id,result}));
  };
 });
 await nav.getByRole('button',{name:/^Notion/}).click();await nav.getByRole('button',{name:/^Zotero/}).click();
 const zPanel=page.locator('#space-panel');
 await zPanel.getByRole('button',{name:'Check again'}).waitFor();
 assert((await text(zPanel)).includes('Open Zotero on this Mac'),'Zotero unavailable detail missing');
 await page.evaluate(()=>{window.zoteroFixture.state='signed_in';});
 await zPanel.getByRole('button',{name:'Check again'}).click();
 const zItem=zPanel.getByRole('button',{name:'<img src=x onerror=alert(1)>Attention'});
 await zItem.waitFor();
 assert(await zPanel.locator('img').count()===0,'Zotero title inserted as markup');
 assert((await text(zPanel)).includes('(read-only)')&&(await text(zPanel)).includes('Vaswani et al.'),'Zotero read-only account or item meta missing');
 await zItem.click();
 await zPanel.locator('pre.space-content').waitFor();
 assert((await text(zPanel.locator('pre.space-content'))).includes('<b>Attention</b>')&&await zPanel.locator('pre b').count()===0,'Zotero content not literal');
 assert(await zPanel.getByRole('button',{name:'Move to trash'}).count()===0,'Read-only Zotero offered a write');
 const zSent=await page.evaluate(()=>window.zoteroFixture.requests.map(r=>r.method));
 assert(!zSent.includes('spaces_write')&&zSent.includes('spaces_read'),'Unexpected Zotero requests: '+zSent.join(','));

 // A registered panel renders with a scoped api; the frame disposes it on leaving.
 await page.evaluate(()=>{
  window.panelLog=[];
  window.interspaceSpaces.register({app:'github',title:'GitHub',render(container,api){window.githubApi=api;window.panelLog.push('render');const p=document.createElement('p');p.textContent='GitHub panel body';container.append(p);},dispose(){window.panelLog.push('dispose');}});
  window.interspaceSpaces.register({app:'evil',title:'Evil',render(){},dispose(){}});
 });
 assert(await nav.getByRole('button',{name:/^Evil/}).count()===0,'Unknown app registered');
 await nav.getByRole('button',{name:/^GitHub/}).click();
 assert((await text(page.locator('#space-panel'))).includes('GitHub panel body'),'Registered panel not rendered');
 assert(!(await text(page.locator('#space-panel'))).includes('Not available yet'),'Registered panel still unavailable');
 const browse=await page.evaluate(()=>window.githubApi.request('spaces_browse',{limit:5}));
 assert(browse.items[0].title==='<b>octo/notes</b>','Browse result not passed through');
 const sent=await page.evaluate(()=>window.spacesFixture.requests.filter(r=>r.method==='spaces_browse'));
 assert(sent.length===1&&JSON.stringify(sent[0].params)===JSON.stringify({limit:5,app:'github'}),'Request not scoped to the panel app: '+JSON.stringify(sent));
 const before=await page.evaluate(()=>window.spacesFixture.requests.length);
 const refused=await page.evaluate(async()=>{const out=[];for(const [m,p] of [['agent_cancel',{task_id:'t1'}],['spaces_browse',{app:'notion'}],['scope_get',{}]]){try{await window.githubApi.request(m,p);out.push('sent '+m);}catch(e){out.push('refused');}}return out;});
 assert(refused.every(x=>x==='refused'),'Out-of-scope panel request allowed: '+refused);
 assert(await page.evaluate(n=>window.spacesFixture.requests.length-n,before)===0,'Refused request reached the bridge');

 // Shared destructive-action dialog: literal text, keyboard-accessible, both answers.
 let answer=page.evaluate(()=>window.githubApi.confirm('Close <i>issue</i> #38?'));
 const dialog=page.locator('#confirm-dialog');
 assert(await dialog.isVisible(),'Confirm dialog hidden');
 assert((await text(dialog)).includes('Close <i>issue</i> #38?')&&await dialog.locator('i').count()===0,'Confirm text not literal');
 await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
 assert(await answer===false,'Cancel did not resolve false');
 answer=page.evaluate(()=>window.githubApi.confirm('Archive the page?'));
 await dialog.getByRole('button',{name:'Confirm',exact:true}).click();
 assert(await answer===true,'Confirm did not resolve true');
 answer=page.evaluate(()=>window.githubApi.confirm('Trash the file?'));
 await page.keyboard.press('Escape');
 assert(await answer===false,'Escape did not resolve false');

 // Mentions go to the composer of the open agent task.
 const noTask=await page.evaluate(()=>window.githubApi.mention('github:issue:octo/notes#41','Track reading list'));
 assert(noTask===false,'Mention reported success without an agent task');
 assert((await text(page.locator('#space-status'))).includes('Open an agent task'),'No-task mention not explained');
 await page.locator('[data-view=tasks]').click();
 assert(await page.evaluate(()=>window.panelLog.join(','))==='render,dispose','Panel not disposed on leaving: '+await page.evaluate(()=>window.panelLog.join(',')));
 await page.locator('[data-open-task="t1"]').click();
 await nav.getByRole('button',{name:/^GitHub/}).click();
 assert(await page.evaluate(()=>window.githubApi.mention('github:issue:octo/notes#41','Track reading list'))===true,'Mention failed with an agent task');
 assert((await text(page.locator('#space-status'))).includes('Fix the date parser'),'Mention target not named');
 await page.evaluate(()=>window.githubApi.openRef('github:issue:octo/notes#7'));
 await page.locator('[data-view=tasks]').click();await page.locator('[data-open-task="t1"]').click();
 assert((await page.locator('#agent-message').inputValue()).includes('@github:issue:octo/notes#41'),'Mention not inserted into the composer');

 // openRef selects the app and tells the panel which resource.
 await page.evaluate(()=>{window.opened=[];window.interspaceSpaces.register({app:'notion',title:'Notion',render(container){container.addEventListener('interspace:open-ref',e=>window.opened.push(e.detail.ref));},dispose(){}});});
 await page.evaluate(()=>window.githubApi.openRef('notion:page:n1'));
 assert((await text(page.locator('#heading'))).includes('Notion'),'openRef did not switch apps');
 assert(await page.evaluate(()=>window.opened.join(','))==='notion:page:n1','openRef not delivered to the panel');

 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:900});
  await nav.getByRole('button',{name:/^Zotero/}).click();
  const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow spaces '+width+' '+colorScheme);fits.push(fit);
 }}
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'frame before panel tags, Not available yet for missing panels, account labels, registration and unknown-app refusal, app-scoped spaces_* requests, literal confirm dialog with Cancel/Confirm/Escape, composer mentions, openRef, dispose on leave, light/dark 320-1280 fit',responsiveStates:fits.length};
}
