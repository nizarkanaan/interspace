/* Controlled bridge test: no native backend, source access or model calls. */
export default async function check(page, url) {
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);
  await page.evaluate(()=>{
    const projects=[{id:'a',name:'Fixture A',brief:'A sample research project',priority:'high',next_action:'Review validation'},{id:'b',name:'Lab notebook',brief:'Another research project',priority:'normal',next_action:'Compare methods'}];
    const tasks={a:[{id:'old-a',title:'A private earlier task',mode:'review',status:'read_only',read_only:true}],b:[]};
    let selected='a';
    const state=()=>({version:4,projects,project_id:selected,project:projects.find(p=>p.id===selected).name,task_id:null,task:null,tasks:tasks[selected],active:null,error:'',connection:{message:'Synthetic test'},scheduler:{max_running:4,running:[],queued:[]}});
    window.testBridge={state,requests:[]};
    window.webkit={messageHandlers:{interspace:{postMessage(request){
      window.testBridge.requests.push(request);
      if(request.method==='switch_project')selected=request.params.project_id;
      if(request.method==='update_project'){Object.assign(projects.find(p=>p.id===request.params.project_id),request.params);if(window.testBridge.holdMetadata){window.testBridge.heldMetadata=request;return;}}
      const result=state();
      queueMicrotask(()=>window.interspaceReceive({id:request.id,result}));
    }}}};
    window.interspaceReceive({type:'state',state:state()});
  });
  const assert=(value, message)=>{if(!value)throw Error(message);};
  assert((await page.locator('#desk-tasks').textContent()).includes('A private earlier task'),'Project A tasks missing');
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  await page.locator('#project-settings summary').click();
  await page.locator('#project-brief').fill('Unsaved A brief');
  await page.locator('#project-picker').selectOption('b');
  assert(!(await page.locator('#desk-tasks').textContent()).includes('A private earlier task'),'A tasks leaked to B');
  assert((await page.locator('#task-count').textContent())==='0 tasks','B task count wrong');
  await page.locator('#project-picker').selectOption('a');
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  assert(await page.locator('#project-brief').inputValue()==='Unsaved A brief','A metadata draft lost');
  await page.locator('#project-form').evaluate(form=>form.requestSubmit());
  assert((await page.evaluate(()=>window.testBridge.requests.find(r=>r.method==='update_project'))).params.project_id==='a','Metadata not project bound');
  await page.evaluate(()=>window.testBridge.holdMetadata=true);
  await page.locator('#project-brief').fill('Submitted brief');
  await page.locator('#project-form').evaluate(form=>form.requestSubmit());
  await page.locator('#project-brief').fill('Newer unsaved brief');
  await page.evaluate(()=>window.interspaceReceive({id:window.testBridge.heldMetadata.id,result:window.testBridge.state()}));
  await page.locator('#project-picker').selectOption('b');
  await page.locator('#project-picker').selectOption('a');
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  assert(await page.locator('#project-brief').inputValue()==='Newer unsaved brief','Newer metadata edit lost after late save response');
  assert((await page.locator('#metadata-status').textContent()).includes('Unsaved'),'Newer metadata edit marked saved');
  const fits=[];
  for(const width of [320,390,760,1024,1280]){
    await page.setViewportSize({width,height:900});
    fits.push({width,...await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:innerWidth}))});
  }
  for(const fit of fits)assert(fit.scroll<=fit.viewport,'Horizontal overflow at '+fit.width);
  assert(errors.length===0,errors.join('\n'));
  return {checks:'project switching, task list isolation, metadata draft isolation, project-bound save, late save response keeps newer edit, responsive fit',fits};
}
