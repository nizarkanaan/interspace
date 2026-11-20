/* Research sources (docs/superpowers/specs/research/credentials.md): Settings → Research sources, and source names for
   the scope editor and research cards. Modelled on providers.js. Keys and emails are write-only: an input is never
   pre-filled, is cleared as soon as its value is sent, and nothing the backend returns is ever shown as a key.
   Every title, detail and URL from the backend is inserted with textContent; a help link is shown only for https. */
(()=>{
// Names of the first sources, for labels before research_sources answers. Everything else comes from the backend.
const KNOWN={semantic_scholar:'Semantic Scholar',openalex:'OpenAlex',arxiv:'arXiv',crossref:'Crossref',unpaywall:'Unpaywall',fulltext:'Open-access full text'};
const STATE={ready:'Ready',needs_key:'Needs your key or email',error:'Test failed',unchecked:'Not tested yet',credential_store_unavailable:'Keychain not available'};
const KIND={api_key:'API key',email:'email address'};
const KEY_RE=/^[\x21-\x7e]{8,256}$/,EMAIL_RE=/^[^\s@<>()",;:\\]+@[^\s@<>()",;:\\]+\.[^\s@<>()",;:\\]+$/;
const el=(tag,cls,text,parent)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);if(parent)parent.append(e);return e;};
let request=()=>Promise.reject(Error('No bridge')),changed=()=>{};
let sources=[],loadError='',loading=null,loaded=false,rev=0,listSeq=0;
const busy=new Set(),notes=new Map(),removing=new Set(),inputs=new Map();

const get=name=>sources.find(s=>s.source===name)||null;
const title=name=>get(name)?.title||KNOWN[name]||(name?String(name).replaceAll('_',' '):'Unknown source');
// Source names for the scope editor: the backend's list, else the first five.
const names=()=>sources.length?sources.map(s=>s.source):Object.keys(KNOWN);
function touch(){rev++;changed();}
function secureUrl(value){if(typeof value!=='string'||value.length>2048||/\s/.test(value))return false;try{const u=new URL(value);return u.protocol==='https:'&&!!u.hostname&&!u.username&&!u.password;}catch{return false;}}
// An https link opens in the user's browser (the Swift shell hands link clicks to the system).
function link(href,text,parent,label){if(!secureUrl(href))return null;const a=el('a','ext-link',text,parent);a.href=href;a.rel='noopener noreferrer';if(label)a.setAttribute('aria-label',label);return a;}
const validRow=r=>r&&typeof r==='object'&&typeof r.source==='string'&&r.source;
function put(row){if(!validRow(row))return;const i=sources.findIndex(s=>s.source===row.source);if(i>=0)sources[i]={...sources[i],...row};else sources.push(row);}

function load(){
 if(loading)return loading;
 const seq=++listSeq;
 loading=request('research_sources',{},{manual:true}).then(r=>{
  if(seq!==listSeq)return;
  sources=Array.isArray(r?.sources)?r.sources.filter(validRow):[];loaded=true;loadError='';
 }).catch(e=>{loadError=e.message||'Research sources could not be loaded.';}).finally(()=>{loading=null;touch();});
 return loading;
}
function statusText(s){
 let text=STATE[s.state]||'Unknown status ('+s.state+')';
 if(s.state==='needs_key'&&s.credential_kind)text='Needs your '+(KIND[s.credential_kind]||'key');
 if(s.state==='ready'&&!s.configured&&s.credential_kind)text+=' · without your '+(KIND[s.credential_kind]||'key');
 return text;
}
function needText(s){
 if(!s.credential_kind)return 'Nothing to enter';
 const kind=KIND[s.credential_kind]||'key';
 if(s.configured)return 'Your '+kind+' is saved';
 return (s.required?'Required: your ':'Optional: your ')+kind;
}
function privacyText(s){
 if(s.credential_kind==='email')return 'Your email goes to '+s.title+' with each request, as the contact address the service asks API users for. It is kept in this Mac’s Keychain, and never shown again or given to agents.'+(s.required?'':' Optional: without it, '+s.title+' still works with a smaller allowance.');
 if(s.credential_kind==='api_key')return 'Your key goes only to '+s.title+'. It is kept in this Mac’s Keychain, and never shown again or given to agents.'+(s.required?'':' Optional: without a key, '+s.title+' works on a smaller shared allowance.');
 return 'No key or email needed. Interspace calls it for you at a polite rate.';
}
function act(name,method,params,done){
 busy.add(name);notes.delete(name);touch();
 return request(method,{source:name,...params},{manual:true}).then(r=>{put(r?.source===name?r:null);notes.set(name,{text:done(r)});})
  .catch(e=>{notes.set(name,{error:e.message||'That did not work.'});}).finally(()=>{busy.delete(name);touch();});
}
function save(s,input){
 const value=input.value.trim();input.setCustomValidity('');
 const problem=!value?'Enter your '+(KIND[s.credential_kind]||'key')+'.':s.credential_kind==='email'?(value.length>254||!EMAIL_RE.test(value)?'Enter an email address, like name@example.org.':''):(KEY_RE.test(value)?'':'A key is 8 to 256 characters, with no spaces.');
 if(problem){input.setCustomValidity(problem);input.reportValidity();return;}
 // The value leaves the page once, in this request; the field is cleared before the reply.
 input.value='';
 act(s.source,'research_credential_set',{value},r=>'Saved in your Keychain'+(r?.state&&r.state!=='ready'?' · '+statusText(r):'.'));
}
function test(s){act(s.source,'research_test',{},r=>r?.state==='ready'?'Test call succeeded.':'Test: '+statusText(r||{state:'error'})+(r?.detail?' · '+r.detail:''));}
function remove(s){removing.delete(s.source);act(s.source,'research_credential_delete',{},()=>'Removed from your Keychain.');}

// One input per source lives as long as the page, so a re-render never loses what is being typed.
function inputFor(s){
 let input=inputs.get(s.source);
 if(!input){input=document.createElement('input');input.id='research-secret-'+s.source.replace(/[^A-Za-z0-9_-]/g,'_');input.autocomplete='off';input.spellcheck=false;input.maxLength=s.credential_kind==='email'?254:256;inputs.set(s.source,input);input.oninput=()=>input.setCustomValidity('');}
 input.type=s.credential_kind==='email'?'email':'password';
 input.placeholder=s.configured?'Saved. Enter a new one to replace it':s.credential_kind==='email'?'name@example.org':'Paste your key';
 return input;
}
function sourceRow(s,list){
 const li=el('li','provider-item research-source',null,list);li.dataset.source=s.source;
 const head=el('div','provider-head',null,li);el('strong','',s.title||title(s.source),head);
 el('span','source-need'+(s.required?' required':''),needText(s),head);
 el('span','provider-state '+(s.state||'unknown'),statusText(s),head);
 if(s.detail)el('p','footnote',s.detail,li);
 el('p','footnote',privacyText({...s,title:s.title||title(s.source)}),li);
 const helpText=s.credential_kind==='api_key'?'Get a free key':'About this service';
 link(s.help_url,helpText,el('p','footnote',null,li),helpText+' from '+(s.title||title(s.source))+' (opens in your browser)');
 const block=busy.has(s.source);
 if(s.credential_kind){
  const form=el('form','research-key',null,li);form.noValidate=true;
  const label=el('label','',(s.title||title(s.source))+' '+(s.configured?'replacement ':'')+(KIND[s.credential_kind]||'key'),form);
  const input=inputFor(s);label.htmlFor=input.id;const row=el('div','key-row',null,form);row.append(input);input.disabled=block;
  const b=el('button','primary',s.configured?'Replace':'Save',row);b.type='submit';b.disabled=block;
  form.onsubmit=e=>{e.preventDefault();save(s,input);};
 }
 const actions=el('div','actions',null,li);
 const t=el('button','','Test',actions);t.type='button';t.disabled=block;t.setAttribute('aria-label','Test '+(s.title||title(s.source)));t.onclick=()=>test(s);
 if(s.credential_kind&&s.configured&&!removing.has(s.source)){const r=el('button','','Remove',actions);r.type='button';r.id='research-remove-'+s.source;r.disabled=block;r.setAttribute('aria-label','Remove your '+(s.title||title(s.source))+' '+(KIND[s.credential_kind]||'key'));r.onclick=()=>{removing.add(s.source);touch();document.getElementById('research-remove-confirm-'+s.source)?.focus();};}
 if(removing.has(s.source)&&s.configured){
  const box=el('div','sign-in-steps',null,li);box.setAttribute('role','group');box.setAttribute('aria-label','Remove '+(s.title||title(s.source)));
  el('p','','Remove your '+(s.title||title(s.source))+' '+(KIND[s.credential_kind]||'key')+' from this Mac’s Keychain?'+(s.required?' Agents cannot use '+(s.title||title(s.source))+' until you enter it again.':''),box);
  const row=el('div','actions',null,box);
  const yes=el('button','primary','Remove',row);yes.type='button';yes.id='research-remove-confirm-'+s.source;yes.onclick=()=>remove(s);
  const no=el('button','','Cancel',row);no.type='button';no.onclick=()=>{removing.delete(s.source);touch();document.getElementById('research-remove-'+s.source)?.focus();};
 }
 const note=notes.get(s.source);if(note)el('p',note.error?'error-text':'footnote',note.error||note.text,li).setAttribute('role',note.error?'alert':'status');
}
function renderSettings(container){
 if(container.dataset.rev===String(rev))return;container.dataset.rev=String(rev);
 const keep=document.activeElement&&container.contains(document.activeElement)?document.activeElement.id:null;
 for(const input of inputs.values())input.remove();
 container.replaceChildren();
 el('h2','','Research sources',container);
 el('p','footnote','Agents search these scholarly services through Interspace: only Interspace calls them, and agents never see your keys or email. Keys and emails stay in this Mac’s Keychain. Research calls use no tokens; each task counts the requests it sends to each source, and the answers that came from the cache.',container);
 if(loadError)el('p','error-text',loadError,container).setAttribute('role','alert');
 if(!sources.length&&!loadError)el('p','muted',loading||!loaded?'Loading research sources…':'No research sources.',container);
 const list=el('ul','provider-list research-sources',null,container);
 for(const s of sources)sourceRow(s,list);
 if(keep){const again=document.getElementById(keep);if(again&&container.contains(again))again.focus();}
}
// Usable means configured, or works without its credential (tasks.md): used to hint in the scope editor.
const usable=name=>{const s=get(name);return !s||!!s.configured||!s.required;};

window.interspaceResearch={
 init(options){request=options.request;changed=options.changed||changed;},
 load,loaded:()=>loaded,list:()=>sources.slice(),get,title,names,usable,secureUrl,link,renderSettings,KNOWN
};
})();
