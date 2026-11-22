// Prints the app's own top job matches (same scoring as the Jobs page) for the "update now" reply.
// Usage: node tools/top.js [new job URLs...]   (run from the repo root; needs Playwright)
const http=require('http'),fs=require('fs'),path=require('path');const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),newU=new Set(process.argv.slice(2));
const srv=http.createServer((q,r)=>{const f=path.join(root,decodeURIComponent(q.url.split('?')[0])==='/'?'index.html':decodeURIComponent(q.url.split('?')[0]));fs.readFile(f,(e,b)=>{if(e){r.writeHead(404);return r.end()}r.writeHead(200,{'Content-Type':f.endsWith('.json')?'application/json':'text/html'});r.end(b)})}).listen(0,async()=>{
 const b=await chromium.launch();const p=await b.newPage();await p.route(/^https?:\/\/(?!127\.0\.0\.1)/,r=>r.abort());
 await p.addInitScript(()=>{sessionStorage.setItem('pa_unlock','1')});await p.goto('http://127.0.0.1:'+srv.address().port+'/index.html#jobs');
 await p.waitForFunction(()=>typeof LIVE!=='undefined'&&LIVE,null,{timeout:15000}).catch(()=>{});
 const out=await p.evaluate(n=>{const f=j=>`${matchOf(j).score}% ${j.t} — ${jobCo(j)}, ${j.loc}${j.sum&&j.sum.sal?' ('+j.sum.sal+')':''}`;const ok=j=>!isPoor(j)&&inTarget(j);
  const nw=JOBS.filter(j=>n.includes(j.u)).sort((a,b)=>matchOf(b).score-matchOf(a).score).map(j=>(ok(j)?'':'[outside target] ')+f(j));
  const top=JOBS.filter(j=>ok(j)&&!trk(j)).sort((a,b)=>matchOf(b).score-matchOf(a).score).slice(0,5).map(f);return {nw,top}},[...newU]);
 console.log('NEW:\n'+(out.nw.join('\n')||'(none)')+'\nTOP UNTRACKED:\n'+out.top.join('\n'));await b.close();srv.close()});
