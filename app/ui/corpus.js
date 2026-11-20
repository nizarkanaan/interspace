/* Corpus tab (docs/superpowers/specs/2026-11-20-task-corpus-design.md): every paper a research task found, merged,
   with its citation verdict, plus the references that could not be verified. Values come from sources and agents and
   are untrusted: every one is set with textContent, and links are https only (research.js `link`). Status is said in
   words; colour only repeats it. */
(()=>{
const R=window.interspaceResearch,RC=window.interspaceResearchCards;
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const count=n=>Number(n||0).toLocaleString('en-US');
const plural=(n,one,many)=>count(n)+' '+(n===1?one:many||one+'s');
const str=v=>typeof v==='string'?v:v==null?'':String(v);
const SHOWN=50;
const VERDICT={verified:'Verified',retracted:'Retracted: do not cite'};
const OPEN={mismatch:'Not verified: differs from the published record',not_found:'Not verified: not found in the sources checked',unchecked:'Not checked'};
const FIELD={title:'title',year:'year',authors:'authors',doi:'DOI',arxiv_id:'arXiv ID'};
const TOOL={research_search:'search',research_citations:'citations of',research_paper:'lookup',verify_citations:'citation check'};
const FILTERS=[['all','All'],['verified','Checked'],['unchecked','Not checked'],['open','Open access']];
const SORTS=[['found','Order found'],['newest','Newest'],['cited','Most cited']];
const secure=u=>typeof u==='string'&&/^https:\/\//i.test(u);

const papersOf=data=>Array.isArray(data?.papers)?data.papers.filter(p=>p&&p.paper&&typeof p.paper==='object'):[];
const unverifiedOf=data=>Array.isArray(data?.unverified)?data.unverified.filter(u=>u&&typeof u==='object'):[];
const checked=p=>p.check&&VERDICT[p.check.status]?p.check.status:null;
const test={all:()=>true,verified:p=>!!checked(p),unchecked:p=>!checked(p),open:p=>secure(p.paper.oa_url)};
function matches(p,q){
 if(!q)return true;const r=p.paper;
 return [r.title,r.venue,...(Array.isArray(r.authors)?r.authors:[])].some(v=>str(v).toLowerCase().includes(q));
}
function sorted(list,how){
 const at=list.map((p,i)=>[p,i]);
 const key={newest:p=>-(Number.isInteger(p.paper.year)?p.paper.year:-1e9),cited:p=>-(Number.isSafeInteger(p.paper.citation_count)?p.paper.citation_count:-1)}[how];
 if(key)at.sort((a,b)=>key(a[0])-key(b[0])||a[1]-b[1]);
 return at.map(x=>x[0]);
}
function provenance(found,parent){
 const list=Array.isArray(found)?found.filter(f=>f&&typeof f==='object'):[];if(!list.length)return;
 const line=el('p','corpus-found footnote',null,parent);
 line.append(list.slice(0,3).map(f=>'Found by '+(str(f.member)||'an agent')+' ('+(TOOL[f.tool]||'research')+(f.query?' “'+str(f.query)+'”':'')+')').join('; ')+(list.length>3?'; and '+plural(list.length-3,'more time')+'.':'.'));
}
function referenceText(r){
 const a=Array.isArray(r?.authors)?r.authors.filter(x=>typeof x==='string'):[];
 const lead=[a.length>3?a.slice(0,3).join(', ')+' et al.':a.join(', '),Number.isInteger(r?.year)?'('+r.year+')':''].filter(Boolean).join(' ');
 const bits=[lead,str(r?.title)||str(r?.raw)].filter(Boolean).map(x=>/[.?!]$/.test(x)?x:x+'.');
 if(r?.doi)bits.push('doi:'+str(r.doi));if(r?.arxiv_id)bits.push('arXiv:'+str(r.arxiv_id));
 return bits.join(' ')||'Reference';
}
function unverifiedSection(parent,list){
 if(!list.length)return;
 const box=el('section','corpus-unverified',null,parent);box.setAttribute('aria-labelledby','corpus-unverified-title');
 el('h3','','References not verified ('+count(list.length)+')',box).id='corpus-unverified-title';
 el('p','footnote','Cited by the agents but not confirmed by the citation checker. Check these before you rely on them.',box);
 const ol=el('ol','reference-list',null,box);
 for(const u of list){
  const cls={mismatch:'mismatch',not_found:'not-found',unchecked:'unchecked'}[u.status]||'unknown';
  const li=el('li','reference '+cls,null,ol);
  const head=el('p','reference-status',null,li);el('strong','',OPEN[u.status]||'Not verified',head);
  const f=(Array.isArray(u.fields)?u.fields:[]).filter(x=>typeof x==='string').map(x=>FIELD[x]||x);
  if(u.status==='mismatch'&&f.length)head.append(' in '+f.join(', '));
  if(u.status==='unchecked'&&u.reason)head.append(': '+str(u.reason));
  el('p','reference-input',referenceText(u.reference),li);
  if(u.closest&&typeof u.closest==='object'){const line=el('p','footnote reference-match',null,li);line.append('Closest record: ');const name=str(u.closest.title)||'Untitled';if(!R.link(u.closest.url,name,line))line.append(name);line.append('. '+referenceText({authors:u.closest.authors,year:u.closest.year,doi:u.closest.doi}).replace(/^Reference$/,''));}
 }
}

function render(container,data,ui,{refresh,loading,error}){
 const keep=document.activeElement&&container.contains(document.activeElement)?{id:document.activeElement.id,start:document.activeElement.selectionStart}:null;
 container.replaceChildren();
 el('h2','visually-hidden','Corpus',container);
 if(error){el('p','error-text',error,container).setAttribute('role','alert');}
 if(!data){el('p','muted',loading?'Loading the corpus…':'The corpus is not loaded yet.',container);return;}
 const papers=papersOf(data),unverified=unverifiedOf(data),verified=papers.filter(p=>checked(p)==='verified').length;
 const summary=el('p','corpus-summary',null,container);
 summary.textContent=plural(papers.length,'paper')+' · '+count(verified)+' verified'+(unverified.length?' · '+plural(unverified.length,'reference')+' not verified':'');
 if(data.incomplete>0)el('p','notice','Some earlier results could not be read, so this list may be incomplete.',container);
 if(data.full)el('p','notice','This task found more papers than the corpus keeps. Later papers are not listed.',container);
 unverifiedSection(container,unverified);
 if(!papers.length){el('p','empty muted','No papers yet. Papers appear here as agents search.',container);return;}

 const tools=el('div','corpus-tools',null,container);
 const sl=el('label','corpus-search',null,tools);el('span','visually-hidden','Search the corpus',sl);
 const input=el('input',null,null,sl);input.type='search';input.id='corpus-search';input.placeholder='Search titles, authors and venues';input.value=ui.q||'';input.autocomplete='off';
 input.oninput=()=>{ui.q=input.value;ui.all=false;refresh();};
 const so=el('label','corpus-sort',null,tools);so.append('Sort ');const sel=el('select',null,null,so);sel.id='corpus-sort';
 for(const [v,t] of SORTS){const o=el('option',null,t,sel);o.value=v;}sel.value=ui.sort||'found';sel.onchange=()=>{ui.sort=sel.value;refresh();};
 const group=el('div','corpus-filters',null,container);group.setAttribute('role','group');group.setAttribute('aria-label','Show');
 for(const [k,t] of FILTERS){const b=el('button','',t+' '+count(papers.filter(test[k]).length),group);b.type='button';b.id='corpus-filter-'+k;b.setAttribute('aria-pressed',String((ui.filter||'all')===k));b.onclick=()=>{ui.filter=k;ui.all=false;refresh();};}

 const q=str(ui.q).trim().toLowerCase();
 const shown=sorted(papers.filter(p=>test[ui.filter||'all'](p)&&matches(p,q)),ui.sort||'found');
 const live=el('p','footnote corpus-count',(shown.length===papers.length?'Showing all ':'Showing '+count(shown.length)+' of ')+plural(papers.length,'paper'),container);live.setAttribute('role','status');
 if(!shown.length){el('p','empty muted','No papers match. Clear the search or choose All.',container);}
 const ol=el('ol','paper-list corpus-list',null,container);ol.setAttribute('aria-label','Papers');
 for(const p of shown.slice(0,ui.all?shown.length:SHOWN)){
  const li=RC.paper(p.paper,ol,{abstract:true}),v=checked(p);
  li.classList.add('corpus-paper',v?'is-'+v:'is-unchecked');
  el('span','paper-verdict',v?VERDICT[v]:'Not checked',li.querySelector('.paper-title'));
  provenance(p.found,li);
 }
 if(shown.length>SHOWN){const b=el('button','link-button',ui.all?'Show fewer':'Show all '+plural(shown.length,'paper'),container);b.type='button';b.id='corpus-more';b.setAttribute('aria-expanded',String(!!ui.all));b.onclick=()=>{ui.all=!ui.all;refresh();};}
 if(keep?.id){const again=document.getElementById(keep.id);if(again){again.focus();if(keep.start!=null&&again.setSelectionRange)try{again.setSelectionRange(keep.start,keep.start);}catch{}}}
}

window.interspaceCorpus={render};
})();
