/* Spaces sidebar frame (connectors.md "UI panels"). Defined before the spaces/<app>.js tags so panels can register.
   A panel file that is missing or never registers leaves its entry showing "Not available yet". */
(()=>{
const APPS=[['notion','Notion'],['github','GitHub'],['gdrive','Google Drive'],['zotero','Zotero']];
const METHODS=new Set(['spaces_status','spaces_sign_in','spaces_complete_sign_in','spaces_cancel_sign_in','spaces_sign_out','spaces_browse','spaces_search','spaces_read','spaces_actions','spaces_write','spaces_changes']);
const AUTH={signed_out:'Not connected',signing_in:'Signing in',expired:'Sign-in expired',unavailable:'Unavailable'};
const panels=new Map(),auth=new Map();
let host=null,selected='notion',mounted=null,dialogDone=null;
const $=id=>document.getElementById(id);
const title=app=>(APPS.find(([a])=>a===app)||[app,app])[1];

function register(panel){
 if(!panel||!APPS.some(([a])=>a===panel.app)||typeof panel.render!=='function')return false;
 if(mounted?.app===panel.app)unmount();
 panels.set(panel.app,panel);host?.refresh();return true;
}
function confirm(text){
 const dialog=$('confirm-dialog');if(dialogDone)dialogDone(false);
 $('confirm-text').textContent=String(text);
 return new Promise(resolve=>{dialogDone=answer=>{dialogDone=null;if(dialog.open)dialog.close();resolve(answer);};dialog.showModal();$('confirm-cancel').focus();});
}
function api(app){return {
 request(method,params={}){
  if(!METHODS.has(method))return Promise.reject(Error('Panels may only call spaces_* methods.'));
  if(params&&params.app!==undefined&&params.app!==app)return Promise.reject(Error('Panels may only call their own app.'));
  return host.request(method,{...params,app},{manual:true});
 },
 openRef(ref){const target=String(ref).split(':')[0];if(!APPS.some(([a])=>a===target))return false;select(target);host.navigate('space');mounted?.container.dispatchEvent(new CustomEvent('interspace:open-ref',{detail:{ref:String(ref)}}));return true;},
 mention(ref,label){const result=host.mention(String(ref),label==null?'':String(label));if(mounted?.app===app)$('space-status').textContent=result.text;return result.ok;},
 confirm
};}
function unmount(){if(!mounted)return;const m=mounted;mounted=null;try{m.panel.dispose?.();}catch(error){console.error(error);}$('space-panel').replaceChildren();}
function mount(){
 const panel=panels.get(selected),box=$('space-panel');
 if(mounted?.app===selected&&mounted.panel===panel)return;
 unmount();box.replaceChildren();
 if(!panel){const p=document.createElement('p');p.className='empty muted';p.textContent='Not available yet';box.append(p);return;}
 const container=document.createElement('div');container.className='space-body';box.append(container);mounted={app:selected,panel,container};
 try{panel.render(container,api(selected));}catch(error){console.error(error);container.textContent='This panel could not be shown.';}
}
function label(app,state){
 const s=state?.spaces?.apps?.[app]||auth.get(app);
 if(s?.state==='signed_in')return s.account?.label||'Signed in';
 if(!panels.has(app))return 'Not available yet';
 return s?AUTH[s.state]||s.state:'';
}
function render(state,view){
 for(const b of document.querySelectorAll('[data-space]')){const app=b.dataset.space;b.setAttribute('aria-pressed',String(view==='space'&&selected===app));b.querySelector('small').textContent=label(app,state);}
 $('spaces-view').hidden=view!=='space';
 if(view==='space')mount();else{unmount();}
}
function select(app){if(app!==selected)$('space-status').textContent='';selected=app;}
function receive(message){
 if(message.type==='spaces_auth'&&message.status)auth.set(message.app,message.status);
 if(mounted?.app===message.app)mounted.container.dispatchEvent(new CustomEvent(message.type==='spaces_auth'?'interspace:spaces-auth':'interspace:spaces-changed',{detail:message}));
 host?.refresh();
}
document.addEventListener('DOMContentLoaded',()=>{
 const dialog=$('confirm-dialog');
 $('confirm-cancel').onclick=()=>dialogDone?.(false);$('confirm-ok').onclick=()=>dialogDone?.(true);
 dialog.addEventListener('cancel',e=>{e.preventDefault();dialogDone?.(false);});
});
window.interspaceSpaces={register,init(options){host=options;},render,select,receive,title:()=>title(selected),confirm};
})();
