/* Simple as a chat for research tasks (docs/superpowers/specs/2026-11-27-simple-chat-view-design.md), from fixture
   events only: each turn reads as your message, one work line for the agent's work, then the reply. What needs the
   user never folds, the Running view's compact copy and a subagent's nested activity keep today's Simple, and
   Detailed shows every step. */
import {install,requests,push,assert,text,fit,evFor} from './research-fixture.mjs';

// A paragraph of exactly n characters that starts with `seed`.
const para=(n,seed)=>{let s=seed;while(s.length<n)s+=' lorem ipsum dolor sit amet';s=s.slice(0,n);return s.endsWith(' ')?s.slice(0,-1)+'x':s;};
const call=(E,id,tool,input,turn='u1')=>E('tool_call',{call_id:id,category:'research',tool,title:tool,input:{tool,...input},decision:{decision:'allow',rule:'research.allow',scope_version:1}},id,turn);
const ok=(E,id,data,turn='u1')=>E('tool_result',{call_id:id,status:'ok',duration_ms:5,output:{text:JSON.stringify(data),truncated:false,blob_id:null},error:null},id,turn);
const user=(E,id,t,turn='u1')=>E('message',{role:'user',text:t},id,turn);
const reply=(E,id,t,turn='u1')=>E('message',{role:'assistant',text:t,final:true},id,turn);
const status=(E,state)=>E('status',{state,detail:'',queue_position:null,reason:null});
const ref=(status,extra={})=>({input:{title:'Paper '+status},status,fields:[],match:null,similarity:null,source:null,...extra});
const report=(...refs)=>({v:1,checked_at:'2026-11-27T10:00:00Z',summary:{},references:refs.map((r,index)=>({index,...r}))});
const member=(id,role,provider)=>({member_id:id,role,brief:'Do the '+role+' part.',provider,model:null,access:'read',default:true});
const team=(E,id,members,turn)=>[E('team_proposed',{team_id:id,summary:'A small team.',budget:{used:10,budget:250000},members},null,turn),E('team_answered',{team_id:id,decision:'approve',members:[],note:null},null,turn)];
const started=(E,id,role,provider,state,turn='u1')=>E('subagent_started',{task_id:id,role,provider,model:null,access:'read',brief:'Do the '+role+' part.',state},null,turn);
const sub=(E,id,role,provider,turn)=>[started(E,id,role,provider,'running',turn),E('subagent_finished',{task_id:id,state:'completed'},null,turn)];

export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const R_TITLE='DRL for RAN slice resource allocation',C_TITLE='Citation checker: check every reference',L_TITLE='Live search',X_TITLE='Restarted reply';
 const rEv=evFor('R'),cEv=evFor('C'),lEv=evFor('L'),xEv=evFor('X');
 const MSG_B=para(200,'Reply b opens')+'\n\n'+['First','Second','Third'].map(w=>'- '+para(78,w+' item')).join('\n')+'\n\n'+para(100,'See the [paper](https://example.org/p) for the method')+'\n\n'+para(200,'Last paragraph');
 const R_EVENTS=[
  rEv('scope',{scope_version:1,scope_digest:'sha256:aa',change:'approved',summary:'Scope approved.'}),
  user(rEv,'user_u1',para(200,'First ask')+'\n\n'+para(500,'Second paragraph of the ask')),
  rEv('reasoning',{text:'Plan the searches.'},'rs_1'),
  call(rEv,'s1','research_search',{query:'DRL RAN slicing'}),ok(rEv,'s1',{searched:['semantic_scholar','openalex'],papers:[{doi:'10.1/a',title:'A'},{doi:'10.1/b',title:'B'}]}),
  call(rEv,'s2','research_search',{query:'O-RAN xApp slicing'}),ok(rEv,'s2',{searched:['arxiv','openalex'],papers:[{doi:'10.1/B',title:'B again'},{arxiv_id:'2401.1',title:'C'}]}),
  call(rEv,'p1','research_paper',{id:'doi:10.1/a'}),ok(rEv,'p1',{paper:{title:'A'}}),
  reply(rEv,'msg_a','I\'ll start by searching three sources.'),
  call(rEv,'sv','save_report',{}),ok(rEv,'sv',{saved:'report.md',characters:1200}),
  rEv('budget',{charge_kind:'reported',tokens:500,used:500,budget:null}),
  reply(rEv,'msg_b',MSG_B),
  user(rEv,'user_u2','Check the claims in the saved report.','u2'),
  ...team(rEv,'tm1',[member('m1','citation_checker','codex')],'u2'),
  ...sub(rEv,'C','citation_checker','codex','u2'),
  rEv('citation_report',report(ref('verified'),ref('verified'),ref('verified')),'cite_1','u2'),
  reply(rEv,'msg_c',para(1500,'One long paragraph'),'u2'),
  user(rEv,'user_u3','Fill the evidence table.','u3'),
  ...team(rEv,'tm2',[member('m2','extractor','claude'),member('m3','extractor','codex'),member('m4','reviewer','codex')],'u3'),
  ...sub(rEv,'E','extractor','claude','u3'),...sub(rEv,'F','extractor','codex','u3'),...sub(rEv,'G','reviewer','codex','u3'),
  call(rEv,'t1','record_table_cells',{},'u3'),ok(rEv,'t1',{recorded:12},'u3'),
  rEv('citation_report',report(ref('verified'),ref('verified'),ref('mismatch',{fields:['year']})),'cite_2','u3'),
  reply(rEv,'msg_d',para(900,'Newest reply'),'u3'),
  status(rEv,'idle')];
 assert(R_EVENTS.find(e=>e.kind==='budget').seq===13,'Fixture budget seq moved');
 // Every item of R in event order, as Detailed shows it: the scope and budget rows are seq:1 and seq:13.
 const DETAILED_R=['seq:1','user_u1','rs_1','s1','s2','p1','msg_a','sv','seq:13','msg_b','user_u2','team:tm1','sub:C','cite_1','msg_c','user_u3','team:tm2','sub:E','sub:F','sub:G','t1','cite_2','msg_d'];
 const SIMPLE_R=['user_u1','work:user_u1','msg_b','user_u2','work:user_u2','msg_c','user_u3','work:user_u3','cite_2','msg_d'];
 await install(page,url,{rows:[],researchRows:[
  {id:'R',mode:'agent',kind:'research',project_id:null,title:R_TITLE,status:'idle',provider:'claude',model:null},
  {id:'C',mode:'agent',kind:'research',project_id:null,parent_task_id:'R',role:'citation_checker',provider:'codex',model:null,title:C_TITLE,status:'completed'},
  {id:'L',mode:'agent',kind:'research',project_id:null,title:L_TITLE,status:'running',provider:'claude',model:null},
  {id:'X',mode:'agent',kind:'research',project_id:null,title:X_TITLE,status:'idle',provider:'claude',model:null}],
  history:{
   R:R_EVENTS,
   C:[user(cEv,'user_u1','Check every reference.'),call(cEv,'v1','verify_citations',{}),ok(cEv,'v1',{references:[{},{},{}]}),
    cEv('citation_report',report(ref('verified'),ref('verified'),ref('not_found')),'cite_c'),reply(cEv,'cm','Checked.')],
   L:[user(lEv,'user_u1','Find sources.'),status(lEv,'running'),call(lEv,'l1','research_search',{query:'O-RAN xApp slicing'})],
   X:[user(xEv,'user_u1','First question','u1'),reply(xEv,'msg_1',para(600,'First answer'),'u1'),
    user(xEv,'user_u4','Fourth question','u4'),reply(xEv,'msg_1','Fourth answer','u4')]}});
 const nav=page.locator('[data-view=research]'),stream=page.locator('#agent-stream');
 const keys=()=>page.evaluate(()=>[...document.querySelectorAll('#agent-stream>[data-item]')].map(n=>n.dataset.item));
 const heading=()=>text(page.locator('#heading'));
 const shows=t=>page.waitForFunction(t=>document.querySelector('#heading').textContent===t,t);
 const openTask=async(id,title)=>{await nav.click();await page.locator('[data-open-task='+id+']').click();await shows(title);};
 const line=k=>stream.locator('[data-item="work:'+k+'"]');
 const active=()=>page.evaluate(()=>document.activeElement?.id||document.activeElement?.tagName);
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

 // T0: each turn is your message, one work line, then the reply; what has a problem stays outside.
 await openTask('R',R_TITLE);
 await page.waitForFunction(()=>document.querySelector('#agent-stream>[data-item=msg_d]'));
 assert(same(await keys(),SIMPLE_R),'Simple turns: '+JSON.stringify(await keys()));
 for(const [k,want] of [['user_u1','Searched 3 sources 2 times · 3 papers · looked up 1 · saved report.md · 8 steps'],
  ['user_u2','Team approved · Codex citation checker finished · 3 references checked: all verified · 3 steps'],
  ['user_u3','Team approved · Claude extractor, Codex extractor, Codex reviewer finished · recorded 12 evidence values · 5 steps']]){
  const t=await text(line(k));assert(t.startsWith(want),'Work line '+k+': '+t);
 }
 assert(await page.evaluate(()=>window.interspaceStream.folded('R'))===16,'Folded steps: '+await page.evaluate(()=>window.interspaceStream.folded('R')));
 const shape=await line('user_u1').evaluate(n=>({tag:n.tagName,card:n.classList.contains('card'),role:n.getAttribute('role'),label:n.getAttribute('aria-label'),buttons:[...n.querySelectorAll('button')].every(b=>b.type==='button')}));
 assert(shape.tag==='DIV'&&shape.card&&shape.role==='group'&&shape.label==='Agent work'&&shape.buttons,'Work line markup: '+JSON.stringify(shape));
 const opens=await line('user_u3').locator('.work-open').evaluateAll(b=>b.map(x=>({text:x.textContent,id:x.id,child:x.dataset.child,type:x.type})));
 assert(same(opens,[{text:'Open Claude extractor',id:'work-open-E',child:'E',type:'button'},{text:'Open Codex extractor',id:'work-open-F',child:'F',type:'button'}]),'Open buttons: '+JSON.stringify(opens));
 const details=page.locator('#work-R-user_u1');
 assert(await details.getAttribute('aria-expanded')==='false'&&await details.getAttribute('aria-label')==='Details of this work, 8 steps'&&(await text(details))==='Details ▸','Details button: '+await details.evaluate(b=>b.outerHTML));
 assert(await details.locator('span[aria-hidden=true]').textContent()==='▸','Arrow not hidden from screen readers');
 assert(await stream.locator('.in-work').count()===0,'Folded items shown while the line is closed');

 // T1: Details by keyboard puts the folded items back in place, in order, each with its own controls; the closing
 // Hide details folds them again and gives focus back to the line.
 await details.focus();await page.keyboard.press('Enter');
 assert(await details.getAttribute('aria-expanded')==='true'&&await active()==='work-R-user_u1','Opened line: focus on '+await active());
 assert(await details.getAttribute('aria-label')==='Hide details of this work, 8 steps'&&(await text(details))==='Hide details ▾','Opened line label: '+await details.getAttribute('aria-label'));
 const FOLDED_U1=['seq:1','rs_1','s1','s2','p1','msg_a','sv','seq:13'];
 {const k=await keys(),at=k.indexOf('work:user_u1');
  assert(same(k.slice(at+1,at+11),[...FOLDED_U1,'work-end:user_u1','msg_b']),'Opened items: '+JSON.stringify(k));
  const inWork=await page.evaluate(()=>[...document.querySelectorAll('#agent-stream>.in-work')].map(n=>n.dataset.item));
  assert(same(inWork,FOLDED_U1),'In-work items: '+JSON.stringify(inWork));}
 assert(await stream.locator('[data-item=s1]').getByRole('button',{name:'Show details'}).count()===1,'An opened search keeps its own Show details');
 const hide=page.locator('#work-end-R-user_u1');
 assert((await text(hide))==='Hide details ▴'&&await hide.getAttribute('type')==='button','Closing button: '+await text(hide));
 await hide.focus();await page.keyboard.press('Enter');
 assert(await details.getAttribute('aria-expanded')==='false'&&await active()==='work-R-user_u1','Hide details: focus on '+await active());
 assert(same(await keys(),SIMPLE_R)&&await stream.locator('.in-work').count()===0,'Hide details left items: '+JSON.stringify(await keys()));

 // Per task: an opened line is kept for the session under its own task, so L's line with the same lead stays closed.
 await details.click();
 assert(await details.getAttribute('aria-expanded')==='true','R line not reopened');
 await openTask('L',L_TITLE);
 await page.waitForFunction(()=>document.querySelector('#agent-stream>[data-item="work:user_u1"]'));
 const lDetails=page.locator('#work-L-user_u1');
 assert(await lDetails.getAttribute('aria-expanded')==='false','L line opened by R');
 assert((await text(line('user_u1').locator('.work-text')))==='Working · Searching “O-RAN xApp slicing” · 1 step','Live line: '+await text(line('user_u1')));

 // T2/T3: what needs the user or went wrong never folds, while the line is closed.
 const outside=async(key,events)=>{
  await push(page,events);
  await page.waitForFunction(k=>document.querySelector('#agent-stream>[data-item="'+k+'"]'),key);
  const inWork=await page.evaluate(k=>document.querySelector('#agent-stream>[data-item="'+k+'"]').classList.contains('in-work'),key);
  assert(!inWork,key+' folded');
 };
 await outside('sub:L1',[started(lEv,'L1','researcher','codex','running')]);
 await outside('team:tm3',[lEv('team_proposed',{team_id:'tm3',summary:'One more researcher.',budget:{used:10,budget:250000},members:[member('m5','researcher','codex')]})]);
 await outside('q1',[lEv('ask',{ask_id:'q1',call_id:'x1',reason:'agent_question',title:'Which years?',detail:'Pick a range.',request:null,options:['text'],request_digest:'sha256:r1'},'q1')]);
 await outside('err1',[lEv('error',{code:'source_down',message:'OpenAlex did not answer.',recoverable:true},'err1')]);
 await outside('f1',[call(lEv,'f1','research_search',{query:'failing'}),lEv('tool_result',{call_id:'f1',status:'error',duration_ms:5,output:{text:'',truncated:false,blob_id:null},error:{code:'unavailable',message:'Search failed.'}},'f1')]);
 await outside('sub:L2',[started(lEv,'L2','researcher','codex','running'),lEv('subagent_status',{task_id:'L2',state:'paused_ask'})]);
 const waiting=status(lEv,'waiting_lock');await outside('seq:'+waiting.seq,[waiting]);
 const queued=status(lEv,'queued');await outside('seq:'+queued.seq,[queued]);
 const edited=lEv('scope',{scope_version:2,scope_digest:'sha256:bb',change:'edited',summary:'Scope edited.'});await outside('seq:'+edited.seq,[edited]);
 assert(await stream.locator('.in-work').count()===0,'Items shown in work while closed');
 await stream.locator('[data-item="team:tm3"]').getByRole('button',{name:'Approve team'}).click();
 await page.waitForFunction(()=>window.rFixture.requests.some(r=>r.method==='team_answer'));
 assert(same((await requests(page,'team_answer')).at(-1),{task_id:'L',team_id:'tm3',decision:'approve'}),'team_answer: '+JSON.stringify((await requests(page,'team_answer')).at(-1)));
 // Once approved, the newest scope row is settled, and both scope rows fold.
 const approved=lEv('scope',{scope_version:2,scope_digest:'sha256:bb',change:'approved',summary:'Scope approved.'});
 await push(page,[approved]);
 await page.waitForFunction(()=>/ 3 steps/.test(document.querySelector('#agent-stream [data-item="work:user_u1"]')?.textContent||''));
 assert(await stream.locator('[data-item="seq:'+edited.seq+'"]').count()===0&&await stream.locator('[data-item="seq:'+approved.seq+'"]').count()===0,'Settled scope rows not folded');

 // Review Focus 1: a search finishes and another starts while the line is open; the line stays open, the new step comes
 // last among the opened items and keyboard focus stays on the line's button.
 await lDetails.click();await lDetails.focus();
 assert(await lDetails.getAttribute('aria-expanded')==='true','L line not opened');
 await push(page,[ok(lEv,'l1',{searched:['arxiv'],papers:[{doi:'10.1/z',title:'Z'}]})]);
 await page.waitForFunction(()=>/Searched 1 source once/.test(document.querySelector('#agent-stream [data-item="work:user_u1"]').textContent));
 await push(page,[call(lEv,'l2','research_search',{query:'second query'})]);
 await page.waitForFunction(()=>document.querySelector('#agent-stream>[data-item=l2]'));
 assert(await lDetails.getAttribute('aria-expanded')==='true','Live events closed the line');
 const order=await page.evaluate(()=>{const all=[...document.querySelectorAll('#agent-stream>[data-item]')],end=all.findIndex(n=>n.dataset.item==='work-end:user_u1');return {before:all[end-1]?.dataset.item,last:[...document.querySelectorAll('#agent-stream>.in-work')].at(-1)?.dataset.item};});
 assert(order.before==='l2'&&order.last==='l2','New step not last before Hide details: '+JSON.stringify(order));
 assert(await active()==='work-L-user_u1','Focus left the line: '+await active());
 assert((await text(line('user_u1'))).startsWith('Working · Searching “second query” · Searched 1 source once · 1 paper'),'Live line after a result: '+await text(line('user_u1')));

 // Open from the line, and Review Focus 3: a script click never focuses the button, yet Back lands on it, with the
 // line where it was.
 await openTask('R',R_TITLE);
 await page.waitForFunction(()=>document.querySelector('#agent-stream [data-item="work:user_u2"]'));
 const lineTop=()=>page.evaluate(()=>{const main=document.querySelector('#agent-view .agent-main'),n=document.querySelector('#agent-stream [data-item="work:user_u2"]');return n.getBoundingClientRect().top-main.getBoundingClientRect().top;});
 await page.evaluate(()=>{const main=document.querySelector('#agent-view .agent-main'),n=document.querySelector('#agent-stream [data-item="work:user_u2"]');main.scrollTop+=n.getBoundingClientRect().top-main.getBoundingClientRect().top-200;});
 const before=await lineTop();
 await page.evaluate(()=>document.getElementById('work-open-C').click());
 await shows(C_TITLE);
 await page.locator('#agent-back').click();
 await shows(R_TITLE);
 assert(await active()==='work-open-C','Back focus: '+await active());
 const after=await lineTop();
 assert(Math.abs(after-before)<=4,'Work line moved from '+before+' to '+after);

 // Untouched copies: the Running view's compact copy and a subagent's nested activity keep today's Simple.
 await page.locator('[data-view=running]').click();
 await page.waitForFunction(()=>document.querySelector('.task-column[data-task="R"] .stream [data-item]'));
 assert(await page.locator('.task-column[data-task="R"] .work-line').count()===0,'Compact copy has a work line');
 await openTask('R',R_TITLE);
 await page.locator('#work-R-user_u2').click();
 await stream.locator('[data-item="sub:C"]').getByRole('button',{name:'Citation checker details'}).click();
 await stream.locator('[data-item="sub:C"]').getByRole('button',{name:'Show Citation checker activity'}).click();
 await page.waitForFunction(()=>document.querySelector('#child-C .card.research'));
 assert(await page.locator('#child-C .work-line').count()===0,'Nested activity has a work line');

 // A colliding reply id keeps its turn-scoped key, and nothing folds.
 await openTask('X',X_TITLE);
 await page.waitForFunction(()=>document.querySelector('#agent-stream>[data-item="msg_1@u4"]'));
 assert(same(await keys(),['user_u1','msg_1','user_u4','msg_1@u4'])&&await stream.locator('.work-line').count()===0,'Collision in Simple: '+JSON.stringify(await keys()));

 // T9 and Review Focus 5: Detailed shows every step with no work line and no stale in-work class; Simple comes back
 // with the opened line still open.
 await openTask('R',R_TITLE);
 await page.waitForFunction(()=>document.querySelector('#work-R-user_u1')?.getAttribute('aria-expanded')==='true');
 await page.evaluate(()=>window.interspaceDisplay.setDetail('detailed'));
 await page.waitForFunction(()=>!document.querySelector('#agent-stream .work-line'));
 assert(await page.locator('#agent-stream .in-work').count()===0,'Stale in-work in Detailed');
 assert(same(await keys(),DETAILED_R),'Detailed items: '+JSON.stringify(await keys()));
 await page.evaluate(()=>window.interspaceDisplay.setDetail('simple'));
 await page.waitForFunction(()=>document.querySelector('#agent-stream .work-line'));
 assert(await details.getAttribute('aria-expanded')==='true','Opened line not kept across Detailed');

 // Layout: a long unbroken query in the live line never overflows.
 await openTask('L',L_TITLE);
 await push(page,[call(lEv,'l9','research_search',{query:'q'.repeat(150)})]);
 await page.waitForFunction(()=>document.querySelector('#agent-stream>[data-item=l9]'));
 const fits=await fit(page,'simple-view-live',async()=>{if(await heading()!==L_TITLE)await openTask('L',L_TITLE);},false,[320,390,600]);

 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'research turns as your message, one work line and the reply; work-line counts (sources, papers, look-ups, report, team, subagents, all-verified citations, values, steps); folded count; at most 2 Open buttons; Details and Hide details by keyboard with focus kept; opened items in order with their own controls; open lines kept per task; asks, errors, failed calls, open teams, running and paused subagents, status rows and an edited scope never fold; Approve team sends team_answer; settled scope rows fold; a live line stays open with the new step last and focus kept; Working with the running search; Open from the line and Back to it with focus and position; compact and nested copies untouched; collision in Simple; Detailed parity without stale in-work and the line kept open across it; long query fits 320/390/600',responsiveStates:fits.length};
}
