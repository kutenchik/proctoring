import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
const require=createRequire(path.resolve('teacher-web/package.json'));
const {buildSync}=require('esbuild');const {chromium}=require('@playwright/test');
test('synthetic observer exports bounded numeric teacher/server trace, stops once and saves no frame bytes',async()=>{
  const script=buildSync({entryPoints:['scripts/stage4b_synthetic/observer.mjs'],bundle:true,write:false,format:'iife',globalName:'Observer'}).outputFiles[0].text;
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage();await page.route('**/*',r=>r.abort());await page.setContent('<div data-stream-observation><canvas style="visibility:visible"></canvas><button>Stop viewing</button></div>');
    await page.addScriptTag({content:script});
    const result=await page.evaluate(async()=>{
      const panel=document.querySelector('[data-stream-observation]');let sample,stops=0,blob,fetches=0;
      window.setInterval=fn=>{sample=fn;return 1;};window.clearInterval=()=>{};
      window.URL.createObjectURL=b=>{blob=b;return 'blob:synthetic';};window.HTMLAnchorElement.prototype.click=()=>{};
      panel.querySelector('button').onclick=()=>stops++;
      const trace={counts:{presented:10},records:[]};
      window.fetch=async path=>{fetches++;if(path!=='/api/v1/live/view/abc/diagnostics')throw Error('Unexpected path');return {ok:true,text:async()=>JSON.stringify({viewer_id:'abc',trace:{counts:{send_completed:10,ack_forwarded:10},records:[]}})};};
      panel.setAttribute('data-stream-observation',JSON.stringify({viewer_id:'abc',state:'live',transport:'relay'}));
      panel.setAttribute('data-stream-metrics',JSON.stringify({frames:10,firstPresentedAt:performance.now(),lastPresentedAt:performance.now()}));
      panel.setAttribute('data-stream-trace',JSON.stringify(trace));
      Observer.start(Date.now()+150000);
      let duplicateRejected=false;try{Observer.start(Date.now()+10000);}catch{duplicateRejected=true;}
      for(let i=0;i<950;i++)sample();
      await new Promise(r=>setTimeout(r,20));
      return {saved:JSON.parse(await blob.text()),stops,fetches,duplicateRejected};
    });
    assert.equal(result.saved.records.length,900);assert.equal(result.fetches,1);assert.equal(result.stops,1);
    assert.equal(result.duplicateRejected,true);assert.equal(result.saved.server.viewer_id,'abc');
    assert.equal(JSON.stringify(result.saved).includes('jpeg_base64'),false);
  } finally {await browser.close();}
});
