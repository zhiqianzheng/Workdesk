'use strict';
(() => {
 const byId=id=>document.getElementById(id);
 let active=false, loading=false, pausedForInput=false, configLoading=false, formError='';
 let selected=new Set(), saved=null;
 const status=(message,error=false)=>{formError=error?message:'';byId('aiStatus').textContent=message;};
 const display=value=>{
  saved=value;active=!!value.enabled;
  byId('aiOpen').textContent=active?'AI · On':'AI · Off';
  byId('aiPause').hidden=!active;
  byId('aiPauseDialog').disabled=!active;
  if(!formError)status(value.status||'已关闭');
 };
 const contacts=()=>{
  const names=[...new Set([...selected,...(state.sessions||[]).map(s=>s.name)])];
  const root=byId('aiContacts');root.replaceChildren();
  if(!names.length){root.textContent='先连接微信并打开需要接管的联系人。';return;}
  for(const name of names){
   const label=document.createElement('label');label.className='ai-check';
   const input=document.createElement('input');input.type='checkbox';input.checked=selected.has(name);
   input.addEventListener('change',()=>{if(input.checked)selected.add(name);else selected.delete(name);});
   const text=document.createElement('span');text.textContent=name;
   label.append(input,text);root.append(label);
  }
 };
 const refreshAI=async()=>{
  if(loading||stopped||configLoading)return;
  loading=true;
  try{display(await api('/api/ai/status'));}catch(error){
   byId('aiOpen').textContent='AI · ?';
   // Keep Pause available after a transport failure: server state is unknown.
   if(byId('aiSettings').open)status(error.message,true);
  }finally{loading=false;}
 };
 byId('aiOpen').onclick=async()=>{
  configLoading=true;
  const fields=()=>byId('aiSettings').querySelectorAll('input,textarea,#aiSave,#aiStart,#aiAddCurrent');
  fields().forEach(field=>field.disabled=true);
  byId('aiSettings').showModal();status('正在读取配置…');
  try{
   const config=await api('/api/ai/status');display(config);
   byId('aiEndpoint').value=config.endpoint;byId('aiModel').value=config.model;
   byId('aiKey').value='';byId('aiKey').placeholder=config.hasKey?'密钥已保存；留空保留':'本机模型可留空';
   byId('aiStyle').value=config.style;byId('aiInterval').value=config.interval;
   byId('aiClearKey').checked=false;byId('aiConsent').checked=false;
   selected=new Set(config.contacts);contacts();
   fields().forEach(field=>field.disabled=false);
  }catch(error){status(error.message,true);}finally{configLoading=false;}
 };
 byId('aiClose').onclick=()=>byId('aiSettings').close();
 byId('aiSettings').addEventListener('close',()=>{byId('aiKey').value='';});
 byId('aiAddCurrent').onclick=()=>{
  if(demo||!state.connected||!state.current||state.view==='navigation')return status('请先打开普通联系人会话。',true);
  selected.add(state.current.name);contacts();
 };
 async function save(start){
  if(configLoading)return;
  if(start&&!byId('aiConsent').checked)return status('启用前请勾选文字传送与自动发送授权。',true);
  if(start&&(demo||busy||historyBrowsing||lastSend?.unresolved||byId('draft').value.trim()||
      [...drafts.values()].some(v=>String(v).trim())||imageDrafts.size))return status('请先退出预览或历史浏览，并处理未发送草稿及待核对发送。',true);
  formError='';
  byId('aiSave').disabled=byId('aiStart').disabled=true;
  try{
   const config={endpoint:byId('aiEndpoint').value.trim(),model:byId('aiModel').value.trim(),
    apiKey:byId('aiKey').value,clearKey:byId('aiClearKey').checked,style:byId('aiStyle').value,
    interval:Number(byId('aiInterval').value),contacts:[...selected]};
   display(await api('/api/ai/config',config));byId('aiKey').value='';
   if(start){display(await api('/api/ai/start',{}));byId('aiSettings').close();}
  }catch(error){status(error.message,true);}finally{byId('aiSave').disabled=byId('aiStart').disabled=false;}
 }
 byId('aiSave').onclick=()=>save(false);byId('aiStart').onclick=()=>save(true);
 async function pause(){
  formError='';
  try{display(await api('/api/ai/pause',{}));return true;}catch(error){status(error.message);notify('未确认 AI 已暂停，请检查连接或停止本地服务。',true);return false;}
 }
 byId('aiPause').onclick=pause;byId('aiPauseDialog').onclick=pause;
 async function manualInput(){
  if(!active||pausedForInput)return;
  pausedForInput=true;
  try{await pause();}finally{pausedForInput=false;}
 }
 byId('draft').addEventListener('input',manualInput);
 byId('draft').addEventListener('compositionstart',manualInput);
 byId('draft').addEventListener('paste',manualInput);
 byId('pickImage').addEventListener('click',manualInput);
 // Navigating to notes/preview is an explicit return to manual use too.
 for(const id of ['privacyButton','notesNav','demoButton','settingsDemo'])byId(id).addEventListener('click',manualInput);
 document.addEventListener('keydown',event=>{if(event.key==='Escape')manualInput();});
 refreshAI();setInterval(refreshAI,2000);
})();
