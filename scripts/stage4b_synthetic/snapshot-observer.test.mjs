import test from 'node:test';
import assert from 'node:assert/strict';
import {summarize} from './snapshot-observer.mjs';
test('browser latency uses one clock and requires actual pending and loaded states',()=>{
 assert.equal(summarize([]).pending_to_thumbnail_ms,null);
 assert.equal(summarize([{state:'available',monotonic_ms:10}]).pending_to_thumbnail_ms,null);
 const result=summarize([{state:'pending',monotonic_ms:20},{state:'available',monotonic_ms:3020,full_image_loaded:false},{state:'available',monotonic_ms:3090,full_image_loaded:true}]);
 assert.equal(result.pending_to_thumbnail_ms,3000);assert.equal(result.full_image_loaded,true);
});
