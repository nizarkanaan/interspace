/* Conversation display (docs/superpowers/specs/2026-11-20-details-panel-and-display-design.md): what the conversation
   shows. It comes from `state.display` and is changed with `display_update`. Every event is still recorded; your
   messages, agent replies, questions for you, team cards, subagents and errors always show. */
(()=>{
const DEFAULT={v:1,thinking:'summary',searches:'summary',tools:true,citations:true,plans:true,notes:true,detail:'simple'};
const DETAIL=[['simple','Simple'],['detailed','Detailed']];
const LEVEL=[['summary','Summary'],['full','Full'],['hidden','Hidden']];
const LEVELS=[
 ['thinking','Thinking','Summary shows the start of each reasoning note; you can open the rest.'],
 ['searches','Paper searches','Summary shows one line per search. Every paper is listed in the Corpus tab.']];
const SWITCHES=[['tools','Commands and file changes'],['citations','Citation reports'],['plans','Plans'],['notes','Status notes (scope, token and status lines)']];
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
let current={...DEFAULT},saving=false,note='',failure='',request=null,onChange=()=>{};

function valid(d){
 if(!d||typeof d!=='object')return {...DEFAULT};
 const out={...DEFAULT};
 for(const k of ['thinking','searches'])if(LEVEL.some(([v])=>v===d[k]))out[k]=d[k];
 if(DETAIL.some(([v])=>v===d.detail))out.detail=d.detail;
 for(const [k] of SWITCHES)if(typeof d[k]==='boolean')out[k]=d[k];
 return out;
}
function set(next){const v=valid(next);if(JSON.stringify(v)!==JSON.stringify(current)&&!saving){current=v;onChange();}}
function save(patch,container){
 const before=current;current={...current,...patch};saving=true;note='';failure='';onChange();renderSettings(container);
 request('display_update',{display:current},{manual:true}).then(r=>{current=valid(r);note='Saved.';})
  .catch(e=>{current=before;failure=e.message||'The display settings were not saved.';})
  .finally(()=>{saving=false;onChange();renderSettings(container);});
}
function renderSettings(container){
 if(!container)return;
 const keep=document.activeElement&&container.contains(document.activeElement)?document.activeElement.id:null;
 container.replaceChildren();
 el('h2','','Conversation display',container);
 el('p','footnote','Choose what the conversation shows. Everything is still recorded. Your messages, agent replies, questions for you, team proposals and errors always show.',container);
 const form=el('form','display-form',null,container);form.onsubmit=e=>e.preventDefault();
 {
  const fs=el('fieldset','display-choice',null,form);el('legend','','Conversation detail',fs);
  const row=el('div','display-options',null,fs);
  for(const [value,text] of DETAIL){
   const l=el('label','display-option',null,row),input=el('input',null,null,l);input.type='radio';input.name='display-detail';input.value=value;input.id='display-detail-'+value;
   input.checked=current.detail===value;input.onchange=()=>save({detail:value},container);l.append(' '+text);
  }
  el('p','footnote','Simple shows your messages, the replies and anything that needs you; each turn\'s agent work folds into one line you can open. Detailed shows every step.',fs);
 }
 for(const [key,label,help] of LEVELS){
  const fs=el('fieldset','display-choice',null,form);el('legend','',label,fs);
  const row=el('div','display-options',null,fs);
  for(const [value,text] of LEVEL){
   const l=el('label','display-option',null,row),input=el('input',null,null,l);input.type='radio';input.name='display-'+key;input.value=value;input.id='display-'+key+'-'+value;
   input.checked=current[key]===value;input.onchange=()=>save({[key]:value},container);l.append(' '+text);
  }
  el('p','footnote',help,fs);
 }
 const fs=el('fieldset','display-choice',null,form);el('legend','','Also show',fs);
 for(const [key,text] of SWITCHES){
  const l=el('label','display-option',null,fs),input=el('input',null,null,l);input.type='checkbox';input.id='display-'+key;
  input.checked=!!current[key];input.onchange=()=>save({[key]:input.checked},container);l.append(' '+text);
 }
 const status=el('p','footnote display-status',saving?'Saving…':note,container);status.setAttribute('role','status');
 if(failure)el('p','error-text',failure,container).setAttribute('role','alert');
 if(keep){const again=document.getElementById(keep);if(again&&!again.disabled)again.focus();}
}

window.interspaceDisplay={
 init(options){request=options.request;onChange=options.changed||onChange;},
 get:()=>current,set,setDetail(value){if(DETAIL.some(([v])=>v===value))save({detail:value},document.getElementById('display-settings'));},renderSettings,DEFAULT
};
})();
