// Lifecycle regressions for the shipped script. No browser packages or network calls.
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../../src/preview.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b}); return {promise,resolve,reject}};
const health = () => new Response(JSON.stringify({status:'ok'}), {headers:{'Content-Type':'application/json'}});
const audio = () => new Response(new Blob(['original fixture']), {headers:{'Content-Type':'audio/mpeg'}});
function fixture(fetcher) {
  const ids = ['preview-form','article-url','article-text','generate-preview','preview-error','preview-result','preview-audio','preview-source','preview-timing','preview-eta','preview-elapsed','preview-download','url-input','text-input'];
  const nodes = Object.fromEntries(ids.map(id => [id, {id,hidden:true,value:'',dataset:{},listeners:{},attributes:{},disabled:false,textContent:'',pause(){},setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]},addEventListener(k,v){this.listeners[k]=v}}]));
  const form=nodes['preview-form']; form.dataset.endpoint='/api/preview'; form.reportValidity=()=>true;
  form.elements={'input-mode':{value:'text'},voice:{value:'en-US-AndrewNeural'}};
  nodes['article-text'].value='An original fictional article.';
  const calls=[], timers=new Map(), intervals=new Map(), events={}, blobs=[], revoked=[]; let next=1;
  class TestURL extends URL {static createObjectURL(blob){blobs.push(blob);return 'blob:fixture-'+blobs.length}static revokeObjectURL(url){revoked.push(url)}}
  const context = {document:{getElementById:id=>nodes[id]},window:{location:{href:'http://demo.test/'},addEventListener:(k,v)=>{events[k]=v}},URL:TestURL,TextEncoder,AbortController,DOMException,TypeError,Error,Blob,Date,
    setTimeout(fn,ms){const id=next++;timers.set(id,{fn,ms});return id},clearTimeout(id){timers.delete(id)},setInterval(fn,ms){const id=next++;intervals.set(id,{fn,ms});return id},clearInterval(id){intervals.delete(id)},
    fetch(input,options){calls.push({url:String(input),options});return fetcher(input,options,calls.length)}};
  vm.runInNewContext(script,context,{filename:'preview.js'});
  return {nodes,calls,timers,intervals,blobs,revoked,submit:()=>form.listeners.submit({preventDefault(){}}),leave:(persisted=true)=>events.pagehide({persisted}),
    fire(ms){const entry=[...timers].find(([,v])=>v.ms===ms);assert.ok(entry,'Expected timer '+ms);timers.delete(entry[0]);entry[1].fn()}};
}
function inactive(f){assert.equal(f.nodes['generate-preview'].disabled,false);assert.equal(f.nodes['preview-timing'].hidden,true);assert.equal(f.intervals.size,0);assert.equal(f.timers.size,0)}

test('cold start polls health before exactly one generation; rapid submits are ignored',async()=>{
 let probes=0,posts=0; const ready=deferred();
 const f=fixture((url)=>String(url).endsWith('/health') ? (++probes===1?Promise.resolve(new Response('Loading',{status:503})):ready.promise) : (posts++,Promise.resolve(audio())));
 const job=f.submit(); await flush();assert.equal(posts,0);await f.submit();assert.equal(probes,1);
 f.fire(2000);await flush();assert.equal(probes,2);assert.equal(posts,0);ready.resolve(health());await job;
 assert.equal(posts,1);assert.equal(f.nodes['preview-result'].hidden,false);inactive(f);
});

test('pagehide aborts waking requests, resets UI, and late health never starts speech',async()=>{
 for(const persisted of [false,true]){
  const old=deferred();const f=fixture(()=>old.promise);const job=f.submit();await flush();const signal=f.calls[0].options.signal;
  f.leave(persisted);assert.equal(signal.aborted,true);inactive(f);old.resolve(health());await job;
  assert.equal(f.calls.length,1);assert.equal(f.nodes['preview-error'].textContent,'');inactive(f);
 }
});

test('cancelled old response cannot replace new audio or reset its pending state',async()=>{
 const old=deferred(),newer=deferred();let posts=0;
 const f=fixture(url=>String(url).endsWith('/health')?Promise.resolve(health()):++posts===1?old.promise:newer.promise);
 const first=f.submit();await flush();f.leave();const second=f.submit();await flush();
 old.resolve(audio());await first;assert.equal(f.nodes['generate-preview'].disabled,true);assert.equal(f.blobs.length,0);
 newer.resolve(audio());await second;assert.equal(f.blobs.length,1);assert.equal(f.nodes['preview-audio'].src,'blob:fixture-1');inactive(f);
});

test('late blob completion after cancellation cannot overwrite newer result',async()=>{
 const body=deferred();let posts=0;
 const f=fixture(url=>Promise.resolve(String(url).endsWith('/health')?health():++posts===1?{ok:true,headers:new Headers({'Content-Type':'audio/mpeg'}),blob:()=>body.promise}:audio()));
 const first=f.submit();await flush();f.leave();await f.submit();const current=f.nodes['preview-audio'].src;
 body.resolve(new Blob(['old audio']));await first;assert.equal(f.nodes['preview-audio'].src,current);assert.equal(f.blobs.length,1);inactive(f);
});

test('late busy JSON cannot mutate a newer request or start another retry',async()=>{
 const oldJSON=deferred(),newHealth=deferred();let probes=0,posts=0;
 const f=fixture(url=>String(url).endsWith('/health')?(++probes===1?Promise.resolve(health()):newHealth.promise):
  (++posts,Promise.resolve({ok:false,status:503,json:()=>oldJSON.promise})));
 const first=f.submit();await flush();f.leave();const second=f.submit();await flush();
 oldJSON.resolve({code:'preview_busy'});await first;
 assert.equal(f.nodes['generate-preview'].textContent,'Generating your preview…');assert.equal(posts,1);assert.equal(f.nodes['preview-timing'].dataset.phase,'waking');
 f.leave();newHealth.resolve(health());await second;inactive(f);
});

test('only explicit busy rejections retry and accepted jobs are never resubmitted',async()=>{
 let posts=0;
 const f=fixture(url=>Promise.resolve(String(url).endsWith('/health')?health():++posts===1?
  new Response(JSON.stringify({code:'preview_busy'}),{status:503,headers:{'Retry-After':'5'}}):audio()));
 const job=f.submit();await flush();assert.equal(posts,1);f.fire(5000);await job;assert.equal(posts,2);inactive(f);
});

test('accepted network errors and rate-limit errors do not retry',async()=>{
 for(const result of [()=>Promise.reject(new TypeError('network failed')),()=>Promise.resolve(new Response(JSON.stringify({error:'Preview limit reached.'}),{status:429}))]){
  let posts=0;const f=fixture(url=>String(url).endsWith('/health')?Promise.resolve(health()):(posts++,result()));
  await f.submit();assert.equal(posts,1);assert.equal(f.nodes['preview-error'].hidden,false);inactive(f);
 }
});

test('wake timeout aborts immediately and an ignored abort cannot produce late audio',async()=>{
 const wake=deferred();const f=fixture(()=>wake.promise);const job=f.submit();await flush();f.fire(90000);
 assert.equal(f.calls[0].options.signal.aborted,true);assert.match(f.nodes['preview-error'].textContent,/took too long/);inactive(f);
 wake.resolve(health());await job;assert.equal(f.calls.length,1);inactive(f);
});

test('generation timeout and late JSON errors do not replace the timeout or retry',async()=>{
 const json=deferred();let posts=0;const f=fixture(url=>String(url).endsWith('/health')?Promise.resolve(health()):
  (posts++,Promise.resolve({ok:false,status:503,json:()=>json.promise})));
 const job=f.submit();await flush();f.fire(250000);assert.match(f.nodes['preview-error'].textContent,/took too long/);inactive(f);
 json.reject(new DOMException('Aborted','AbortError'));await job;assert.equal(posts,1);assert.match(f.nodes['preview-error'].textContent,/took too long/);inactive(f);
});
