/* Controlled source panel bridge: no filesystem writes or model calls. */
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(url);
 await page.evaluate(()=>{
  const projects=[{id:'a',name:'Source A',brief:'Fixture A',priority:'normal',next_action:'',latest_run:null},{id:'b',name:'Source B',brief:'Fixture B',priority:'normal',next_action:'',latest_run:null}];
  const selections={a:{mode:'unconfirmed',version:1,selection_version:0,revision:null,paths:[]},b:{mode:'unconfirmed',version:1,selection_version:0,revision:null,paths:[]}};
  let selected='a',plan=null;
  const catalog=id=>({project_id:id,revision:'commit-'+id,selection:selections[id],suggested:['README.md'],context_characters:null,files:[{path:'README.md',mode:'100644',bytes:20,eligible:true,reason:''},{path:'notes/'+id+'.txt',mode:'100644',bytes:30,eligible:true,reason:''},{path:'.env',mode:'100644',bytes:10,eligible:false,reason:'Credential filename excluded'}],limits:{files:16,file_bytes:250000,context_characters:240000,preview_lines:200}});
  const state=()=>({version:2,projects,project_id:selected,project:projects.find(p=>p.id===selected).name,threads:{workspace:[],project:[]},pending:plan,active:null,active_project_id:null,active_run_id:null,active_project:'Workspace',error:'',connection:{message:'Synthetic source test'},usage:[],run:null,runs:[],source_selection:selections[selected],source_error:''});
  window.sourceFixture={requests:[],showPlan(){plan={id:'selected-plan',kind:'team',project_id:'a',project:'Source A',revision:'commit-a',goal:'Review chosen evidence',digest:'digest',tasks:[{id:'research',role:'researcher',objective:'Inspect selected text',expected_output:'Findings',dependencies:[],capabilities:['committed_snapshot']}],limits:{max_calls:2},source_scope:{version:1,selection_version:1,revision:'commit-a',paths:['notes/a.txt']}};window.interspaceReceive({type:'state',state:state()});},heldPreview:null,heldSave:null,holdSave:false,catalog,state};
  window.webkit={messageHandlers:{interspace:{postMessage(request){
   window.sourceFixture.requests.push(request);let result;
   if(request.method==='switch_project')selected=request.params.project_id;
   if(request.method==='list_sources')result=catalog(request.params.project_id);
   else if(request.method==='preview_source'){window.sourceFixture.heldPreview=request;return;}
   else if(request.method==='save_sources'){plan=null;
    selections[request.params.project_id]={mode:'selected',version:1,selection_version:request.params.selection_version+1,revision:request.params.revision,paths:request.params.paths};
    result=state();if(window.sourceFixture.holdSave){window.sourceFixture.heldSave={request,result};return;}
   }else result=state();
   queueMicrotask(()=>window.interspaceReceive({id:request.id,result}));
  }}}};window.interspaceReceive({type:'state',state:state()});
 });
 const assert=(v,m)=>{if(!v)throw Error(m);};
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.locator('#sources-panel').waitFor({state:'visible'});
 assert(await page.locator('#send').isDisabled(),'New project can send before source Save');
 await page.getByRole('checkbox',{name:'Select notes/a.txt',exact:true}).check();
 await page.getByRole('checkbox',{name:'Select README.md',exact:true}).uncheck();
 await page.getByRole('button',{name:'Preview notes/a.txt',exact:true}).click();
 await page.locator('#project-picker').selectOption('b');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.evaluate(()=>window.interspaceReceive({id:window.sourceFixture.heldPreview.id,result:{project_id:'a',revision:'commit-a',path:'notes/a.txt',text:'A_PRIVATE_PREVIEW',start:1,end:200,lines:300,omitted:true}}));
 assert(!(await page.locator('#source-preview').textContent()).includes('A_PRIVATE_PREVIEW'),'A preview leaked into B');
 await page.locator('#project-picker').selectOption('a');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 assert(await page.getByRole('checkbox',{name:'Select notes/a.txt',exact:true}).isChecked(),'A draft lost on switch');
 await page.getByRole('button',{name:'Save sources',exact:true}).click();
 const save=await page.evaluate(()=>window.sourceFixture.requests.find(r=>r.method==='save_sources'));
 assert(save.params.project_id==='a'&&save.params.revision==='commit-a'&&save.params.selection_version===0,'Source save lost scope/version');
 assert(JSON.stringify(save.params.paths)==='["notes/a.txt"]','Unexpected source files saved');
 assert(await page.locator('#send').isEnabled(),'Project still blocked after Save');
 await page.getByRole('button',{name:'Project conversation',exact:true}).click();
 await page.evaluate(()=>window.sourceFixture.showPlan());
 assert((await page.locator('#plan').textContent()).includes('Approved sources · selection 1'),'Plan source selection missing');
 assert((await page.locator('#plan').textContent()).includes('notes/a.txt'),'Exact plan source path missing');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.evaluate(()=>window.sourceFixture.holdSave=true);
 await page.getByRole('checkbox',{name:'Select README.md',exact:true}).check();
 await page.getByRole('button',{name:'Save sources',exact:true}).click();
 await page.getByRole('checkbox',{name:'Select notes/a.txt',exact:true}).uncheck();
 await page.locator('#project-picker').selectOption('b');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.evaluate(()=>window.interspaceReceive({id:window.sourceFixture.heldSave.request.id,result:window.sourceFixture.heldSave.result}));
 assert(await page.locator('#project-picker').inputValue()==='b','Late save switched the selected project');
 await page.locator('#project-picker').selectOption('a');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 assert(!(await page.getByRole('checkbox',{name:'Select notes/a.txt',exact:true}).isChecked()),'Late save erased newer source draft');
 assert((await page.locator('#sources-status').textContent()).includes('Unsaved'),'Newer source draft marked saved');
 await page.getByRole('button',{name:'Preview README.md',exact:true}).click();
 await page.evaluate(()=>window.interspaceReceive({id:window.sourceFixture.heldPreview.id,result:{project_id:'a',revision:'commit-a',path:'README.md',text:'1 COMMITTED PREVIEW',start:1,end:200,lines:300,omitted:true}}));
 assert((await page.locator('#source-preview').textContent()).includes('omitted'),'Long preview omission not explicit');
 assert((await page.locator('#source-file-list').textContent()).includes('Credential filename excluded'),'Exclusion reason missing');
 const fits=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){await page.setViewportSize({width,height:900});const fit=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(fit.scroll<=fit.width,'Overflow '+width);fits.push({...fit,colorScheme});}}
 assert(!errors.length,errors.join('\n'));return {checks:'explicit Save gate, committed preview, exclusions, source CAS, switching/drafts, late preview/save isolation, light/dark responsive fit',fits};
}
