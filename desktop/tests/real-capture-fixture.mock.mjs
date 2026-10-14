import {_electron} from '@playwright/test';
import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {prepare} from '../scripts/prepare-real-capture.mjs';
const fixture=await prepare();
const runs=path.resolve('../build/stage4a-stream-fix/real-capture-preparation-tests');await mkdir(runs,{recursive:true});
const output=path.join(runs,'mock-'+randomUUID());
const instance=await _electron.launch({args:[path.join(fixture,'main.cjs'),'--mock-capture','--output',output],timeout:20000});
async function until(predicate){const deadline=Date.now()+12000;while(Date.now()<deadline){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw Error('mock_condition_timeout');}
try {
  const page=await instance.firstWindow();await page.waitForLoadState();
  assert.equal(await page.locator('#start').isDisabled(),true);
  assert.equal(await instance.evaluate(()=>globalThis.__mockCaptureFixture.getSourcesCalls()),0);
  assert.equal(await page.evaluate(()=>window.captureFixture.start(false)),false);
  assert.equal(await instance.evaluate(()=>globalThis.__mockCaptureFixture.getSourcesCalls()),0);
  await page.locator('#consent').check();await page.locator('#start').click();
  await until(async()=>await instance.evaluate(()=>globalThis.__mockCaptureFixture.report().captured)>0);
  assert.ok(await instance.evaluate(()=>globalThis.__mockCaptureFixture.getSourcesCalls())>0);
  await page.locator('#button-a').click();await page.mouse.wheel(0,100);
  const probes=await instance.evaluate(()=>globalThis.__mockCaptureFixture.report().recent.find(x=>x.result==='captured'));
  assert.deepEqual(probes.guards.map(x=>x.stage),['before_mask','after_initial_mask','after_sources','after_final_mask']);
  assert.equal(probes.masks.length,2);assert.equal(probes.guards[2].source.matches,1);
  // Trigger an actual production privacy check using only synthetic DOM/capture.
  await page.locator('.camera-preview').evaluate(el=>el.remove());
  await until(async()=>await instance.evaluate(()=>globalThis.__mockCaptureFixture.recorder.state)==='failed');
  const first=await readFile(path.join(output,'first-failure.json'),'utf8');
  assert.equal(JSON.parse(first).code,'privacy_mask_unavailable');
  const calls=await instance.evaluate(()=>globalThis.__mockCaptureFixture.getSourcesCalls());
  await page.locator('#stop').click();await page.waitForTimeout(300);
  assert.equal(await instance.evaluate(()=>globalThis.__mockCaptureFixture.getSourcesCalls()),calls);
  assert.equal(await page.evaluate(()=>window.captureFixture.start(true)),false);
  assert.equal(await readFile(path.join(output,'first-failure.json'),'utf8'),first);
  const report=JSON.parse(await readFile(path.join(output,'result.json'),'utf8'));
  assert.equal(report.mode,'mock');assert.equal(report.state,'failed');
  assert.equal(/jpeg|base64|data:image|pixels|screenshot/.test(JSON.stringify(report)),false);
  console.log(JSON.stringify({mode:'mock',consent_gate:true,boundary_stages:4,first_failure_preserved:true,no_restart:true,output}));
} finally {await instance.close();}
const cleanup=JSON.parse(await readFile(path.join(output,'cleanup.json'),'utf8'));assert.equal(cleanup.fixture_window_closed,true);
