import test from 'node:test';
import assert from 'node:assert/strict';
import {buildSync} from 'esbuild';
import {chromium} from '@playwright/test';

test('verified cleanup replaces pending report and stale evidence actions', async()=>{
  const script=buildSync({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {flushSync} from 'react-dom';import {LiveSummary} from './src/screens/LiveSummary';
    const root=createRoot(document.getElementById('root'));
    const workflow={session_id:'session-test',events:{cursor:0,records:[{event_id:'event-1',event_type:'phone_visible',snapshot_path:'snapshots/event-1.jpg'}]},summary:{score:1,total_questions:2},registration:{candidate:null},session:{ended:true,elapsed_seconds:20},quiz:{total:2,mode:'native'},reference:{ready:true},report:{status:'complete',available:true,file_name:'report.pdf'}};
    window.proctoring={evidence:async()=>({ok:false})};
    window.update=(cleaned)=>{workflow.report.available=!cleaned;flushSync(()=>root.render(<LiveSummary state={{protection:{requested:false},config:{remote_enabled:false},synchronization:{fully_synchronized:cleaned}}} workflow={{...workflow}} busy={false}/>))};`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,format:'iife',write:false}).outputFiles[0].text;
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage();await page.route('**/*',r=>r.abort());
    await page.setContent('<div id="root"></div>');await page.addScriptTag({content:script});
    await page.evaluate(()=>window.update(false));
    await page.getByRole('button',{name:'View snapshot',exact:true}).click();
    await page.getByText('Evidence file is unavailable',{exact:true}).waitFor();
    await page.evaluate(()=>window.update(true));
    assert.equal(await page.getByText('Preparing the session report…',{exact:true}).count(),0);
    assert.equal(await page.getByText('Evidence file is unavailable',{exact:true}).count(),0);
    for(const name of ['View snapshot','View reference','Open report','Save report as…'])
      assert.equal(await page.getByRole('button',{name,exact:true}).count(),0);
    await page.getByText('Local uploaded evidence has been removed after complete server receipt. Reports and snapshots remain on the teacher server.',{exact:true}).waitFor();
  } finally {await browser.close();}
});
