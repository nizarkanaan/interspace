/* Research tasks without a project, the Research sidebar entry, presets, the scope research section and research
   teams, against a fake bridge only (docs/superpowers/specs/research/tasks.md). */
import {install,requests,push,assert,text,fit,ev,resetSeq} from './research-fixture.mjs';
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 resetSeq();
 const rows=[{id:'p-task',mode:'agent',kind:'project',project_id:'p1',title:'Fix the parser',status:'idle',provider:'claude',model:null}];
 const research=[{id:'r-dup',mode:'agent',kind:'research',project_id:null,title:'Duplicated research row',status:'completed',provider:'codex',model:null},{id:'r-old',mode:'agent',kind:'research',project_id:null,title:'Earlier <b>review</b>',status:'idle',provider:null,model:null}];
 await install(page,url,{rows,researchRows:research});
 const nav=page.locator('[data-view=research]');

 // The sidebar's Research entry lists research tasks once each; the project desk does not.
 assert((await text(nav)).includes('Research')&&(await text(page.locator('#research-nav-count')))==='2','Research entry count: '+await text(nav));
 assert(!(await text(page.locator('#desk-tasks'))).includes('Duplicated research row')&&(await text(page.locator('#desk-tasks'))).includes('Fix the parser'),'Desk shows research rows');
 await nav.click();
 assert(await nav.getAttribute('aria-pressed')==='true'&&(await text(page.locator('#heading')))==='Research','Research view');
 const list=await text(page.locator('#research-tasks'));
 assert(list.includes('Earlier <b>review</b>')&&await page.locator('#research-tasks b').count()===0&&(await page.locator('#research-tasks .desk-task').count())===2,'Research list: '+list);
 assert(list.includes('no project')&&!(await text(page.locator('#research-tasks'))).includes('Fix the parser'),'Research row text');
 assert((await page.locator('#new-task').textContent())==='New research question','Research new button');

 // New research question: research kind preselected, no project field, presets shown.
 await page.locator('#new-task').click();
 assert(await page.locator('input[name=new-kind][value=research]').isChecked(),'Research kind not preselected');
 assert(await page.locator('#new-agent-project').isHidden()&&await page.locator('#new-presets').isVisible(),'Research fields');
 assert((await text(page.locator('#new-mode-note'))).includes('without a project')&&(await text(page.locator('#new-mode-note'))).includes('report and a BibTeX file'),'Research note');
 // Literature review by keyboard: an empty topic never leaves the page.
 await page.locator('input[name=new-preset][value=literature_review]').focus();await page.keyboard.press('Space');
 assert((await text(page.locator('#new-goal-label')))==='Topic of the review','Preset label');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 assert((await requests(page,'scope_default')).length===0,'Empty topic sent');
 assert((await page.locator('#new-goal').evaluate(i=>i.validationMessage)).includes('topic of the review'),'Topic validation');
 await page.locator('#new-goal').fill('synthetic <i>retrieval</i> methods');
 assert(await page.locator('#new-preview').isVisible()&&(await text(page.locator('#new-preview-text'))).startsWith('Write a literature review on: synthetic <i>retrieval</i> methods'),'Preview');
 assert((await text(page.locator('#new-preview-text'))).includes('citation checker'),'Preview asks for the checker');
 // The draft survives leaving and coming back.
 await page.locator('[data-view=tasks]').click();await nav.click();await page.locator('#new-task').click();
 assert(await page.locator('input[name=new-preset][value=literature_review]').isChecked()&&(await page.locator('#new-goal').inputValue())==='synthetic <i>retrieval</i> methods','Draft lost');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#new-agent-scope .scope-editor'));
 assert(JSON.stringify(await requests(page,'scope_default'))===JSON.stringify([{project_id:null,kind:'research'}]),'scope_default params');
 const note=await text(page.locator('#new-agent-scope-note'));
 assert(note.includes('Literature review, no project')&&note.includes('research sources only'),'Scope note: '+note);
 // The research scope editor: a source per row, no project, commands or network fieldsets.
 const legends=await page.locator('#new-agent-scope legend').allTextContents();
 assert(JSON.stringify(legends)===JSON.stringify(['Research sources','Search and time limit']),'Legends: '+JSON.stringify(legends));
 const unpaywall=page.getByLabel('Unpaywall',{exact:true});
 assert(await unpaywall.inputValue()==='ask'&&await page.getByLabel('arXiv',{exact:true}).inputValue()==='allow','Research defaults');
 assert((await text(page.locator('#new-agent-scope .research-scope'))).includes('Needs your key or email in Settings'),'Unusable source hint');
 await unpaywall.selectOption('off');await page.getByLabel('Crossref',{exact:true}).selectOption('ask');
 await page.getByRole('button',{name:'Create task',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#agent-view').hidden);
 const create=(await requests(page,'agent_create'))[0];
 assert(create.project_id===null&&create.kind==='research'&&create.title==='Literature review: synthetic <i>retrieval</i> methods'&&!('provider' in create),'agent_create: '+JSON.stringify(create));
 assert(JSON.stringify(create.scope.research.sources)===JSON.stringify({semantic_scholar:'allow',openalex:'allow',arxiv:'allow',crossref:'ask',unpaywall:'off'})&&create.scope.projects.length===0,'Research scope sent: '+JSON.stringify(create.scope));
 assert((await requests(page,'switch_project')).length===0,'Research task switched project');
 assert((await page.locator('#agent-message').inputValue()).startsWith('Write a literature review on: synthetic <i>retrieval</i> methods'),'First message not waiting in the composer');
 assert((await text(page.locator('#breadcrumb')))==='Research'&&(await page.locator('#agent-back').textContent())==='← Research','Research breadcrumb/back');
 // Scope chips name the research sources and the missing project.
 const chips=await page.locator('#agent-scope .scope-chips').allTextContents();
 assert(chips[0].includes('Research: Semantic Scholar, OpenAlex, arXiv')&&chips[0].includes('Research, asks first: Crossref')&&chips[0].includes('No project: no files or commands')&&!chips[0].includes('Unpaywall'),'Chips: '+chips[0]);
 await page.locator('#agent-back').click();
 assert((await text(page.locator('#heading')))==='Research'&&(await text(page.locator('#research-tasks'))).includes('Literature review: synthetic'),'Back to Research');

 // Verify my references: the bibliography is required and goes into the message unchanged.
 await page.locator('#new-task').click();
 await page.locator('input[name=new-preset][value=verify_references]').check();
 assert(await page.locator('#new-bib').isVisible()&&(await text(page.locator('#new-goal-label'))).includes('optional'),'Bibliography field');
 await page.locator('#new-title').fill('Check my <script>refs</script>');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 assert((await requests(page,'scope_default')).length===1&&(await page.locator('#new-bib').evaluate(i=>i.validationMessage)).includes('Paste the references'),'Empty bibliography sent');
 const bib='Example, A. (2021). A synthetic paper. Fixture Journal.\n@article{x, title={<img src=x onerror="window.pwned=1">}}';
 await page.locator('#new-bib').fill(bib);
 assert((await text(page.locator('#new-preview-text'))).endsWith('References:\n'+bib),'Bibliography not in the message');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#new-agent-scope .scope-editor'));
 await page.getByRole('button',{name:'Create task',exact:true}).click();
 await page.waitForFunction(()=>window.rFixture.requests.filter(r=>r.method==='agent_create').length===2&&!document.querySelector('#agent-view').hidden);
 assert((await requests(page,'agent_create'))[1].title==='Check my <script>refs</script>','Typed title');
 assert((await page.locator('#agent-message').inputValue()).endsWith(bib),'Bibliography message');

 // A project task still works, unchanged: project select shown, project scope, no kind sent.
 await page.locator('[data-view=tasks]').click();await page.locator('#new-task').click();
 assert(await page.locator('input[name=new-kind][value=project]').isChecked()&&await page.locator('#new-agent-project').isVisible()&&await page.locator('#new-presets').isHidden(),'Project kind from the desk');
 await page.locator('#new-title').fill('Project work');await page.locator('#new-goal').fill('Fix the tests');
 await page.getByRole('button',{name:'Review scope',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#new-agent-scope .scope-editor'));
 assert(JSON.stringify((await requests(page,'scope_default'))[2])===JSON.stringify({project_id:'p1'}),'Project scope_default');
 const plegends=await page.locator('#new-agent-scope legend').allTextContents();
 assert(plegends.includes('Commands')&&plegends.includes('Research sources'),'Project legends: '+JSON.stringify(plegends));
 // Leaving research off keeps the scope without a research key, so its digest is unchanged.
 await page.getByRole('button',{name:'Create task',exact:true}).click();
 await page.waitForFunction(()=>window.rFixture.requests.filter(r=>r.method==='agent_create').length===3);
 const pc=(await requests(page,'agent_create'))[2];
 assert(pc.project_id==='p1'&&!('kind' in pc)&&!('research' in pc.scope),'Project create: '+JSON.stringify(pc));
 // Editing a project scope to allow arXiv adds the research key with every listed source.
 await page.waitForFunction(()=>!document.querySelector('#agent-view').hidden&&document.querySelector('#agent-scope .scope-chips').textContent.includes('Research: off'));
 await page.getByRole('button',{name:'Edit scope',exact:true}).click();
 await page.locator('#agent-scope').getByLabel('arXiv',{exact:true}).selectOption('allow');
 await page.locator('#agent-scope').getByRole('button',{name:'Save scope',exact:true}).click();
 await page.waitForFunction(()=>window.rFixture.requests.some(r=>r.method==='scope_update'));
 const upd=(await requests(page,'scope_update'))[0].scope.research.sources;
 assert(upd.arxiv==='allow'&&upd.semantic_scholar==='off'&&Object.keys(upd).length===5,'scope_update research: '+JSON.stringify(upd));

 // A research team: members stay read-only, the citation checker role reads plainly, no Review changes.
 await page.evaluate(()=>{window.rFixture.history.N4=[];});
 await nav.click();await page.locator('[data-open-task=N4]').click();
 await push(page,[ev('N4','status',{state:'paused_team',detail:'',queue_position:null,reason:null}),
  ev('N4','team_proposed',{team_id:'tm1',summary:'Search, then check.',budget:null,members:[{member_id:'m1',role:'researcher',brief:'Search sources.',provider:'codex',model:null,access:'read',default:true},{member_id:'m2',role:'citation_checker',brief:'Check every reference.',provider:'codex',model:null,access:'read',default:true}]}),
  ev('N4','subagent_started',{team_id:'tm1',member_id:'m2',task_id:'N4-c',role:'citation_checker',provider:'codex',model:null,access:'read',brief:'Check every reference.',state:'running',diff_summary:{files:[{path:'x',additions:1,deletions:0}]}})]);
 await page.waitForFunction(()=>document.querySelector('#agent-stream .team-member[data-member=m2]'));
 assert((await text(page.locator('#agent-stream .team-member[data-member=m2] h4')))==='Citation checker','Citation checker title');
 const write=page.locator('#agent-stream .team-member[data-member=m1] select option[value=write]');
 assert(await write.isDisabled()&&(await write.textContent()).includes('not in a research task'),'Write offered in a research team');
 const sub=page.locator('#agent-stream .card.subagent');
 assert((await text(sub)).includes('Citation checker')&&await sub.getByRole('button',{name:/Review/}).count()===0,'Review offered for a research subagent');

 // With no project at all, New task opens on a research question and the project kind is unavailable.
 await page.evaluate(()=>{window.rFixture.requests.length=0;});
 const fits=await fit(page,'research-task',async()=>{await nav.click();},true);
 const fitsNew=await fit(page,'research-new',async()=>{await nav.click();await page.locator('#new-task').click();},true);
 await install(page,url,{projects:[],rows:[],researchRows:[]});
 assert(!(await page.locator('#new-task').isDisabled()),'New task disabled without a project');
 await page.locator('#new-task').click();
 assert(await page.locator('input[name=new-kind][value=research]').isChecked()&&await page.locator('input[name=new-kind][value=project]').isDisabled(),'No-project kinds');
 assert(!(await page.locator('#propose-task').isDisabled()),'Review scope disabled without a project');
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'Research sidebar entry from state.research.tasks with count, project desk without research rows, literal row text, New research question with research kind preselected, Literature review preset by keyboard and Verify my references, validation before scope_default, message preview, draft kept, scope_default {project_id:null,kind:research}, research scope editor without project/commands/network, source hints, exact agent_create with kind research and no project, no project switch, first message waiting in the composer, research chips, Back to Research, bibliography required and sent unchanged, project task unchanged with no kind and no research key, research key added by scope edit, research team read-only with citation checker and no Review, no-project install, light/dark 320-1280 fit',responsiveStates:fits.length+fitsNew.length};
}
