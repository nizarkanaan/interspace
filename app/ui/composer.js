/* Keyboard-first composer: Enter sends, Shift+Enter adds a line, "/" opens commands, "@" opens mentions.
   The menu is an ARIA combobox listbox; suggestions are inserted as plain text. */
(()=>{
const MAX_SUGGESTIONS=8;
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};

// commands(): [{name, hint, run}]; mentions(): [{value, hint}]; onSend(text); onInput(text).
function attach({input,menu,form,commands,mentions,onSend,onInput}){
 let items=[],active=0,token=null;
 input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls',menu.id);input.setAttribute('aria-expanded','false');
 menu.setAttribute('role','listbox');menu.hidden=true;
 const close=()=>{items=[];token=null;menu.hidden=true;menu.replaceChildren();input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');};
 const draw=()=>{
  menu.replaceChildren();
  items.forEach((x,i)=>{const li=el('li','',null,menu);li.id=menu.id+'-'+i;li.setAttribute('role','option');li.setAttribute('aria-selected',String(i===active));el('span','mono',x.label,li);if(x.hint)el('span','footnote',x.hint,li);li.onmousedown=e=>{e.preventDefault();active=i;choose();};});
  menu.hidden=!items.length;input.setAttribute('aria-expanded',String(!!items.length));
  if(items.length)input.setAttribute('aria-activedescendant',menu.id+'-'+active);else input.removeAttribute('aria-activedescendant');
 };
 // Finds the "/command" at the start or the "@mention" that ends at the caret.
 const update=()=>{
  const caret=input.selectionStart??input.value.length,before=input.value.slice(0,caret);
  const slash=/^\/(\S*)$/.exec(before),at=/(^|\s)@([^\s@]*)$/.exec(before);
  if(slash){const q=slash[1].toLowerCase();token={kind:'command',start:0,end:caret};items=commands().filter(c=>c.name.startsWith(q)).map(c=>({label:'/'+c.name,hint:c.hint,command:c}));}
  else if(at){const q=at[2].toLowerCase();token={kind:'mention',start:caret-at[2].length-1,end:caret};const seen=new Set();items=mentions().filter(m=>!seen.has(m.value)&&seen.add(m.value)&&(m.value.toLowerCase().includes(q)||String(m.hint||'').toLowerCase().includes(q))).slice(0,MAX_SUGGESTIONS).map(m=>({label:m.value,hint:m.hint,value:m.value}));}
  else{close();return;}
  active=Math.min(active,Math.max(0,items.length-1));draw();
 };
 const choose=()=>{
  const x=items[active];if(!x||!token)return;
  if(x.command){input.value='';onInput('');close();x.command.run();return;}
  const text='@'+x.value+' ',v=input.value;input.value=v.slice(0,token.start)+text+v.slice(token.end);
  const caret=token.start+text.length;input.setSelectionRange(caret,caret);onInput(input.value);close();input.focus();
 };
 input.addEventListener('input',()=>{active=0;onInput(input.value);update();});
 input.addEventListener('click',update);
 input.addEventListener('blur',()=>setTimeout(()=>{if(document.activeElement!==input)close();},0));
 input.addEventListener('keydown',e=>{
  if(e.isComposing)return;
  if(items.length){
   if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();active=(active+(e.key==='ArrowDown'?1:items.length-1))%items.length;draw();return;}
   if(e.key==='Enter'&&!e.shiftKey||e.key==='Tab'&&!e.shiftKey){e.preventDefault();choose();return;}
   if(e.key==='Escape'){e.preventDefault();close();return;}
  }
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}
 });
 form.addEventListener('submit',e=>{e.preventDefault();const raw=input.value;if(!raw.trim())return;if(raw.trim().startsWith('/')){const name=raw.trim().slice(1).split(/\s/)[0],c=commands().find(c=>c.name===name);if(c){input.value='';onInput('');close();c.run();return;}}onSend(raw);});
 return {close};
}
window.interspaceComposer={attach};
})();
