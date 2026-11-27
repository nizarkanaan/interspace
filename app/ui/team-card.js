/* Team proposals and subagent cards (docs/superpowers/specs/multi-provider/orchestration.md).
   stream.js owns the event store and calls teamCard/subagentCard while it builds a card; this file owns the
   edit drafts and sends team_answer exactly as the contract states. Summary, brief, reason and report text from
   the model are inserted with textContent only. */
(()=>{
const P=window.interspaceProviders;
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const tokens=n=>Number(n||0).toLocaleString('en-US');
const safeId=s=>String(s).replace(/[^A-Za-z0-9_-]/g,'_');
const ACCESS={read:'Read only',write:'Can write'};
const DOES={read:'reads',write:'writes'};
const FIELDS=['role','brief','provider','model','access'];
const drafts=new Map();

// Display names: "Implementer", or "Implementer 2" when a role repeats.
function names(members){const seen={},count={};for(const m of members)count[m.role]=(count[m.role]||0)+1;return new Map(members.map(m=>{seen[m.role]=(seen[m.role]||0)+1;return [m.member_id,P.roleTitle(m.role)+(count[m.role]>1?' '+seen[m.role]:'')];}));}
function draftFor(taskId,team){
 const key=taskId+'/'+team.team_id;let d=drafts.get(key);
 if(!d){d={members:(team.members||[]).map(m=>Object.fromEntries(FIELDS.map(f=>[f,m[f]??null]).concat([['member_id',m.member_id]]))),removed:new Set(),declining:false,note:'',sending:false,sent:null,error:''};drafts.set(key,d);}
 return d;
}
function edited(team,d){
 if(d.removed.size)return true;
 return d.members.some(m=>{const o=(team.members||[]).find(x=>x.member_id===m.member_id);return !o||FIELDS.some(f=>(o[f]??null)!==(m[f]??null));});
}
function check(d,card){
 const kept=d.members.filter(m=>!d.removed.has(m.member_id));
 if(!kept.length)return 'Keep at least one member, or decline the team.';
 for(const m of kept){
  if(!String(m.brief||'').trim())return 'Every member needs a brief.';
  const problem=P.checkModel(m.provider,m.model||'');
  if(problem){const input=card.querySelector('[data-member="'+CSS.escape(m.member_id)+'"] .member-model');if(input){input.setCustomValidity(problem);input.reportValidity();}return problem;}
  if(m.access==='write'&&P.get(m.provider)&&!P.canWrite(m.provider))return P.title(m.provider)+' cannot write: give that member read access or another provider.';
 }
 return '';
}
function send(ctx,team,d,decision,card){
 if(d.sending||d.sent)return;
 const params={task_id:ctx.taskId,team_id:team.team_id,decision};
 if(decision==='approve'){
  // A problem opens the editors in a Simple card, so it can be fixed there.
  const problem=check(d,card);if(problem){d.error=problem;d.editing=true;ctx.bump();return;}
  if(edited(team,d))params.members=d.members.filter(m=>!d.removed.has(m.member_id)).map(m=>({member_id:m.member_id,role:m.role,brief:String(m.brief).trim(),provider:m.provider,model:m.model||null,access:m.access}));
 }else if(d.note.trim())params.note=d.note.trim();
 d.sending=true;d.error='';ctx.bump();
 ctx.request('team_answer',params,{manual:true}).then(()=>{d.sent=decision;}).catch(e=>{d.error=e.message||'The answer was not accepted.';}).finally(()=>{d.sending=false;ctx.bump();});
}
function budgetLine(b){return b&&b.budget!=null?'Budget: '+tokens(b.used)+' / '+tokens(b.budget)+' tokens used by this task so far':'';}
// Default, the Orchestrator's suggestion with its one-line reason, or the user's own change to the member.
const ROUTED=['provider','model','access'];
function marker(proposed,m,parent){
 const mine=m&&ROUTED.some(f=>(proposed[f]??null)!==(m[f]??null));
 const reason=typeof proposed.reason==='string'?proposed.reason.trim():'';
 const e=mine?el('span','marker changed','Your change',parent):proposed.default?el('span','marker default','Default',parent):el('span','marker suggested',reason?'Suggested: '+reason:'Suggested (no reason given)',parent);
 return e;
}

function memberEditor(ctx,team,d,m,label,list,locked){
 const proposed=(team.members||[]).find(x=>x.member_id===m.member_id)||m,removed=d.removed.has(m.member_id);
 const box=el('li','team-member'+(removed?' removed':''),null,list);box.dataset.member=m.member_id;
 const head=el('div','member-head',null,box);el('h4','',label,head);P.badge(m.provider,head);marker(proposed,m,head);if(removed)el('span','marker removed-tag','Removed',head);
 const base='tm-'+safeId(ctx.taskId).slice(0,12)+'-'+safeId(team.team_id).slice(0,12)+'-'+safeId(m.member_id);
 if(removed){el('p','footnote',m.brief,box);}
 else{
  const bl=el('label','',label+' brief',box);bl.htmlFor=base+'-brief';
  const brief=el('textarea','member-brief',null,box);brief.id=base+'-brief';brief.rows=3;brief.maxLength=6000;brief.value=m.brief||'';brief.disabled=locked;brief.oninput=()=>{m.brief=brief.value;};
  const row=el('div','member-fields',null,box);
  const provider=P.providerSelect(row,{id:base+'-provider',label:label+' provider',value:m.provider});provider.disabled=locked;
  const model=P.modelInput(row,{id:base+'-model',label:label+' model',provider:m.provider,value:m.model||''});model.classList.add('member-model');model.disabled=locked;
  const al=el('div','field',null,row),alabel=el('label','',label+' access',al);alabel.htmlFor=base+'-access';
  const access=el('select','',null,al);access.id=base+'-access';access.disabled=locked;
  for(const v of ['read','write']){const o=el('option','',ACCESS[v],access);o.value=v;}
  // A research task has no project to write to (research/tasks.md): its members stay read-only.
  const research=!!window.interspaceAgent?.isResearch?.(ctx.taskId);
  const sync=()=>{const w=access.querySelector('option[value=write]');const can=!research&&(!P.get(m.provider)||P.canWrite(m.provider));w.disabled=!can;w.textContent=can?ACCESS.write:research?ACCESS.write+' (not in a research task)':ACCESS.write+' (not available on '+P.title(m.provider)+')';if(!can&&m.access==='write')m.access='read';access.value=m.access==='write'?'write':'read';};
  sync();
  const remark=()=>head.querySelector('.marker').replaceWith(marker(proposed,m));
  // A model belongs to its provider, so a new provider starts at Default; the model control is always looked up again because its list can swap it.
  provider.onchange=()=>{m.provider=provider.value;m.model=null;const cur=box.querySelector('.member-model');cur.value='';cur.setCustomValidity('');cur.setProvider(provider.value);sync();head.querySelector('.provider-badge').replaceWith(P.badge(m.provider));remark();};
  model.onchange=model.oninput=()=>{const cur=box.querySelector('.member-model');cur.setCustomValidity('');m.model=cur.value.trim()||null;remark();};
  access.onchange=()=>{m.access=access.value;remark();};
 }
 if(!locked){const b=el('button','quiet',removed?'Keep':'Remove',box);b.type='button';b.setAttribute('aria-label',(removed?'Keep ':'Remove ')+label);b.onclick=()=>{if(removed)d.removed.delete(m.member_id);else d.removed.add(m.member_id);ctx.bump();};}
}
function memberSummary(m,label,list){
 const li=el('li','team-member closed',null,list);li.dataset.member=m.member_id;
 const head=el('div','member-head',null,li);el('h4','',label,head);P.badge(m.provider,head);
 el('span','footnote',(m.model||'default model')+' · '+(ACCESS[m.access]||m.access),head);
 if(m.brief)el('p','',m.brief,li);
}
// Simple (2026-11-27-readable-workspace-design.md): "Codex researcher · reads", one member per line.
const short=(m,label)=>P.title(m.provider)+' '+String(label).toLowerCase();
function memberLine(m,label,list){const li=el('li','team-line',short(m,label)+' · '+(DOES[m.access]||m.access),list);li.dataset.member=m.member_id;}
// "Details ▸" is named for what it opens ("Researcher details", "Team details"); the arrow is not read out.
function detailsButton(parent,cls,name,onclick){
 const b=el('button',cls,'Details ',parent);b.type='button';b.setAttribute('aria-label',name+' details');b.setAttribute('aria-expanded','false');
 el('span','','▸',b).setAttribute('aria-hidden','true');b.onclick=onclick;return b;
}
// "Hide details ▾" on an opened card folds it back to its Simple line. Its name starts with what it shows.
function hideButton(parent,cls,name,onclick){
 const b=el('button',cls+' is-open','Hide details ',parent);b.type='button';b.setAttribute('aria-label','Hide '+name+' details');b.setAttribute('aria-expanded','true');
 el('span','','▾',b).setAttribute('aria-hidden','true');b.onclick=onclick;return b;
}
// The answered team on one line; Details opens today's answered card in place.
function answeredLine(card,ctx,team,answered){
 card.classList.add('is-line');
 const members=Array.isArray(answered.members)&&answered.members.length?answered.members:answered.decision==='approve'?team.members||[]:[],n=names(members);
 el('p','team-line-text',answered.decision==='approve'?'Team approved'+(members.length?' · '+members.map(m=>short(m,n.get(m.member_id))).join(', '):''):'Team declined',card);
 detailsButton(card,'team-details','Team',ctx.unfold);
}
// Edit team (or Details on a proposal that can no longer be answered) opens today's editors in the same card. The
// button that did it is gone, so focus moves to the first editor, or to the card.
function reveal(card,ctx,d){
 const box=card.parentNode,key=card.dataset.item;d.editing=true;ctx.bump();
 const now=box&&[...box.children].find(c=>c.dataset.item===key);if(!now)return;
 const first=now.querySelector('.team-member textarea:not(:disabled)');if(first)first.focus();else{now.tabIndex=-1;now.focus();}
}
// Hide details on an untouched proposal folds the editors away again; focus goes back to the button that opens them.
function conceal(card,ctx,d){
 const box=card.parentNode,key=card.dataset.item;d.editing=false;ctx.bump();
 const now=box&&[...box.children].find(c=>c.dataset.item===key);
 now?.querySelector('.team-edit,.team-details')?.focus();
}
// A team_proposed card, open until team_answered arrives or the task ends.
function teamCard(card,ctx){
 const t=ctx.team,team=t.proposal,answered=t.answered;
 card.classList.add('team');card.setAttribute('role','group');card.setAttribute('aria-label','Proposed team');
 if(!team){el('h3','','Team',card);if(answered)el('p','answered',answered.decision==='approve'?'Team approved':'Team declined',card);return;}
 if(answered&&ctx.folded){answeredLine(card,ctx,team,answered);return;}
 // Simple shows a short card: the members one per line and the summary, until Edit team opens the editors.
 // A proposal already edited (in Detailed) keeps its editors and its "You changed this team" note.
 const draft=draftFor(ctx.taskId,team),folded=!answered&&!ctx.compact&&!!ctx.simple&&!draft.editing&&!edited(team,draft);
 if(!answered&&!ctx.compact&&ctx.simple)card.classList.add('is-simple');
 const head=el('div','card-head',null,card);el('span','badge','Team',head);el('strong','','Proposed team',head);
 el('span','state',answered?(answered.decision==='approve'?'Approved':'Declined'):ctx.closed?'Closed':'Needs your approval',head);
 // Opened from Simple: the answered card folds back to its line, an untouched proposal back to its short card.
 if(ctx.simple&&answered)hideButton(head,'team-details','Team',ctx.refold);
 else if(ctx.simple&&!ctx.compact&&!folded&&draft.editing&&!edited(team,draft))hideButton(head,'team-details','Proposed team',()=>conceal(card,ctx,draft));
 if(team.summary)el('p','team-summary',team.summary,card);
 const bl=budgetLine(team.budget);if(bl&&!folded)el('p','footnote',bl,card);
 const list=el('ul','team-members',null,card);
 if(answered){
  const members=Array.isArray(answered.members)&&answered.members.length?answered.members:answered.decision==='approve'?team.members||[]:[];
  const n=names(members);for(const m of members)memberSummary(m,n.get(m.member_id),list);
  if(!members.length){const n2=names(team.members||[]);for(const m of team.members||[])memberSummary(m,n2.get(m.member_id),list);}
  el('p','answered',answered.decision==='approve'?'You approved this team.':'You declined this team'+(answered.note?': '+answered.note:'.'),card);
  return;
 }
 const d=draftFor(ctx.taskId,team),locked=d.sending||!!d.sent||ctx.closed,n=names(d.members);
 // The Running view shows a read-only copy that leads to the task: one editable form per proposal, so the team
 // that is approved is always the one on screen, and no control id appears twice.
 if(ctx.compact){
  for(const m of d.members)if(!d.removed.has(m.member_id))memberSummary(m,n.get(m.member_id),list);
  if(ctx.closed&&!d.sent){el('p','footnote','This proposal is no longer open: the task is '+ctx.closedText+'.',card);return;}
  if(d.sent){el('p','footnote',(d.sent==='approve'?'Approved':'Declined')+'. Waiting for the Orchestrator.',card);return;}
  const go=el('button','primary','Review the proposed team',el('div','actions',null,card));go.type='button';go.onclick=ctx.open;
  return;
 }
 if(folded){list.classList.add('team-lines');for(const m of d.members)if(!d.removed.has(m.member_id))memberLine(m,n.get(m.member_id),list);}
 else for(const m of d.members)memberEditor(ctx,team,d,m,n.get(m.member_id),list,locked);
 if(ctx.closed&&!d.sent){el('p','footnote','This proposal is no longer open: the task is '+ctx.closedText+'.',card);if(folded)detailsButton(card,'team-details','Proposed team',()=>reveal(card,ctx,d));return;}
 if(d.error)el('p','error-text',d.error,card).setAttribute('role','alert');
 if(d.sent){el('p','footnote',(d.sent==='approve'?'Approved':'Declined')+'. Waiting for the Orchestrator.',card);if(folded)detailsButton(card,'team-details','Proposed team',()=>reveal(card,ctx,d));return;}
 el('p','footnote',folded?'Nothing runs until you approve.':edited(team,d)?'You changed this team: Approve sends your edited team, which is checked again before it starts.':'Nothing runs until you approve. You can change each member’s provider, model, access and brief, or remove members.',card);
 const actions=el('div','actions',null,card);
 if(d.declining){
  const id='tm-'+safeId(ctx.taskId).slice(0,12)+'-'+safeId(team.team_id).slice(0,12)+'-note';
  const wrap=el('div','decline-note',null,actions),l=el('label','','Note for the Orchestrator (optional)',wrap);l.htmlFor=id;
  const note=el('textarea','',null,wrap);note.id=id;note.rows=2;note.maxLength=2000;note.value=d.note;note.disabled=d.sending;note.oninput=()=>{d.note=note.value;};
  const go=el('button','primary','Decline team',actions);go.type='button';go.disabled=d.sending;go.onclick=()=>send(ctx,team,d,'decline',card);
  const back=el('button','','Keep reviewing',actions);back.type='button';back.disabled=d.sending;back.onclick=()=>{d.declining=false;ctx.bump();};
  return;
 }
 const ok=el('button','primary','Approve team',actions);ok.type='button';ok.disabled=d.sending||d.removed.size===d.members.length;ok.onclick=()=>send(ctx,team,d,'approve',card);
 const no=el('button','','Decline',actions);no.type='button';no.disabled=d.sending;no.onclick=()=>{d.declining=true;ctx.bump();};
 if(folded){const e=el('button','team-edit','Edit team',actions);e.type='button';e.setAttribute('aria-expanded','false');e.disabled=d.sending;e.onclick=()=>reveal(card,ctx,d);}
}

// One child run: provider, role, state, tokens and its latest activity line, live without expanding;
// its full stream loads on demand.
function subagentCard(card,ctx){
 const s=ctx.sub,label=P.roleTitle(s.role||'subagent'),st=ctx.status||{state:s.state||'queued'};
 card.classList.add('subagent');card.setAttribute('aria-label',label+' subagent');card.dataset.child=s.task_id;
 const head=el('div','card-head',null,card);P.badge(s.provider,head);el('strong','',label,head);
 // A child that answered its brief waits idle for a follow-up; on its card that reads as finished.
 const finished=st.state==='idle'&&s.finished;
 el('span','state '+(finished?'finished':st.state||''),finished?'Finished':ctx.statusText({state:st.state}),head);
 // Simple: provider, role and state on one line; Details opens the full card in place.
 if(ctx.folded){card.classList.add('is-line');detailsButton(head,'sub-details',label,ctx.unfold);return;}
 if(ctx.simple)hideButton(head,'sub-details',label,ctx.refold);
 const facts=[(s.model||'default model'),ACCESS[s.access]||s.access];if(s.tokens_used!=null)facts.push(tokens(s.tokens_used)+' tokens');
 el('p','footnote',facts.filter(Boolean).join(' · '),card);
 if(s.brief)el('p','',s.brief,card);
 if(ctx.activity){const a=el('p','sub-activity',null,card);a.setAttribute('aria-label',label+' latest activity');el('span','footnote','Latest: ',a);a.append(ctx.activity);}
 const diff=s.diff_summary;
 if(diff&&Array.isArray(diff.files)){const add=diff.files.reduce((a,f)=>a+(f.additions||0),0),del=diff.files.reduce((a,f)=>a+(f.deletions||0),0);el('p','footnote mono',diff.files.length+' file'+(diff.files.length===1?'':'s')+' changed · +'+add+' −'+del+(diff.branch?' · '+diff.branch:''),card);}
 if(ctx.citation&&ctx.citationCard){const box=el('div','sub-citation',null,card);ctx.citationCard(box,ctx.citation.citation,{state:ctx.citation,bump:ctx.bumpChild});}
 if(s.report_excerpt){const det=el('details','report',null,card);el('summary','','Report',det);ctx.markdown(s.report_excerpt,det);}
 const merged=window.interspaceReview?.merged?.(s.task_id);
 if(merged)el('p','merged-line',merged.merge_commit?'Merged into '+merged.into+' · '+String(merged.merge_commit).slice(0,8):'Already merged into '+merged.into,card).setAttribute('role','status');
 const actions=el('div','actions',null,card);
 // The compact copy (Running view) has no ids and no expansion: the task view owns those.
 const id=name=>ctx.compact?'':name+ctx.key;
 if(!ctx.compact){const toggle=el('button','',ctx.expanded?'Hide activity':'Show activity',actions);toggle.type='button';toggle.id=id('sub-toggle-');toggle.setAttribute('aria-expanded',String(ctx.expanded));toggle.setAttribute('aria-label',(ctx.expanded?'Hide ':'Show ')+label+' activity');toggle.onclick=ctx.toggle;if(ctx.expanded){toggle.setAttribute('aria-controls',ctx.childBox.id);}}
 const open=el('button','','Open',actions);open.type='button';if(!ctx.compact)open.id=id('sub-open-');open.setAttribute('aria-label','Open '+label+' subagent');open.onclick=ctx.open;
 if((s.access==='write'||diff)&&!window.interspaceAgent?.isResearch?.(s.task_id)){const r=el('button','','Review changes',actions);r.type='button';if(!ctx.compact)r.id=id('review-');r.setAttribute('aria-label','Review '+label+' changes');r.disabled=!window.interspaceReview;r.onclick=()=>window.interspaceReview?.open(s.task_id);}
 if(ctx.expanded)card.append(ctx.childBox);
}

window.interspaceTeam={teamCard,subagentCard};
})();
