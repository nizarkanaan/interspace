/* Report reader (docs/superpowers/specs/2026-11-20-report-reader-design.md): report.md at reading width, its [n]
   citations linked to its own reference list, and each reference marked with the citation checker's verdict from the
   task's corpus. Report text comes from agents and is untrusted: it goes through the text-safe Markdown renderer, and
   everything added here is set with textContent. Matching is exact and local; an unmatched reference says so. */
(()=>{
const RC=window.interspaceResearchCards;
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const size=b=>!Number.isFinite(b)?'':b<1024?b+' bytes':b<1048576?(b/1024).toFixed(1)+' KB':(b/1048576).toFixed(1)+' MB';
const HEADING=/^\s*(references|bibliography|works cited|reference list)\s*:?\s*$/i;
const CITE=/\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]/g;
const DOI=/10\.\d{4,9}\/[^\s"<>]+/i;
const ARXIV=/arxiv[:\s/]*(\d{4}\.\d{4,5})/i;
const MIN_TITLE=20;
const norm=s=>String(s||'').toLowerCase().replace(/^\s*retracted\s*[:\-–—]\s*/,'').replace(/[^a-z0-9]+/g,' ').trim();
const doiOf=s=>{const m=String(s||'').match(DOI);return m?m[0].replace(/[.,;:)\]]+$/,'').toLowerCase():null;};
const arxivOf=s=>{const m=String(s||'').match(ARXIV);return m?m[1]:null;};
const VERDICT={verified:['verified','Verified'],retracted:['retracted','Retracted: do not cite'],unverified:['not-verified','Not verified'],unchecked:['unchecked','Not checked'],none:['none','Not found by the agents: possibly cited from memory']};

// The verdict for one reference, from the corpus. Papers confirmed by the checker win over unverified entries.
function verdictFor(text,corpus){
 const papers=Array.isArray(corpus?.papers)?corpus.papers.filter(p=>p&&p.paper):[];
 const open=Array.isArray(corpus?.unverified)?corpus.unverified.filter(u=>u&&u.reference):[];
 const doi=doiOf(text),ax=arxivOf(text),t=norm(text);
 const same=(r,raw)=>{
  if(doi&&r.doi&&String(r.doi).toLowerCase()===doi)return true;
  if(ax&&r.arxiv_id&&String(r.arxiv_id).includes(ax))return true;
  const title=norm(r.title||raw||'');return title.length>=MIN_TITLE&&t.includes(title);
 };
 const p=papers.find(x=>same(x.paper));
 if(p?.check?.status==='verified')return VERDICT.verified;
 if(p?.check?.status==='retracted'||p?.paper?.retracted===true)return VERDICT.retracted;
 if(open.some(u=>same(u.reference,u.reference.raw)))return VERDICT.unverified;
 return p?VERDICT.unchecked:VERDICT.none;
}
// The report's reference list: the list (or the paragraphs) under a References heading. Returns [{node, n}].
function referenceList(box){
 const heading=[...box.querySelectorAll('h3,h4,h5,h6')].find(h=>HEADING.test(h.textContent));
 if(!heading)return [];
 // List items when the section has a list; otherwise only paragraphs that start with a number ("[3] …", "3. …").
 const section=[];for(let node=heading.nextElementSibling;node&&!/^H\d$/.test(node.tagName);node=node.nextElementSibling)section.push(node);
 const lists=section.filter(n=>n.tagName==='OL'||n.tagName==='UL');
 const refs=lists.length?lists.flatMap(l=>[...l.children]):section.filter(n=>n.tagName==='P'&&/^\s*\[?\d{1,3}[\].)]\s/.test(n.textContent));
 return refs.map((node,i)=>{const lead=node.textContent.match(/^\s*\[?(\d{1,3})[\].)]\s/);return {node,n:lead?Number(lead[1]):i+1};});
}
function numbers(group){
 const out=[];for(const part of group.split(/\s*,\s*/)){const r=part.split(/\s*[–-]\s*/).map(Number);out.push(...r);}
 return out.filter(n=>Number.isInteger(n));
}
const CLAIM={supported:'supported',partly:'partly supported',not_supported:'not supported',cannot_tell:'cannot tell from the source'};
function linkCitations(box,known,state,claims){
 const verdict=new Map((claims||[]).map(c=>[c.id,c])),seen={};
 const walker=document.createTreeWalker(box,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('a,code,pre,.report-reference')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});
 const texts=[];while(walker.nextNode())texts.push(walker.currentNode);
 let count=0;
 for(const node of texts){
  const value=node.nodeValue;if(!CITE.test(value)){CITE.lastIndex=0;continue;}CITE.lastIndex=0;
  const frag=document.createDocumentFragment();let last=0,m;
  while((m=CITE.exec(value))){
   const ns=numbers(m[1]);if(!ns.some(n=>known.has(n)))continue;
   frag.append(value.slice(last,m.index),'[');
   m[1].split(/(\d+)/).forEach(bit=>{
    if(/^\d+$/.test(bit)&&known.has(Number(bit))){const a=el('a','cite-link',bit,frag);const id='report-cite-'+(++count);a.id=id;a.href='#report-ref-'+bit;
     // Claim ids number each reference's citations in reading order, as research/claims.py does.
     seen[bit]=(seen[bit]||0)+1;const cid=bit+':'+seen[bit],c=verdict.get(cid);a.dataset.claim=cid;
     if(c&&c.verdict){a.classList.add('claim-'+c.verdict);a.title=(c.reason||'')+(c.quote?' — “'+c.quote+'”':'');}
     a.setAttribute('aria-label','Reference '+bit+(c&&c.verdict?', '+CLAIM[c.verdict]:''));
     a.onclick=e=>{e.preventDefault();state.from=id;const ref=document.getElementById('report-ref-'+bit);if(ref){ref.scrollIntoView({block:'center'});ref.focus();}};}
    else if(bit)frag.append(bit);
   });
   frag.append(']');last=m.index+m[0].length;
  }
  if(last){frag.append(value.slice(last));node.replaceWith(frag);}
 }
}

function render(container,{name,bytes,text,truncated,corpus,loading,error,saving,note,saveError,onSave,claims,checking,checkError,canCheck,onCheck}){
 container.replaceChildren();
 el('h2','visually-hidden','Report',container);
 const bar=el('div','reader-bar',null,container);
 const what=el('p','reader-file',null,bar);el('strong','mono',name,what);if(size(bytes))what.append(' · '+size(bytes));
 const tools=el('span','reader-actions',null,bar);
 const check=el('button','',checking?'Starting…':'Check claims',tools);check.type='button';check.id='reader-check';check.disabled=!canCheck||!!checking;check.onclick=onCheck;
 check.title='An independent model checks whether each cited source supports its sentence.';
 const save=el('button','',saving?'Saving…':'Save report',tools);save.type='button';save.id='reader-save';save.disabled=!!saving;save.onclick=onSave;
 if(checkError)el('p','error-text',checkError,container).setAttribute('role','alert');
 claimSummary(container,claims);
 if(note)el('p','footnote reader-note',note,container).setAttribute('role','status');
 if(saveError)el('p','error-text',saveError,container).setAttribute('role','alert');
 if(error){el('p','error-text',error,container).setAttribute('role','alert');return;}
 if(text==null){el('p','muted',loading?'Loading the report…':'The report is not loaded yet.',container);return;}
 if(truncated)el('p','notice','Only the beginning of this report is shown. Save it to read all of it.',container);
 const state={from:null};
 const box=RC.markdown(text,container);box.classList.add('reader-text');
 const refs=referenceList(box),known=new Set();
 const tally={};
 for(const {node,n} of refs){
  if(known.has(n))continue;known.add(n);
  const [cls,word]=verdictFor(node.textContent,corpus);tally[cls]=(tally[cls]||0)+1;
  node.classList.add('report-reference','is-'+cls);node.id='report-ref-'+n;node.tabIndex=-1;
  const mark=el('span','report-verdict',word);node.prepend(mark);
  const back=el('a','report-back','Back to text',node);back.href='#';back.onclick=e=>{e.preventDefault();const from=state.from&&document.getElementById(state.from);if(from){from.scrollIntoView({block:'center'});from.focus();}};
 }
 linkCitations(box,known,state,claims?.claims);
 claimList(container,box,claims);
 if(refs.length){
  const s=el('p','footnote reader-summary',null,container);container.insertBefore(s,box);
  const parts=[['verified','verified'],['retracted','retracted'],['not-verified','not verified'],['unchecked','not checked'],['none','not in the corpus']].filter(([k])=>tally[k]).map(([k,w])=>tally[k]+' '+w);
  s.textContent=known.size+(known.size===1?' reference':' references')+': '+parts.join(', ')+'.'+(corpus?'':' The corpus is still loading.');
 }
}

// The claim check (2026-11-20-claim-check-design.md): a summary line, then the claims worth a second look.
const ORDER=['not_supported','partly','cannot_tell'];
const WORD={supported:'Supported',partly:'Partly supported',not_supported:'Not supported',cannot_tell:'Can’t tell from the source'};
function claimSummary(container,claims){
 const c=claims?.counts;if(!c||!c.claims)return;
 const p=el('p','claim-summary',null,container);p.setAttribute('role','status');
 const parts=[['supported','supported'],['partly','partly'],['not_supported','not supported'],['cannot_tell','can’t tell']].filter(([k])=>c[k]).map(([k,w])=>c[k]+' '+w);
 p.textContent=c.pending?'Checking claims: '+(c.claims-c.pending)+' of '+c.claims+' done'+(parts.length?' ('+parts.join(', ')+')':'')+'.':c.claims+(c.claims===1?' claim: ':' claims: ')+parts.join(', ')+'.';
}
function claimList(container,box,claims){
 const list=(claims?.claims||[]).filter(c=>ORDER.includes(c.verdict)).sort((a,b)=>ORDER.indexOf(a.verdict)-ORDER.indexOf(b.verdict));
 if(!list.length)return;
 const d=el('details','claim-list',null,null);container.insertBefore(d,box);d.open=list.some(c=>c.verdict!=='cannot_tell');
 el('summary','','Claims to look at ('+list.length+')',d);
 const ol=el('ol','',null,d);
 for(const c of list){
  const li=el('li','claim-item is-'+c.verdict,null,ol);
  el('span','claim-verdict',WORD[c.verdict],li);
  el('p','claim-sentence',c.sentence,li);
  el('p','footnote','Source ['+c.n+']: '+(c.reference||''),li);
  if(c.reason)el('p','claim-reason',c.reason,li);
  if(c.quote)el('blockquote','claim-quote',c.quote,li);
  const go=el('a','report-back','Show in text',li);go.href='#';go.onclick=e=>{e.preventDefault();const a=box.querySelector('[data-claim="'+c.id+'"]');if(a){a.scrollIntoView({block:'center'});a.focus();}};
 }
}

window.interspaceReader={render,verdictFor};
})();
