'use strict';
const $ = id => document.getElementById(id);
const storage = {get(key, fallback=''){try{return localStorage.getItem(key) ?? fallback;}catch{return fallback;}},set(key,value){try{localStorage.setItem(key,value);return true;}catch{return false;}}};
let focusAppearance=storage.get('workdesk-focus-appearance','0')==='1', composerExpanded=!focusAppearance, readingReady=false;
const appearances = {
 workdesk:{brand:'WORKDESK',caption:'项目资料工作台',mark:'▥',left:'',right:''},
 document:{brand:'DOCUMENTS',caption:'文档导航',mark:'W',left:'文档阅读视图',right:'本地工作区　 ·　 100%'},
 code:{brand:'EXPLORER',caption:'PROJECT WORKSPACE',mark:'⌘',left:'main　 /　 workspace',right:'UTF-8　 ·　 Markdown　 ·　 本地工作区'},
 terminal:{brand:'WORKSPACE',caption:'LOCAL TERMINAL',mark:'>_',left:'[workdesk]  local workspace',right:'UTF-8　 ·　 scrollback'}
};
const defaultDraftPlaceholder=$('draft').placeholder;
const terminalLabels={sendButton:['Send','提交记录 ↗'],sendImage:['Send image','发送图片 ↗'],removeImage:['Remove','移除'],nativeButton:['Open WeChat','打开原窗口 ↗']};
const terminalRelocations=['scopeNote','nativeButton'].map(id=>{const element=$(id),marker=document.createComment(id+' home');element.before(marker);return {element,marker};});
function syncTerminalChrome(){
 const terminal=document.documentElement.dataset.appearance==='terminal';
 for(const [id,labels] of Object.entries(terminalLabels))$(id).textContent=labels[terminal?0:1];
 for(const {element,marker} of terminalRelocations){if(terminal)$('terminalExtras').append(element);else marker.after(element);}
 $('draft').rows=terminal?1:3;
 if(!terminal){$('draft').style.removeProperty('height');$('draft').style.removeProperty('overflow-y');}
}
function resizeDraft(){
 const editor=$('draft');
 if(document.documentElement.dataset.appearance!=='terminal'||!editor.clientWidth)return;
 const atBottom=$('recordList').scrollHeight-$('recordList').scrollTop-$('recordList').clientHeight<45;
 editor.style.height='0px';
 const limit=Math.max(52,Math.min(156,innerHeight*.24));
 editor.style.height=Math.max(26,Math.min(editor.scrollHeight,limit))+'px';
 editor.style.overflowY=editor.scrollHeight>limit?'auto':'hidden';
 if(atBottom&&!historyBrowsing)$('recordList').scrollTop=$('recordList').scrollHeight;
}
function setAppearance(name,persist=true){
 if(!Object.hasOwn(appearances,name))name='workdesk';
 const appearance=appearances[name];
 document.documentElement.dataset.appearance=name;
 $('draft').placeholder=name==='terminal'?'':defaultDraftPlaceholder;
 $('draft').setAttribute('aria-label',name==='terminal'?'Message input':'聊天输入');
 syncTerminalChrome();
 $('brandName').textContent=appearance.brand;$('brandCaption').textContent=appearance.caption;$('brandMark').textContent=appearance.mark;
 $('appearanceStatusLeft').textContent=appearance.left;$('appearanceStatusRight').textContent=appearance.right;
 document.querySelectorAll('.appearance-switch button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.appearance===name)));
 if(readingReady){syncReadingAppearance();syncTools();syncSidebar();render();requestAnimationFrame(resizeDraft);}
 if(persist&&!storage.set('workdesk-appearance',name))notify('外观已切换，但浏览器未允许保存；关闭页面后可能恢复默认。');
}
document.querySelectorAll('.appearance-switch button').forEach(button=>button.addEventListener('click',()=>setAppearance(button.dataset.appearance)));
setAppearance(storage.get('workdesk-appearance','workdesk'),false);
let sidebarCollapsed=storage.get('workdesk-sidebar-collapsed','0')==='1';
let sidebarReturnFocus=null;
function syncSidebar(){
 $('sidebar').hidden=sidebarCollapsed;
 document.documentElement.dataset.sidebarCollapsed=String(sidebarCollapsed);
 $('sidebarToggle').setAttribute('aria-expanded',String(!sidebarCollapsed));
 $('sidebarToggle').textContent=sidebarCollapsed?'展开目录':'收起目录';
 $('sidebarToggle').title=(sidebarCollapsed?'展开左侧导航与联系人目录':'收起左侧导航与联系人目录')+' · Ctrl+Alt+X';
 $('sidebarToggle').setAttribute('aria-keyshortcuts','Control+Alt+X');
}
syncSidebar();
function toggleSidebar(fromShortcut=false){
 if(fromShortcut){
  cancelComposerFocus?.();
  if(sidebarCollapsed)sidebarReturnFocus=document.activeElement;
 }
 sidebarCollapsed=!sidebarCollapsed;
 storage.set('workdesk-sidebar-collapsed',sidebarCollapsed?'1':'0');
 historyCooldown=Math.max(historyCooldown,Date.now()+600);
 syncSidebar();
 requestAnimationFrame(()=>{
  renderRecords();resizeDraft();
  if(!fromShortcut)return;
  if(!sidebarCollapsed){$('search').focus({preventScroll:true});return;}
  const target=sidebarReturnFocus;
  const fallback=page==='notes'?$('notes'):$('draft');
  const usable=element=>element?.isConnected&&!element.disabled&&element.getClientRects().length&&!$('sidebar').contains(element);
  if(usable(target)&&target!==document.body)target.focus({preventScroll:true});
  else if(usable(fallback))fallback.focus({preventScroll:true});
  sidebarReturnFocus=null;
 });
}
$('sidebarToggle').onclick=()=>toggleSidebar();
let toolsCollapsed=storage.get('workdesk-tools-collapsed','1')==='1';
function syncTools(){
 document.documentElement.dataset.toolsCollapsed=String(toolsCollapsed);
 $('toolsToggle').textContent=document.documentElement.dataset.appearance==='terminal'?(toolsCollapsed?'Tools':'Hide tools'):(toolsCollapsed?'展开工具':'收起工具');
 $('toolsToggle').setAttribute('aria-expanded',String(!toolsCollapsed));
 $('toolsToggle').title=document.documentElement.dataset.appearance==='terminal'?'Toggle workspace tools':toolsCollapsed?'显示导航、外观、项目信息和历史工具':'隐藏顶部辅助工具';
}
syncTools();
$('toolsToggle').onclick=()=>{
 toolsCollapsed=!toolsCollapsed;
 storage.set('workdesk-tools-collapsed',toolsCollapsed?'1':'0');
 historyCooldown=Math.max(historyCooldown,Date.now()+600);
 syncTools();
 requestAnimationFrame(()=>{renderRecords();resizeDraft();});
};
const fragment = new URLSearchParams(location.hash.slice(1));
let token = fragment.get('key');
if (token) {sessionStorage.setItem('workdesk-key', token);history.replaceState(null,'',location.pathname);}
else token = sessionStorage.getItem('workdesk-key') || '';
let aliases;try{aliases=JSON.parse(storage.get('workdesk-aliases','{}'));if(!aliases||typeof aliases!=='object'||Array.isArray(aliases)) aliases={};}catch{aliases={};}
let state={connected:false,sessions:[],records:[],canSend:false}, demo=false, busy=false, page='records', lastSend=null, stopped=false, refreshing=false;
const drafts = new Map();
const imageDrafts = new Map();
const imageReads = new Map();
let composingDraft=false, compositionEndedAt=-Infinity;
let directoryResults=null, revision=0;
let historyBinding=null, historyRows=[], historyBrowsing=false, historyLoading=false, historyCooldown=0;
let historyDirection='', historyNotice='';
const sessionSeen=new Map(), sessionActivity=new Set();
let sessionsInitialized=false;
const demoProjects=[{id:'demo1',key:'demo1',name:'需求梳理'},{id:'demo2',key:'demo2',name:'界面设计'},{id:'demo3',key:'demo3',name:'交付事项'}];
const demoRecords={demo1:['第一阶段：整理使用场景与页面结构。','目录名称支持自定义，正文以工作记录的形式呈现。','本条为虚构示例，用于展示长文字的阅读效果。\n文字会自动换行，保留段落；内容可切换为表格或文档视图。','下一步：确认文字接口后进行收发验证。'],demo2:['页面采用灰白色与低饱和度绿色。','减少装饰，保留清晰的目录、记录和编辑区域。'],demo3:['核对当前对象与草稿保护。','图片、语音及文件在原窗口中处理。']};
let statusTimer;
function notify(text,persistent=false){$('status').textContent=text;$('status').classList.add('visible');clearTimeout(statusTimer);if(!persistent)statusTimer=setTimeout(()=>$('status').classList.remove('visible'),6500);}
async function api(path,body){const result=await fetch(path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,...(body!==undefined?{'Content-Type':'application/json'}:{})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});const value=await result.json();if(!result.ok){const error=new Error(value.error||'连接失败');error.outcome=value.state;throw error;}return value;}
function alias(item,index=0){if(demo)return item.name;if(!aliases[item.key]){const numbers=Object.values(aliases).map(v=>Number(/^资料项目 (\d+)$/.exec(String(v))?.[1]||0));aliases[item.key]=`资料项目 ${String(Math.max(0,...numbers)+1).padStart(3,'0')}`;storage.set('workdesk-aliases',JSON.stringify(aliases));}return String(aliases[item.key]);}
function currentAlias(){const c=state.current;if(!c)return '项目资料';const index=state.sessions.findIndex(s=>s.key===c.key);return alias(c,Math.max(0,index));}
function rememberDraft(){if(state.current)drafts.set(state.current.key,$('draft').value);}
function recordIdentity(row){return row.id+'\0'+row.text;}
function mergeHistory(previous,incoming){
 if(!previous.length||!incoming.length)return incoming;
 const index=new Map(previous.map((r,i)=>[recordIdentity(r),i]));
 const matches=incoming.map((r,i)=>[index.get(recordIdentity(r)),i]).filter(([i])=>i!==undefined);
 if(!matches.length)return incoming; // Do not invent continuity across a gap or recycled UIA identities.
 if(matches.some(([i],j)=>j&&i<=matches[j-1][0]))return incoming;
 const first=matches[0],last=matches[matches.length-1];
 const rows=[...previous.slice(0,first[0]),...incoming.map(r=>({...previous[index.get(recordIdentity(r))],...r})),...previous.slice(last[0]+1)];
 return historyDirection==='older'?rows.slice(0,600):rows.slice(-600);
}
function updateSessionActivity(next){
 if(demo||!next.connected||next.mode!=='uia')return;
 const updates=[];
 for(const item of next.sessions){
  const old=sessionSeen.get(item.key);
  const changed=old&&(old.preview!==item.preview||old.time!==item.time);
  const increased=(item.unreadCount||0)>(old?.unreadCount||0);
  const newUnread=!old&&item.unreadCount>0;
  if(sessionsInitialized&&!item.draft&&((changed&&item.preview)||increased||newUnread)){
   const reading=item.key===next.current?.key&&page==='records'&&!document.hidden&&!historyBrowsing;
   if(!reading){sessionActivity.add(item.key);updates.push(item);}
  }
  if(old?.unreadCount>0&&!item.unreadCount&&!changed)sessionActivity.delete(item.key);
  if(item.key===next.current?.key&&page==='records'&&!document.hidden&&!historyBrowsing)sessionActivity.delete(item.key);
  sessionSeen.set(item.key,{preview:item.preview,time:item.time,unreadCount:item.unreadCount});
 }
 sessionsInitialized=true;
 // Keep the observation cache bounded; no message content is written to browser storage.
 if(sessionSeen.size>300){const visible=new Set(next.sessions.map(s=>s.key));for(const key of sessionSeen.keys())if(!visible.has(key)){sessionSeen.delete(key);sessionActivity.delete(key);}}
 if(updates.length&&page==='records'&&!document.hidden&&!lastSend?.unresolved&&!focusAppearance){
  const item=updates[0];
  notify(`${item.name} 有新消息${item.unreadLabel?'（'+item.unreadLabel+'条未读）':''}：${(item.preview||'会话有更新').slice(0,90)}${updates.length>1?'；另有 '+(updates.length-1)+' 个会话更新':''}`);
 }
}
function renderUnreadSummary(){
 const sessions=demo?[]:state.sessions;
 const count=sessions.reduce((sum,s)=>sum+(s.unreadCount||0),0);
 const lowerBound=sessions.some(s=>s.unreadLabel?.endsWith('+'));
 const unknown=sessions.filter(s=>!s.unreadCount&&sessionActivity.has(s.key)).length;
 const label=[count?`${count}${lowerBound?'+':''} 条未读`:'',unknown?`${unknown} 个会话有更新`:''].filter(Boolean).join(' · ');
 $('unreadSummary').textContent=!state.connected?'连接后显示会话更新':state.mode!=='uia'?'当前连接暂不提供未读信息':label||'暂无可见未读消息';
 $('unreadSummary').title='统计微信当前已加载的会话；数字来自微信。“新”表示发现更新但未提供准确条数。';
 document.title=(label?`（${count?count+(lowerBound?'+':''):'新'}）`:'')+'项目资料 · Workdesk';
 if(focusAppearance){$('unreadSummary').textContent=count?`${count}${lowerBound?'+':''} 项更新`:unknown?`${unknown} 项更新`:'目录';$('unreadSummary').title='当前已加载目录的更新数量';document.title=document.documentElement.dataset.appearance==='code'?'workspace.md · 工作区':'项目资料 · 文档';}
 if(document.documentElement.dataset.appearance==='terminal')document.title='workdesk · Terminal';
}
function applyState(next){
 updateSessionActivity(next);
 rememberDraft();const oldKey=state.current?.key;
 const binding=next.current?.binding;
 if(binding!==historyBinding){historyBinding=binding;historyRows=[];historyBrowsing=false;historyNotice='';$('recordList').dataset.signature='';}
 if(next.connected&&next.canHistory&&!demo){
  const incomingIds=new Set(next.records.map(row=>row.id));
  historyRows=historyRows.map(row=>row.imagePending&&!incomingIds.has(row.id)?{...row,imagePending:false,imageUnavailable:!row.image}:row);
  historyRows=historyDirection==='latest'?next.records:mergeHistory(historyRows,next.records);
  // Keep a bounded set of image previews while retaining older text in memory.
  let images=0;for(let i=historyRows.length-1;i>=0;i--)if(historyRows[i].image&&++images>24){historyRows[i]={...historyRows[i],image:undefined};}
  next={...next,records:historyRows};
 }
 state=next;if(oldKey!==state.current?.key)$('draft').value=state.current?drafts.get(state.current.key)||'':'';render();
}
async function loadHistory(direction){
 if(busy||demo||!state.connected||!state.canHistory||!state.current||Date.now()<historyCooldown)return;
 if($('recordSearch').value.trim()){$('recordSearch').value='';}
 const binding=state.current.binding;busy=true;historyLoading=true;revision++;historyDirection=direction;
 let cooldown=180;
 historyNotice=direction==='latest'?'正在返回最新消息…':direction==='older'?'正在加载更早记录…':'正在加载后续记录…';render();
 try{
  const next=await api('/api/history',{binding,direction});
  if(next.state==='pending'){cooldown=900;historyNotice='微信仍在加载，请稍候点同步。';return;}
  if(next.current?.binding!==binding)throw new Error('会话已变化，请重新同步。');
  historyBrowsing=direction!=='latest';
  if(!next.historyChanged)cooldown=900;
  historyNotice=next.historyChanged?(historyBrowsing?'正在浏览历史 · 向下滚动或点“回到最新”':'已返回最新消息'):'本次没有加载到更多记录，可稍候再试或到微信查看。';
  applyState(next);
  if(direction==='latest')$('recordList').scrollTop=$('recordList').scrollHeight;
 }catch(error){cooldown=900;historyNotice=error.message;notify(error.message);}
 finally{busy=false;historyLoading=false;historyDirection='';historyCooldown=Date.now()+cooldown;render();}
}

function syncReadingAppearance(){
 document.documentElement.dataset.focusAppearance=String(focusAppearance);
 $('focusAppearance').setAttribute('aria-pressed',String(focusAppearance));
 $('focusAppearance').textContent=focusAppearance?'完整视图':'专注外观';
 $('recordDetails').hidden=!focusAppearance&&document.documentElement.dataset.appearance!=='terminal';
 $('toggleComposer').hidden=!focusAppearance;
 $('readingHint').textContent=focusAppearance?'阅读视图':'连续正文 · 精简目录';
 $('composerArea').hidden=focusAppearance&&!composerExpanded;
 $('toggleComposer').textContent=composerExpanded?'收起批注':'添加批注';
 $('toggleComposer').setAttribute('aria-expanded',String(composerExpanded));
 $('search').placeholder=focusAppearance?'查找目录或名称…':'输入备注名或群名…';
 $('searchContacts').textContent=focusAppearance?'查找':'搜索联系人';
}
$('focusAppearance').onclick=()=>{
 focusAppearance=!focusAppearance;
 historyCooldown=Math.max(historyCooldown,Date.now()+500);
 composerExpanded=!focusAppearance||!!$('draft').value||imageDrafts.has(state.current?.key);
 storage.set('workdesk-focus-appearance',focusAppearance?'1':'0');
 syncReadingAppearance();render();
};
$('toggleComposer').onclick=()=>{composerExpanded=!composerExpanded;syncReadingAppearance();if(composerExpanded&&!$('draft').disabled)$('draft').focus({preventScroll:true});};
$('recordDetails').onclick=()=>{
 const root=$('detailRows');root.replaceChildren();
 for(const row of state.records){const item=document.createElement('li');item.textContent=row.text+(row.image?' [图片附件]':'');root.append(item);}
 $('readingDetails').showModal();
};
$('closeDetails').onclick=()=>$('readingDetails').close();
function appendReadingRecords(root,rows){
 let paragraph=null, length=0, count=0, attachments=0;
 for(const row of rows){
  const timeOnly=/^(?:(?:昨天|前天|星期[一二三四五六日天])\s*)?\d{1,2}:\d{2}$/.test(row.text.trim());
  if(timeOnly&&!row.image){paragraph=null;continue;}
  if(!paragraph||count>=5||length+row.text.length>240||row.image||row.imagePending||row.imageUnavailable||row.text.includes('\n')){
   paragraph=document.createElement('p');paragraph.className='reading-paragraph';root.append(paragraph);length=0;count=0;
  }
  const entry=document.createElement('span');entry.className='reading-entry';entry.dataset.recordId=recordIdentity(row);
  if(count)paragraph.append(document.createTextNode('　'));
  entry.append(document.createTextNode(row.text));
  if(row.image||row.imagePending||row.imageUnavailable){
   const link=document.createElement('button');link.className='reading-attachment';link.textContent=`附件 ${String(++attachments).padStart(2,'0')}.png`;
   link.disabled=!row.image;if(!row.image){link.textContent+=row.imagePending?' · 加载中':' · 暂无预览';link.title='回到图片所在记录后同步，或在微信中查看。';}
   link.onclick=()=>{$('largeImage').src=row.image;$('imageViewer').showModal();};entry.append(link);
  }
  paragraph.append(entry);length+=row.text.length;count++;
  if(row.image||row.imagePending||row.imageUnavailable||row.text.includes('\n'))paragraph=null;
 }
 if(!root.children.length){const empty=document.createElement('p');empty.className='empty-record';empty.textContent='当前仅有时间记录，可在“记录详情”查看。';root.append(empty);}
}
// Stable, display-only terminal decoration. Original records remain the sole data source.
function terminalSeed(value){let seed=2166136261;for(const char of value){seed=Math.imul(seed^char.codePointAt(0),16777619);}return seed>>>0;}
function terminalColumns(value){let width=0;for(const char of value)width+=char.codePointAt(0)>255?2:1;return width;}
function appendTerminalRecords(root,rows,columns){
 const units=['transport','scheduler','workspace','registry','pipeline','resolver','indexer','worker'];
 const paths=['src/core/session.ts','src/runtime/queue.ts','src/services/catalog.ts','src/cache/index.ts','src/config/local.ts','src/io/stream.ts'];
 const take=(tokens,budget)=>{let result='';for(const token of tokens){if(result.length+token.length>budget)break;result+=token;}return result;};
 for(const row of rows){
  const seed=terminalSeed((state.current?.key||'')+'\0'+recordIdentity(row));
  const unit=units[seed%units.length],path=paths[(seed>>>4)%paths.length],hex=seed.toString(16).padStart(8,'0');
  const messageWidth=terminalColumns(row.text);
  const target=Math.floor(columns*([.94,.82,.98,.63,.90,.74,.97,.46][(seed>>>8)%8]));
  const available=Math.max(0,target-messageWidth-12);
  const prefixBudget=Math.floor(available*([.12,.68,.35,.82,.51][(seed>>>12)%5]));
  const start=['[trace] ','[debug] ','[build] ','[index] '][seed%4];
  const prefixTokens=[start,unit+' ',`task=${hex.slice(0,4)} `,`source=${path} `,'phase=resolve ',`cache=${seed%3?'hit':'miss'} `,'scope=workspace ',`revision=${hex} `,'mode=incremental ','platform=win32 ','encoding=utf8 ','strategy=local-first '];
  const prefix=take(prefixTokens,prefixBudget);
  const suffixTokens=[`  duration=${12+seed%380}ms`, `  module=${unit}`,`  source=${path}`,`  checksum=${hex}`,`  items=${2+(seed>>>6)%96}`,'  scope=workspace','  output=dist/local','  mode=incremental','  encoding=utf8','  cache=memory','  platform=win32','  dependency=runtime','  format=esm','  target=local'];
  const suffix=take(suffixTokens,Math.max(0,available-prefix.length));
  const line=document.createElement('div');line.className='terminal-output';line.dataset.recordId=recordIdentity(row);
  const decoration=value=>{const span=document.createElement('span');span.className='terminal-decoration';span.setAttribute('aria-hidden','true');span.textContent=value;return span;};
  const message=document.createElement('span');message.className='terminal-message reading-entry';message.textContent=row.text;
  // Keep the complete message in one element, with no generated text inside it.
  line.append(decoration(prefix+'note="'),message,decoration('"'+suffix));
  if(row.image||row.imagePending||row.imageUnavailable){
   const attachment=document.createElement('button');attachment.className='terminal-attachment';
   attachment.textContent=row.image?'[artifact.png]':row.imagePending?'[artifact.png · loading]':'[artifact.png · unavailable]';
   attachment.disabled=!row.image;attachment.title='查看这条记录的图片预览';
   attachment.onclick=()=>{$('largeImage').src=row.image;$('imageViewer').showModal();};line.append(attachment);
  }
  root.append(line);
 }
}
function renderProjects(){
 const container=$('projects');const scroll=container.scrollTop;container.replaceChildren();
 const query=$('search').value.trim().toLowerCase();
 const entries=directoryResults===null?state.sessions:directoryResults;
 entries.forEach(s=>{
  const displayName=s.name;
  if(directoryResults===null&&query&&!s.name.toLowerCase().includes(query)&&!displayName.toLowerCase().includes(query))return;
  const observed=directoryResults===null&&!demo;
  const fresh=observed&&(s.unreadCount>0||sessionActivity.has(s.key));
  const button=document.createElement('button');button.className='project'+(s.key===state.current?.key?' selected':'')+(fresh?' has-unread':'');
  button.title=focusAppearance?displayName:s.name+(s.preview?'\n'+s.preview:'');
  const icon=document.createElement('span');icon.className='project-icon';icon.textContent='▱';
  const text=document.createElement('div');text.className='project-copy';
  const heading=document.createElement('div');heading.className='project-line';
  const name=document.createElement('span');name.className='project-name';name.textContent=displayName;heading.append(name);
  if(fresh&&s.unreadLabel){const badge=document.createElement('span');badge.className='unread-badge';badge.textContent=s.unreadLabel;badge.setAttribute('aria-label',s.unreadLabel+'条未读');heading.append(badge);}
  text.append(heading);
  if(!focusAppearance){const preview=document.createElement('small');preview.className='project-preview';preview.textContent=observed?(s.preview||'暂无消息预览'):(s.category||'联系人');text.append(preview);}
  if(!focusAppearance&&observed&&s.time){const time=document.createElement('small');time.className='project-time';time.textContent=s.time+(s.muted?' · 免打扰':'');text.append(time);}
  button.append(icon,text);button.disabled=busy;button.onclick=()=>selectProject(s);container.append(button);
 });
 if(!container.children.length){const hint=document.createElement('div');hint.className='empty-directory';
  hint.textContent=directoryResults!==null?'没有找到可打开的联系人。请尝试准确备注名或更具体的关键词。':query?'当前目录没有匹配项。按 Enter 或点“搜索联系人”查找其他会话。':'连接后，这里显示最近会话。';container.append(hint);}
 container.scrollTop=scroll;renderUnreadSummary();
 $('searchContacts').disabled=!state.canSearch||demo||busy||!query;
 $('clearDirectory').hidden=!query&&directoryResults===null;
}
async function searchContacts(){
 if(busy||demo||!state.canSearch)return;const query=$('search').value.trim();if(!query)return;
 busy=true;revision++;render();
 try{const result=await api('/api/search',{query});
  if(result.state==='pending'){notify('搜索仍在进行，请稍候再次搜索。');return;}
  if($('search').value.trim()===query){directoryResults=result.results;renderProjects();}
 }catch(error){notify(error.message);}finally{busy=false;render();}
}
async function clearDirectory(){
 if(busy)return;busy=true;revision++;
 try{if(state.canSearch&&!demo)await api('/api/search',{query:''});directoryResults=null;$('search').value='';}
 catch(error){notify(error.message);}finally{busy=false;render();}
}
function renderRecords(){const root=$('recordList');const atBottom=root.scrollHeight-root.scrollTop-root.clientHeight<45;const oldScroll=root.scrollTop;const anchor=Array.from(root.querySelectorAll('[data-record-id]')).find(n=>n.getBoundingClientRect&&n.getBoundingClientRect().bottom>root.getBoundingClientRect().top+1);const anchorId=anchor?.dataset.recordId;const anchorTop=anchor?.getBoundingClientRect?.().top;const query=$('recordSearch').value.trim().toLowerCase();const rows=state.records.filter(r=>!query||r.text.toLowerCase().includes(query));const terminal=document.documentElement.dataset.appearance==='terminal';const columns=terminal?Math.max(24,Math.floor((root.clientWidth-40)/8)):0;const signature=JSON.stringify([state.mode,demo,focusAppearance,terminal,columns,rows]);if(root.dataset.signature!==signature){root.replaceChildren();if(terminal&&rows.length)appendTerminalRecords(root,rows,columns);else if(focusAppearance&&rows.length)appendReadingRecords(root,rows);else rows.forEach((r,i)=>{const row=document.createElement('div');row.className='record';row.dataset.recordId=recordIdentity(r);const number=document.createElement('span');number.className='number';number.textContent=String(i+1).padStart(3,'0');const text=document.createElement('div');text.className='content';text.textContent=r.text;if(r.image){const picture=document.createElement('img');picture.src=r.image;picture.alt='当前窗口中的图片预览';picture.className='record-image';picture.onclick=()=>{$('largeImage').src=r.image;$('imageViewer').showModal();};text.append(picture);}else if(r.imagePending){const pending=document.createElement('small');pending.className='pending-preview';pending.textContent='图片预览加载中…';text.append(pending);}const source=document.createElement('span');source.className='source';source.textContent=demo?'示例资料':r.image?'图片预览':state.mode==='ocr'?'识别文字':'原始记录';row.append(number,text,source);root.append(row);});if(!rows.length){const empty=document.createElement('div');empty.className='empty-record';empty.textContent=query?'没有匹配的记录。':state.view==='navigation'?state.detail:'当前窗口还没有可读取的文字记录。';root.append(empty);}root.dataset.signature=signature;const retained=Array.from(root.querySelectorAll('[data-record-id]')).find(n=>n.dataset.recordId===anchorId);if(retained&&(!atBottom||historyBrowsing||historyDirection==='older'))root.scrollTop=oldScroll+retained.getBoundingClientRect().top-anchorTop;else root.scrollTop=atBottom&&!historyBrowsing?root.scrollHeight:oldScroll;}$('recordCount').textContent=String(state.records.length);}
function updateComposer(){const limit=state.mode==='ocr'?200:4000;$('draft').maxLength=limit;const can=state.connected&&state.canSend&&!demo&&!busy&&!lastSend?.unresolved;$('draft').disabled=!state.connected||demo||state.view==='navigation';$('draft').readOnly=busy;$('sendButton').disabled=!can||!$('draft').value.trim()||$('draft').value.length>limit||(state.mode==='ocr'&&/[\r\n\t]/.test($('draft').value));$('charCount').textContent=$('draft').value.length+' / '+limit;$('sendHint').textContent=demo?'界面预览不发送任何消息。':lastSend?.unresolved?'上次发送待核对；请在设置中检查结果或打开原窗口。':state.hasNativeDraft?'发送时会清空微信当前聊天中的旧草稿，再发送这里的内容。':state.sendNote||'提交记录会通过微信发送给当前对象。';$('checkSend').disabled=!lastSend;$('resolveSend').disabled=!lastSend?.unresolved;renderImageDraft();resizeDraft();}
function render(){$('olderRecords').disabled=$('latestRecords').disabled=busy||demo||!state.canHistory;$('historyStatus').textContent=historyNotice||(state.canHistory?'在记录区域向上滚动，加载更早消息':'当前连接暂不支持历史滚动');$('scopeNote').textContent=state.view==='navigation'?'公众号文章请在微信中查看；联系人目录保持可用，选择好友或群聊即可恢复聊天。':state.mode==='ocr'?'当前使用 OCR：搜索联系人与图片收发暂不可用。':'在记录区域向上滚动查看历史；已读取内容临时保留在本页。图片为微信窗口预览，历史浏览期间点“回到最新”恢复查看新消息。';$('setup').hidden=state.connected;$('connectedArea').hidden=!state.connected;$('demoBanner').hidden=!demo;$('projectTitle').textContent=currentAlias();$('subtitle').textContent=state.connected?'记录、查阅与补充，集中在同一份资料中。':'将往来文字整理为一份持续更新的工作记录。';$('setupDetail').textContent=state.detail||'打开本机连接后即可开始。';$('connectionLabel').textContent=demo?'界面预览':state.connected?'本地已连接':'等待本地连接';$('connectionDot').classList.toggle('connected',state.connected&&!demo);$('renameButton').disabled=!state.current;$('recipient').textContent=document.documentElement.dataset.appearance==='terminal'?(demo?'Demo · sending disabled':state.current?`To: ${state.current.name}`:'To: —'):(demo?'虚构示例 · 不会发送':state.current?`实际对象：${state.current.name}`:'等待选择项目');renderProjects();renderRecords();updateComposer();}
async function refresh(manual=false){if(demo||busy||stopped||refreshing)return;refreshing=true;const version=revision;try{const next=await api('/api/state');if(busy||demo||version!==revision)return;applyState(next);if(next.connected)$('syncTime').textContent=new Date().toLocaleTimeString('zh-CN',{hour12:false});if(manual)notify(next.connected?'已更新本机记录。':next.detail);}catch(error){applyState({connected:false,sessions:[],records:[],canSend:false,detail:error.message});if(manual)notify(error.message);}finally{refreshing=false;}}
async function selectProject(project){
 if(busy)return;
 if(demo){showDemo(project.id);return;}
 cancelComposerFocus?.();
 const startingPage=page;
 let confirmed=null;
 busy=true;revision++;render();
 try{
  const next=await api('/api/select',{id:project.id});
  if(next.state==='pending'){notify(next.detail,true);return;}
  directoryResults=null;$('search').value='';applyState(next);
  if(next.connected&&next.view!=='navigation'&&next.current?.key===project.key)confirmed=next.current;
 }catch(error){notify(error.message);}
 finally{
  busy=false;render();
  if(confirmed&&page===startingPage&&!document.querySelector('dialog[open]')){
   if(page!=='records')setPage('records');
   composerExpanded=true;syncReadingAppearance();
   sidebarCollapsed=true;sidebarReturnFocus=null;
   storage.set('workdesk-sidebar-collapsed','1');syncSidebar();
   renderRecords();resizeDraft();
   if(!$('draft').disabled){
    $('draft').focus({preventScroll:true});
    retainComposerFocus(confirmed)();
   }
  }
 }
}
function showDemo(id='demo1'){rememberDraft();demo=true;const p=demoProjects.find(x=>x.id===id)||demoProjects[0];applyState({connected:true,current:{...p,binding:'demo'},sessions:demoProjects,records:demoRecords[p.id].map((text,i)=>({id:`${id}-${i}`,text})),canSend:false});$('syncTime').textContent='示例';setPage('records');}
async function exitDemo(){demo=false;applyState({connected:false,sessions:[],records:[],canSend:false,detail:'正在检查本机连接…'});await refresh();}
function setPage(next){rememberDraft();page=next;$('recordPage').hidden=next!=='records';$('notesPage').hidden=next!=='notes';$('recordsNav').classList.toggle('active',next==='records');$('notesNav').classList.toggle('active',next==='notes');$('breadcrumb').textContent=next==='records'?'项目资料':'工作笔记';$('privacyButton').textContent=next==='records'?'切换笔记  Esc':'返回资料';$('status').classList.remove('visible');if(next==='notes')$('notes').focus();else {if(!historyBrowsing)sessionActivity.delete(state.current?.key);renderProjects();refresh();}}
let cancelComposerFocus=null;
function retainComposerFocus(captured){
 cancelComposerFocus?.();
 let moved=false;
 let finished=false, frame=null;
 const editor=$('draft');
 const allowed=target=>[document.body,document.documentElement,editor,$('sendButton'),$('sendImage')].includes(target);
 const cleanup=()=>{
  document.removeEventListener('pointerdown',onPointer,true);
  document.removeEventListener('focusin',onFocus,true);
  editor.removeEventListener('blur',onWindowFocus);
  document.removeEventListener('keydown',onKey,true);
  window.removeEventListener('focus',onWindowFocus);
  document.removeEventListener('visibilitychange',onWindowFocus);
  observer.disconnect();
  if(frame!==null)cancelAnimationFrame(frame);
  if(cancelComposerFocus===cancel)cancelComposerFocus=null;
 };
 const cancel=()=>{moved=true;cleanup();};
 const onPointer=event=>{if(event.target!==editor)cancel();};
 const onFocus=event=>{if(!allowed(event.target))cancel();};
 const onKey=event=>{if(event.key==='Tab'||event.key==='Escape')cancel();};
 const restore=()=>{
  if(!finished)return;
  if(moved||page!=='records'||demo||stopped||$('composerArea').hidden
     ||(state.current&&state.current.key!==captured.key)
     ||document.querySelector('dialog[open]')||!allowed(document.activeElement)){cleanup();return;}
  // A transient disabled input or background window is not a deliberate focus move.
  if(editor.disabled||busy||document.hidden||!document.hasFocus())return;
  if(state.current?.binding!==captured.binding){cleanup();return;}
  if(document.activeElement!==editor)editor.focus({preventScroll:true});
 };
 const onWindowFocus=()=>{if(frame!==null)cancelAnimationFrame(frame);frame=requestAnimationFrame(restore);};
 const observer=new MutationObserver(onWindowFocus);
 observer.observe(editor,{attributes:true,attributeFilter:['disabled','readonly']});
 document.addEventListener('pointerdown',onPointer,true);
 document.addEventListener('focusin',onFocus,true);
 editor.addEventListener('blur',onWindowFocus);
 document.addEventListener('keydown',onKey,true);
 window.addEventListener('focus',onWindowFocus);
 document.addEventListener('visibilitychange',onWindowFocus);
 cancelComposerFocus=cancel;
 return ()=>{
  finished=true;
  if(moved)return;
  restore();
  if(cancelComposerFocus!==cancel)return;
  onWindowFocus();
 };
}
async function send(){if($('sendButton').disabled||busy)return;const captured={requestId:crypto.randomUUID(),binding:state.current.binding,text:$('draft').value,key:state.current.key,unresolved:true};const restoreFocus=retainComposerFocus(captured);lastSend=captured;busy=true;revision++;render();try{const result=await api('/api/send',captured);finishSend(result,captured);}catch(error){captured.unresolved=error.outcome!=='rejected';notify(error.message,captured.unresolved);}finally{busy=false;updateComposer();restoreFocus();if(!lastSend.unresolved)refresh();}}
function finishSend(result,captured){if(result.state==='not_sent'){captured.unresolved=false;notify(result.detail||'未点击发送，草稿已保留。',true);updateComposer();return;}captured.unresolved=result.state!=='observed';notify(result.detail||'请核对原窗口。',captured.unresolved);if(!captured.unresolved&&captured.kind==='image'){if(imageDrafts.get(captured.key)?.data===captured.image)imageDrafts.delete(captured.key);updateComposer();return;}if(!captured.unresolved){drafts.delete(captured.key);if(state.current?.key===captured.key&&$('draft').value===captured.text)$('draft').value='';}updateComposer();}
$('sendButton').onclick=send;
$('checkSend').onclick=async()=>{if(!lastSend)return;try{const result=await api('/api/send-status',{requestId:lastSend.requestId});finishSend(result,lastSend);$('settings').close();}catch(error){notify(error.message,true);}};
$('resolveSend').onclick=()=>{if(!lastSend?.unresolved)return;lastSend.unresolved=false;notify('已解除锁定。若原窗口已发送，请先清空此处草稿，避免重复。',true);$('settings').close();updateComposer();};
$('nativeButton').onclick=async()=>{try{await api('/api/native',{});}catch(error){notify(error.message);}};
$('draft').addEventListener('input',()=>{rememberDraft();updateComposer();});
$('draft').addEventListener('compositionstart',()=>{composingDraft=true;});
$('draft').addEventListener('compositionend',()=>{composingDraft=false;compositionEndedAt=performance.now();});
$('draft').addEventListener('keydown',async event=>{
 if(event.key!=='Enter'||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey)return;
 if(event.isComposing||composingDraft||event.keyCode===229)return;
 event.preventDefault();
 if(event.repeat||performance.now()-compositionEndedAt<150||busy||imageReads.has(state.current?.key))return;
 const key=state.current?.key;
 if($('draft').value.trim())await send();
 else if(imageDrafts.has(key))await sendImage();
});
$('draft').addEventListener('paste',event=>{
 const clipboard=event.clipboardData;if(!clipboard)return;
 const items=Array.from(clipboard.items||[]).filter(item=>item.kind==='file'&&item.type.startsWith('image/'));
 const files=items.length?items.map(item=>item.getAsFile()).filter(Boolean):Array.from(clipboard.files||[]).filter(file=>file.type.startsWith('image/'));
 if(!files.length)return; // Let the browser paste plain text at the caret as usual.
 event.preventDefault();
 if(files.length!==1){notify('目前一次支持一张图片，请逐张粘贴。');return;}
 if(!canAttachImage()){notify('当前暂不能添加图片，请检查连接或上次发送状态。');return;}
 const text=clipboard.getData('text/plain');
 if(text){
  const editor=$('draft');
  if(editor.value.length-(editor.selectionEnd-editor.selectionStart)+text.length>editor.maxLength){notify('剪贴板文字超过当前长度限制，请分次粘贴。');return;}
  editor.setRangeText(text,editor.selectionStart,editor.selectionEnd,'end');rememberDraft();updateComposer();
 }
 attachImage(files[0]);
});
$('search').oninput=()=>{directoryResults=null;renderProjects();};$('search').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();searchContacts();}};$('searchContacts').onclick=searchContacts;$('clearDirectory').onclick=clearDirectory;$('recordSearch').oninput=renderRecords;
for(const id of ['refreshSide','refreshButton','connectButton','settingsReconnect'])$(id).onclick=()=>{if(demo)exitDemo();else refresh(true);};
for(const id of ['demoButton','settingsDemo'])$(id).onclick=()=>{$('settings').close();showDemo();};
$('exitDemo').onclick=exitDemo;
$('recordsNav').onclick=() =>setPage('records');$('notesNav').onclick=()=>setPage('notes');$('returnButton').onclick=()=>setPage('records');$('privacyButton').onclick=()=>setPage(page==='records'?'notes':'records');
document.addEventListener('keydown',event=>{
 if(event.isComposing||composingDraft||event.keyCode===229||document.querySelector('dialog[open]'))return;
 if(event.ctrlKey&&event.altKey&&!event.shiftKey&&!event.metaKey&&event.code==='KeyX'&&!event.getModifierState('AltGraph')){
  event.preventDefault();if(!event.repeat)toggleSidebar(true);return;
 }
 if(event.key==='Escape'||(event.ctrlKey&&event.shiftKey&&event.code==='Space')){event.preventDefault();setPage(page==='records'?'notes':'records');}
});
$('tableView').onclick=()=>{$('recordList').classList.remove('document');$('tableView').classList.add('selected');$('documentView').classList.remove('selected');};
$('documentView').onclick=()=>{$('recordList').classList.add('document');$('documentView').classList.add('selected');$('tableView').classList.remove('selected');};
$('settingsButton').onclick=()=>$('settings').showModal();
$('renameButton').onclick=()=>{$('aliasInput').value=currentAlias();$('rename').dataset.key=state.current.key;$('rename').showModal();$('aliasInput').select();};
$('cancelRename').onclick=()=>$('rename').close();
$('renameForm').onsubmit=event=>{event.preventDefault();const key=$('rename').dataset.key;const value=$('aliasInput').value.trim();if(!value)return;aliases[key]=value;if(!storage.set('workdesk-aliases',JSON.stringify(aliases)))notify('别名已修改，但浏览器未允许保存。');$('rename').close();render();};
$('notes').value=storage.get('workdesk-notes');$('noteDate').textContent=new Date().toLocaleDateString('zh-CN');
$('notes').oninput=()=>{$('noteSaved').textContent=storage.set('workdesk-notes',$('notes').value)?'已保存于本机浏览器':'无法保存，请复制保留';};
$('stopButton').onclick=async()=>{if(busy){notify('请等待当前操作结束。');return;}try{await api('/api/stop',{});stopped=true;state={connected:false,sessions:[],records:[],canSend:false,detail:'服务已停止。需要时双击“启动工作台”重新打开。'};render();$('settings').close();notify('本地服务已停止。');}catch(error){notify(error.message);}};
function renderImageDraft(){
 const selected=imageDrafts.get(state.current?.key);
 const loading=imageReads.has(state.current?.key);
 $('imageDraft').hidden=!selected;
 $('imageDraft').querySelector('small').textContent=document.documentElement.dataset.appearance==='terminal'?'Send this image to the recipient shown above.':'点击发送图片后，会发给上方标明的实际对象。';
 if(selected){$('imageThumb').src=selected.preview;$('imageName').textContent=selected.name;}else{$('imageThumb').removeAttribute('src');}
 $('pickImage').disabled=!state.connected||!state.canSendImage||demo||busy||lastSend?.unresolved;
 $('removeImage').disabled=busy||lastSend?.unresolved;
 $('sendImage').disabled=!selected||!state.connected||!state.canSendImage||demo||busy||lastSend?.unresolved||loading;
 if(loading)$('sendButton').disabled=true;
 $('composerShortcut').textContent=loading?'正在读取图片，请稍候…':selected&&$('draft').value.trim()?'Enter 先发文字，再按一次发图片；Shift+Enter 换行。':'Ctrl+V 粘贴文字或图片 · Enter 发送 · Shift+Enter 换行';
}
function canAttachImage(){return Boolean(state.current&&state.connected&&state.canSendImage&&!demo&&!busy&&!lastSend?.unresolved);}
$('pickImage').onclick=()=>$('imageFile').click();
$('imageFile').onchange=()=>{
 const file=$('imageFile').files[0];$('imageFile').value='';if(file)attachImage(file);
};
async function attachImage(file){
 if(!canAttachImage())return;
 const key=state.current.key;
 if(file.size>8*1024*1024||!['image/png','image/jpeg','image/webp'].includes(file.type)){notify('请选择 8 MB 以内的 PNG、JPEG 或 WebP 图片。');return;}
 const readId=Symbol();imageReads.set(key,readId);updateComposer();
 try{const preview=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('无法读取图片。'));reader.readAsDataURL(file);});
 if(imageReads.get(key)!==readId)return;
 imageDrafts.set(key,{name:file.name||'粘贴的图片',preview,data:preview.split(',')[1]});
 }catch(error){if(imageReads.get(key)===readId)notify(error.message);}
 finally{if(imageReads.get(key)===readId)imageReads.delete(key);updateComposer();}
}
$('removeImage').onclick=()=>{imageReads.delete(state.current?.key);imageDrafts.delete(state.current?.key);updateComposer();};
async function sendImage(){
 if($('sendImage').disabled||busy)return;
 const selected=imageDrafts.get(state.current.key);
 const captured={requestId:crypto.randomUUID(),binding:state.current.binding,key:state.current.key,image:selected.data,kind:'image',unresolved:true};
 const restoreFocus=retainComposerFocus(captured);
 lastSend=captured;busy=true;revision++;render();
 try{finishSend(await api('/api/send-image',captured),captured);}
 catch(error){captured.unresolved=error.outcome!=='rejected';notify(error.message,captured.unresolved);}
 finally{busy=false;render();restoreFocus();if(!captured.unresolved)refresh();}
}
$('olderRecords').onclick=()=>loadHistory('older');
$('latestRecords').onclick=()=>loadHistory('latest');
$('recordList').addEventListener('wheel',event=>{
 if(event.ctrlKey||event.deltaY===0||!state.canHistory||demo||$('recordSearch').value.trim())return;
 const root=$('recordList');
 const older=event.deltaY<0&&root.scrollTop<=160;
 const newer=event.deltaY>0&&root.scrollHeight-root.scrollTop-root.clientHeight<=2&&historyBrowsing;
 if(older||newer){if(root.scrollTop<=2||newer)event.preventDefault();loadHistory(older?'older':'newer');}
},{passive:false});
$('recordList').addEventListener('scroll',()=>{
 const list=$('recordList');
 if(list.scrollHeight>list.clientHeight+2&&list.scrollTop<=2&&!historyLoading&&!$('recordSearch').value.trim())loadHistory('older');
});
$('sendImage').onclick=sendImage;
$('closeImage').onclick=()=>$('imageViewer').close();
$('imageViewer').addEventListener('close',()=>$('largeImage').removeAttribute('src'));
window.addEventListener('hashchange',()=>{const key=new URLSearchParams(location.hash.slice(1)).get('key');if(key){token=key;sessionStorage.setItem('workdesk-key',key);history.replaceState(null,'',location.pathname);stopped=false;revision++;refresh();}});
readingReady=true;syncReadingAppearance();render();refresh();setInterval(()=>{if(!$('rename').open)refresh();},1000);

document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});

let draftResizeFrame=0;
const draftObserver=new ResizeObserver(entries=>{
 if(document.documentElement.dataset.appearance!=='terminal')return;
 const width=Math.round(entries[0].contentRect.width);
 if($('draft').dataset.measuredWidth===String(width))return;
 $('draft').dataset.measuredWidth=String(width);
 cancelAnimationFrame(draftResizeFrame);draftResizeFrame=requestAnimationFrame(resizeDraft);
});
draftObserver.observe($('draft'));
window.addEventListener('resize',()=>{cancelAnimationFrame(draftResizeFrame);draftResizeFrame=requestAnimationFrame(resizeDraft);});
