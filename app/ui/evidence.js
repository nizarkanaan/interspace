/* Evidence tab (docs/superpowers/specs/2026-11-20-evidence-table-design.md): choose columns, have Claude and Codex fill
   the table independently, then see where they agree, where they disagree and which numbers to check. Values and
   quotes come from agents and papers and are set as text. Status is said in words; colour only repeats it.
   Compact table (2026-11-27-readable-workspace-design.md): a cell holds its status word and value, and opens a drawer
   beside the table with the paper, the column, each value with its quote and, for a disagreement, the choice. */
(()=>{
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const NAMES={claude:'Claude',codex:'Codex'};
const name=p=>NAMES[p]||p;
// Claude first, then Codex, then any other provider in the order it came.
const ORDER=['claude','codex'];
const ordered=list=>[...list].sort((a,b)=>(ORDER.indexOf(a)+1||ORDER.length+1)-(ORDER.indexOf(b)+1||ORDER.length+1));
const DEFAULT_ON=['design','sample','setting','finding'];
// A cell's word is short; the drawer says it in full.
const WORD={agree:'Agree',check:'Check',disagree:'Disagree',not_reported:'Not reported',waiting:'Waiting',resolved:'Decided',one_source:'One source'};
const FULL={...WORD,check:'Agree, check the number',resolved:'Decided by you'};
// A waiting cell with one value names the provider still to come.
const waitWord=providers=>providers.length?'Waiting for '+(providers.includes('claude')?'Codex':'Claude'):WORD.waiting;

// A short paper label: the first author's surname (the last word, or the text before a comma), "& Surname" for a
// second author or "et al." for more, then the year. Without usable authors it is the title, which the table clamps.
const surname=a=>{const s=a.trim(),i=s.indexOf(',');return (i>0?s.slice(0,i).trim():'')||s.split(/\s+/).pop();};
function paperLabel(paper){
 const p=paper&&typeof paper==='object'?paper:{};
 const names=Array.isArray(p.authors)?p.authors.filter(a=>typeof a==='string'&&a.trim()).map(surname):[];
 if(!names.length)return {label:String(p.title??'').trim()||'Untitled',clamp:true};
 const year=p.year!=null&&String(p.year).trim()?' '+String(p.year).trim():'';
 return {label:(names.length===1?names[0]:names.length===2?names[0]+' & '+names[1]:names[0]+' et al.')+year,clamp:false};
}

function picker(container,data,ui,{busy,canFill,onFill,onCancel}){
 const presets=data?.presets||[];
 if(!ui.chosen)ui.chosen=new Set(DEFAULT_ON.filter(id=>presets.some(p=>p.id===id)));  // Only once the presets have loaded.
 if(!ui.custom)ui.custom=[];if(!ui.rows)ui.rows='cited';
 const form=el('form','evidence-picker',null,container);form.onsubmit=e=>e.preventDefault();
 el('p','footnote','Claude and Codex each fill the table on their own. Cells where they agree are usually right; where they disagree, you decide.',form);
 const cols=el('fieldset','evidence-choice',null,form);el('legend','','Columns',cols);
 for(const p of presets){const l=el('label','display-option',null,cols),c=el('input',null,null,l);c.type='checkbox';c.id='ev-col-'+p.id;c.checked=ui.chosen.has(p.id);c.onchange=()=>{c.checked?ui.chosen.add(p.id):ui.chosen.delete(p.id);};l.append(' '+p.name);el('span','footnote',' '+p.instruction,l);}
 ui.custom.forEach((c,i)=>{
  const row=el('div','evidence-custom',null,cols);
  const n=el('input',null,null,row);n.placeholder='Column name';n.value=c.name;n.maxLength=60;n.setAttribute('aria-label','Column '+(i+1)+' name');n.oninput=()=>{c.name=n.value;};
  const t=el('input',null,null,row);t.placeholder='What to extract, in one sentence';t.value=c.instruction;t.maxLength=300;t.setAttribute('aria-label','Column '+(i+1)+' instruction');t.oninput=()=>{c.instruction=t.value;};
  const l=el('label','display-option',null,row),k=el('input',null,null,l);k.type='checkbox';k.checked=!!c.numeric;k.onchange=()=>{c.numeric=k.checked;};l.append(' Number');
  const x=el('button','quiet','Remove',row);x.type='button';x.onclick=()=>{ui.custom.splice(i,1);ui.rerender();};
 });
 const add=el('button','link-button','Add a column',cols);add.type='button';add.id='ev-add';add.onclick=()=>{ui.custom.push({name:'',instruction:'',numeric:false});ui.rerender();};
 const rows=el('fieldset','evidence-choice',null,form);el('legend','','Rows',rows);
 for(const [v,t] of [['cited','Papers cited in the report'],['checked','Every paper the citation checker confirmed (up to 50)']]){const l=el('label','display-option',null,rows),r=el('input',null,null,l);r.type='radio';r.name='ev-rows';r.value=v;r.checked=ui.rows===v;r.onchange=()=>{ui.rows=v;};l.append(' '+t);}
 const acts=el('div','actions',null,form);
 const fill=el('button','primary',busy?'Starting…':'Fill table',acts);fill.type='button';fill.id='ev-fill';fill.disabled=!!busy||!canFill;
 fill.onclick=()=>{const columns=[...presets.filter(p=>ui.chosen.has(p.id)),...ui.custom.filter(c=>c.name.trim()&&c.instruction.trim())];onFill(columns,ui.rows);};
 if(onCancel){const c=el('button','quiet','Cancel',acts);c.type='button';c.onclick=onCancel;}
 if(!canFill)el('p','footnote','Wait for the agent to finish, then fill the table.',form);
}

function cell(td,c,col,row,ui){
 const s=c.status,key=row.id+':'+col.id;
 td.className='ev-cell is-'+s+(ui.drawer===key?' is-open':'');td.dataset.cell=key;td.tabIndex=0;
 const providers=ordered(Object.keys(c.values||{}));
 const word=el('span','ev-word',WORD[s]||s,td);
 if(s==='waiting'){word.textContent=waitWord(providers);return;}
 if(s==='resolved'){el('span','ev-value',c.resolved?.value??'',td);return;}
 if(s==='disagree'){for(const p of providers)el('span','ev-pair',name(p)+': '+(c.values[p]?.value??''),td);return;}
 el('span','ev-value',c.values[providers[0]]?.value||'',td);
}

// The drawer for the cell `ui.drawer` ("rowId:colId"), found again on every render so it follows live data. It closes
// when the row or the column is gone.
function drawer(parent,table,ui,{onResolve,shut}){
 const key=ui.drawer,row=table.rows.find(r=>table.columns.some(col=>r.id+':'+col.id===key));
 const col=row&&table.columns.find(x=>row.id+':'+x.id===key),c=col&&row.cells?.[col.id];
 if(!c){ui.drawer=null;ui.typing=null;return null;}
 const s=c.status,providers=ordered(Object.keys(c.values||{}));
 const d=el('aside','ev-drawer is-'+s,null,parent);d.id='ev-drawer';d.tabIndex=-1;d.dataset.for=key;d.setAttribute('role','region');d.setAttribute('aria-label','Cell details');
 const head=el('div','ev-drawer-head',null,d);
 el('h3','ev-drawer-title',row.paper?.title||'Untitled',head);
 const x=el('button','ev-drawer-close','×',head);x.type='button';x.id='ev-drawer-close';x.setAttribute('aria-label','Close cell details');x.onclick=shut;
 const meta=[row.paper?.year,row.source_kind?(row.source_kind==='full text'?'Full text':'Abstract only'):''].filter(v=>v!=null&&v!=='').join(' · ');
 if(meta)el('p','footnote',meta,d);
 const about=el('p','ev-drawer-col',null,d);el('strong','',col.name,about);if(col.instruction)el('span','footnote',col.instruction,about);
 el('p','ev-word',s==='waiting'?waitWord(providers):FULL[s]||s,d);
 for(const p of providers){const v=c.values[p],box=el('div','ev-option',null,d);el('span','ev-who',name(p),box);el('span','ev-value',v?.value??'',box);if(v?.quote)el('blockquote','ev-quote-line','“'+v.quote+'”',box);}
 if(s==='resolved'){
  const box=el('div','ev-option',null,d);el('span','ev-who','Your value',box);el('span','ev-value',c.resolved?.value??'',box);
  const u=el('button','link-button','Undo',box);u.type='button';u.id='ev-undo';u.onclick=()=>onResolve(row.id,col.id,null);
 }
 if(s!=='disagree')return d;
 const acts=el('div','ev-drawer-actions',null,d);
 for(const p of providers){const use=el('button','','Use '+name(p)+'’s',acts);use.type='button';use.id='ev-use-'+p.replace(/[^A-Za-z0-9_-]/g,'_');use.onclick=()=>onResolve(row.id,col.id,c.values[p].value);}
 if(ui.typing!==key){const own=el('button','quiet','Type my own',acts);own.type='button';own.id='ev-own';own.onclick=()=>{ui.typing=key;ui.draft='';ui.focusOwn=true;ui.rerender();};return d;}
 // What is typed survives a re-render from a pushed update.
 const form=el('div','ev-own',null,d);
 const input=el('input',null,null,form);input.id='ev-own-value';input.maxLength=300;input.value=ui.draft||'';input.setAttribute('aria-label','Your value for '+col.name);input.oninput=()=>{ui.draft=input.value;};
 const save=()=>{if(input.value.trim()){ui.typing=null;ui.draft='';onResolve(row.id,col.id,input.value);}};
 // Cancel, or Esc in the field, stops typing and goes back to Type my own; the drawer stays open.
 const cancel=()=>{ui.typing=null;ui.draft='';ui.rerender();document.getElementById('ev-own')?.focus();};
 input.onkeydown=e=>{
  if(e.isComposing)return;
  if(e.key==='Enter'){e.preventDefault();save();}
  // Handled here, so the window's Esc (agent.js) does not also close the drawer.
  else if(e.key==='Escape'){e.preventDefault();cancel();}
 };
 const ok=el('button','primary','Save',form);ok.type='button';ok.id='ev-own-save';ok.onclick=save;
 const no=el('button','quiet','Cancel',form);no.type='button';no.id='ev-own-cancel';no.onclick=cancel;
 if(ui.focusOwn){ui.focusOwn=false;requestAnimationFrame(()=>input.focus());}
 return d;
}
const cellIn=(container,key)=>[...container.querySelectorAll('td[data-cell]')].find(td=>td.dataset.cell===key)||null;
// Closing puts keyboard focus back on the cell when it was in the drawer.
function close(container,ui){
 const key=ui.drawer,back=!!container.querySelector('#ev-drawer')?.contains(document.activeElement);
 ui.drawer=null;ui.typing=null;ui.draft='';ui.rerender();
 if(back)cellIn(container,key)?.focus();
}
// The evidence area last rendered; Esc (agent.js) asks it to close a drawer that is on screen before leaving Focus.
let live=null;
function closeDrawer(){
 const d=live?.container.querySelector('#ev-drawer');
 if(!d||!live.ui.drawer||!d.getClientRects().length)return false;
 close(live.container,live.ui);return true;
}

function render(container,data,ui,{busy,canFill,error,note,onFill,onResolve,onExport}){
 ui.rerender=()=>render(container,data,ui,{busy,canFill,error,note,onFill,onResolve,onExport});
 live={container,ui};
 // Keyboard focus, the table's scroll and the drawer's scroll survive the rebuild.
 const active=document.activeElement,mine=!!active&&container.contains(active);
 const keep=mine?active.id:null,keepCell=mine&&active.matches('td[data-cell]')?active.dataset.cell:null;
 const oldWrap=container.querySelector('.ev-wrap'),oldDrawer=container.querySelector('#ev-drawer'),inDrawer=mine&&!!oldDrawer?.contains(active);
 const scroll=oldWrap?[oldWrap.scrollLeft,oldWrap.scrollTop]:null,drawerScroll=oldDrawer?[oldDrawer.dataset.for,oldDrawer.scrollTop]:null;
 container.replaceChildren();container.classList.remove('has-table');
 el('h2','visually-hidden','Evidence table',container);
 if(error)el('p','error-text',error,container).setAttribute('role','alert');
 if(note)el('p','footnote',note,container).setAttribute('role','status');
 if(!data){el('p','muted','Loading the evidence table…',container);return;}
 const table=data.table;
 if(!table||ui.editing){picker(container,data,ui,{busy,canFill,onFill,onCancel:table?()=>{ui.editing=false;ui.rerender();}:null});return;}
 container.classList.add('has-table');
 const c=table.counts||{};
 const bar=el('div','reader-bar',null,container);
 const sum=el('p','claim-summary',null,bar);sum.setAttribute('role','status');
 sum.textContent=c.cells+' cells: '+[[c.agree+c.check,'agree'+(c.check?' ('+c.check+' number'+(c.check===1?'':'s')+' to check)':'')],[c.disagree,'disagree'],[c.resolved,'decided by you'],[c.not_reported,'not reported'],[c.waiting,'waiting'],[c.one_source,'from one source']].filter(([n])=>n).map(([n,w])=>n+' '+w).join(', ')+'.';
 const acts=el('span','reader-actions',null,bar);
 const f=el('button','',ui.needs?'Show all cells':'Needs you',acts);f.type='button';f.id='ev-filter';f.setAttribute('aria-pressed',String(!!ui.needs));f.onclick=()=>{ui.needs=!ui.needs;ui.rerender();};
 const x=el('button','','Export CSV',acts);x.type='button';x.id='ev-export';x.onclick=onExport;
 // Inline confirmation: native confirm() dialogs do not show in the app's web view.
 if(ui.confirmNew){el('span','footnote','Replace the current table?',acts);const y=el('button','danger','Start a new table',acts);y.type='button';y.id='ev-new-yes';y.onclick=()=>{ui.confirmNew=false;ui.editing=true;ui.drawer=null;ui.typing=null;ui.rerender();};const no=el('button','quiet','Keep it',acts);no.type='button';no.id='ev-new-no';no.onclick=()=>{ui.confirmNew=false;ui.rerender();};}
 else{const n=el('button','quiet','Start a new table',acts);n.type='button';n.id='ev-new';n.onclick=()=>{ui.confirmNew=true;ui.rerender();};}
 const area=el('div','ev-body',null,container);
 const wrap=el('div','ev-wrap',null,area);wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Evidence table, scrolls sideways. Enter on a cell shows its details.');
 const t=el('table','ev-table',null,wrap);
 const head=el('tr','',null,el('thead','',null,t));el('th','','Paper',head).scope='col';for(const col of table.columns){const th=el('th','',col.name,head);th.scope='col';th.title=col.instruction;}
 const body=el('tbody','',null,t);
 let shown=0;
 for(const row of table.rows){
  if(ui.needs&&!table.columns.some(col=>['disagree','check'].includes(row.cells[col.id].status)))continue;shown++;
  const tr=el('tr','',null,body);
  const th=el('th','',null,tr);th.scope='row';if(row.paper?.title)th.title=row.paper.title;
  const label=paperLabel(row.paper);el('span','ev-paper'+(label.clamp?' is-clamped':''),label.label,th);
  const meta=[label.clamp?row.paper?.year:null,row.source_kind?(row.source_kind==='full text'?'Full text':'Abstract only'):null].filter(v=>v!=null&&v!=='').join(' · ');
  if(meta)el('span','ev-source footnote',meta,th);
  for(const col of table.columns)cell(el('td','',null,tr),row.cells[col.id],col,row,ui);
 }
 // A cell opens its drawer by click or Enter; Enter also moves into it. Arrow keys move between cells.
 const open=(key,keyboard)=>{
  if(ui.drawer!==key){ui.drawer=key;ui.typing=null;ui.draft='';ui.rerender();}
  const d=container.querySelector('#ev-drawer');if(!d)return;
  if(keyboard)d.focus();else d.scrollIntoView({block:'nearest'});
 };
 t.onclick=e=>{const td=e.target.closest('td[data-cell]');if(td)open(td.dataset.cell,false);};
 t.onkeydown=e=>{
  const td=e.target;if(!td.matches('td[data-cell]'))return;
  if(e.key==='Enter'){e.preventDefault();open(td.dataset.cell,true);return;}
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)||e.altKey||e.ctrlKey||e.metaKey||e.shiftKey)return;
  e.preventDefault();
  const i=td.cellIndex,tr=td.parentElement;
  const next=e.key==='ArrowLeft'?td.previousElementSibling:e.key==='ArrowRight'?td.nextElementSibling:(e.key==='ArrowUp'?tr.previousElementSibling:tr.nextElementSibling)?.cells[i];
  if(next?.matches('td[data-cell]'))next.focus();
 };
 const d=ui.drawer?drawer(area,table,ui,{onResolve,shut:()=>close(container,ui)}):null;
 if(!shown)area.before(el('p','empty muted',ui.needs?'Nothing needs you: every cell agrees or is decided.':'No rows.'));
 if(scroll){wrap.scrollLeft=scroll[0];wrap.scrollTop=scroll[1];}
 if(d&&drawerScroll&&drawerScroll[0]===d.dataset.for)d.scrollTop=drawerScroll[1];
 if(keepCell)cellIn(container,keepCell)?.focus({preventScroll:true});
 else if(keep){const again=document.getElementById(keep);if(again)again.focus();}
 // The drawer button that was used (Use, Undo, Save) can be gone after the update: keyboard focus stays in the drawer,
 // on Undo, the first choice or the drawer itself, or goes back to the cell when the drawer has closed.
 if(inDrawer&&!container.contains(document.activeElement)){
  const next=d?d.querySelector('#ev-undo')||d.querySelector('.ev-drawer-actions button')||d:cellIn(container,drawerScroll[0])||wrap;
  next.focus({preventScroll:true});
 }
}

window.interspaceEvidence={render,paperLabel,closeDrawer};
})();
