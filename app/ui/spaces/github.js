/* GitHub Spaces panel (connectors.md "UI panels"). Remote text is always inserted with textContent. */
(()=>{
const APP='github';
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
const labelList=text=>text.split(',').map(s=>s.trim()).filter(Boolean);
const KIND={repo:'repository',issue:'issue',pull:'pull request',branch:'branch',file:'file'};

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

 function paintAccount(){
  const s=view.auth;ui.account.replaceChildren();
  if(!s){ui.account.append(el('p',{class:'muted',text:'Checking GitHub…'}));return;}
  if(s.state==='signed_in'){
   ui.account.append(el('p',{text:'Connected as '+(s.account&&s.account.label||'GitHub')}),
    el('button',{type:'button',class:'secondary',text:'Disconnect',onclick:signOut}));
   return;
  }
  if(s.detail)ui.account.append(el('p',{class:'muted',text:s.detail}));
  ui.account.append(el('button',{type:'button',text:s.state==='expired'?'Reconnect GitHub':'Connect GitHub',onclick:beginSignIn}));
 }
 function refreshStatus(){
  return call('spaces_status').then(result=>{
   view.auth=(result.apps||[]).find(a=>a.app===APP)||{state:'signed_out'};paintAccount();
   if(view.auth.state==='signed_in'&&!view.trail.length)browse(null,'Repositories');
   else if(view.auth.state!=='signed_in')ui.main.replaceChildren();
  }).catch(fail);
 }

 function beginSignIn(){
  call('spaces_sign_in').then(step=>{
   if(step.kind!=='token_entry'){say('This sign-in method is not supported here.');return;}
   const input=el('input',{type:'password',autocomplete:'off',spellcheck:'false',required:true,'aria-label':step.label});
   const valid=()=>{try{return new RegExp(step.pattern).test(input.value);}catch(error){return input.value.length>0;}};
   const form=el('form',{class:'space-form',onsubmit:e=>{
    e.preventDefault();if(!valid()){say('That does not look like a GitHub fine-grained token. It starts with github_pat_.');return;}
    const token=input.value;input.value='';say('Checking the token with GitHub…');
    call('spaces_complete_sign_in',{token}).then(status=>{view.auth=status;say('');paintAccount();view.trail=[];if(status.state==='signed_in')browse(null,'Repositories');}).catch(fail);
   }},
    el('label',{text:step.label},input),
    el('p',{class:'muted',text:'Create a fine-grained personal access token on GitHub: choose the repositories to share, and give it Contents, Issues and Pull requests access (read, or read and write). Instructions: '+step.help_url}),
    el('button',{type:'submit',text:'Connect'}),
    el('button',{type:'button',class:'secondary',text:'Cancel',onclick:()=>{call('spaces_cancel_sign_in').catch(()=>{});ui.main.replaceChildren();say('');}}));
   ui.main.replaceChildren(form);input.focus();
  }).catch(fail);
 }
 function signOut(){
  api.confirm('Disconnect GitHub? The saved token is removed from the Keychain. Delete the token on GitHub too if you no longer need it.').then(ok=>{
   if(!ok)return;return call('spaces_sign_out').then(status=>{view.auth=status;view.trail=[];ui.main.replaceChildren();paintAccount();});
  }).catch(fail);
 }

 // Listing ------------------------------------------------------------------
 function browse(ref,title){
  if(ref===null)view.trail=[{ref:null,title}];
  else{const at=view.trail.findIndex(t=>t.ref===ref);if(at>=0)view.trail=view.trail.slice(0,at+1);else view.trail.push({ref,title});}
  view.query='';load(false);
 }
 function load(more,quiet){
  const parent=view.trail.length?view.trail[view.trail.length-1].ref:null;
  const params=view.query?{query:view.query}:parent?{parent}:{};
  if(more)params.cursor=view.next;
  if(!quiet)say('Loading…');
  call(view.query?'spaces_search':'spaces_browse',params).then(page=>{
   view.items=more?view.items.concat(page.items||[]):(page.items||[]);view.next=page.next_cursor||null;if(!quiet)say('');paintMain();
  }).catch(fail);
 }
 function describe(item){
  const m=item.meta||{},bits=[KIND[item.kind]||item.kind];
  if(item.kind==='file'&&m.type==='dir')bits[0]='folder';
  if(m.state)bits.push(m.state);
  if(m.default)bits.push('default');
  if(m.private===true)bits.push('private');
  if(item.updated_at)bits.push('updated '+item.updated_at.slice(0,10));
  return ' '+bits.join(' · ');
 }
 function paintMain(){
  const crumbs=el('nav',{'aria-label':'GitHub location',class:'space-trail'});
  view.trail.forEach((t,i)=>{
   if(i)crumbs.append(document.createTextNode(' / '));
   crumbs.append(i===view.trail.length-1&&!view.query?el('span',{text:t.title}):el('button',{type:'button',class:'link',text:t.title,onclick:()=>browse(t.ref,t.title)}));
  });
  if(view.query)crumbs.append(document.createTextNode(' / '),el('span',{text:'Search: '+view.query}));
  const box=el('input',{type:'search',maxlength:500,placeholder:'Search GitHub (repositories, issues, pull requests)','aria-label':'Search GitHub',value:view.query});
  const search=el('form',{class:'space-search',role:'search',onsubmit:e=>{e.preventDefault();view.query=box.value.trim();load(false);}},box,el('button',{type:'submit',text:'Search'}));
  const list=el('ul',{class:'space-list'});
  for(const item of view.items){
   const row=el('li',{},
    el('button',{type:'button',class:'link',text:(item.meta&&item.meta.number?'#'+item.meta.number+' ':'')+(item.title||'Untitled'),onclick:()=>open(item)}),
    el('small',{class:'muted',text:describe(item)}));
   const extra=[item.meta&&item.meta.description,item.meta&&item.meta.labels].filter(Boolean).join(' · ');
   if(extra)row.append(el('div',{class:'muted',text:extra}));
   list.append(row);
  }
  if(!view.items.length)list.append(el('li',{class:'muted',text:view.query?'No matches.':'Nothing here. Check which repositories the token can see.'}));
  ui.main.replaceChildren(search,crumbs,list);
  if(view.next)ui.main.append(el('button',{type:'button',class:'secondary',text:'Load more',onclick:()=>load(true)}));
  if(view.selected)ui.main.append(detail());
 }

 // Detail -------------------------------------------------------------------
 function open(item){
  view.selected=item;view.content=null;
  if(item.has_children)browse(item.ref,item.title||'Untitled');else paintMain();
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
  else if(content.format==='unavailable')box.append(el('p',{class:'muted',text:content.meta&&content.meta.reason||'This cannot be shown here.'}));
  else{
   box.append(el('pre',{class:'space-content',text:content.text}));
   if(content.truncated&&content.next_cursor)box.append(el('button',{type:'button',class:'secondary',text:'Read more',onclick:()=>read(content.next_cursor)}));
  }
  if(item.kind==='repo')box.append(createIssue(),createPull(item));
  if(item.kind==='issue')box.append(
   textAction('Comment','github.issue.comment','body','Comment (Markdown)',65536),
   editIssue(),
   closeIssue());
  if(item.kind==='pull')box.append(textAction('Comment','github.pull.comment','body','Comment (Markdown)',65536));
  return box;
 }
 function write(action,params,done){
  const item=view.selected;say('Saving to GitHub…');
  return call('spaces_write',{action,ref:item.ref,params,idempotency_key:newKey()}).then(result=>{
   say(result.summary||'Done.');if(done)done(result);if(view.selected===item)read(null);
  }).catch(fail);
 }
 function textAction(label,action,field,placeholder,max){
  const area=el('textarea',{rows:3,maxlength:max,placeholder,'aria-label':label});
  return el('form',{class:'space-form',onsubmit:e=>{e.preventDefault();if(!area.value.trim())return;write(action,{[field]:area.value},()=>{area.value='';});}},
   area,el('button',{type:'submit',text:label}));
 }
 function createIssue(){
  const title=el('input',{maxlength:256,placeholder:'Issue title','aria-label':'New issue title',required:true});
  const body=el('textarea',{rows:3,maxlength:65536,placeholder:'Optional description (Markdown)','aria-label':'New issue description'});
  const labels=el('input',{maxlength:1000,placeholder:'Labels, comma-separated','aria-label':'New issue labels'});
  return el('form',{class:'space-form','aria-label':'Create issue',onsubmit:e=>{
   e.preventDefault();const params={title:title.value.trim()};if(!params.title)return;
   if(body.value.trim())params.body=body.value;const names=labelList(labels.value);if(names.length)params.labels=names;
   write('github.repo.create_issue',params,()=>{title.value='';body.value='';labels.value='';load(false,true);});
  }},title,body,labels,el('button',{type:'submit',text:'Create issue'}));
 }
 function createPull(item){
  const title=el('input',{maxlength:256,placeholder:'Pull request title','aria-label':'Pull request title',required:true});
  const head=el('input',{maxlength:255,placeholder:'From branch (already pushed)','aria-label':'Branch to merge from',required:true});
  const base=el('input',{maxlength:255,placeholder:'Into branch','aria-label':'Branch to merge into',required:true,value:item.meta&&item.meta.default_branch||''});
  const body=el('textarea',{rows:3,maxlength:65536,placeholder:'Optional description (Markdown)','aria-label':'Pull request description'});
  const draft=el('input',{type:'checkbox'});
  return el('form',{class:'space-form','aria-label':'Open pull request',onsubmit:e=>{
   e.preventDefault();const params={title:title.value.trim(),head:head.value.trim(),base:base.value.trim()};
   if(!params.title||!params.head||!params.base)return;if(body.value.trim())params.body=body.value;if(draft.checked)params.draft=true;
   write('github.repo.create_pull',params,()=>{title.value='';head.value='';body.value='';draft.checked=false;load(false,true);});
  }},title,head,base,body,el('label',{text:'Draft'},draft),el('button',{type:'submit',text:'Open pull request'}));
 }
 function editIssue(){
  const title=el('input',{maxlength:256,placeholder:'New title (leave empty to keep)','aria-label':'New issue title'});
  const labels=el('input',{maxlength:1000,placeholder:'Labels, comma-separated (replaces all)','aria-label':'Replace issue labels'});
  return el('form',{class:'space-form','aria-label':'Edit issue',onsubmit:e=>{
   e.preventDefault();const content=view.content;
   if(!content||!content.version){say('Read the issue before editing it.');return;}
   const params={base_version:content.version};
   if(title.value.trim())params.title=title.value.trim();
   if(labels.value.trim())params.labels=labelList(labels.value);
   if(!params.title&&!params.labels){say('Give a new title or labels.');return;}
   write('github.issue.update',params,()=>{title.value='';labels.value='';});
  }},title,labels,el('button',{type:'submit',text:'Save changes'}));
 }
 function closeIssue(){
  const reason=el('select',{'aria-label':'Close reason'},el('option',{value:'completed',text:'Completed'}),el('option',{value:'not_planned',text:'Not planned'}));
  return el('div',{class:'space-form'},reason,el('button',{type:'button',class:'danger',text:'Close issue',onclick:()=>{
   const item=view.selected;
   api.confirm('Close issue "'+(item.title||'Untitled')+'" on GitHub?').then(ok=>{
    if(!ok)return;return write('github.issue.close',{reason:reason.value},()=>load(false,true));
   }).catch(fail);
  }}));
 }

 container.addEventListener('interspace:spaces-auth',e=>{const s=e.detail&&e.detail.status;if(s&&live()){view.auth=s;paintAccount();}});
 container.addEventListener('interspace:open-ref',e=>{
  const ref=e.detail&&e.detail.ref;if(!ref||!ref.startsWith(APP+':')||!live())return;
  open({ref,kind:ref.split(':')[1],title:ref.split(':').slice(2).join(':'),has_children:false,meta:{}});
 });
 paintAccount();refreshStatus();
}

function register(){
 if(!window.interspaceSpaces||typeof window.interspaceSpaces.register!=='function')return;
 window.interspaceSpaces.register({app:APP,title:'GitHub',render,dispose(){disposed=true;generation++;}});
}
register();
})();
