// Optional read-only end-to-end test against a running local Workdesk + Chrome CDP.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const endpoint = process.env.CDP_ENDPOINT || 'http://127.0.0.1:19223';
const sessionPath = process.env.WORKDESK_SESSION_FILE || path.join(os.homedir(), '.local/share/workdesk/runtime/18765/session.json');
const session = JSON.parse(fs.readFileSync(sessionPath, 'utf8'));
const targets = await (await fetch(endpoint + '/json/list')).json();
const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise((resolve, reject) => {ws.onopen = resolve; ws.onerror = reject;});
let serial = 0;
const pending = new Map();
ws.onmessage = event => {
 const data = JSON.parse(event.data);
 if (!pending.has(data.id)) return;
 const item = pending.get(data.id); pending.delete(data.id); clearTimeout(item.timer);
 if (data.error) item.reject(new Error(data.error.message)); else item.resolve(data.result);
};
function call(method, params = {}) {
 return new Promise((resolve, reject) => {
  const id = ++serial;
  const timer = setTimeout(() => {pending.delete(id);reject(new Error('CDP timeout: '+method));}, 15000);
  pending.set(id, {resolve, reject, timer}); ws.send(JSON.stringify({id,method,params}));
 });
}
async function evaluate(expression) {
 const result = await call('Runtime.evaluate', {expression,returnByValue:true,awaitPromise:true});
 if (result.exceptionDetails) throw new Error('Browser evaluation failed');
 return result.result.value;
}
async function wait(expression) {
 for (let i=0;i<120;i++) {
  if (await evaluate(expression)) return;
  await new Promise(resolve=>setTimeout(resolve,500));
 }
 throw new Error('Browser state did not settle');
}
try {
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:session.url});
 await wait("!!document.getElementById('directoryTitle') && typeof state !== 'undefined' && state.connected && !busy && state.sessions.some(s=>s.folder)");
 assert.equal(await evaluate("state.directoryView"),'root');
 assert.equal(await evaluate("state.sessions.filter(s=>s.publicAccount).length"),0);
 assert.equal(await evaluate("document.querySelectorAll('#projects .folder').length"),1);
 console.log('页面验证：主目录只有公众号聚合入口，没有平铺公众号。');
 await evaluate("document.querySelector('#projects .folder').click()");
 await wait("state.directoryView==='subscriptions' && !busy");
 assert.equal(await evaluate("document.getElementById('directoryTitle').textContent"),'主会话 / 公众号');
 assert.equal(await evaluate("document.getElementById('backDirectory').disabled"),false);
 assert.equal(await evaluate("state.sessions.every(s=>s.publicAccount)"),true);
 console.log('页面验证：进入公众号目录后，返回按钮启用，列表仅包含公众号。');
 const folderShot = await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 fs.writeFileSync('/tmp/workdesk-subscriptions.png',Buffer.from(folderShot.data,'base64'));
 await evaluate("document.querySelector('#projects .project').click()");
 await wait("!!state.current && !busy");
 if(await evaluate('sidebarCollapsed')) await evaluate("document.getElementById('sidebarToggle').click()");
 assert.equal(await evaluate("document.getElementById('backDirectory').disabled"),false);
 console.log('页面验证：打开具体公众号后，返回按钮仍然可用。');
 await evaluate("document.getElementById('backDirectory').click()");
 await wait("state.directoryView==='root' && !state.current && !busy");
 assert.equal(await evaluate("state.sessions.filter(s=>s.publicAccount).length"),0);
 assert.equal(await evaluate("document.querySelectorAll('#projects .folder').length"),1);
 assert.equal(await evaluate("document.getElementById('draft').disabled"),true);
 await evaluate('refresh(true)');
 await wait("state.directoryView==='root' && !state.current && !busy");
 console.log('页面验证：返回主目录并刷新后，层级保持正确，未跳回公众号。');
 const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 fs.writeFileSync('/tmp/workdesk-root-directory.png',Buffer.from(shot.data,'base64'));
} finally {
 ws.close();
}
