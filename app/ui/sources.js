/* Committed-source settings. Local drafts and asynchronous replies stay project-owned. */
window.interspaceSources=(()=>{
 const $=id=>document.getElementById(id);const records=new Map();let current=null;
 const node=(tag,text,parent)=>{const e=document.createElement(tag);e.textContent=text;parent.append(e);return e;};
 const record=id=>{if(!records.has(id))records.set(id,{catalog:null,draft:null,dirty:false,epoch:0,loading:false,saving:false,loadId:0,previewId:0,preview:null,error:'',baseVersion:0,revision:null});return records.get(id);};
 function paintStatus(r){
  const state=current.state;$('sources-status').textContent=r.error||
   (r.loading?'Loading committed files…':r.saving?'Saving sources…':r.dirty?'Unsaved source changes':state.source_error||
   (state.source_selection?.mode==='selected'?'Saved sources · selection '+state.source_selection.selection_version:state.source_selection?.mode==='unconfirmed'?'Save a source set before project chat.':'Legacy source defaults remain active until you save a selection.'));
  $('save-sources').disabled=!!state.active||r.loading||r.saving||!r.catalog||!r.draft?.size||!!state.source_error;
  $('sources-refresh').disabled=r.loading;
  const selectedFiles=(r.catalog?.files||[]).filter(f=>r.draft?.has(f.path));
  const totalBytes=selectedFiles.reduce((total,f)=>total+(f.bytes||0),0);
  const contextSize=!r.dirty&&Number.isFinite(r.catalog?.context_characters)?r.catalog.context_characters+' numbered context characters':'numbered context checked on Save';
  $('source-count').textContent=(r.draft?.size||0)+'/16 files · '+totalBytes+' committed bytes · '+contextSize+'. Limits: 250,000 bytes per file; 240,000 context characters.';
 }
 function paint(){
  if(!current?.visible)return;
  const r=record(current.state.project_id),list=$('source-file-list');paintStatus(r);
  $('sources-revision').textContent=r.catalog?'Committed revision '+r.catalog.revision:'';
  list.replaceChildren();$('source-selected').replaceChildren();
  for(const name of [...(r.draft||[])].sort()){
   const row=node('div','',$('source-selected'));row.className='selected-source';node('span',name,row);
   const remove=node('button','Remove',row);remove.setAttribute('aria-label','Remove '+name);remove.disabled=!!current.state.active;
   remove.onclick=()=>{r.draft.delete(name);r.dirty=true;r.epoch++;paint();};
  }
  const query=$('source-filter').value.toLowerCase();
  for(const file of r.catalog?.files||[]){
   if(!file.path.toLowerCase().includes(query))continue;
   const row=node('div','',list);row.className='source-row';const label=node('label','',row);
   const input=node('input','',label);input.type='checkbox';input.setAttribute('aria-label','Select '+file.path);
   input.checked=r.draft?.has(file.path)||false;input.disabled=!file.eligible||!!current.state.active;
   const info=node('span','',label);info.className='file-info';node('span',file.path,info);
   node('small',file.eligible?(file.bytes+' committed bytes'):file.reason,info);
   input.onchange=()=>{input.checked?r.draft.add(file.path):r.draft.delete(file.path);r.dirty=true;r.epoch++;paint();};
   const button=node('button','Preview',row);button.setAttribute('aria-label','Preview '+file.path);button.disabled=!file.eligible;
   button.onclick=()=>preview(file.path);
  }
  const box=$('source-preview');box.replaceChildren();box.hidden=!r.preview;
  if(r.preview){const p=r.preview;node('h3',p.path,box);node('p','Committed '+p.revision+' · LF lines '+p.start+'–'+p.end+' of '+p.lines,box).className='footnote';if(p.omitted)node('p','Preview limited to 200 lines; remaining lines omitted.',box).className='notice';node('pre',p.text,box).tabIndex=0;}
 }
 function load(refresh=false){
  if(!current?.visible)return;
  const owner=current.state.project_id,r=record(owner);if(r.loading)return;
  const sequence=++r.loadId;r.loading=true;r.error='';paintStatus(r);
  current.request('list_sources',{project_id:owner}).then(result=>{
   if(sequence!==r.loadId||result.project_id!==owner)return;
   r.catalog=result;
   if(!r.draft||!r.dirty){r.draft=new Set(result.selection.mode==='selected'?result.selection.paths:result.suggested);r.dirty=false;}
   if(!r.dirty||refresh){r.baseVersion=result.selection.selection_version;r.revision=result.revision;}
  }).catch(error=>{if(sequence===r.loadId)r.error=error.message;}).finally(()=>{
   if(sequence===r.loadId)r.loading=false;
   if(current?.state.project_id===owner)paint();
  });
 }
 function preview(path){
  const owner=current.state.project_id,r=record(owner),sequence=++r.previewId,revision=r.catalog.revision;
  r.preview=null;paint();
  current.request('preview_source',{project_id:owner,revision,path}).then(result=>{
   if(current?.state.project_id!==owner||r.previewId!==sequence||result.project_id!==owner||result.revision!==revision)return;
   r.preview=result;r.error='';paint();
  }).catch(error=>{if(current?.state.project_id===owner&&r.previewId===sequence){r.error=error.message;paintStatus(r);}});
 }
 function save(){
  const owner=current.state.project_id,r=record(owner),epoch=r.epoch;
  const params={project_id:owner,revision:r.revision,selection_version:r.baseVersion,paths:[...r.draft].sort()};
  r.saving=true;r.error='';paintStatus(r);
  current.request('save_sources',params).then(result=>{
   if(result.project_id!==owner)return;
   const selection=result.source_selection;
   r.catalog.selection=selection;r.baseVersion=selection.selection_version;r.revision=selection.revision;
   if(r.epoch===epoch){r.draft=new Set(selection.paths);r.dirty=false;}
  }).catch(error=>{r.error=error.message;}).finally(()=>{r.saving=false;if(current?.state.project_id===owner)paint();});
 }
 function render(state,request,visible){
  const prior=current?.state.project_id;
  if(prior&&prior!==state.project_id){const previous=record(prior);previous.previewId++;previous.preview=null;$('source-filter').value='';}
  current={state,request,visible:visible&&!!state.project_id};$('sources-panel').hidden=!current.visible;
  if(!current.visible)return;
  const r=record(state.project_id),panel=$('sources-panel');
  panel.ontoggle=()=>{if(panel.open&&!r.catalog&&!r.loading&&!r.error)load();};
  $('sources-refresh').onclick=()=>load(true);$('source-filter').oninput=paint;$('save-sources').onclick=save;
  if(state.source_selection?.mode==='unconfirmed')panel.open=true;
  if(r.catalog&&!r.saving&&r.catalog.selection.selection_version!==(state.source_selection?.selection_version||0))r.catalog=null;
  paint();if(panel.open&&!r.catalog&&!r.loading&&!r.error&&!state.source_error)load();
 }
 return {render};
})();
