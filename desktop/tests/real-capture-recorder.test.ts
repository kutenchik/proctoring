import test from 'node:test';
import assert from 'node:assert/strict';
import { Recorder } from './fixtures/real-capture/recorder';
import type { CaptureGeometryDiagnostic } from '../../shared/screen-geometry';
const snapshot={sampled_at:1,window_destroyed:false,web_contents_destroyed:false,display_count:1,display_id:1,
  content:[0,0,800,600],display_bounds:[0,0,1920,1080],display_size:[1920,1080],display_scale:1,zoom:1,focused:true,maximized:false};
function geometry():CaptureGeometryDiagnostic{return {stage:'after_sources',failed:['content_x'],before:structuredClone(snapshot),
  after:{...structuredClone(snapshot),content:[1,0,800,600]},events:[],source:{matches:1,width:1280,height:720,empty:false}};}

test('approval and explicit consent are both required, with countdown and no restart',()=>{
  let now=0;const denied=new Recorder(false,'real',()=>now);assert.equal(denied.start(true),false);assert.equal(denied.begin(),false);
  const r=new Recorder(true,'real',()=>now);for(const v of [false,undefined,1,'true',{}])assert.equal(r.start(v),false);
  assert.equal(r.start(true),true);assert.equal(r.begin(),false);now=5000;assert.equal(r.begin(),true);
  r.stop();assert.equal(r.begin(),false);assert.equal(r.start(true),false);
});
test('one in-flight attempt and fixed-size numeric histories; no arbitrary mask or diagnostic text',()=>{
  let now=0;const r=new Recorder(true,'mock',()=>now);r.start(true);
  for(let i=0;i<40;i++){now=5000+i*250;assert.equal(r.begin(),true);assert.equal(r.begin(),false);
    for(let j=0;j<8;j++)r.boundary({...geometry(),failed:[]});
    for(let j=0;j<5;j++)r.mask('initial_mask',Array(20).fill({x:'secret',y:0,width:20,height:20,answer:'secret'}));
    r.success();}
  const report=r.report();assert.equal(report.recent.length,12);assert.equal(report.captured,40);
  assert.ok(report.recent.every(a=>a.guards.length===4&&a.masks.length===2&&a.masks[0].rectangles.length===16));
  assert.equal(JSON.stringify(report).includes('secret'),false);
  now+=250;r.begin();assert.throws(()=>r.boundary({...geometry(),answer:'secret'} as any),/fixture_invalid_numeric_diagnostic/);
});
test('first guard failure is frozen before generic cleanup and secondary errors are bounded',()=>{
  let now=0;const r=new Recorder(true,'real',()=>now);r.start(true);now=5000;r.begin();const g=geometry();r.boundary(g);
  r.fail('capture_geometry_changed',g);const first=JSON.stringify(r.report().first_failure);g.failed.push('zoom');
  for(let i=0;i<10;i++)r.fail('private error text');r.stop();now=100000;
  assert.equal(JSON.stringify(r.report().first_failure),first);assert.equal(r.report().secondary.length,4);
  assert.equal(r.status().seconds,5);assert.equal(r.report().state,'failed');assert.equal(r.begin(),false);
  assert.equal(JSON.stringify(r.report()).includes('private error'),false);
});
test('time bound ends capture, late completion cannot count as a captured frame',()=>{
  let now=0;const r=new Recorder(true,'mock',()=>now);r.start(true);now=155000;
  assert.equal(r.begin(),false);assert.equal(r.state,'complete');assert.equal(r.start(true),false);
  const pending=new Recorder(true,'mock',()=>now);pending.start(true);now+=5000;pending.begin();pending.stop();pending.success();
  assert.equal(pending.report().captured,0);assert.equal(pending.report().first_failure,null);
});
test('transient mask rejection is preserved but not mislabelled as production terminal failure',()=>{
  let now=0;const r=new Recorder(true,'mock',()=>now);r.start(true);now=5000;r.begin();r.fail('privacy_mask_changed');
  assert.equal((r.report().first_failure as any).terminal_in_production,false);assert.equal(r.state,'failed');
});
