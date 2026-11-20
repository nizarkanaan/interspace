/* Evidence tab (docs/superpowers/specs/2026-11-20-evidence-table-design.md): choose columns, have Claude and Codex fill
   the table independently, then see where they agree, where they disagree and which numbers to check. Values and
   quotes come from agents and papers and are set as text. Status is said in words; colour only repeats it. */
(()=>{
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
const NAMES={claude:'Claude',codex:'Codex'};
const name=p=>NAMES[p]||p;
const DEFAULT_ON=['design','sample','setting','finding'];
const WORD={agree:'Agree',check:'Agree, check the number',disagree:'Disagree',not_reported:'Not reported',waiting:'Waiting',resolved:'Your choice',one_source:'One source'};

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

function cell(td,c,col,row,onResolve,ui){
 const s=c.status;td.className='ev-cell is-'+s;td.dataset.cell=row.id+':'+col.id;
 const providers=Object.keys(c.values||{});
 const word=el('span','ev-word',WORD[s]||s,td);
 if(s==='waiting'){if(providers.length)word.textContent='Waiting for '+(providers.includes('claude')?'Codex':'Claude');return;}
 if(s==='resolved'){el('span','ev-value',c.resolved.value,td);const u=el('button','link-button','Undo',td);u.type='button';u.onclick=()=>onResolve(row.id,col.id,null);return;}
 if(s!=='disagree'){
  const v=c.values[providers[0]];el('span','ev-value',v?.value||'',td);
  if(v?.quote){const d=el('details','ev-quote',null,td);el('summary','','Quote',d);for(const p of providers)if(c.values[p].quote)el('blockquote','',name(p)+': “'+c.values[p].quote+'”',d);}
  return;
 }
 for(const p of providers){
  const box=el('div','ev-option',null,td);el('span','ev-who',name(p),box);el('span','ev-value',c.values[p].value,box);
  if(c.values[p].quote)el('blockquote','ev-quote-line','“'+c.values[p].quote+'”',box);
  const use=el('button','','Use '+name(p)+'’s',box);use.type='button';use.onclick=()=>onResolve(row.id,col.id,c.values[p].value);
 }
 const key=row.id+':'+col.id;
 if(ui.typing===key){
  const input=el('input',null,null,td);input.id='ev-own-'+key.replace(/[^A-Za-z0-9_-]/g,'_');input.maxLength=300;input.setAttribute('aria-label','Your value for '+col.name);
  const save=el('button','primary','Save',td);save.type='button';save.onclick=()=>{if(input.value.trim()){ui.typing=null;onResolve(row.id,col.id,input.value);}};
  const cancel=el('button','quiet','Cancel',td);cancel.type='button';cancel.onclick=()=>{ui.typing=null;ui.rerender();};
  requestAnimationFrame(()=>input.focus());
 }else{const own=el('button','quiet','Type my own',td);own.type='button';own.onclick=()=>{ui.typing=key;ui.rerender();};}
}

function render(container,data,ui,{busy,canFill,error,note,onFill,onResolve,onExport}){
 ui.rerender=()=>render(container,data,ui,{busy,canFill,error,note,onFill,onResolve,onExport});
 const keep=document.activeElement&&container.contains(document.activeElement)?document.activeElement.id:null;
 container.replaceChildren();
 el('h2','visually-hidden','Evidence table',container);
 if(error)el('p','error-text',error,container).setAttribute('role','alert');
 if(note)el('p','footnote',note,container).setAttribute('role','status');
 if(!data){el('p','muted','Loading the evidence table…',container);return;}
 const table=data.table;
 if(!table||ui.editing){picker(container,data,ui,{busy,canFill,onFill,onCancel:table?()=>{ui.editing=false;ui.rerender();}:null});return;}
 const c=table.counts||{};
 const bar=el('div','reader-bar',null,container);
 const sum=el('p','claim-summary',null,bar);sum.setAttribute('role','status');
 sum.textContent=c.cells+' cells: '+[[c.agree+c.check,'agree'+(c.check?' ('+c.check+' number'+(c.check===1?'':'s')+' to check)':'')],[c.disagree,'disagree'],[c.resolved,'decided by you'],[c.not_reported,'not reported'],[c.waiting,'waiting'],[c.one_source,'from one source']].filter(([n])=>n).map(([n,w])=>n+' '+w).join(', ')+'.';
 const acts=el('span','reader-actions',null,bar);
 const f=el('button','',ui.needs?'Show all cells':'Needs you',acts);f.type='button';f.id='ev-filter';f.setAttribute('aria-pressed',String(!!ui.needs));f.onclick=()=>{ui.needs=!ui.needs;ui.rerender();};
 const x=el('button','','Export CSV',acts);x.type='button';x.id='ev-export';x.onclick=onExport;
 // Inline confirmation: native confirm() dialogs do not show in the app's web view.
 if(ui.confirmNew){el('span','footnote','Replace the current table?',acts);const y=el('button','danger','Start a new table',acts);y.type='button';y.id='ev-new-yes';y.onclick=()=>{ui.confirmNew=false;ui.editing=true;ui.rerender();};const no=el('button','quiet','Keep it',acts);no.type='button';no.id='ev-new-no';no.onclick=()=>{ui.confirmNew=false;ui.rerender();};}
 else{const n=el('button','quiet','Start a new table',acts);n.type='button';n.id='ev-new';n.onclick=()=>{ui.confirmNew=true;ui.rerender();};}
 const wrap=el('div','ev-wrap',null,container);wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Evidence table, scrolls sideways');
 const t=el('table','ev-table',null,wrap);
 const head=el('tr','',null,el('thead','',null,t));el('th','','Paper',head).scope='col';for(const col of table.columns){const th=el('th','',col.name,head);th.scope='col';th.title=col.instruction;}
 const body=el('tbody','',null,t);
 let shown=0;
 for(const row of table.rows){
  if(ui.needs&&!table.columns.some(col=>['disagree','check'].includes(row.cells[col.id].status)))continue;shown++;
  const tr=el('tr','',null,body);
  const th=el('th','',null,tr);th.scope='row';el('span','ev-paper',row.paper.title||'Untitled',th);if(row.paper.year)el('span','footnote',' ('+row.paper.year+')',th);
  if(row.source_kind)el('span','ev-source footnote',row.source_kind==='full text'?'Full text':'Abstract only',th);
  for(const col of table.columns)cell(el('td','',null,tr),row.cells[col.id],col,row,onResolve,ui);
 }
 if(!shown)el('p','empty muted',ui.needs?'Nothing needs you: every cell agrees or is decided.':'No rows.',container);
 if(keep){const again=document.getElementById(keep);if(again)again.focus();}
}

window.interspaceEvidence={render};
})();
