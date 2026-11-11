/* Controlled bridge test: no native backend, source access or model calls. */
export default async function check(page, url) {
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);
  await page.evaluate(()=>{
    const report=id=>({id,stage:'completed',goal:'Review '+id,revision:'abcdef123456',results:{researcher:{summary:'Report '+id,findings:[{claim:'Snapshot evidence',evidence:[{source:'README.md',start:1,end:1}]}],proposal:'Proposal only'},reviewer:{summary:'Checked',findings:[],proposal:'Accepted',verdict:'accept'}},events:[],sources:{'README.md':{lines:1}},artifact_id:'artifact-'+id,revision_round:0,revision_limit:1});
    const projects=[{id:'a',name:'Sample Project',brief:'A sample research project',priority:'high',next_action:'Review validation',latest_run:{stage:'completed'},has_pending_plan:false},{id:'b',name:'Lab notebook',brief:'Another research project',priority:'normal',next_action:'Compare methods',latest_run:null,has_pending_plan:false}];
    const runs={a:[report('a-new'),report('a-old')],b:[]};
    let selected='a',selectedRun='a-new';
    const threads={a:[{role:'user',text:'A private conversation'}],b:[]};
    const state=()=>({version:2,projects,project_id:selected,project:projects.find(p=>p.id===selected).name,threads:{workspace:[],project:threads[selected]},pending:null,active:null,active_project_id:null,active_run_id:null,active_project:'Workspace',error:'',connection:{message:'Synthetic test'},usage:[],run:runs[selected].find(r=>r.id===selectedRun)||null,runs:runs[selected]});
    window.testBridge={state,heldSource:null,heldChat:null,requests:[]};
    window.webkit={messageHandlers:{interspace:{postMessage(request){
      window.testBridge.requests.push(request);
      let result;
      if(request.method==='source'){window.testBridge.heldSource=request;return;}
      if(request.method==='chat'){window.testBridge.heldChat=request;return;}
      if(request.method==='switch_project'){selected=request.params.project_id;selectedRun=runs[selected][0]?.id;}
      if(request.method==='select_run')selectedRun=request.params.run_id;
      if(request.method==='update_project'){Object.assign(projects.find(p=>p.id===request.params.project_id),request.params);if(window.testBridge.holdMetadata){window.testBridge.heldMetadata=request;return;}}
      result=state();
      queueMicrotask(()=>window.interspaceReceive({id:request.id,result}));
    }}}};
    window.interspaceReceive({type:'state',state:state()});
  });
  const assert=(value, message)=>{if(!value)throw Error(message);};
  await page.locator('[data-view=workspace]').click();
  await page.locator('#message').fill('Workspace draft');
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  await page.locator('#message').fill('A draft');
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  await page.locator('#project-settings summary').click();
  await page.locator('#project-brief').fill('Unsaved A brief');
  await page.locator('#project-picker').selectOption('b');
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  assert(await page.locator('#message').inputValue()==='', 'A draft leaked to B');
  await page.locator('#message').fill('B draft');
  assert(!(await page.locator('#transcript').textContent()).includes('A private conversation'),'A thread leaked to B');
  await page.locator('#project-picker').selectOption('a');
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  assert(await page.locator('#message').inputValue()==='A draft','A draft lost');
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
  assert(await page.locator('#project-brief').inputValue()==='Newer unsaved brief','Newer metadata edit lost after late save response');
  assert((await page.locator('#metadata-status').textContent()).includes('Unsaved'),'Newer metadata edit marked saved');
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  await page.locator('#artifact-browser summary').click();
  await page.locator('#run-picker').selectOption('a-old');
  assert((await page.locator('#result-body').textContent()).includes('Report a-old'),'Old run not restored');
  await page.locator('#result-body .citation').click();
  await page.locator('#project-picker').selectOption('b');
  await page.evaluate(()=>window.interspaceReceive({id:window.testBridge.heldSource.id,result:{text:'A_PRIVATE_SOURCE'}}));
  assert(await page.locator('#source-box').isHidden(),'Delayed A source appeared in B');
  await page.locator('[data-view=workspace]').click();
  assert(await page.locator('#message').inputValue()==='Workspace draft','Workspace draft lost');
  assert(await page.locator('.project-card').count()===2,'Overview missing project');
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  await page.locator('#message').fill('B submitted');
  await page.locator('#composer').evaluate(form=>form.requestSubmit());
  await page.locator('#project-picker').selectOption('a');
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  await page.evaluate(()=>window.interspaceReceive({id:window.testBridge.heldChat.id,result:{started:true}}));
  assert(await page.locator('#message').inputValue()==='A draft','Late B send erased A draft');
  await page.locator('#project-picker').selectOption('b');
  await page.getByRole('button',{name:'Project conversation',exact:true}).click();
  assert(await page.locator('#message').inputValue()==='', 'Submitted B draft retained');
  const fits=[];
  for(const width of [320,390,760,1024,1280]){
    await page.setViewportSize({width,height:900});
    fits.push({width,...await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:innerWidth}))});
  }
  for(const fit of fits)assert(fit.scroll<=fit.viewport,'Horizontal overflow at '+fit.width);
  assert(errors.length===0,errors.join('\n'));
  return {checks:'project switching, draft isolation, metadata save, history, late source/send responses, overview, responsive fit',fits};
}
