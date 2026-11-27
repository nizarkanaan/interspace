/* Agent event stream (docs/superpowers/specs/agentic-spaces/events.md): an ordered per-task store and text-only cards.
   Model and event text is only ever inserted with textContent. */
(()=>{
const TERMINAL=new Set(['completed','failed','cancelled','budget_exhausted','time_limit','interrupted']);
const BUSY=new Set(['queued','starting','running','waiting_lock','paused_ask','paused_scope','paused_team','cancelling']);
const STATUS={queued:'Queued',starting:'Starting',running:'Running',waiting_lock:'Waiting for a lock',paused_ask:'Needs your answer',paused_scope:'Scope needs approval',paused_team:'Team needs your approval',idle:'Waiting for your message',cancelling:'Stopping',completed:'Completed',failed:'Failed',cancelled:'Cancelled',budget_exhausted:'Token budget exhausted',time_limit:'Time limit reached',interrupted:'Interrupted: the app quit mid-task and nothing resumes automatically'};
const NOTABLE=new Set(['queued','waiting_lock','paused_scope','cancelling',...TERMINAL]);
const SUBAGENT=['team_id','member_id','task_id','role','provider','model','access','brief','state','tokens_used','report_excerpt','diff_summary'];
const CATEGORY={command:'Command',file_read:'Read file',file_write:'Write files',network:'Network',web_search:'Web search',mcp:'MCP tool',orchestrate:'Orchestration',research:'Research'};
const RESULT={ok:'Done',error:'Failed',denied:'Denied',cancelled:'Cancelled'};
const REASON={outside_scope:'Outside the task scope',destructive:'Destructive action: always asks',network_host:'Network host not in the scope',escalation:'Asks to run outside the sandbox',mcp_tool:'External MCP tool: always asks',agent_question:'The agent asks you'};
const OPTION={allow_once:'Allow once',add_to_scope:'Add to scope',deny:'Deny'};
const ANSWERED={allow_once:'Allowed once',add_to_scope:'Added to scope',deny:'Denied',text:'Replied',cancelled:'Closed: the task was cancelled'};
const MAX_PAGES=20,COMPACT_ITEMS=5;
const tasks=new Map(),views=new WeakMap(),parents=new Map();
let request=()=>Promise.reject(Error('No bridge')),changed=()=>{},hostChanged=()=>{},open=()=>{},rowStatus=()=>null,stampOf=()=>'',showTab=null,isRoot=()=>false;

const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const tokens=n=>Number(n||0).toLocaleString('en-US');
function model(id){
 if(!tasks.has(id))tasks.set(id,{id,rev:0,lastSeq:0,buffer:new Map(),fetching:false,items:new Map(),status:null,usage:null,outputs:null,budget:null,scopeEvent:null,workspace:null,openAsk:null,paths:new Set(),loadError:'',children:new Map()});
 return tasks.get(id);
}
function item(m,key){let it=m.items.get(key);if(!it){it={key,version:0};m.items.set(key,it);}it.version++;return it;}
function row(m,e,kind,fields){Object.assign(item(m,'seq:'+e.seq),{row:kind},fields);}
// Before 2026-11-27 every Claude session numbered its replies from msg_1, so after a restart a later turn's reply
// reused an earlier turn's id. A message or reasoning id that already belongs to another turn is kept under a
// turn-scoped key (msg_1@u4), in its own place; ids that do not collide keep their key.
function turnKey(m,key,e){const it=m.items.get(key),turn=e.turn_id;return it&&it.turn!=null&&typeof turn==='string'&&turn&&it.turn!==turn?key+'@'+turn:key;}
function turnItem(m,key,e){const k=turnKey(m,key,e),fresh=!m.items.has(k),it=item(m,k);if(fresh)it.turn=e.turn_id??null;return it;}
const valid=e=>e&&typeof e==='object'&&typeof e.task_id==='string'&&e.task_id&&Number.isSafeInteger(e.seq)&&e.seq>0&&typeof e.kind==='string';

// Paths seen in a task become @mention candidates.
function remember(m,data){
 const input=data?.input||{};for(const p of [input.path,...(Array.isArray(input.paths)?input.paths:[])])if(typeof p==='string'&&p)m.paths.add(p);
 for(const f of data?.files||[])if(typeof f?.path==='string')m.paths.add(f.path);
}
function apply(m,e){
 const d=e.data&&typeof e.data==='object'?e.data:{},key=typeof e.item_id==='string'&&e.item_id?e.item_id:'seq:'+e.seq;
 if(e.v!==1){row(m,e,'unsupported',{text:'Unsupported event (format version '+String(e.v)+')'});return;}
 switch(e.kind){
  case 'status':{m.status=d;if(NOTABLE.has(d.state))row(m,e,'status',{text:statusText(d)});
   // An open proposal closes for good when its turn ends (stopped, interrupted, idle): a later turn never reopens it.
   if(TERMINAL.has(d.state)||d.state==='idle')for(const it of m.items.values())if(it.team&&!it.team.answered&&!it.team.closed){it.team.closed=statusText(d).toLowerCase();it.version++;}return;}
  case 'message_delta':{const it=turnItem(m,key,e);it.message={role:d.role||'assistant',text:(it.message&&!it.message.final?it.message.text:'')+(d.text_delta||''),final:false};return;}
  case 'message':{if(d.role==='user'&&d.client_id)m.items.delete('client:'+d.client_id);turnItem(m,key,e).message={role:d.role==='user'?'user':'assistant',text:String(d.text??''),final:true};return;}
  case 'reasoning':turnItem(m,key,e).reasoning=String(d.text??'');return;
  case 'plan_update':item(m,'plan').plan=Array.isArray(d.steps)?d.steps:[];return;
  case 'tool_call':item(m,key).call=d;remember(m,d);return;
  case 'tool_output_delta':{const it=item(m,key);it.output=(it.output||'')+(d.text||'');return;}
  case 'tool_result':item(m,key).result=d;return;
  case 'diff':{remember(m,d);m.workspace=d.workspace||m.workspace;if(d.cumulative){m.items.delete('cumulative');item(m,'cumulative').diff=d;}else item(m,key).diff=d;return;}
  case 'ask':{const it=item(m,key);it.ask=d;it.sending=false;it.answerError='';m.openAsk=key;if(d.request)remember(m,d.request);return;}
  case 'answer':{const it=item(m,key);it.answer=d;it.sending=false;if(m.openAsk===key)m.openAsk=null;return;}
  case 'budget':m.budget=d;if(d.charge_kind!=='reserved')row(m,e,'budget',{text:(d.charge_kind==='estimated'?'Estimated ':'Reported ')+tokens(d.tokens)+' tokens'+(d.charge_kind==='estimated'?' (no counts returned)':'')+' · '+tokens(d.used)+(d.budget==null?' used':' / '+tokens(d.budget)+' used')});return;
  case 'scope':m.scopeEvent=d;row(m,e,'scope',{change:d.change,text:'Scope v'+d.scope_version+' '+({approved:'approved',edited:'edited: approve it before the next action',amended:'amended and approved'}[d.change]||String(d.change))+(d.summary?': '+d.summary:'')});return;
  case 'error':item(m,key).error=d;return;
  // Research (docs/superpowers/specs/research/tasks.md): a citation report card, call counts and the task's outputs.
  case 'citation_report':item(m,key).citation=d;return;
  case 'research_usage':m.usage=d;return;
  case 'outputs':m.outputs=d;return;
  case 'corpus':m.corpus=d;return;
  case 'claims':m.claims=d;return;
  case 'evidence':m.evidence=d;return;
  case 'team_proposed':case 'team_answered':{if(typeof d.team_id!=='string')break;const it=item(m,'team:'+d.team_id);it.team={...(it.team||{}),[e.kind==='team_proposed'?'proposal':'answered']:d};return;}
  case 'subagent_started':case 'subagent_status':case 'subagent_finished':{
   if(typeof d.task_id!=='string'||!d.task_id)break;const k='sub:'+d.task_id,it=item(m,k);it.sub=it.sub||{};
   for(const f of SUBAGENT)if(d[f]!==undefined)it.sub[f]=d[f];if(e.kind==='subagent_finished')it.sub.finished=true;
   m.children.set(d.task_id,k);parents.set(d.task_id,m.id);return;}
  default:row(m,e,'unsupported',{text:'Unsupported event ('+e.kind+')'});return;
 }
 row(m,e,'unsupported',{text:'Unsupported event ('+e.kind+')'});
}
function drain(m){while(m.buffer.has(m.lastSeq+1)){const e=m.buffer.get(m.lastSeq+1);m.buffer.delete(e.seq);apply(m,e);m.lastSeq=e.seq;m.rev++;}}
function accept(m,e){if(valid(e)&&e.task_id===m.id&&e.seq>m.lastSeq&&!m.buffer.has(e.seq))m.buffer.set(e.seq,e);}
// Replays missed events from the last seen seq; a gap the backend cannot fill is noted, then skipped.
// Live events that arrive while a page loads are buffered; if they still leave a hole, it asks once more.
async function sync(m){
 if(m.fetching)return;m.fetching=true;m.loadError='';
 try{for(let page=0;page<MAX_PAGES;page++){const before=m.lastSeq,r=await request('task_events',{task_id:m.id,after_seq:m.lastSeq},{manual:true});for(const e of r?.events||[])accept(m,e);drain(m);if(r?.complete!==false&&!m.buffer.size||m.lastSeq===before)break;}}
 catch(error){m.loadError=error.message||'Earlier events could not be loaded.';}
 finally{m.fetching=false;}
 if(m.buffer.size){const next=Math.min(...m.buffer.keys());row(m,{seq:'gap-'+next},'gap',{text:'Some earlier events could not be loaded.'});m.lastSeq=next-1;drain(m);}
 m.rev++;changed(m.id);
}
function receive(e){
 if(!valid(e))return;const m=model(e.task_id);if(e.seq<=m.lastSeq||m.buffer.has(e.seq))return;
 m.buffer.set(e.seq,e);drain(m);if(m.buffer.size)sync(m);changed(m.id);
}
function statusText(s){
 if(!s)return 'Not started';let text=STATUS[s.state]||'Unknown state ('+s.state+')';
 if(s.state==='queued'&&s.queue_position)text+=' (position '+s.queue_position+')';
 if(s.state==='failed'&&s.reason)text+=': '+s.reason;
 if(s.detail&&['waiting_lock','paused_ask','paused_scope','cancelling'].includes(s.state))text+=' · '+s.detail;
 return text;
}
// The latest thing a task did, as one short line: the newest agent text, tool call, question, change or error.
const oneLine=t=>{const lines=String(t).split('\n').map(x=>x.trim()).filter(Boolean),last=lines.at(-1)||'';return Array.from(last).length>160?Array.from(last).slice(0,159).join('')+'…':last;};
function activity(id){
 const m=tasks.get(id);if(!m)return '';const list=[...m.items.values()];
 for(let i=list.length-1;i>=0;i--){const it=list[i];
  if(it.error)return 'Error: '+oneLine(it.error.message||it.error.code||'');
  if(it.ask)return (it.answer?'Answered: ':'Needs your answer: ')+oneLine(it.ask.title||'');
  if(it.call)return (CATEGORY[it.call.category]||'Tool')+': '+oneLine(it.call.category==='research'&&window.interspaceResearchCards?.toolTitle(it.call.input?.tool)||it.call.title||it.call.tool||'');
  if(it.diff&&(it.diff.files||[]).length)return 'Changed '+(it.diff.files||[]).length+' file'+((it.diff.files||[]).length===1?'':'s');
  if(it.message&&it.message.role==='assistant'&&String(it.message.text).trim())return oneLine(it.message.text);
  if(it.plan){const step=it.plan.find(s=>s.status==='in_progress');if(step)return 'Plan: '+oneLine(step.text??'');}
 }
 return '';
}
// A child's latest citation report (the citation checker runs as a subagent), shown on its card in the parent.
function citationOf(id){const m=tasks.get(id);if(!m)return null;const list=[...m.items.values()];for(let i=list.length-1;i>=0;i--)if(list[i].citation)return list[i];return null;}
// A child's state: its own stream when loaded, else a terminal task row (after a restart the parent never hears
// that a child was interrupted), else the parent's subagent events.
function childStatus(id,fallback){
 const own=tasks.get(id)?.status;if(own)return own;
 const r=rowStatus(id);if(r&&TERMINAL.has(r))return {state:r,detail:'',queue_position:null,reason:null};
 return {state:fallback||'queued',detail:'',queue_position:null,reason:null};
}
function budgetText(b){if(!b)return '';let text='Tokens '+tokens(b.used)+(b.budget==null?' used':' / '+tokens(b.budget));if(b.reserved)text+=' · '+tokens(b.reserved)+' reserved for this turn';if(b.overshoot)text+=' · over budget by '+tokens(b.overshoot);return text;}

// Text-safe Markdown: fenced code, `code` and **bold**; everything else stays literal text.
function inline(text,parent){for(const part of text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/)){if(!part)continue;if(/^`[^`]+`$/.test(part))el('code','',part.slice(1,-1),parent);else if(/^\*\*[^*]+\*\*$/.test(part))el('strong','',part.slice(2,-2),parent);else parent.append(document.createTextNode(part));}}
function markdown(text,parent){
 const box=el('div','md',null,parent);let code=null,para=[];
 const flush=()=>{if(para.length){inline(para.join('\n'),el('p','',null,box));para=[];}};
 for(const line of String(text).split('\n')){
  if(/^```/.test(line)){if(code){code=null;}else{flush();code=el('code','',null,el('pre','code-block',null,box));}continue;}
  if(code){code.textContent+=(code.textContent?'\n':'')+line;continue;}
  if(!line.trim()){flush();continue;}para.push(line);
 }
 flush();return box;
}
function pairs(object,parent){const dl=el('dl','pairs',null,parent);for(const [k,v] of Object.entries(object||{})){if(v==null||v==='')continue;el('dt','',k.replaceAll('_',' '),dl);el('dd','',typeof v==='string'?v:Array.isArray(v)&&v.every(x=>typeof x==='string')?v.join(' '):JSON.stringify(v),dl);}return dl;}
function blobButton(m,it,label,blob,field,parent){
 if(!blob||it[field]!=null)return;
 const b=el('button','link-button',label,parent);b.type='button';
 b.onclick=()=>{b.disabled=true;request('task_blob',{task_id:m.id,blob_id:blob},{manual:true}).then(r=>{it[field]=String(r?.text??'');}).catch(error=>{it.blobError=error.message;}).finally(()=>{it.version++;changed(m.id);});};
}
function diffBlock(m,it,d,parent){
 const box=el('div','diff',null,parent);
 if(d.cumulative){el('h3','','Task change',box);if(d.workspace)el('p','footnote','Branch '+d.workspace.branch+' against '+d.workspace.base_commit,box);}
 const files=el('ul','diff-files',null,box);
 for(const f of d.files||[]){const li=el('li','',null,files);el('span','mono',(f.old_path?f.old_path+' → ':'')+f.path,li);el('span','diff-count',f.binary?'binary':'+'+(f.additions||0)+' −'+(f.deletions||0),li);el('span','footnote',f.change,li);}
 const patch=it.fullDiff??d.patch;
 if(patch){const pre=el('pre','diff-patch',null,box);pre.tabIndex=0;pre.setAttribute('aria-label','Patch');for(const line of patch.replace(/\n$/,'').split('\n')){const cls=/^(\+\+\+|---|diff |index )/.test(line)?'meta':line[0]==='+'?'add':line[0]==='-'?'del':line.startsWith('@@')?'hunk':'ctx';el('span','diff-line '+cls,line+'\n',pre);}}
 if(d.truncated)blobButton(m,it,'Show full diff',d.blob_id,'fullDiff',box);
}
function askCard(m,it,card,compact){
 const a=it.ask;card.classList.add('ask');card.setAttribute('role','group');card.setAttribute('aria-label',a.title||'Question');
 el('p','badge',REASON[a.reason]||a.reason,card);el('h3','',a.title,card);if(a.detail)el('p','',a.detail,card);
 if(a.request)pairs(a.request,card);
 const options=Array.isArray(a.options)?a.options:[];
 if(options.includes('add_to_scope')&&a.scope_patch)el('p','footnote','Add to scope changes the scope: '+patchText(a.scope_patch),card);
 if(it.answer){el('p','answered',(ANSWERED[it.answer.decision]||it.answer.decision)+(it.answer.decision==='add_to_scope'?' (scope v'+it.answer.scope_version+')':''),card);return;}
 if(it.answerError)el('p','error-text',it.answerError,card).setAttribute('role','alert');
 const actions=el('div','actions',null,card),busy=!!it.sending||!!it.sent;
 let reply=null;
 if(options.includes('text')){const id='reply-'+m.id+'-'+it.key+(compact?'-compact':'');const label=el('label','footnote','Your reply',actions);label.htmlFor=id;reply=el('textarea','ask-reply',null,actions);reply.id=id;reply.disabled=busy;const b=el('button','primary','Reply',actions);b.type='button';b.disabled=busy;b.onclick=()=>{if(reply.value.trim())answer(m.id,it.key,'text',reply.value);};}
 for(const option of ['allow_once','add_to_scope','deny']){
  if(!options.includes(option)||option==='add_to_scope'&&!(a.scope_patch&&a.patched_scope_digest))continue;
  const b=el('button',option==='allow_once'?'primary':'',OPTION[option],actions);b.type='button';b.disabled=busy;b.onclick=()=>answer(m.id,it.key,option);
 }
 if(it.sent)el('p','footnote','Answer sent. Waiting for the task.',card);
}
function patchText(patch){const out=[];const walk=(v,path)=>{if(Array.isArray(v)){v.forEach(x=>typeof x==='object'&&x?walk(x,path):out.push(path+': '+x));}else if(v&&typeof v==='object'){for(const [k,x] of Object.entries(v))walk(x,path?path+'.'+k:k);}else out.push(path+': '+v);};walk(patch,'');return out.join('; ');}
function toolCard(m,it,card){
 const c=it.call||{},r=it.result;
 if(c.category==='research'&&display().searches==='summary'&&!it.showFull&&!(r&&r.status&&r.status!=='ok')){
  window.interspaceResearchCards.toolSummary(card,{call:c,result:r,output:it.fullOutput??(r?.output?.text||'')});
  const b=el('button','link-button','Show details',card);b.type='button';b.setAttribute('aria-expanded','false');b.onclick=()=>{it.showFull=true;it.version++;changed(m.id);};return;}
 if(c.category==='research'){window.interspaceResearchCards.toolCard(card,{call:c,result:r,output:it.fullOutput??(r?.output?.text||''),state:it,bump:()=>{it.version++;changed(m.id);}});if(r?.output?.truncated)blobButton(m,it,'Show full result',r.output.blob_id,'fullOutput',card);if(it.showFull&&display().searches==='summary'){const b=el('button','link-button','Show less',card);b.type='button';b.setAttribute('aria-expanded','true');b.onclick=()=>{it.showFull=false;it.version++;changed(m.id);};}return;}
 card.classList.add('tool');
 const head=el('div','card-head',null,card);el('span','badge',CATEGORY[c.category]||c.category||'Tool',head);el('strong','mono',c.title||c.tool||'Tool call',head);
 el('span','state '+(r?r.status:'running'),r?(RESULT[r.status]||r.status)+(r.exit_code!=null?' · exit '+r.exit_code:'')+(r.duration_ms!=null?' · '+r.duration_ms+' ms':''):it.call?'Running':'Output',head);
 const input=c.input||{};
 if(Array.isArray(input.argv))el('p','mono command',input.argv.join(' ')+(input.cwd&&input.cwd!=='.'?'   (in '+input.cwd+')':''),card);
 else if(Object.keys(input).length)pairs(input,card);
 if(c.decision)el('p','footnote',(c.decision.decision==='deny'?'Denied by ':'Allowed by ')+c.decision.rule+(c.decision.scope_version!=null?' (scope v'+c.decision.scope_version+')':''),card);
 const output=it.fullOutput??(r?.output?.text||it.output||'');
 if(output){const pre=el('pre','tool-output',output,card);pre.tabIndex=0;pre.setAttribute('aria-label','Output');}
 if(r?.output?.truncated)blobButton(m,it,'Show full output',r.output.blob_id,'fullOutput',card);
 if(r?.error)el('p','error-text',(r.error.code?r.error.code+': ':'')+r.error.message,card);
 if(it.diff)diffBlock(m,it,it.diff,card);
}
// Conversation display (2026-11-20-details-panel-and-display-design.md). Your messages, replies, questions, team
// cards, subagents, errors and failed calls always show; the rest follows Settings → Conversation display.
const NOTE_ROWS=new Set(['budget','scope','status']);
const display=()=>window.interspaceDisplay?.get?.()||{thinking:'summary',searches:'summary',tools:true,citations:true,plans:true,notes:true,detail:'simple'};
function visible(it,d){
 if(it.message||it.team||it.sub||it.ask||it.error||it.blobError)return true;
 if(it.row)return d.notes||!NOTE_ROWS.has(it.row);
 if(it.citation)return !!d.citations;
 if(it.call||it.result||it.output!=null){
  if(it.result&&it.result.status&&it.result.status!=='ok')return true;
  // Simple (2026-11-27-readable-workspace-design.md) hides orchestration calls whatever the commands switch says;
  // a failed one still shows (above), a waiting one does not.
  if(it.call?.category==='orchestrate'&&d.detail!=='detailed')return false;
  return it.call?.category==='research'?d.searches!=='hidden':!!d.tools;
 }
 if(it.diff)return !!d.tools;
 if(it.reasoning!=null)return d.thinking!=='hidden';
 if(it.plan)return !!d.plans;
 return true;
}
const SUMMARY_CHARS=280;
function reasoningCard(it,card,d){
 const text=String(it.reasoning);card.classList.add('reasoning-card');
 if(d.thinking==='full'){el('p','footnote reasoning-label','Reasoning',card);markdown(text,card);return;}
 const first=text.split(/\n\s*\n/)[0].trim(),short=first.length>SUMMARY_CHARS?first.slice(0,SUMMARY_CHARS).replace(/\s+\S*$/,'')+'…':first;
 const p=el('p','reasoning-summary',null,card);el('span','footnote reasoning-label','Reasoning ',p);p.append(short);
 if(short!==text.trim()){const d2=el('details','reasoning',null,card);el('summary','','Show all',d2);markdown(text,d2);}
}
// Simple as a chat (2026-11-27-simple-chat-view-design.md): in a research task's main conversation each turn reads as
// your message, one work line for the agent's work, then the reply. Code tasks, the Running view's compact copy and a
// subagent's nested activity keep the Simple above.
const LIVE=new Set(['queued','starting','running','waiting_lock','cancelling']);
const safe=s=>String(s).replace(/[^A-Za-z0-9_-]/g,'_');
const simpleOn=(m,options={})=>!options.compact&&!options.nested&&display().detail!=='detailed'&&!!window.interspaceAgent?.isResearch?.(m.id);
// What folds into the work line; everything else stays in full, so nothing that needs the user, or went wrong, folds.
// `interim` holds the turn's final assistant messages that a later assistant message follows; `newestScope` is the
// last scope row, which stays while its change is still `edited`.
function stays(m,it,{interim,newestScope}={}){
 if(it.ask||it.error||it.blobError)return true;
 if(it.message)return !(it.message.role==='assistant'&&it.message.final&&!!interim?.has(it));
 if(it.call||it.result||it.output!=null)return !(it.call?.category==='research'&&(!it.result||it.result.status==='ok'));
 if(it.reasoning!=null)return false;
 if(it.row==='budget')return false;
 if(it.row==='scope')return it===newestScope&&it.change==='edited';
 if(it.team)return !it.team.answered;
 if(it.sub){const s=childStatus(it.sub.task_id,it.sub.state).state;return !(s==='completed'||s==='idle'&&it.sub.finished);}
 if(it.citation){const c=window.interspaceResearchCards?.citationCounts?.(it.citation);return !c||c.problems!==0;}
 return true;
}
// Turns split at your messages (pending ones too); items before the first one join turn 1, whose lead key is `start`
// when it has no message. Per turn: the lead, the work line when anything folded (then, opened, the folded items and
// the closing Hide details), then the turn's other items in their original order, the reply included.
function digest(m,list){
 const R=window.interspaceResearchCards,turns=[];let newestScope=null;
 for(const it of list){
  if(it.row==='scope')newestScope=it;
  if(!turns.length)turns.push({lead:null,items:[]});
  const turn=turns.at(-1),user=it.message?.role==='user';
  if(user&&!turn.lead)turn.lead=it;else if(user)turns.push({lead:it,items:[]});else turn.items.push(it);
 }
 const entries=[];let folded=0;
 // A message of yours still sending or not sent (`client:`, pending or failed) starts no newer turn for the previews:
 // the reply just read stays whole until the server takes the next message.
 let newest=turns.length-1;while(newest>0&&turns[newest].lead?.message?.pending)newest--;
 turns.forEach((turn,i)=>{
  const lead=turn.lead?turn.lead.key:'start',interim=new Set();let later=false;
  for(let j=turn.items.length-1;j>=0;j--){const msg=turn.items[j].message;if(msg?.role!=='assistant')continue;if(later&&msg.final)interim.add(turn.items[j]);later=true;}
  const work=[],kept=[];for(const it of turn.items)(stays(m,it,{interim,newestScope})?kept:work).push(it);
  // An earlier turn's long message and reply show their first lines (preview); the newest turn is always whole.
  let reply=null;for(const it of turn.items)if(it.message?.role==='assistant')reply=it;
  const earlier=i<newest,long=msg=>earlier&&msg.final&&!msg.pending&&!msg.failed&&String(msg.text).length>LONG;
  if(turn.lead)entries.push({key:turn.lead.key,it:turn.lead,preview:long(turn.lead.message)?'message':null});
  if(work.length){
   folded+=work.length;
   const open=openWork.has(m.id+'|'+lead),live=i===turns.length-1&&LIVE.has(m.status?.state);
   let text=R.workParts(work).join(' · ');
   if(live){let run=null;for(const it of work)if(it.call?.category==='research'&&!it.result)run=it;text='Working'+(run?' · '+R.summaryText({call:run.call,result:null,output:''}):'')+' · '+text;}
   const children=[];for(const it of work)if(it.sub&&children.length<2)children.push({id:it.sub.task_id,name:R.workerName(it.sub)});
   entries.push({key:'work:'+lead,work:true,lead,items:work,open,live,text,children});
   if(open){for(const it of work)entries.push({key:it.key,it,inWork:true});entries.push({key:'work-end:'+lead,end:true,lead});}
  }
  for(const it of kept)entries.push({key:it.key,it,preview:it===reply&&long(it.message)?'reply':null,pointer:!!it.citation});
 });
 return {entries,folded};
}
// The digest's part of a cached node's version.
const entryVersion=(m,entry)=>entry.work?entry.text+'|'+entry.open+'|'+entry.children.map(c=>c.id+'='+c.name).join(','):entry.preview?entry.preview+'|'+openMsgs.has(m.id+'|'+entry.key):entry.pointer?'pointer|'+corpusButton(m):'';
// Opened work lines and whole messages stay open for the session, per task.
const openWork=new Set(),openMsgs=new Set();
const workId=(m,entry)=>safe(String(m.id).slice(0,8))+'-'+safe(entry.lead);
// "Searched 3 sources 2 times · 3 papers · 8 steps", up to 2 Open buttons for finished subagents, then Details ▸ or
// Hide details ▾. The toggle keeps its id, so focus comes back to it after the render (render() restores it by id).
function workLine(m,entry){
 const line=el('div','card work-line');line.dataset.item=entry.key;line.setAttribute('role','group');line.setAttribute('aria-label','Agent work');
 el('span','work-text',entry.text,line);
 for(const c of entry.children){const b=el('button','work-open','Open '+c.name,line);b.type='button';b.id='work-open-'+safe(c.id);b.dataset.child=c.id;b.onclick=()=>open(c.id);}
 const steps=entry.items.length,b=el('button','work-details',entry.open?'Hide details ':'Details ',line);b.type='button';b.id='work-'+workId(m,entry);
 b.setAttribute('aria-expanded',String(entry.open));b.setAttribute('aria-label',(entry.open?'Hide details':'Details')+' of this work, '+tokens(steps)+' step'+(steps===1?'':'s'));
 el('span','',entry.open?'▾':'▸',b).setAttribute('aria-hidden','true');
 b.onclick=()=>{const k=m.id+'|'+entry.lead;if(openWork.has(k))openWork.delete(k);else openWork.add(k);changed(m.id);};
 return line;
}
// The closing "Hide details ▴" after the opened items; focus goes back to the line's own toggle.
function workEnd(m,entry){
 const end=el('div','work-end');end.dataset.item=entry.key;const id=workId(m,entry);
 const b=el('button','work-hide','Hide details ',end);b.type='button';b.id='work-end-'+id;b.setAttribute('aria-expanded','true');b.setAttribute('aria-label','Hide details of this work');
 el('span','','▴',b).setAttribute('aria-hidden','true');
 b.onclick=()=>{openWork.delete(m.id+'|'+entry.lead);changed(m.id);document.getElementById('work-'+id)?.focus();};
 return end;
}
// Long messages: over 600 characters, an earlier turn's message shows about its first 240 characters and its reply
// about its first 300.
const LONG=600,PREVIEW={message:240,reply:300};
// Cuts a rendered message to about its first `limit` characters: blocks past the cut get `hidden`, the block that
// crosses it keeps showing, clamped to 3 lines (.is-cut), with its links out of the tab order, and a list that crosses
// it is cut per item. A cut item clamps its text in an inner box, so it keeps its bullet or number. A table that
// crosses it is cut per row instead (a clamp would break its layout): its header and first body row always show, a
// later row that starts past the cut is hidden, and the links in the rows shown stay reachable. Returns whether
// anything was cut.
function cut(box,limit){
 let total=0,cutting=false;
 const walk=node=>{
  if(cutting||total>=limit){node.hidden=true;cutting=true;return;}
  const n=node.textContent.length;
  if(total+n<=limit){total+=n;return;}
  if(node.matches('ul,ol')){for(const li of node.children)walk(li);return;}
  if(node.matches('.table-wrap')){
   total+=node.querySelector('thead')?.textContent.length||0;
   [...(node.querySelector('tbody')?.rows||[])].forEach((tr,i)=>{if(i&&total>=limit)tr.hidden=true;else total+=tr.textContent.length;});
   node.classList.add('is-cut');cutting=true;return;
  }
  if(node.tagName==='LI'){const text=el('div','cut-text');text.append(...node.childNodes);node.append(text);}
  node.classList.add('is-cut');for(const a of node.querySelectorAll('a'))a.tabIndex=-1;total+=n;cutting=true;
 };
 for(const node of box.children)walk(node);
 return cutting;
}
// Show whole message ▾ / Show whole reply ▾, then Show less ▴. The toggle keeps its id, so render() gives focus back.
function preview(m,it,entry,box,msg){
 const key=m.id+'|'+it.key,open=openMsgs.has(key),id=safe(String(m.id).slice(0,8))+'-'+safe(it.key);
 if(!cut(open?box.cloneNode(true):box,PREVIEW[entry.preview]))return;
 box.id='msg-'+id;
 const b=el('button','more',open?'Show less ':entry.preview==='reply'?'Show whole reply ':'Show whole message ',msg);b.type='button';b.id='more-'+id;
 b.setAttribute('aria-expanded',String(open));b.setAttribute('aria-controls',box.id);
 el('span','',open?'▴':'▾',b).setAttribute('aria-hidden','true');
 b.onclick=()=>{if(openMsgs.has(key))openMsgs.delete(key);else openMsgs.add(key);it.version++;changed(m.id);};
}
// A citation report with any problem, in the chat view: one warn line with its counts, Show citation report ▸ (the brief
// card of the problem rows, opened in place and kept in it.briefOpen) and, on a root research task, Open Corpus ›. The
// toggle keeps its id, so render() gives focus back; the brief card's box is always there, so aria-controls names it.
const corpusButton=m=>!!(showTab&&isRoot(m.id));
function citationPointer(m,it,card){
 const R=window.interspaceResearchCards,id=safe(String(m.id).slice(0,8))+'-'+safe(it.key),open=!!it.briefOpen,bump=()=>{it.version++;changed(m.id);};
 card.classList.add('citation-pointer','is-line');
 el('p','pointer-text',R.citationPointerText(it.citation),card);
 const b=el('button','pointer-toggle',open?'Hide citation report ':'Show citation report ',card);b.type='button';b.id='cite-'+id;
 b.setAttribute('aria-expanded',String(open));b.setAttribute('aria-controls','cite-box-'+id);
 el('span','',open?'▾':'▸',b).setAttribute('aria-hidden','true');
 b.onclick=()=>{it.briefOpen=!it.briefOpen;bump();};
 if(corpusButton(m)){const c=el('button','pointer-corpus','Open Corpus ',card);c.type='button';c.setAttribute('aria-label','Open Corpus tab');el('span','','›',c).setAttribute('aria-hidden','true');c.onclick=()=>showTab('corpus');}
 const box=el('div','card cite-box',null,card);box.id='cite-box-'+id;box.hidden=!open;
 if(open)R.citationCard(box,it.citation,{state:it,bump,brief:true});
}
function build(m,it,compact,entry){
 if(entry?.work)return workLine(m,entry);
 if(entry?.end)return workEnd(m,entry);
 if(it.row){const r=el('p','row-event '+it.row,it.text);r.dataset.item=it.key;return r;}
 if(it.message){const msg=el('div','message '+it.message.role+(it.message.pending?' pending':''));msg.dataset.item=it.key;el('small','',it.message.role==='user'?'You':'Agent',msg);
  const box=(it.message.role==='assistant'&&it.message.final&&window.interspaceAgent?.isResearch?.(m.id)?window.interspaceResearchCards.markdown:markdown)(it.message.text,msg);
  if(entry?.preview)preview(m,it,entry,box,msg);
  if(!it.message.final&&!it.message.pending)el('span','streaming footnote','Writing…',msg);if(it.message.pending&&!it.message.failed)el('span','footnote','Sending…',msg);if(it.message.failed)el('p','error-text','Not sent: '+it.message.failed,msg);return msg;}
 const card=el('article','card');card.dataset.item=it.key;
 // Simple folds team and subagent cards until they are opened; the compact copy (Running view) never folds.
 const simple=!compact&&display().detail!=='detailed',fold={simple,folded:simple&&!unfolded.has(m.id+'|'+it.key),unfold:()=>unfold(m,it,card,true),refold:()=>unfold(m,it,card,false)};
 if(it.team){const row=rowStatus(m.id),late=!BUSY.has(m.status?.state)&&TERMINAL.has(row);
  window.interspaceTeam.teamCard(card,{...fold,taskId:m.id,team:it.team,request,compact:!!compact,open:()=>open(m.id),closed:!!it.team.closed||terminal(m.status)||late,
   closedText:it.team.closed||(terminal(m.status)||!late?statusText(m.status).toLowerCase():statusText({state:row}).toLowerCase()),bump:()=>{it.version++;changed(m.id);}});}
 else if(it.sub)window.interspaceTeam.subagentCard(card,{...subContext(m,it,compact),...fold});
 else if(it.ask)askCard(m,it,card,compact);
 else if(it.citation&&entry?.pointer)citationPointer(m,it,card);
 else if(it.citation)window.interspaceResearchCards.citationCard(card,it.citation,{state:it,bump:()=>{it.version++;changed(m.id);}});
 else if(it.call||it.result||it.output!=null)toolCard(m,it,card);
 else if(it.diff){card.classList.add('diff-card');diffBlock(m,it,it.diff,card);}
 else if(it.reasoning!=null)reasoningCard(it,card,display());
 else if(it.plan){el('h3','','Plan',card);const ol=el('ol','plan-steps',null,card);for(const s of it.plan){const li=el('li',s.status,null,ol);el('span','footnote',{completed:'Done',in_progress:'In progress',pending:'Pending'}[s.status]||s.status,li);li.append(' '+String(s.text??''));}}
 if(it.error){card.classList.add('error-card');el('p','error-text',(it.error.recoverable?'Error (the task stays usable)':'Error')+' · '+it.error.code+': '+it.error.message,card);}
 if(it.blobError)el('p','error-text',it.blobError,card);
 return card;
}
const terminal=s=>!!s&&TERMINAL.has(s.state);
// Cards opened from Simple stay open for the session, until Hide details folds them again. Either replaces the
// button that did it, so focus moves to the opened card, or back to its Details button.
const unfolded=new Set();
function unfold(m,it,card,open){
 const box=card.parentNode,key=m.id+'|'+it.key;
 if(open)unfolded.add(key);else{unfolded.delete(key);it.expanded=false;}
 it.version++;changed(m.id);
 const now=box&&[...box.children].find(c=>c.dataset.item===it.key);
 if(!now||now===card)return;
 if(open){now.tabIndex=-1;now.focus();}else now.querySelector('.sub-details,.team-details')?.focus();
}
// A subagent card also changes with its child's own stream, the child's task row and host state (a merge).
const stamp=(m,it)=>it.sub?it.version+'|'+(tasks.get(it.sub.task_id)?.rev||0)+'|'+(rowStatus(it.sub.task_id)||'')+'|'+stampOf(it.sub.task_id):it.version;
// A child's own stream renders into one container that lives as long as its card, so it reconciles in place.
// Only the task view's card holds it: a compact copy (Running view) never expands, so the container is never moved.
function subContext(m,it,compact){
 const child=it.sub.task_id,key=String(child).replace(/[^A-Za-z0-9_-]/g,'_');
 if(compact)return {sub:it.sub,key,compact:true,expanded:false,childBox:null,statusText,markdown,status:childStatus(child,it.sub.state),activity:activity(child),toggle:()=>{},open:()=>open(child)};
 if(it.expanded&&!it.childBox){it.childBox=el('div','stream nested');it.childBox.id='child-'+key;it.childBox.setAttribute('role','log');it.childBox.setAttribute('aria-label','Subagent activity');}
 if(it.expanded)render(it.childBox,child,{nested:true});
 return {sub:it.sub,key,expanded:!!it.expanded,childBox:it.childBox,statusText,markdown,status:childStatus(child,it.sub.state),activity:activity(child),
  citation:citationOf(child),citationCard:window.interspaceResearchCards?.citationCard,bumpChild:()=>{const cm=model(child);cm.rev++;changed(child);},
  toggle:()=>{it.expanded=!it.expanded;it.version++;if(it.expanded)sync(model(child));changed(m.id);},
  open:()=>open(child)};
}
function childChanged(id){
 const parent=parents.get(id),pm=parent&&tasks.get(parent),it=pm&&pm.items.get(pm.children.get(id));
 if(it?.expanded&&it.childBox)render(it.childBox,id,{nested:true});
}
// Reconciles cards in place, so focus, open details and scroll position survive new events. The node cache belongs
// to the task the container shows: a parent and its child share #agent-stream, and keys such as user_u1, seq:N and
// cumulative repeat in every task, so another task starts a fresh cache. options: {compact} for the Running view's
// copy, {nested} for a subagent's activity inside its card; neither is ever digested (simpleOn).
function render(container,taskId,options={}){
 const m=model(taskId);let v=views.get(container);if(!v||v.task!==taskId){v={task:taskId,cache:new Map()};views.set(container,v);}const cache=v.cache;
 const focus=document.activeElement&&container.contains(document.activeElement)&&document.activeElement.id?document.activeElement.id:null;
 const shown=display(),shownKey=JSON.stringify(shown);
 let list=[...m.items.values()].filter(it=>visible(it,shown));
 if(options.compact){const open=m.openAsk&&m.items.get(m.openAsk);list=list.slice(-COMPACT_ITEMS);if(open&&!list.includes(open))list.push(open);}
 const d=simpleOn(m,options)?digest(m,list):{entries:list.map(it=>({key:it.key,it})),folded:0};
 if(!options.compact&&!options.nested)m.folded=d.folded;
 // A reused node takes its in-work class from this render, so switching views never leaves a stale one.
 const nodes=d.entries.map(entry=>{
  const it=entry.it,hit=cache.get(entry.key),version=(it?stamp(m,it):'')+'|'+shownKey+'|'+entryVersion(m,entry);let node=hit&&hit.version===version?hit.node:null;
  if(!node){node=build(m,it,options.compact,entry);if(hit){const was=hit.node.querySelector('details');const now=node.querySelector('details');if(was&&now)now.open=was.open;}cache.set(entry.key,{version,node});}
  node.classList.toggle('in-work',!!entry.inWork);return node;});
 const live=new Set(d.entries.map(e=>e.key));
 for(const key of [...cache.keys()])if(!m.items.has(key)&&!live.has(key))cache.delete(key);
 nodes.forEach((n,i)=>{if(container.children[i]!==n)container.insertBefore(n,container.children[i]||null);});
 while(container.children.length>nodes.length)container.lastElementChild.remove();
 if(m.loadError&&!options.compact){const note=el('p','error-text',m.loadError,container);note.setAttribute('role','alert');}
 if(focus&&document.activeElement?.id!==focus){const again=document.getElementById(focus);if(again&&container.contains(again))again.focus();}
}
function answer(taskId,key,decision,text){
 const m=model(taskId),it=m.items.get(key);if(!it?.ask||it.sending||it.answer)return;
 const a=it.ask,params={task_id:taskId,ask_id:a.ask_id,request_digest:a.request_digest,decision};
 if(decision==='text')params.text=text;
 if(decision==='add_to_scope')params.scope_digest=a.patched_scope_digest;
 it.sending=true;it.answerError='';it.version++;changed(taskId);
 request('agent_answer',params,{manual:true}).then(()=>{it.sent=decision;}).catch(error=>{it.answerError=error.message||'The answer was not accepted.';}).finally(()=>{it.sending=false;it.version++;changed(taskId);});
}
function optimistic(taskId,text,clientId){const m=model(taskId);item(m,'client:'+clientId).message={role:'user',text,final:true,pending:true};changed(taskId);}
function failed(taskId,clientId,reason){const it=model(taskId).items.get('client:'+clientId);if(!it)return;it.message.failed=reason;it.version++;changed(taskId);}

window.interspaceStream={
 // showTab(tab) switches the task view's results tab; isRoot(id) says whether a task is a root research task.
 init(options){request=options.request;hostChanged=options.changed||hostChanged;open=options.open||open;rowStatus=options.rowStatus||rowStatus;stampOf=options.stamp||stampOf;showTab=options.showTab||showTab;isRoot=options.isRoot||isRoot;changed=id=>{hostChanged(id);childChanged(id);};},
 receive,sync:id=>sync(model(id)),render,activity,childStatus,optimistic,failed,statusText,budgetText,
 has:id=>tasks.has(id)&&tasks.get(id).lastSeq>0,ids:()=>[...tasks.keys()],
 // How many steps the task's last main-conversation render folded into work lines (0 outside Simple's chat view).
 folded:id=>tasks.get(id)?.folded||0,
 parentOf:id=>parents.get(id)||null,
 children:id=>{const m=tasks.get(id);return m?[...m.children.values()].map(k=>m.items.get(k)?.sub).filter(Boolean):[];},
 status:id=>tasks.get(id)?.status||null,usage:id=>tasks.get(id)?.usage||null,outputs:id=>tasks.get(id)?.outputs||null,corpus:id=>tasks.get(id)?.corpus||null,claims:id=>tasks.get(id)?.claims||null,evidence:id=>tasks.get(id)?.evidence||null,budget:id=>tasks.get(id)?.budget||null,scopeEvent:id=>tasks.get(id)?.scopeEvent||null,workspace:id=>tasks.get(id)?.workspace||null,
 busy:s=>!!s&&BUSY.has(s.state),terminal:s=>!!s&&TERMINAL.has(s.state),
 mentions(id){const m=tasks.get(id);if(!m)return [];return [...m.paths].map(p=>({value:p,hint:'File'}));}
};
})();
