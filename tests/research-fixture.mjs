/* Shared fake bridge for the research UI suites (docs/superpowers/specs/research/): no backend, network, Keychain,
   provider or model call. Every reply is synthetic fixture data; keys and emails below are fake. */
export const FAKE_KEY='fixture-key-0123456789abcdef';
export const FAKE_EMAIL='fixture.person@example.invalid';

export const SOURCES=[
 {source:'semantic_scholar',title:'Semantic Scholar',credential_kind:'api_key',required:false,configured:false,state:'ready',detail:'Shared pool: often throttled without a key.',help_url:'https://www.semanticscholar.org/product/api',capabilities:['search','paper','citations']},
 {source:'openalex',title:'OpenAlex',credential_kind:'api_key',required:false,configured:false,state:'unchecked',detail:'',help_url:'https://openalex.org/settings/api',capabilities:['search','paper','citations','retraction']},
 {source:'arxiv',title:'arXiv',credential_kind:null,required:false,configured:false,state:'ready',detail:'',help_url:'https://info.arxiv.org/help/api/index.html',capabilities:['search','paper','bibtex']},
 {source:'crossref',title:'Crossref',credential_kind:'email',required:false,configured:false,state:'ready',detail:'Literal <img src=x onerror="window.pwned=1"> detail',help_url:'javascript:window.pwned=1',capabilities:['paper','bibtex','retraction']},
 {source:'unpaywall',title:'Unpaywall',credential_kind:'email',required:true,configured:false,state:'needs_key',detail:'',help_url:'http://unpaywall.org/products/api',capabilities:['fulltext']}
];

export const ROUTING={v:1,orchestrator:{provider:'claude',model:null},roles:{researcher:{provider:'codex',model:null},implementer:{provider:'claude',model:null},reviewer:{provider:'codex',model:null},tester:{provider:'claude',model:null},writer:{provider:'claude',model:null},citation_checker:{provider:'codex',model:null}}};

const scopeBase={v:1,version:1,commands:{workspace:'allow',allow:[],deny:[]},network:{default:'deny',allow_hosts:[],deny_hosts:[]},apps:[],web_search:'deny',limits:{token_budget:250000,time_limit_s:3600}};
export const PROJECT_SCOPE={...scopeBase,task_id:null,projects:[{project_id:'p1',access:'write',read:['**'],write:['**'],deny:[]}]};
export const RESEARCH_SCOPE={...scopeBase,task_id:null,projects:[],network:{default:'deny',allow_hosts:[],deny_hosts:[]},research:{sources:{semantic_scholar:'allow',openalex:'allow',arxiv:'allow',crossref:'allow',unpaywall:'ask'}}};

let seq=0;
export const ev=(task_id,kind,data,item_id=null)=>({v:1,task_id,seq:++seq,at:'2026-11-19T10:00:00.000Z',kind,turn_id:'t-1',item_id,data});
export const resetSeq=()=>{seq=0;};

// Installs the fake bridge. opts: {projects, rows, researchRows, history:{task:[events]}, scopes:{task:scope}}.
export async function install(page,url,opts={}){
 await page.goto(url);
 await page.evaluate(o=>{
  const projects=o.projects??[{id:'p1',name:'Fixture project',brief:'',priority:'normal',next_action:''}];
  const rows=o.rows??[],research=o.researchRows??[];
  const sources=JSON.parse(JSON.stringify(o.sources));const list={providers:[
   {name:'claude',title:'Claude',models:[],default_model:null,capabilities:{write:true,web_search:true,approvals:true}},
   {name:'codex',title:'Codex',models:[],default_model:null,capabilities:{write:true,web_search:true,approvals:true}}],
   status:[{provider:'claude',state:'signed_in',account:'Fixture',detail:''},{provider:'codex',state:'signed_in',account:'Fixture',detail:''}],routing:o.routing};
  let projectId=projects[0]?.id||null;
  const state=()=>({provider_limits:f.limits||{},display:f.display,version:4,projects,project_id:projectId,project:projects.find(p=>p.id===projectId)?.name||null,task_id:null,task:null,tasks:rows.filter(r=>r.project_id===projectId),research:{tasks:research},active:null,error:'',scheduler:{max_running:4,running:[],queued:[]}});
  const f=window.rFixture={display:o.display||undefined,requests:[],hold:{},held:[],failNext:{},history:o.history||{},scopes:o.scopes||{},outputs:o.outputs||{},saved:o.saved??true,rows,research,sources,
   respond(r,result){window.interspaceReceive({id:r.id,result});},fail(r,error){window.interspaceReceive({id:r.id,error});},
   push(events){for(const event of events)window.interspaceReceive({type:'event',event});},
   setState(){window.interspaceReceive({type:'state',state:state()});}};
  const row=name=>sources.find(s=>s.source===name);
  window.webkit={messageHandlers:{interspace:{postMessage(r){
   f.requests.push(JSON.parse(JSON.stringify(r)));const p=r.params||{};
   if(f.hold[r.method]){f.held.push(r);return;}
   if(f.failNext[r.method]){const e=f.failNext[r.method];delete f.failNext[r.method];queueMicrotask(()=>f.fail(r,e));return;}
   let result={};
   if(r.method==='state')result=state();
   else if(r.method==='switch_project'){projectId=p.project_id;result=state();}
   else if(r.method==='providers_list')result=JSON.parse(JSON.stringify(list));
   else if(r.method==='routing_update'){list.routing=p.routing;result=p.routing;}
   else if(r.method==='research_sources')result={sources:JSON.parse(JSON.stringify(sources))};
   else if(r.method==='research_credential_set'){const s=row(p.source);s.configured=true;s.state='ready';s.detail='';result={...s};}
   else if(r.method==='research_credential_delete'){const s=row(p.source);s.configured=false;s.state=s.required?'needs_key':'ready';result={...s};}
   else if(r.method==='research_test'){const s=row(p.source);result={source:s.source,configured:s.configured,required:s.required,state:p.source==='openalex'?'error':'ready',detail:p.source==='openalex'?'Test call failed: <b>rate limited</b>':''};}
   else if(r.method==='scope_default')result={scope:JSON.parse(JSON.stringify(p.kind==='research'?o.researchScope:o.projectScope))};
   else if(r.method==='agent_create'){const id='N'+(rows.length+research.length);const r2={id,mode:'agent',title:p.title,status:'idle',provider:p.provider||'claude',model:null,project_id:p.project_id,kind:p.kind||'project'};(p.kind==='research'?research:rows).push(r2);f.scopes[id]={...p.scope,task_id:id};result={task_id:id};queueMicrotask(()=>f.setState());}
   else if(r.method==='task_events'){const events=(f.history[p.task_id]||[]).filter(e=>e.seq>p.after_seq);result={events,last_seq:events.length?events[events.length-1].seq:p.after_seq,complete:true};}
   else if(r.method==='scope_get')result={scope:f.scopes[p.task_id]||{...o.projectScope,task_id:p.task_id},scope_digest:'sha256:aa',scope_approval:null};
   else if(r.method==='scope_update'){f.scopes[p.task_id]={...p.scope,version:p.base_version+1};result={scope:f.scopes[p.task_id],scope_digest:'sha256:s2'};}
   else if(r.method==='scope_approve')result={scope_approval:{v:1,scope_version:p.scope_version,scope_digest:p.scope_digest,approved_at:'2026-11-19T10:00:00.000Z',by:'user'}};
   else if(r.method==='task_blob')result={blob_id:p.blob_id,text:f.blobs?.[p.blob_id]??''};
   else if(r.method==='task_outputs')result={outputs:(f.outputs[p.task_id]||[]).map(x=>({...x}))};
   else if(r.method==='task_output_read'){const o=(f.outputs[p.task_id]||[]).find(x=>x.name===p.name);const x=(f.readable?.[p.task_id]||{})[p.name];if(!o||x==null){queueMicrotask(()=>f.fail(r,'Unknown output.'));return;}result={name:o.name,kind:o.kind,text:x,truncated:false};}
   else if(r.method==='task_output_save')result={saved:f.saved};
   else if(r.method==='claims_start'){const c=(o.claims||{})[p.task_id];if(!c){queueMicrotask(()=>f.fail(r,'The report has no numbered citations to check.'));return;}f.claimsNow=JSON.parse(JSON.stringify(c.start));result=JSON.parse(JSON.stringify(c.start));}
   else if(r.method==='task_claims')result=JSON.parse(JSON.stringify(f.claimsNow||{claims:[],counts:{claims:0,pending:0},started_at:null}));
   else if(r.method==='agent_message')result={accepted:true};
   else if(r.method==='task_archive'){const t=[...rows,...research].find(x=>x.id===p.task_id);t.archived=p.archived;result={archived:p.archived};queueMicrotask(()=>f.setState());}
   else if(r.method==='task_delete_check')result=JSON.parse(JSON.stringify((o.deleteChecks||{})[p.task_id]||{working:false,subagents:0,kind:'research',branches:[]}));
   else if(r.method==='task_delete'){for(const list of [rows,research]){const i=list.findIndex(x=>x.id===p.task_id);if(i>=0)list.splice(i,1);}const c=(o.deleteChecks||{})[p.task_id];const names=(c?.branches||[]).filter(b=>b.exists&&!b.checked_out).map(b=>b.name);result={deleted:[p.task_id],deleted_branches:p.branches==='delete'?names:[],kept_branches:p.branches==='delete'?[]:names.map(n=>({name:n,reason:'You chose to keep it.'}))};queueMicrotask(()=>f.setState());}
   else if(r.method==='display_update'){f.display={v:1,thinking:'summary',searches:'summary',tools:true,citations:true,plans:true,notes:true,...p.display};result=f.display;}
   else if(r.method==='task_corpus'){const c=(o.corpora||{})[p.task_id];if(!c){queueMicrotask(()=>f.fail(r,'Only research tasks have a corpus.'));return;}result=JSON.parse(JSON.stringify(c));}
   else if(r.method==='agent_answer'||r.method==='team_answer')result={accepted:true};
   queueMicrotask(()=>f.respond(r,result));
  }}}};
  f.setState();
 },{routing:JSON.parse(JSON.stringify(ROUTING)),projectScope:PROJECT_SCOPE,researchScope:RESEARCH_SCOPE,sources:SOURCES,...opts});
}
export const requests=(page,method)=>page.evaluate(m=>window.rFixture.requests.filter(r=>r.method===m).map(r=>r.params),method);
export const push=(page,events)=>page.evaluate(list=>window.rFixture.push(list),events);
export const assert=(v,m)=>{if(!v)throw Error(m);};
export const text=async loc=>(await loc.textContent())||'';
// Light/dark at 320–1280: no horizontal page scroll. `show` re-opens the surface after each resize.
export async function fit(page,label,show,shots){
 const out=[];
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});for(const width of [320,390,760,1024,1280]){
  await page.setViewportSize({width,height:900});await page.waitForFunction(()=>innerWidth>=1100||!document.querySelector('#agent-view.split'));if(show)await show();
  const f=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  assert(f.scroll<=f.width,'Overflow '+label+' '+width+' '+colorScheme+': '+f.scroll);out.push(f);
  if(shots&&(width===390||width===1280))await page.screenshot({path:'workspace-data/'+label+'-'+colorScheme+'-'+width+'.png',fullPage:true});
 }}
 await page.emulateMedia({colorScheme:'light'});await page.setViewportSize({width:1280,height:1000});
 return out;
}
