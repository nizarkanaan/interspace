/* Google Drive Spaces panel (connectors.md "UI panels"). Remote text is always inserted with textContent. */
(()=>{
const APP='gdrive',NAME='Google Drive';
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
const KIND_LABEL={folder:'folder',doc:'Google Doc',file:'file'};

function render(container,api){
 disposed=false;const mine=++generation;
 const live=()=>!disposed&&mine===generation;
 const ui={
  status:el('p',{class:'muted',role:'status','aria-live':'polite'}),
  account:el('div',{class:'space-account'}),
  main:el('div',{class:'space-main'}),
 };
 const view={auth:null,trail:[],items:[],next:null,query:'',selected:null,content:null,waiting:false};
 container.replaceChildren(ui.account,ui.status,ui.main);
 const say=text=>{if(live())ui.status.textContent=text||'';};
 const call=(method,params)=>api.request(method,params||{}).then(result=>{if(!live())throw Object.assign(Error('stale'),{stale:true});return result;});
 const fail=error=>{if(!error||!error.stale)say(errorText(error));};

 function paintAccount(){
  const s=view.auth;ui.account.replaceChildren();
  if(!s){ui.account.append(el('p',{class:'muted',text:'Checking Google Drive…'}));return;}
  if(s.state==='signed_in'){
   ui.account.append(el('p',{text:'Connected to '+(s.account&&s.account.label||NAME)}),
    el('button',{type:'button',class:'secondary',text:'Disconnect',onclick:signOut}));
   return;
  }
  if(s.detail)ui.account.append(el('p',{class:'muted',text:s.detail}));
  if(view.waiting)return;
  ui.account.append(el('button',{type:'button',text:s.state==='expired'?'Reconnect Google Drive':'Connect Google Drive',onclick:beginSignIn}));
 }
 function signedIn(status){
  view.auth=status;view.waiting=false;say('');paintAccount();view.trail=[];
  if(status.state==='signed_in')browse(null,NAME);else ui.main.replaceChildren();
 }
 function refreshStatus(){
  return call('spaces_status').then(result=>{
   view.auth=(result.apps||[]).find(a=>a.app===APP)||{state:'signed_out'};paintAccount();
   if(view.auth.state==='signed_in'&&!view.trail.length)browse(null,NAME);
   else if(view.auth.state!=='signed_in')ui.main.replaceChildren();
  }).catch(fail);
 }

 // Sign-in: first the user's own OAuth client (token_entry), then Google in the browser.
 function cancelSignIn(){view.waiting=false;call('spaces_cancel_sign_in').catch(()=>{});ui.main.replaceChildren();say('');paintAccount();}
 function beginSignIn(){
  call('spaces_sign_in').then(step=>{
   if(step.kind==='token_entry')clientForm(step);
   else if(step.kind==='browser')browserWait(step);
   else say('This sign-in method is not supported here.');
  }).catch(fail);
 }
 function clientForm(step){
  const input=el('input',{type:'password',autocomplete:'off',spellcheck:'false',required:true,'aria-label':step.label});
  const valid=()=>{try{return new RegExp(step.pattern).test(input.value);}catch(error){return input.value.length>0;}};
  const form=el('form',{class:'space-form',onsubmit:e=>{
   e.preventDefault();if(!valid()){say('That does not look like a Google OAuth client JSON.');return;}
   const token=input.value;input.value='';say('Checking the OAuth client with Google…');
   call('spaces_complete_sign_in',{token}).then(signedIn).catch(fail);
  }},
   el('label',{text:step.label},input),
   el('p',{class:'muted',text:'In Google Cloud, create a project, enable the Google Drive and Google Docs APIs, add yourself as a test user, then create an OAuth client of type Desktop app. Download its JSON and paste the whole file here. It is stored only in your Keychain. Guide: '+step.help_url}),
   el('button',{type:'submit',text:'Save client'}),
   el('button',{type:'button',class:'secondary',text:'Cancel',onclick:cancelSignIn}));
  ui.main.replaceChildren(form);input.focus();
 }
 function browserWait(step){
  view.waiting=true;paintAccount();
  ui.main.replaceChildren(el('section',{class:'space-form'},
   el('p',{text:'Continue in your browser. Interspace opened the Google sign-in page.'}),
   el('p',{class:'muted',text:'If no page opened, copy this address into your browser: '+step.url}),
   el('p',{class:'muted',text:'This sign-in expires at '+String(step.expires_at||'').slice(11,16)+' UTC.'}),
   el('button',{type:'button',class:'secondary',text:'Cancel',onclick:cancelSignIn})));
 }
 function signOut(){
  api.confirm('Disconnect Google Drive? The saved sign-in is removed from the Keychain; your OAuth client stays saved.').then(ok=>{
   if(!ok)return;return call('spaces_sign_out').then(signedIn);
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
 function paintMain(){
  const crumbs=el('nav',{'aria-label':'Google Drive location',class:'space-trail'});
  view.trail.forEach((t,i)=>{
   if(i)crumbs.append(document.createTextNode(' / '));
   crumbs.append(i===view.trail.length-1&&!view.query?el('span',{text:t.title}):el('button',{type:'button',class:'link',text:t.title,onclick:()=>browse(t.ref,t.title)}));
  });
  if(view.query)crumbs.append(document.createTextNode(' / '),el('span',{text:'Search: '+view.query}));
  const box=el('input',{type:'search',maxlength:500,placeholder:'Search Google Drive','aria-label':'Search Google Drive',value:view.query});
  const search=el('form',{class:'space-search',role:'search',onsubmit:e=>{e.preventDefault();view.query=box.value.trim();load(false);}},box,el('button',{type:'submit',text:'Search'}));
  const list=el('ul',{class:'space-list'});
  for(const item of view.items){
   list.append(el('li',{},
    el('button',{type:'button',class:'link',text:item.title||'Untitled',onclick:()=>open(item)}),
    el('small',{class:'muted',text:' '+(KIND_LABEL[item.kind]||item.kind)+(item.updated_at?' · edited '+item.updated_at.slice(0,10):'')})));
  }
  if(!view.items.length)list.append(el('li',{class:'muted',text:view.query?'No matches.':'Nothing here yet. Interspace sees only Drive files it created or that you opened with it.'}));
  ui.main.replaceChildren(search,crumbs,list);
  if(view.next)ui.main.append(el('button',{type:'button',class:'secondary',text:'Load more',onclick:()=>load(true)}));
  const parent=view.trail.length?view.trail[view.trail.length-1].ref:null;
  if(parent&&!view.query&&!view.selected)ui.main.append(createDoc(parent));
  if(view.selected)ui.main.append(detail());
 }

 // Detail -------------------------------------------------------------------
 function open(item){
  view.selected=item;view.content=null;
  if(item.kind==='folder')browse(item.ref,item.title||'Untitled');else paintMain();
  read(null);
 }
 function read(cursor){
  const item=view.selected;
  call('spaces_read',cursor?{ref:item.ref,cursor}:{ref:item.ref}).then(content=>{
   if(view.selected!==item)return;
   view.content=cursor&&view.content?Object.assign({},content,{text:view.content.text+content.text}):content;paintMain();
  }).catch(fail);
 }
 function detail(){
  const item=view.selected,content=view.content;
  const box=el('section',{class:'space-detail','aria-label':item.title||'Untitled'},
   el('h3',{text:item.title||'Untitled'}),
   el('button',{type:'button',class:'secondary',text:'Mention in chat',onclick:()=>api.mention(item.ref,item.title||'Untitled')}));
  if(item.url)box.append(el('p',{class:'muted',text:item.url}));
  if(!content)box.append(el('p',{class:'muted',text:'Reading…'}));
  else if(content.format==='unavailable')box.append(el('p',{class:'muted',text:(content.meta&&content.meta.reason)||'This item cannot be shown as text.'}));
  else if(item.kind!=='folder'){
   box.append(el('pre',{class:'space-content',text:content.text}));
   if(content.truncated&&content.next_cursor)box.append(el('button',{type:'button',class:'secondary',text:'Read more',onclick:()=>read(content.next_cursor)}));
  }
  if(item.kind==='doc')box.append(
   textAction('Append to document','gdrive.doc.append','text','Text to append as a new paragraph',100000),
   replaceAction());
  if(item.kind==='folder')box.append(createDoc(item.ref));
  box.append(renameAction(),el('button',{type:'button',class:'danger',text:'Move to trash',onclick:trash}));
  return box;
 }
 function write(action,ref,params,done){
  const item=view.selected;say('Saving to Google Drive…');
  return call('spaces_write',{action,ref,params,idempotency_key:newKey()}).then(result=>{
   say(result.summary||'Done.');if(done)done(result);if(item&&view.selected===item)read(null);
  }).catch(fail);
 }
 function textAction(label,action,field,placeholder,max){
  const area=el('textarea',{rows:3,maxlength:max,placeholder,'aria-label':label});
  return el('form',{class:'space-form',onsubmit:e=>{e.preventDefault();if(!area.value.trim())return;write(action,view.selected.ref,{[field]:area.value},()=>{area.value='';});}},
   area,el('button',{type:'submit',text:label}));
 }
 function replaceAction(){
  const find=el('input',{maxlength:1000,placeholder:'Find (exact, case-sensitive)','aria-label':'Text to find'});
  const replace=el('input',{maxlength:100000,placeholder:'Replace with','aria-label':'Replacement text'});
  return el('form',{class:'space-form',onsubmit:e=>{
   e.preventDefault();const content=view.content;
   if(!find.value){say('Enter the text to find.');return;}
   if(!content||!content.version){say('Read the document before replacing text.');return;}
   write('gdrive.doc.replace_text',view.selected.ref,{find:find.value,replace:replace.value,base_version:content.version},()=>{find.value='';replace.value='';});
  }},find,replace,el('button',{type:'submit',text:'Replace all'}));
 }
 function renameAction(){
  const name=el('input',{maxlength:300,placeholder:'New name','aria-label':'New name',required:true});
  return el('form',{class:'space-form',onsubmit:e=>{
   e.preventDefault();const value=name.value.trim();if(!value)return;
   write('gdrive.file.rename',view.selected.ref,{name:value},()=>{name.value='';view.selected=Object.assign({},view.selected,{title:value});load(false);});
  }},name,el('button',{type:'submit',text:'Rename'}));
 }
 function createDoc(folder){
  const title=el('input',{maxlength:300,placeholder:'New document title','aria-label':'New document title',required:true});
  const body=el('textarea',{rows:3,maxlength:100000,placeholder:'Optional Markdown','aria-label':'New document text'});
  return el('form',{class:'space-form',onsubmit:e=>{
   e.preventDefault();const params={title:title.value.trim()};if(!params.title)return;if(body.value.trim())params.markdown=body.value;
   write('gdrive.folder.create_doc',folder,params,()=>{title.value='';body.value='';load(false);});
  }},title,body,el('button',{type:'submit',text:'Create Google Doc'}));
 }
 function trash(){
  const item=view.selected;
  api.confirm('Move "'+(item.title||'Untitled')+'" to the Google Drive trash?').then(ok=>{
   if(!ok)return;return write('gdrive.file.trash',item.ref,{},()=>{view.selected=null;view.content=null;load(false);});
  }).catch(fail);
 }

 container.addEventListener('interspace:spaces-auth',e=>{const s=e.detail&&e.detail.status;if(s&&live())signedIn(s);});
 container.addEventListener('interspace:open-ref',e=>{
  const ref=e.detail&&e.detail.ref;if(!ref||!ref.startsWith(APP+':')||!live())return;
  open({ref,kind:ref.split(':')[1],title:'',has_children:false,meta:{}});
 });
 paintAccount();refreshStatus();
}

function register(){
 if(!window.interspaceSpaces||typeof window.interspaceSpaces.register!=='function')return;
 window.interspaceSpaces.register({app:APP,title:NAME,render,dispose(){disposed=true;generation++;}});
}
register();
})();
