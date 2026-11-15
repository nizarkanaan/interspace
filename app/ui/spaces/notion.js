/* Notion Spaces panel (connectors.md "UI panels"). Remote text is always inserted with textContent. */
(()=>{
const APP='notion';
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

function render(container,api){
 disposed=false;const mine=++generation;
 const live=()=>!disposed&&mine===generation;
 const ui={
  status:el('p',{class:'muted',role:'status','aria-live':'polite'}),
  account:el('div',{class:'space-account'}),
  main:el('div',{class:'space-main'}),
 };
 const view={auth:null,trail:[],items:[],next:null,query:'',selected:null,content:null,busy:false};
 container.replaceChildren(ui.account,ui.status,ui.main);
 const say=text=>{if(live())ui.status.textContent=text||'';};
 const call=(method,params)=>api.request(method,params||{}).then(result=>{if(!live())throw Object.assign(Error('stale'),{stale:true});return result;});
 const fail=error=>{if(!error||!error.stale)say(errorText(error));};

 function paintAccount(){
  const s=view.auth;ui.account.replaceChildren();
  if(!s){ui.account.append(el('p',{class:'muted',text:'Checking Notion…'}));return;}
  if(s.state==='signed_in'){
   ui.account.append(el('p',{text:'Connected to '+(s.account&&s.account.label||'Notion')}),
    el('button',{type:'button',class:'secondary',text:'Disconnect',onclick:signOut}));
   return;
  }
  if(s.detail)ui.account.append(el('p',{class:'muted',text:s.detail}));
  ui.account.append(el('button',{type:'button',text:s.state==='expired'?'Reconnect Notion':'Connect Notion',onclick:beginSignIn}));
 }
 function refreshStatus(){
  return call('spaces_status').then(result=>{
   view.auth=(result.apps||[]).find(a=>a.app===APP)||{state:'signed_out'};paintAccount();
   if(view.auth.state==='signed_in'&&!view.trail.length)browse(null,'Notion');
   else if(view.auth.state!=='signed_in')ui.main.replaceChildren();
  }).catch(fail);
 }

 function beginSignIn(){
  call('spaces_sign_in').then(step=>{
   if(step.kind!=='token_entry'){say('This sign-in method is not supported here.');return;}
   const input=el('input',{type:'password',autocomplete:'off',spellcheck:'false',required:true,'aria-label':step.label});
   const valid=()=>{try{return new RegExp(step.pattern).test(input.value);}catch(error){return input.value.length>0;}};
   const form=el('form',{class:'space-form',onsubmit:e=>{
    e.preventDefault();if(!valid()){say('That does not look like a Notion token.');return;}
    const token=input.value;input.value='';say('Checking the token with Notion…');
    call('spaces_complete_sign_in',{token}).then(status=>{view.auth=status;say('');paintAccount();view.trail=[];if(status.state==='signed_in')browse(null,'Notion');}).catch(fail);
   }},
    el('label',{text:step.label},input),
    el('p',{class:'muted',text:'Create an internal connection in Notion, share the pages you want with it, then paste its token. Instructions: '+step.help_url}),
    el('button',{type:'submit',text:'Connect'}),
    el('button',{type:'button',class:'secondary',text:'Cancel',onclick:()=>{call('spaces_cancel_sign_in').catch(()=>{});ui.main.replaceChildren();say('');}}));
   ui.main.replaceChildren(form);input.focus();
  }).catch(fail);
 }
 function signOut(){
  api.confirm('Disconnect Notion? The saved token is removed from the Keychain.').then(ok=>{
   if(!ok)return;return call('spaces_sign_out').then(status=>{view.auth=status;view.trail=[];ui.main.replaceChildren();paintAccount();});
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
  const crumbs=el('nav',{'aria-label':'Notion location',class:'space-trail'});
  view.trail.forEach((t,i)=>{
   if(i)crumbs.append(document.createTextNode(' / '));
   crumbs.append(i===view.trail.length-1&&!view.query?el('span',{text:t.title}):el('button',{type:'button',class:'link',text:t.title,onclick:()=>browse(t.ref,t.title)}));
  });
  if(view.query)crumbs.append(document.createTextNode(' / '),el('span',{text:'Search: '+view.query}));
  const box=el('input',{type:'search',maxlength:500,placeholder:'Search Notion','aria-label':'Search Notion',value:view.query});
  const search=el('form',{class:'space-search',role:'search',onsubmit:e=>{e.preventDefault();view.query=box.value.trim();load(false);}},box,el('button',{type:'submit',text:'Search'}));
  const list=el('ul',{class:'space-list'});
  for(const item of view.items){
   const row=el('li',{},
    el('button',{type:'button',class:'link',text:item.title||'Untitled',onclick:()=>open(item)}),
    el('small',{class:'muted',text:' '+item.kind+(item.updated_at?' · edited '+item.updated_at.slice(0,10):'')}));
   const meta=Object.entries(item.meta||{}).map(([k,v])=>k+': '+v).join(' · ');
   if(meta)row.append(el('div',{class:'muted',text:meta}));
   list.append(row);
  }
  if(!view.items.length)list.append(el('li',{class:'muted',text:view.query?'No matches.':'Nothing here yet. Share pages with the Interspace connection in Notion.'}));
  ui.main.replaceChildren(search,crumbs,list);
  if(view.next)ui.main.append(el('button',{type:'button',class:'secondary',text:'Load more',onclick:()=>load(true)}));
  if(view.selected)ui.main.append(detail());
 }

 // Detail -------------------------------------------------------------------
 function open(item){
  view.selected=item;view.content=null;
  if(item.kind!=='block'&&item.has_children)browse(item.ref,item.title||'Untitled');else paintMain();
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
  else{
   box.append(el('pre',{class:'space-content',text:content.text}));
   if(content.truncated&&content.next_cursor)box.append(el('button',{type:'button',class:'secondary',text:'Read more',onclick:()=>read(content.next_cursor)}));
  }
  if(item.kind==='page')box.append(
   textAction('Append to page','notion.page.append','markdown','Text to append (Markdown headings, lists, to-dos)',100000),
   textAction('Comment','notion.page.comment','text','Comment',2000),
   propertyAction(),
   el('button',{type:'button',class:'danger',text:'Move to trash',onclick:archive}));
  if(item.kind==='database')box.append(createPage());
  return box;
 }
 function write(action,params,done){
  const item=view.selected;say('Saving to Notion…');
  return call('spaces_write',{action,ref:item.ref,params,idempotency_key:newKey()}).then(result=>{
   say(result.summary||'Done.');if(done)done(result);if(view.selected===item)read(null);
  }).catch(fail);
 }
 function textAction(label,action,field,placeholder,max){
  const area=el('textarea',{rows:3,maxlength:max,placeholder,'aria-label':label});
  return el('form',{class:'space-form',onsubmit:e=>{e.preventDefault();if(!area.value.trim())return;write(action,{[field]:area.value},()=>{area.value='';});}},
   area,el('button',{type:'submit',text:label}));
 }
 function propertyAction(){
  const name=el('input',{maxlength:100,placeholder:'Property','aria-label':'Property name'});
  const value=el('input',{maxlength:2000,placeholder:'New value','aria-label':'Property value'});
  return el('form',{class:'space-form',onsubmit:e=>{
   e.preventDefault();const content=view.content;
   if(!name.value.trim()||!content||!content.version){say('Read the page before changing a property.');return;}
   const raw=value.value,number=Number(raw);
   const parsed=raw==='true'?true:raw==='false'?false:raw!==''&&Number.isFinite(number)?number:raw;
   write('notion.page.update_properties',{properties:{[name.value.trim()]:parsed},base_version:content.version},()=>{value.value='';});
  }},name,value,el('button',{type:'submit',text:'Set property'}));
 }
 function createPage(){
  const title=el('input',{maxlength:2000,placeholder:'Title','aria-label':'New page title',required:true});
  const body=el('textarea',{rows:3,maxlength:100000,placeholder:'Optional text','aria-label':'New page text'});
  return el('form',{class:'space-form',onsubmit:e=>{
   e.preventDefault();const params={title:title.value.trim()};if(!params.title)return;if(body.value.trim())params.markdown=body.value;
   write('notion.database.create_page',params,()=>{title.value='';body.value='';load(false);});
  }},title,body,el('button',{type:'submit',text:'Create page'}));
 }
 function archive(){
  const item=view.selected;
  api.confirm('Move "'+(item.title||'Untitled')+'" to the Notion trash?').then(ok=>{
   if(!ok)return;return write('notion.page.archive',{},()=>{view.selected=null;view.content=null;load(false);});
  }).catch(fail);
 }

 container.addEventListener('interspace:spaces-auth',e=>{const s=e.detail&&e.detail.status;if(s&&live()){view.auth=s;paintAccount();}});
 container.addEventListener('interspace:open-ref',e=>{
  const ref=e.detail&&e.detail.ref;if(!ref||!ref.startsWith(APP+':')||!live())return;
  open({ref,kind:ref.split(':')[1],title:'',has_children:false,meta:{}});
 });
 paintAccount();refreshStatus();
}

function register(){
 if(!window.interspaceSpaces||typeof window.interspaceSpaces.register!=='function')return;
 window.interspaceSpaces.register({app:APP,title:'Notion',render,dispose(){disposed=true;generation++;}});
}
register();
})();
