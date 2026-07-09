// Crisp per-page PNG via CDP clip. Usage: node clip-shot.mjs <html> <outDir> <page1> [page2 ...]
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, basename } from 'node:path';
import { pathToFileURL } from 'node:url';

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const [htmlPath, outDir, ...pages] = process.argv.slice(2);
const PORT = 9544;
const PAGE_H = 296 * 96 / 25.4;   // A4 page height in CSS px
const PAGE_W = 794;
const fileUrl = pathToFileURL(htmlPath).href;
const udd = mkdtempSync(join(tmpdir(), 'cdp-'));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const chrome = spawn(CHROME, ['--headless=new','--disable-gpu','--no-sandbox','--no-first-run',
  '--no-default-browser-check','--hide-scrollbars',`--remote-debugging-port=${PORT}`,`--user-data-dir=${udd}`,'about:blank'], { stdio:'ignore' });

async function ws(){ for(let i=0;i<60;i++){ try{ const r=await fetch(`http://127.0.0.1:${PORT}/json/version`); const j=await r.json(); if(j.webSocketDebuggerUrl) return j.webSocketDebuggerUrl; }catch{} await sleep(250);} throw new Error('no cdp'); }
function client(sock){ let id=0; const pend=new Map(); const wait=[]; sock.addEventListener('message',ev=>{ const m=JSON.parse(ev.data); if(m.id&&pend.has(m.id)){ const{resolve,reject}=pend.get(m.id); pend.delete(m.id); m.error?reject(new Error(m.error.message)):resolve(m.result);} else if(m.method){ for(let i=wait.length-1;i>=0;i--) if(wait[i].method===m.method){wait[i].resolve(m);wait.splice(i,1);} } });
  const send=(method,params={},sessionId)=>new Promise((res,rej)=>{ const mid=++id; pend.set(mid,{resolve:res,reject:rej}); sock.send(JSON.stringify({id:mid,method,params,...(sessionId?{sessionId}:{})})); });
  const waitFor=(method,t=30000)=>new Promise((res,rej)=>{ const w={method,resolve:res}; wait.push(w); setTimeout(()=>{const i=wait.indexOf(w); if(i>=0){wait.splice(i,1);rej(new Error('timeout '+method));}},t); });
  return {send,waitFor}; }

(async()=>{
  const url=await ws(); const sock=new WebSocket(url);
  await new Promise((res,rej)=>{sock.addEventListener('open',res);sock.addEventListener('error',rej);});
  const {send,waitFor}=client(sock);
  const {targetId}=await send('Target.createTarget',{url:'about:blank'});
  const {sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});
  await send('Page.enable',{},sessionId);
  const loaded=waitFor('Page.loadEventFired');
  // natural DPR so mm maps at 96dpi; wide viewport so the page isn't constrained
  await send('Emulation.setDeviceMetricsOverride',{width:1000,height:1200,deviceScaleFactor:1,mobile:false},sessionId);
  await send('Page.navigate',{url:fileUrl},sessionId);
  await loaded; await sleep(700);
  const stem=basename(htmlPath).replace('.html','');
  // real page offsets + width from the DOM
  const {result:offs}=await send('Runtime.evaluate',{returnByValue:true,
    expression:"JSON.stringify([...document.querySelectorAll('.page')].map(e=>({t:e.offsetTop,h:e.offsetHeight,w:e.offsetWidth})))"},sessionId);
  const rects=JSON.parse(offs.value);
  for(const p of pages){
    const n=parseInt(p,10);
    const r=rects[n-1]||{t:(n-1)*PAGE_H,h:PAGE_H,w:PAGE_W};
    const {data}=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,
      clip:{x:0,y:r.t,width:r.w,height:r.h,scale:2}},sessionId);
    const out=join(outDir,`${stem}-p${String(n).padStart(2,'0')}.png`);
    writeFileSync(out,Buffer.from(data,'base64'));
    console.log('shot',out);
  }
  sock.close(); chrome.kill(); process.exit(0);
})().catch(e=>{console.error('ERR',e.message);try{chrome.kill();}catch{}process.exit(1);});
