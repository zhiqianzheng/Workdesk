'use strict';
(() => {
 const byId=id=>document.getElementById(id);
 let active=false, loading=false, configLoading=false, formError='';
 let selected=new Set(), saved=null;
 const status=(message,error=false)=>{formError=error?message:'';byId('aiStatus').textContent=message;};
 const display=value=>{
  saved=value;active=!!value.enabled;
  const health=value.health?.state;
  const waiting=active&&['waiting','stalled','starting'].includes(health);
  byId('aiOpen').textContent=active?(waiting?'AI · Wait':'AI · On'):'AI · Off';
  byId('aiPause').hidden=!active;
  byId('aiPauseDialog').disabled=!active;
  const metrics=value.metrics||{};
  const detail=active&&value.health ?
   `${health==='stalled'?'检测超时，请检查服务':health==='waiting'?'等待窗口可读取':health==='starting'?'正在启动检测':'正在检测'} · 最近扫描 ${value.health.scanAgeSeconds??'—'} 秒前 · 已扫描 ${metrics.scans||0} 次 · 已观察到回复 ${metrics.replies||0} 条` : '';
  const message=[value.status,detail,waiting?value.health?.detail:''].filter(Boolean).join('\n');
  byId('aiOpen').title=message;
  if(!formError)status(message||'已关闭');
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
   byId('aiAllContacts').checked=!!config.allContacts;
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
    interval:Number(byId('aiInterval').value),contacts:[...selected],allContacts:byId('aiAllContacts').checked};
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
 refreshAI();setInterval(refreshAI,2000);
})();
