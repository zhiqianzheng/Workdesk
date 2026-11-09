const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const refresh = source.slice(source.indexOf('async function refresh('), source.indexOf('async function selectProject('));

async function run() {
 const context = vm.createContext({
  demo:false,busy:false,stopped:false,refreshing:false,revision:0,
  state:{connected:true,sessions:[{id:'synthetic'}]},
  api:async()=>({pending:true,detail:'Loading'}),
  notify:text=>context.notifications.push(text),notifications:[],
  render:()=>{},applyState:value=>{context.state=value;},
  $:()=>({textContent:''}),Date,
 });
 vm.runInContext(refresh, context);
 await vm.runInContext('refresh(true)',context);
 assert.equal(context.state.connected,true,'pending refresh must not disconnect an active chat');
 assert.equal(context.state.sessions.length,1,'pending refresh must retain the directory');
 assert(context.notifications.includes('Loading'));
 context.refreshing=true;
 const before=context.notifications.length;
 await vm.runInContext('refresh(true)',context);
 assert.equal(context.notifications.length,before+1,'reconnect must give feedback during a running poll');
 context.refreshing=false;
 context.api=async()=>({connected:true,sessions:[{id:'ready'}]});
 await vm.runInContext('refresh()',context);
 assert.equal(context.state.sessions[0].id,'ready','completed slow result must be applied');
 const composer = source.slice(source.indexOf('function updateComposer(){'), source.indexOf('function render(){'));
 const elements = new Map();
 Object.assign(context, {
  state:{connected:true,mode:'native',current:null,canSend:false},demo:false,busy:false,lastSend:null,
  updateAttachments:()=>{},renderImageDraft:()=>{},resizeDraft:()=>{},
  $:id=>{if(!elements.has(id))elements.set(id,{value:''});return elements.get(id);},
 });
 vm.runInContext(composer,context);
 vm.runInContext('updateComposer()',context);
 assert.equal(elements.get('draft').disabled,true,'root directory must not allow composing to the old recipient');
 const authSource=source.slice(source.indexOf('async function renewSession('),source.indexOf('function ',source.indexOf('async function api(')+20));
 const calls=[];
 const auth=vm.createContext({token:'expired',stopped:true,sessionStorage:{setItem:(k,v)=>{auth.saved=v;}},
  fetch:async(path,options)=>{calls.push({path,options});if(path==='/api/session/reconnect')return {ok:true,status:200,json:async()=>({token:'renewed'})};
   return options.headers.Authorization==='Bearer renewed'?{ok:true,status:200,json:async()=>({ready:true})}:{ok:false,status:401,json:async()=>({error:'expired'})};}
 });
 vm.runInContext(authSource,auth);
 const recovered=await vm.runInContext("api('/api/state')",auth);
 assert.equal(recovered.ready,true);
 assert.equal(auth.saved,'renewed');
 assert.equal(auth.stopped,false);
 assert.equal(calls.length,3);
 assert.equal(calls[1].options.headers['X-Workdesk-Reconnect'],'1');
 calls.length=0;
 auth.fetch=async()=>{calls.push(1);return {ok:false,status:401,json:async()=>({error:'denied'})};};
 await assert.rejects(vm.runInContext("api('/api/state')",auth));
 assert.equal(calls.length,2,'failed recovery must not loop');
 console.log('6 frontend regressions passed');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
