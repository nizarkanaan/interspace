/* Research cards (docs/superpowers/specs/research/tools.md and tasks.md): research tool calls as paper lists, the
   citation report, a task's outputs (report and BibTeX) and its research call counts. All research results are
   untrusted: every value is inserted with textContent, and a link is made only for an https URL. Nothing here says a
   reference is verified unless the checker's report row says `verified`. */
(()=>{
const R=window.interspaceResearch;
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const count=n=>Number(n||0).toLocaleString('en-US');
const plural=(n,one,many)=>count(n)+' '+(n===1?one:many||one+'s');
const str=v=>typeof v==='string'?v:v==null?'':String(v);
const PAPERS_SHOWN=5,ROWS_SHOWN=10;
const TOOL={research_search:'Search papers',research_paper:'Look up a paper',research_citations:'Follow citations',research_fulltext:'Find an open copy',research_bibtex:'Get BibTeX',verify_citations:'Check citations'};
const RESULT={ok:'Done',error:'Failed',denied:'Denied',cancelled:'Cancelled'};
const SKIP={not_configured:'not set up',rate_limited:'rate limited',unavailable:'unavailable',bad_response:'unreadable reply',not_found:'not found',denied:'not allowed by the scope',off:'off in the scope'};
const STATUS={
 verified:{label:'Verified',cls:'verified'},
 mismatch:{label:'Not verified: differs from the published record',cls:'mismatch'},
 not_found:{label:'Not verified: not found in the sources checked',cls:'not-found'},
 retracted:{label:'Retracted: do not cite',cls:'retracted'},
 unchecked:{label:'Not checked',cls:'unchecked'}
};
const ORDER=['verified','mismatch','not_found','retracted','unchecked'];
// Rows are listed problems first, so a collapsed report never hides a retracted or unverified reference.
const RANK={retracted:0,mismatch:1,not_found:2,unchecked:4,verified:5};
const SUMMARY={verified:'verified',mismatch:'mismatch',not_found:'not found',retracted:'retracted',unchecked:'unchecked'};
const FIELD={title:'title',year:'year',authors:'authors',doi:'DOI',arxiv_id:'arXiv ID'};

// A list of untrusted strings, at most `max` long; anything else is dropped.
const strings=(v,max=50)=>Array.isArray(v)?v.filter(x=>typeof x==='string'&&x.trim()).slice(0,max):[];
function sourceBadges(list,parent){const box=el('span','source-badges',null,parent);for(const s of strings(list,10)){const b=el('span','source-badge',R.title(s),box);b.dataset.source=s;}return box;}
// Citation-style line: `Authors (Year). Venue.`; empty parts are left out.
function citeLine(authors,year,venue){const a=authorsText(authors),y=Number.isInteger(year)?'('+year+')':'',v=str(venue).trim();const lead=[a,y].filter(Boolean).join(' ');return [lead,v].filter(Boolean).map(x=>/[.?!]$/.test(x)?x:x+'.').join(' ');}
function authorsText(list){const a=strings(list,200);if(!a.length)return '';return a.length>3?a.slice(0,3).join(', ')+' et al.':a.join(', ');}
// One paper: the title links only to an https URL; DOI and arXiv ID are plain text.
function paper(p,parent,{abstract=false}={}){
 const li=el('li','paper',null,parent);if(!p||typeof p!=='object'){el('span','muted','Unreadable record',li);return li;}
 const head=el('div','paper-title',null,li);const name=str(p.title).trim()||'Untitled';
 if(!R.link(p.url,name,head))el('strong','',name,head);
 if(p.retracted===true)el('span','paper-flag retracted','Retracted',head);
 const meta=citeLine(p.authors,p.year,p.venue);
 if(meta)el('p','paper-meta',meta,li);
 const facts=el('p','paper-facts footnote',null,li);
 sourceBadges(p.sources,facts);
 if(Number.isSafeInteger(p.citation_count)&&p.citation_count>=0)el('span','',plural(p.citation_count,'citation'),facts);
 if(p.doi)el('span','mono','doi:'+str(p.doi),facts);
 if(p.arxiv_id)el('span','mono','arXiv:'+str(p.arxiv_id),facts);
 R.link(p.oa_url,'Open-access copy',facts,'Open-access copy of '+name+' (opens in your browser)');
 if(abstract&&p.abstract){const d=el('details','paper-abstract',null,li);el('summary','','Abstract',d);el('p','',str(p.abstract),d);}
 return li;
}
// A long list shows its first rows and a toggle; `state` keeps the choice across re-renders of the card.
function collapsible(parent,items,shown,state,key,bump,label,draw){
 const all=!!state[key],list=el('ol',label.cls,null,parent);
 items.slice(0,all?items.length:shown).forEach(x=>draw(x,list));
 if(items.length>shown){const b=el('button','link-button',all?'Show fewer':'Show all '+count(items.length)+' '+label.noun,parent);b.type='button';b.setAttribute('aria-expanded',String(all));b.onclick=()=>{state[key]=!all;bump();};}
 return list;
}
function paperList(parent,papers,state,bump,key='papers'){
 const list=Array.isArray(papers)?papers:[];
 if(!list.length){el('p','muted','No papers.',parent);return;}
 collapsible(parent,list,PAPERS_SHOWN,state,key,bump,{cls:'paper-list',noun:'papers'},(p,ol)=>paper(p,ol));
}
function parse(text){try{const v=JSON.parse(text);return v&&typeof v==='object'?v:null;}catch{return null;}}
function skipped(list,parent){
 const rows=Array.isArray(list)?list.filter(s=>s&&typeof s.source==='string'):[];
 if(rows.length)el('p','footnote','Skipped: '+rows.map(s=>R.title(s.source)+' ('+(SKIP[s.reason]||str(s.reason).replaceAll('_',' ')||'no reason given')+')').join(', '),parent);
}
// A research tool_call/tool_result pair. `output` is the result's text: the tool's JSON, perhaps cut short.
function toolCard(card,{call,result,output,state,bump}){
 const c=call||{},r=result,input=c.input&&typeof c.input==='object'?c.input:{};card.classList.add('tool','research');
 const tool=str(input.tool||c.tool);
 const head=el('div','card-head',null,card);el('span','badge','Research',head);el('strong','',TOOL[tool]||c.title||tool||'Research tool',head);
 el('span','state '+(r?r.status:'running'),r?(RESULT[r.status]||r.status)+(r.duration_ms!=null?' · '+r.duration_ms+' ms':''):'Running',head);
 const ask=[];if(input.query)ask.push('“'+str(input.query)+'”');if(input.id)ask.push(str(input.id));if(input.source)ask.push('from '+R.title(input.source));
 if(ask.length)el('p','research-query',ask.join(' · '),card);
 if(c.decision)el('p','footnote',(c.decision.decision==='deny'?'Denied by ':'Allowed by ')+c.decision.rule+(c.decision.scope_version!=null?' (scope v'+c.decision.scope_version+')':''),card);
 if(r?.error)el('p','error-text',(r.error.code?r.error.code+': ':'')+str(r.error.message),card);
 if(!output)return;
 const data=parse(output);
 if(!data){
  el('p','footnote',r?.output?.truncated?'The result was cut short, so it is shown as raw text.':'The result is not in the expected format, so it is shown as raw text.',card);
  const pre=el('pre','tool-output',output,card);pre.tabIndex=0;pre.setAttribute('aria-label','Raw result');return;
 }
 if(Array.isArray(data.searched)&&data.searched.length)el('p','footnote','Searched '+data.searched.filter(s=>typeof s==='string').map(R.title).join(', '),card);
 skipped(data.skipped,card);
 if(Array.isArray(data.papers)){el('p','footnote',plural(data.papers.length,'paper')+(data.source?' · from '+R.title(data.source):''),card);paperList(card,data.papers,state,bump);}
 else if('paper' in data){if(data.paper)paper(data.paper,el('ol','paper-list',null,card),{abstract:true});else el('p','muted','No record found for this ID.',card);}
 else if('oa_url' in data){const p=el('p','',null,card);if(!R.link(data.oa_url,'Open-access copy',p))p.textContent=data.oa_url?'A copy was found, but its address is not https, so it is not shown.':'No open-access copy found.';const f=[data.license,data.version,data.host_type].map(str).filter(Boolean);if(f.length)el('p','footnote',f.join(' · ')+(data.source?' · from '+R.title(data.source):''),card);}
 else if(Array.isArray(data.entries)){for(const e of data.entries.slice(0,100)){const box=el('div','bib-entry',null,card);el('p','footnote mono',str(e?.id),box);if(e?.bibtex){const pre=el('pre','tool-output',str(e.bibtex),box);pre.tabIndex=0;pre.setAttribute('aria-label','BibTeX for '+str(e.id));}else el('p','error-text','No BibTeX: '+(str(e?.error).replaceAll('_',' ')||'not available'),box);}}
 else if(Array.isArray(data.references)&&data.summary)el('p','footnote','Checked '+plural(data.references.length,'reference')+'. The citation report below gives the result for each one.',card);
 else{const pre=el('pre','tool-output',output,card);pre.tabIndex=0;pre.setAttribute('aria-label','Result');}
 if(data.truncated)el('p','footnote','The result was shortened to fit.',card);
}

// Citation report: counts come from the rows themselves, so a summary can never claim more than the rows show.
function inputText(input){
 if(!input||typeof input!=='object')return 'Reference';
 const a=authorsText(input.authors),y=input.year!=null&&str(input.year)?'('+str(input.year)+')':'',t=str(input.title)||str(input.raw);
 const bits=[[a,y].filter(Boolean).join(' '),t].filter(Boolean).map(x=>/[.?!]$/.test(x)?x:x+'.');if(input.doi)bits.push('doi:'+str(input.doi));if(input.arxiv_id)bits.push('arXiv:'+str(input.arxiv_id));
 return bits.join(' ')||'Reference';
}
function referenceRow(ref,list){
 const s=STATUS[ref?.status],li=el('li','reference '+(s?s.cls:'unknown'),null,list);
 if(Number.isSafeInteger(ref?.index)&&ref.index>=0){const n=el('p','reference-number',null,li);el('span','visually-hidden','Reference ',n);n.append(count(ref.index+1));}
 const label=s?s.label:'Unknown result ('+str(ref?.status)+'): not verified';
 const head=el('p','reference-status',null,li);el('strong','',label,head);
 if(ref?.status==='mismatch'){const f=strings(ref.fields,8).map(x=>FIELD[x]||x);if(f.length)head.append(' in '+f.join(', '));}
 if(ref?.status==='unchecked')head.append(': '+(str(ref.reason).replaceAll('_',' ')||'no source could check it'));
 el('p','reference-input',inputText(ref?.input),li);
 const m=ref?.match;
 if(m&&typeof m==='object'){
  const line=el('p','footnote reference-match',null,li);line.append(ref.status==='verified'?'Matched: ':ref.status==='retracted'?'Matched (retracted): ':'Closest record: ');
  const name=str(m.title)||'Untitled';if(!R.link(m.url,name,line))line.append(name);
  line.append('. ');const meta=citeLine(m.authors,m.year,m.venue);if(meta)line.append(meta+' ');
  if(m.doi)line.append('doi:'+str(m.doi));
 }
 const facts=[];if(ref?.source)facts.push('checked with '+R.title(ref.source));if(typeof ref?.similarity==='number')facts.push('title similarity '+Math.round(ref.similarity*100)+'%');
 if(facts.length)el('p','footnote',facts.join(' · '),li);
}
function citationCard(card,report,{state,bump}){
 card.classList.add('citation-report');card.setAttribute('role','group');card.setAttribute('aria-label','Citation report');
 const refs=Array.isArray(report?.references)?report.references:[];
 const counts=Object.fromEntries(ORDER.map(k=>[k,0]));let other=0;for(const r of refs)if(r&&r.status in counts)counts[r.status]++;else other++;
 const head=el('div','card-head',null,card);el('span','badge','Citations',head);el('strong','','Citation report',head);
 el('span','state',plural(refs.length,'reference'),head);
 const sum=el('ul','citation-summary',null,card);sum.setAttribute('aria-label','Citation summary');
 for(const k of ORDER){const li=el('li',STATUS[k].cls,null,sum);el('strong','',count(counts[k]),li);li.append(' '+SUMMARY[k]);}
 if(other){const li=el('li','unknown',null,sum);el('strong','',count(other),li);li.append(' unknown');}
 const unverified=refs.length-counts.verified;
 if(counts.retracted)el('p','retracted-alert',plural(counts.retracted,'reference')+(counts.retracted===1?' is retracted. Do not cite it.':' are retracted. Do not cite them.'),card);
 const meaning='Verified means a published record matched: title at least 90% similar, plus the year (within one) and the first author when the reference gives them.';
 el('p','footnote',(unverified?plural(unverified,'reference')+(unverified===1?' is':' are')+' not verified. ':refs.length?'Every reference is verified. ':'No references were checked. ')+(refs.length?meaning:''),card);
 const rank=r=>r&&r.status in RANK?RANK[r.status]:3;
 const sorted=refs.map((r,i)=>[r,i]).sort((a,b)=>rank(a[0])-rank(b[0])||a[1]-b[1]).map(x=>x[0]);
 if(refs.length)collapsible(card,sorted,ROWS_SHOWN,state,'refs',bump,{cls:'reference-list',noun:'references'},referenceRow);
 if(report?.checked_at)el('p','footnote','Checked at '+str(report.checked_at),card);
}

// Text-safe Markdown for report.md: headings, lists, quotes, fenced code, `code`, **bold**, *italic* and
// [links](https://…). Every piece of text is a text node; a link that is not https stays plain text, and an https
// link's real host is shown after its text, so text that looks like another address cannot hide where it goes.
function inline(text,parent){
 for(const part of text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\([^)\s]+\))/)){
  if(!part)continue;
  if(/^`[^`]+`$/.test(part))el('code','',part.slice(1,-1),parent);
  else if(/^\*\*[^*]+\*\*$/.test(part))el('strong','',part.slice(2,-2),parent);
  else if(/^\*[^*]+\*$/.test(part))el('em','',part.slice(1,-1),parent);
  else if(/^\[[^\]]+\]\([^)]+\)$/.test(part)){const i=part.indexOf('](');const label=part.slice(1,i),href=part.slice(i+2,-1);if(R.link(href,label,parent)){if(label!==href)el('span','link-host',' ('+new URL(href).hostname+')',parent);}else parent.append(document.createTextNode(label+' ('+href+')'));}
  else parent.append(document.createTextNode(part));
 }
}
function markdown(text,parent){
 const box=el('div','md report-md',null,parent);let code=null,para=[],list=null;
 const flush=()=>{if(para.length){inline(para.join('\n'),el('p','',null,box));para=[];}};
 for(const line of String(text).split('\n')){
  if(/^```/.test(line)){flush();list=null;if(code)code=null;else code=el('code','',null,el('pre','code-block',null,box));continue;}
  if(code){code.textContent+=(code.textContent?'\n':'')+line;continue;}
  let m;
  if(!line.trim()){flush();list=null;continue;}
  if((m=/^(#{1,6})\s+(.*)$/.exec(line))){flush();list=null;inline(m[2],el('h'+Math.min(6,m[1].length+2),'',null,box));continue;}
  if((m=/^\s*([-*+]|\d+[.)])\s+(.*)$/.exec(line))){flush();const ordered=/\d/.test(m[1]);if(!list||list.ordered!==ordered){list=el(ordered?'ol':'ul','',null,box);list.ordered=ordered;}inline(m[2],el('li','',null,list));continue;}
  if((m=/^>\s?(.*)$/.exec(line))){flush();list=null;inline(m[1],el('blockquote','',null,box));continue;}
  list=null;para.push(line);
 }
 flush();return box;
}

// Outputs panel: the task's report and BibTeX, viewed in place and saved through the app's save panel.
const outputState=new Map();
const KIND={report:'Report',bibtex:'BibTeX references'};
const size=b=>!Number.isFinite(b)?'':b<1024?b+' bytes':b<1048576?(b/1024).toFixed(1)+' KB':(b/1048576).toFixed(1)+' MB';
function outputsPanel(container,taskId,data,{request,refresh}){
 const list=Array.isArray(data?.outputs)?data.outputs.filter(o=>o&&typeof o.name==='string'&&o.name):[];
 container.replaceChildren();container.hidden=!list.length;if(!list.length)return;
 if(!outputState.has(taskId))outputState.set(taskId,new Map());const st=outputState.get(taskId);
 el('h2','','Outputs',container);
 el('p','footnote','Saved in Interspace on this Mac. Save copies a file to a place you choose.',container);
 const ul=el('ul','output-list',null,container);
 for(const o of list){
  const s=st.get(o.name)||{};st.set(o.name,s);const safe=String(o.name).replace(/[^A-Za-z0-9_-]/g,'_');
  const li=el('li','output-item',null,ul);li.dataset.output=o.name;
  const head=el('div','output-head',null,li);el('strong','mono',o.name,head);el('span','footnote',[KIND[o.kind]||str(o.kind),size(o.bytes)].filter(Boolean).join(' · '),head);
  const acts=el('div','actions',null,li);
  const view=el('button','',s.open?'Hide':'View',acts);view.type='button';view.id='output-view-'+safe;view.setAttribute('aria-expanded',String(!!s.open));view.setAttribute('aria-label',(s.open?'Hide ':'View ')+o.name);
  view.onclick=()=>{s.open=!s.open;if(s.open&&s.text==null&&!s.loading)read(taskId,o,s,request,refresh);refresh();};
  const save=el('button','',s.saving?'Saving…':'Save',acts);save.type='button';save.id='output-save-'+safe;save.disabled=!!s.saving;save.setAttribute('aria-label','Save '+o.name);
  save.onclick=()=>{s.saving=true;s.note='';s.error='';refresh();request('task_output_save',{task_id:taskId,name:o.name},{manual:true}).then(r=>{s.note=r?.saved?'Saved.':'Not saved.';}).catch(e=>{s.error=e.message||'The file was not saved.';}).finally(()=>{s.saving=false;refresh();});};
  if(o.kind==='bibtex')el('p','footnote','Holds the references the citation checker verified; mismatched ones are marked in a comment, and not-found or retracted ones are left out.',li);
  if(s.note)el('p','footnote',s.note,li).setAttribute('role','status');
  if(s.error)el('p','error-text',s.error,li).setAttribute('role','alert');
  if(s.open){
   const body=el('div','output-body',null,li);body.id='output-body-'+safe;view.setAttribute('aria-controls',body.id);
   if(s.loading)el('p','muted','Loading…',body);
   else if(s.readError)el('p','error-text',s.readError,body);
   else if(s.text!=null){
    if(s.truncated)el('p','footnote','Only the beginning of this file is shown. Save it to read all of it.',body);
    if(o.kind==='report'||/\.md$/i.test(o.name))markdown(s.text,body);
    else{const pre=el('pre','output-text',s.text,body);pre.tabIndex=0;pre.setAttribute('aria-label',o.name);}
   }
  }
 }
}
// task_output_read {task_id, name} -> {name, kind, text, truncated}: UTF-8, capped at 1 MiB (research/tasks.md).
function read(taskId,o,s,request,refresh){
 s.loading=true;s.readError='';
 request('task_output_read',{task_id:taskId,name:o.name},{manual:true}).then(r=>{if(typeof r?.text!=='string')throw Error('This file could not be read.');s.text=r.text;s.truncated=!!r.truncated;})
  .catch(e=>{s.readError=e.message||'This file could not be read.';}).finally(()=>{s.loading=false;refresh();});
}

// Research requests per source: `calls` are requests sent, `cached` answers the cache gave instead (tasks.md, Wave 2A).
// Counts only, never money.
function usageText(u){
 const calls=u&&typeof u.calls==='object'?u.calls:{},cached=u&&typeof u.cached==='object'?u.cached:{};
 const names=[...new Set([...Object.keys(calls),...Object.keys(cached)])].filter(n=>Number.isSafeInteger(calls[n])||Number.isSafeInteger(cached[n]));
 if(!names.length)return '';
 return 'Research requests: '+names.map(n=>{const c=Number.isSafeInteger(calls[n])?calls[n]:0,k=Number.isSafeInteger(cached[n])?cached[n]:0;return R.title(n)+' '+count(c)+' sent'+(k?', '+count(k)+' answered from cache':'');}).join(' · ');
}

window.interspaceResearchCards={toolTitle:name=>TOOL[name]||'',paper,toolCard,citationCard,outputsPanel,usageText,markdown,paperList};
})();
