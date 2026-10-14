import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';
import { chromium } from '@playwright/test';
import { readFileSync } from 'node:fs';
test('persistent warning preserves DOM identity, order and reserved layout through updates and clearing', async()=>{
  const script=buildSync({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {flushSync} from 'react-dom';import {ReviewEvents} from './src/components/ReviewEvents';const root=createRoot(document.getElementById('root'));window.update=(records,healthy=true,raw=0)=>flushSync(()=>root.render(<><span data-raw-label>{raw%2?'left':'unavailable'}</span><div data-raw-box style={{position:'absolute',transform:'translateX('+raw+'px)'}}/><ReviewEvents records={records} healthy={healthy}/></>));`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,format:'iife',write:false}).outputFiles[0].text;
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage();await page.route('**/*',r=>r.abort());
    await page.setContent('<div id="root" style="width:400px"></div>');
    await page.addStyleTag({content:readFileSync('src/styles.css','utf8').replace(/^@import.*$/gm,'')});await page.addScriptTag({content:script});
    const result=await page.evaluate(()=>{
      const row=(state,id='one')=>({event_id:id,event_type:'second_person',state,activated_timestamp:'2026-10-14T10:00:00Z'});
      window.update([row('active')]);const card=document.querySelector('.review-warning'),item=document.querySelector('.event-item');
      const y=document.querySelector('.recent-events').getBoundingClientRect().y;
      for(let i=0;i<100;i++)window.update([row(i%2?'clearing':'active')],true,i);
      const stable=card===document.querySelector('.review-warning')&&item===document.querySelector('.event-item');
      const animations=card.getAnimations().length;
      window.update([row('closed')]);const closed=!document.querySelector('.review-warning');
      const sameY=y===document.querySelector('.recent-events').getBoundingClientRect().y;
      window.update([row('closed'),row('active','two')]);const newId=document.querySelector('.review-warning').getAttribute('data-active-event-id');
      window.update([row('active','two')],false);const unavailable=!document.querySelector('.review-warning');
      return {stable,animations,closed,sameY,newId,unavailable};
    });
    assert.deepEqual(result,{stable:true,animations:0,closed:true,sameY:true,newId:'two',unavailable:true});
  } finally {await browser.close();}
});
