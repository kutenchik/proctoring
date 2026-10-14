import test from 'node:test';
import assert from 'node:assert/strict';
import {buildSync} from 'esbuild';
import {chromium} from '@playwright/test';
import {readFileSync} from 'node:fs';

test('snapshot availability preserves event DOM, open state and reserved layout', async()=>{
  const script=buildSync({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {flushSync} from 'react-dom';import {I18nProvider} from './src/i18n';import {EventSnapshot} from './src/EventSnapshot';const root=createRoot(document.getElementById('root'));window.update=(status)=>flushSync(()=>root.render(<I18nProvider><ol><li key="event-1" data-event="event-1"><strong>Phone visible</strong><EventSnapshot attemptId="attempt" snapshot={{status,item_id:status==='available'?'event_file':null}}/></li><li data-next>Next event</li></ol></I18nProvider>));`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,format:'iife',write:false}).outputFiles[0].text;
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage();page.setDefaultTimeout(5000);
    await page.route('**/*',r=>r.abort());
    await page.setContent('<div id="root"></div>');
    await page.addStyleTag({content:readFileSync('src/live.css','utf8')});
    await page.addScriptTag({content:script});
    const result=await page.evaluate(()=>{
      window.update('pending');const row=document.querySelector('[data-event]');const y=document.querySelector('[data-next]').getBoundingClientRect().y;
      window.update('available');const button=document.querySelector('.event-snapshot-slot button');button.click();
      // flush the click update before reading expansion through another render.
      window.update('available');
      const url=document.querySelector('.event-snapshot-slot img').getAttribute('src');
      for(let i=0;i<50;i++)window.update('available');
      return {same:row===document.querySelector('[data-event]'),sameButton:button===document.querySelector('.event-snapshot-slot button'),open:button.getAttribute('aria-expanded'),url,animations:row.getAnimations().length,reserved:y===document.querySelector('.event-snapshot-slot').getBoundingClientRect().bottom};
    });
    assert.equal(result.same,true);assert.equal(result.sameButton,true);assert.equal(result.open,'true');
    assert.equal(result.url,'/api/v1/attempts/attempt/evidence/event_file');assert.equal(result.animations,0);assert.equal(result.reserved,true);
    await page.evaluate(()=>window.update('disabled'));await page.getByText('Snapshots disabled by exam policy').waitFor();
  } finally {await browser.close();}
});
