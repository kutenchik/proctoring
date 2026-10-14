import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {chromium} from '@playwright/test';

test('remote observer reads pending and decoded thumbnail/full image without exporting pixels',async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();page.setDefaultTimeout(5000);await page.route('**/*',r=>r.abort());
  await page.setContent('<div class="live-event-group"><li><a href="#/attempt/test">Open</a><div class="event-snapshot"><div class="event-snapshot-slot">Snapshot pending</div></div></li></div>');
  const source=readFileSync('../scripts/stage4b_synthetic/snapshot-observer.mjs','utf8').replaceAll('export function','function');
  await page.addScriptTag({content:source+';window.installSnapshotObserver=start;'});
  await page.evaluate(()=>window.installSnapshotObserver('test',Date.now()+60000));
  await page.waitForFunction(()=>document.querySelector('aside p').textContent.includes('pending'));
  await page.evaluate(()=>{
   const image=document.createElement('img');image.src='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="green"/></svg>');
   document.querySelector('.event-snapshot-slot').replaceChildren(image);
   const figure=document.createElement('figure');figure.append(image.cloneNode());document.querySelector('.event-snapshot').append(figure);
  });
  await page.waitForFunction(()=>document.querySelector('aside p').textContent.includes('available; full image loaded: true'));
  const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Save snapshot numerical diagnostics'}).click();
  const download=await downloadPromise;const data=JSON.parse(readFileSync(await download.path(),'utf8'));
  assert.equal(data.pending_observed,true);assert.equal(data.full_image_loaded,true);assert.ok(data.pending_to_thumbnail_ms>=0);
  assert.equal(JSON.stringify(data).includes('data:image'),false);
 } finally {await browser.close();}
});
