/* Zotero Spaces panel (connectors.md "UI panels"). Remote text is always inserted with textContent. */
(()=>{
const APP='zotero';
const KEY_PATTERN=/^[A-Za-z0-9]{24}$/;
const ITEM_TYPES=[['journalArticle','Journal article'],['book','Book'],['bookSection','Book section'],['conferencePaper','Conference paper'],['preprint','Preprint'],['report','Report'],['thesis','Thesis'],['webpage','Web page'],['document','Document']];
let disposed=true,generation=0;

function el(tag,props,...children){
 const e=document.createElement(tag);
 for(const [k,v] of Object.entries(props||{})){
  if(k==='text')e.textContent=v==null?'':String(v);
  else if(k.startsWith('on'))e.addEventListener(k.slice(2),v);
  else if(v!==false&&v!=null)e.setAttribute(k,v===true?'':String(v));
 }
 for(const c of children)if(c)e.append(c);
 return e;
}
const newKey=()=>(crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random()).replace(/[^A-Za-z0-9]/g,'').slice(0,64);
const errorText=error=>error&&error.message?error.message:'Something went wrong. Try again.';
const list=text=>text.split(',').map(s=>s.trim()).filter(Boolean);

function render(container,api){
 disposed=false;const mine=++generation;
 const live=()=>!disposed&&mine===generation;
 const ui={
  status:el('p',{class:'muted',role:'status','aria-live':'polite'}),
  account:el('div',{class:'space-account'}),
  main:el('div',{class:'space-main'}),
 };
 const view={auth:null,trail:[],items:[],next:null,query:'',selected:null,content:null};
 container.replaceChildren(ui.account,ui.status,ui.main);
 const say=text=>{if(live())ui.status.textContent=text||'';};
 const call=(method,params)=>api.request(method,params||{}).then(result=>{if(!live())throw Object.assign(Error('stale'),{stale:true});return result;});
 const fail=error=>{if(!error||!error.stale)say(errorText(error));};
 const canWrite=()=>!!(view.auth&&view.auth.state==='signed_in'&&(view.auth.granted||[]).includes('library:write'));

 function paintAccount(){
  const s=view.auth;ui.account.replaceChildren();
  if(!s){ui.account.append(el('p',{class:'muted',text:'Checking Zotero…'}));return;}
  if(s.state==='signed_in'){
   ui.account.append(el('p',{text:'Connected to '+(s.account&&s.account.label||'Zotero')+(canWrite()?'':' (read-only)')}));
   if(!canWrite())ui.account.append(el('button',{type:'button',text:'Add a web API key to make changes',onclick:beginSignIn}));
   ui.account.append(el('button',{type:'button',class:'secondary',text:'Disconnect',onclick:signOut}));
   return;
  }
  if(s.detail)ui.account.append(el('p',{class:'muted',text:s.detail}));
  if(s.state==='unavailable')ui.account.append(el('button',{type:'button',text:'Check again',onclick:refreshStatus}));
  ui.account.append(el('button',{type:'button',class:s.state==='unavailable'?'secondary':'',text:'Connect Zotero',onclick:beginSignIn}));
 }
 function adopt(status){
  view.auth=status||{state:'signed_out'};paintAccount();
  if(view.auth.state==='signed_in'){if(!view.trail.length)browse(null,'Zotero');}
  else{view.trail=[];view.selected=null;ui.main.replaceChildren();}
 }
 function refreshStatus(){
  return call('spaces_status').then(result=>adopt((result.apps||[]).find(a=>a.app===APP))).catch(fail);
 }

 function beginSignIn(){
  call('spaces_sign_in').then(step=>{
   if(step.kind!=='local_check'){say('This sign-in method is not supported here.');return;}
   const input=el('input',{type:'password',autocomplete:'off',spellcheck:'false',maxlength:24,'aria-label':'Zotero web API key (optional)'});
   const form=el('form',{class:'space-form',onsubmit:e=>{
    e.preventDefault();const key=input.value.trim();
    if(key&&!KEY_PATTERN.test(key)){say('That does not look like a Zotero API key.');return;}
    input.value='';say(key?'Checking Zotero and the key…':'Checking Zotero…');
    call('spaces_complete_sign_in',key?{write_key:key}:{}).then(status=>{say('');view.trail=[];adopt(status);}).catch(fail);
   }},
    el('p',{class:'muted',text:step.detail}),
    el('label',{text:'Web API key (optional, for changes)'},input),
    el('button',{type:'submit',text:'Connect'}),
    el('button',{type:'button',class:'secondary',text:'Cancel',onclick:()=>{call('spaces_cancel_sign_in').catch(()=>{});ui.main.replaceChildren();say('');if(view.auth&&view.auth.state==='signed_in')paintMain();}}));
   ui.main.replaceChildren(form);input.focus();
  }).catch(fail);
 }
 function signOut(){
  api.confirm('Disconnect Zotero? Any saved web API key is removed from the Keychain.').then(ok=>{
   if(!ok)return;return call('spaces_sign_out').then(adopt);
  }).catch(fail);
 }

 // Listing ------------------------------------------------------------------
 function browse(ref,title){
  if(ref===null)view.trail=[{ref:null,title}];
  else{const at=view.trail.findIndex(t=>t.ref===ref);if(at>=0)view.trail=view.trail.slice(0,at+1);else view.trail.push({ref,title});}
  view.query='';load(false);
 }
 function load(more){
  const parent=view.trail.length?view.trail[view.trail.length-1].ref:null;
  const params=view.query?{query:view.query}:parent?{parent}:{};
  if(more)params.cursor=view.next;
  say('Loading…');
  call(view.query?'spaces_search':'spaces_browse',params).then(page=>{
   view.items=more?view.items.concat(page.items||[]):(page.items||[]);view.next=page.next_cursor||null;say('');paintMain();
  }).catch(fail);
 }
 function describe(item){
  const m=item.meta||{},bits=[m.type||item.kind];
  if(m.creators)bits.push(m.creators);
  if(m.date)bits.push(String(m.date).slice(0,4));
  if(m.children)bits.push(m.children+' attached');
  if(item.kind==='collection'&&m.items!=null)bits.push(m.items+' items');
  return bits.join(' · ');
 }
 function paintMain(){
  const crumbs=el('nav',{'aria-label':'Zotero location',class:'space-trail'});
  view.trail.forEach((t,i)=>{
   if(i)crumbs.append(document.createTextNode(' / '));
   crumbs.append(i===view.trail.length-1&&!view.query?el('span',{text:t.title}):el('button',{type:'button',class:'link',text:t.title,onclick:()=>browse(t.ref,t.title)}));
  });
  if(view.query)crumbs.append(document.createTextNode(' / '),el('span',{text:'Search: '+view.query}));
  const box=el('input',{type:'search',maxlength:500,placeholder:'Search My Library','aria-label':'Search Zotero',value:view.query});
  const search=el('form',{class:'space-search',role:'search',onsubmit:e=>{e.preventDefault();view.query=box.value.trim();load(false);}},box,el('button',{type:'submit',text:'Search'}));
  const rows=el('ul',{class:'space-list'});
  for(const item of view.items){
   rows.append(el('li',{},
    el('button',{type:'button',class:'link',text:item.title||'Untitled',onclick:()=>open(item)}),
    el('small',{class:'muted',text:' '+describe(item)+(item.updated_at?' · edited '+item.updated_at.slice(0,10):'')})));
  }
  if(!view.items.length)rows.append(el('li',{class:'muted',text:view.query?'No matches.':'Nothing here yet.'}));
  ui.main.replaceChildren(search,crumbs,rows);
  if(view.next)ui.main.append(el('button',{type:'button',class:'secondary',text:'Load more',onclick:()=>load(true)}));
  if(view.selected)ui.main.append(detail());
 }

 // Detail -------------------------------------------------------------------
 function open(item){
  view.selected=item;view.content=null;
  if(item.kind==='library'||item.kind==='collection'||item.has_children)browse(item.ref,item.title||'Untitled');else paintMain();
  read(null);
 }
 function read(cursor){
  const item=view.selected;
  call('spaces_read',cursor?{ref:item.ref,cursor}:{ref:item.ref}).then(content=>{
   if(view.selected!==item)return;
   if(!item.title&&content.title)item.title=content.title;
   view.content=cursor&&view.content?Object.assign({},content,{text:view.content.text+content.text}):content;paintMain();
  }).catch(fail);
 }
 function detail(){
  const item=view.selected,content=view.content,type=(item.meta||{}).type||(content&&content.meta||{}).type;
  const box=el('section',{class:'space-detail','aria-label':item.title||'Untitled'},
   el('h3',{text:item.title||'Untitled'}),
   el('button',{type:'button',class:'secondary',text:'Mention in chat',onclick:()=>api.mention(item.ref,item.title||'Untitled')}));
  if(item.url)box.append(el('p',{class:'muted',text:item.url}));
  if(!content)box.append(el('p',{class:'muted',text:'Reading…'}));
  else if(content.format==='unavailable')box.append(el('p',{class:'muted',text:(content.meta&&content.meta.reason)||'No text to show.'}));
  else{
   box.append(el('pre',{class:'space-content',text:content.text}));
   if(content.truncated&&content.next_cursor)box.append(el('button',{type:'button',class:'secondary',text:'Read more',onclick:()=>read(content.next_cursor)}));
  }
  if(!canWrite()){
   if(item.kind!=='attachment')box.append(el('p',{class:'muted',text:'Read-only. Add a Zotero web API key to make changes.'}));
   return box;
  }
  if(item.kind==='item'){
   if(type!=='note')box.append(textAction('Add note','zotero.item.add_note','Note text'));
   box.append(tagAction(),el('button',{type:'button',class:'danger',text:'Move to trash',onclick:trash}));
  }
  if(item.kind==='collection')box.append(addToCollection());
  if(item.kind==='library')box.append(createItem());
  return box;
 }
 function write(action,params,done){
  const item=view.selected;say('Saving to Zotero…');
  return call('spaces_write',{action,ref:item.ref,params,idempotency_key:newKey()}).then(result=>{
   say(result.summary||'Done.');if(done)done(result);if(view.selected===item)read(null);
  }).catch(fail);
 }
 function textAction(label,action,placeholder){
  const area=el('textarea',{rows:3,maxlength:100000,placeholder,'aria-label':label});
  return el('form',{class:'space-form',onsubmit:e=>{e.preventDefault();if(!area.value.trim())return;write(action,{text:area.value},()=>{area.value='';});}},
   area,el('button',{type:'submit',text:label}));
 }
 function tagAction(){
  const input=el('input',{maxlength:2000,placeholder:'Tags, separated by commas','aria-label':'Tags to add'});
  return el('form',{class:'space-form',onsubmit:e=>{e.preventDefault();const tags=list(input.value);if(!tags.length)return;write('zotero.item.add_tags',{tags},()=>{input.value='';});}},
   input,el('button',{type:'submit',text:'Add tags'}));
 }
 function addToCollection(){
  const input=el('input',{maxlength:600,placeholder:'zotero:item:…','aria-label':'Item reference to add'});
  return el('form',{class:'space-form',onsubmit:e=>{e.preventDefault();const ref=input.value.trim();if(!ref)return;write('zotero.collection.add_item',{item:ref},()=>{input.value='';load(false);});}},
   el('p',{class:'muted',text:'Add an item from the same library by its reference (use Mention in chat on an item to copy it).'}),
   input,el('button',{type:'submit',text:'Add to collection'}));
 }
 function createItem(){
  const kind=el('select',{'aria-label':'Item type'},...ITEM_TYPES.map(([v,t])=>el('option',{value:v,text:t})));
  const title=el('input',{maxlength:2000,placeholder:'Title','aria-label':'New item title',required:true});
  const creators=el('input',{maxlength:5000,placeholder:'Authors: Last, First; Last, First','aria-label':'Authors'});
  const date=el('input',{maxlength:100,placeholder:'Date','aria-label':'Date'});
  const url=el('input',{type:'url',maxlength:2000,placeholder:'https://…','aria-label':'URL'});
  return el('form',{class:'space-form',onsubmit:e=>{
   e.preventDefault();const params={item_type:kind.value,title:title.value.trim()};if(!params.title)return;
   const names=creators.value.split(';').map(s=>s.trim()).filter(Boolean);if(names.length)params.creators=names;
   if(date.value.trim())params.date=date.value.trim();if(url.value.trim())params.url=url.value.trim();
   write('zotero.library.create_item',params,()=>{title.value='';creators.value='';date.value='';url.value='';load(false);});
  }},kind,title,creators,date,url,el('button',{type:'submit',text:'Add item'}));
 }
 function trash(){
  const item=view.selected;
  api.confirm('Move "'+(item.title||'Untitled')+'" to the Zotero trash?').then(ok=>{
   if(!ok)return;return write('zotero.item.trash',{},()=>{view.selected=null;view.content=null;load(false);});
  }).catch(fail);
 }

 container.addEventListener('interspace:spaces-auth',e=>{const s=e.detail&&e.detail.status;if(s&&live())adopt(s);});
 container.addEventListener('interspace:open-ref',e=>{
  const ref=e.detail&&e.detail.ref;if(!ref||!ref.startsWith(APP+':')||!live())return;
  open({ref,kind:ref.split(':')[1],title:'',has_children:false,meta:{}});
 });
 paintAccount();refreshStatus();
}

function register(){
 if(!window.interspaceSpaces||typeof window.interspaceSpaces.register!=='function')return;
 window.interspaceSpaces.register({app:APP,title:'Zotero',render,dispose(){disposed=true;generation++;}});
}
register();
})();
