import { _electron } from '@playwright/test';
import { build } from 'esbuild';
import { mkdir,writeFile } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const output=path.resolve('../build/stage4a-stream-fix/focus-investigation');
await mkdir(output,{recursive:true});
await build({entryPoints:['tests/fixtures/capture-focus.ts'],bundle:true,platform:'node',format:'cjs',external:['electron'],outfile:path.join(output,'fixture.cjs')});
const instance=await _electron.launch({args:[path.join(output,'fixture.cjs')],timeout:20000});
const results=[];
try {
  await instance.evaluate(async()=>{for(let i=0;i<100&&!globalThis.captureTest;i++)await new Promise(r=>setTimeout(r,25));if(!globalThis.captureTest)throw Error('fixture_not_ready');});
  const owner=instance.windows().find(p=>p.url().includes('button'));
  for(const action of ['idle','focus','click','scroll','other-focus','owner-focus','move','resize','maximize','restore','zoom']) {
    await instance.evaluate(()=>globalThis.captureTest.begin());
    if(action==='click')await owner.locator('#click').click();
    else if(action==='scroll') {await owner.mouse.move(200,200);await owner.mouse.wheel(0,120);await owner.waitForTimeout(100);}
    else if(action!=='idle')await instance.evaluate((_electron,action)=>{const t=globalThis.captureTest;
      if(action==='focus'||action==='owner-focus')t.owner.focus();
      if(action==='other-focus')t.other.focus();
      if(action==='move')t.owner.setPosition(60,60);
      if(action==='resize')t.owner.setSize(820,620);
      if(action==='maximize')t.owner.maximize();
      if(action==='restore')t.owner.unmaximize();
      if(action==='zoom')t.owner.webContents.setZoomFactor(1.1);
    },action);
    await owner.waitForTimeout(150);
    results.push({action,...await instance.evaluate(()=>globalThis.captureTest.finish())});
  }
  const events=await instance.evaluate(()=>globalThis.captureTest.events);
  const inputs=await owner.evaluate(()=>({clicks:window.testClicks,scroll:window.scrollY}));
  await writeFile(path.join(output,'isolated-electron-diagnostics.json'),JSON.stringify({real_capture:false,results,events,inputs},null,2));
  assert.equal(inputs.clicks,1);assert.ok(inputs.scroll>0);
  assert.equal(results.find(r=>r.action==='focus').after.focus,true);
  assert.equal(results.find(r=>r.action==='other-focus').after.focus,false);
  for(const r of results.slice(0,6))assert.equal(r.ok,true,r.action);
  for(const r of results.slice(6)) {assert.equal(r.ok,false,r.action);assert.equal(r.code,'capture_geometry_changed');assert.equal(r.geometry.stage,'after_sources');}
  assert.deepEqual(results.find(r=>r.action==='move').geometry.failed,['content_x','content_y']);
  assert.deepEqual(results.find(r=>r.action==='resize').geometry.failed,['content_width','content_height']);
  assert.deepEqual(results.find(r=>r.action==='zoom').geometry.failed,['zoom']);
  console.log(JSON.stringify({passed:results.length,inputs,results:results.map(({action,ok,geometry})=>({action,ok,guard:geometry?.stage,failed:geometry?.failed}))}));
} finally {await instance.close();}
