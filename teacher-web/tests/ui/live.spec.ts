import { test, expect, type Page } from '@playwright/test';
import { execFileSync, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
const origin='http://127.0.0.1:5177';
const python=path.resolve('../.venv-server/Scripts/python.exe');
async function setup(page:Page,mode='relay'){
  await page.goto('about:blank'); // A new synthetic account must bootstrap its own CSRF, not retain the previous React auth state.
  const email=`live-${randomUUID()}@example.invalid`,password='Synthetic-only-49383!';
  const token=execFileSync(python,[path.resolve('tests/issue_test_token.py'),'invite',email],{encoding:'utf8'}).trim();
  expect((await page.request.post('/api/v1/auth/accept-invite',{headers:{Origin:origin},data:{token,name:'Live Test Teacher',password}})).ok()).toBe(true);
  expect((await page.request.post('/api/v1/auth/login',{headers:{Origin:origin},data:{email,password}})).ok()).toBe(true);
  const process=spawn(python,['-u',path.resolve('tests/live_student.py'),email,mode],{stdio:'pipe'});let ack=0;const starts:Record<string,unknown>[]=[];const packets:Record<string,unknown>[]=[];
  let stdout='',stderr='';process.stderr.on('data',data=>{stderr+=data;});
  const item=await new Promise<{exam_id:string;attempt_id:string}>((resolve,reject)=>{
    const timeout=setTimeout(()=>reject(new Error(`Synthetic connection timeout: ${stderr}`)),15000);
    process.on('exit',code=>{clearTimeout(timeout);if(code)reject(new Error(stderr));});
    process.stdout.on('data',data=>{stdout+=data;let newline;while((newline=stdout.indexOf('\n'))>=0){const value=JSON.parse(stdout.slice(0,newline));stdout=stdout.slice(newline+1);if(value.type==='ready'){clearTimeout(timeout);resolve(value);}if(value.type==='frame_ack')ack++;if(value.type==='direct_ready')starts.push(value);if(value.type==='direct_packet')packets.push(value.packet);}});
  });
  try {
    await page.goto(`/#/live/${item.exam_id}`);
    await expect(page.getByText('Live connection established',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:/Synthetic Live Student/}).click();
    await expect(page.getByRole('heading',{name:'Synthetic Live Student',exact:true})).toBeVisible();
  } catch(error){await stop(process);throw error;}
  return {...item,process,acks:()=>ack,starts,packets};
}
async function stop(process:ChildProcessWithoutNullStreams){
  if(process.exitCode!==null)return;
  const exit=new Promise<void>(resolve=>process.once('exit',()=>resolve()));process.stdin.write('exit\n');
  await Promise.race([exit,new Promise<void>(resolve=>setTimeout(resolve,4000))]);if(process.exitCode===null)process.kill();
}

test('active snapshot changes pending to decoded full image without reload and survives student exit',async({page})=>{
  const item=await setup(page,'snapshots');
  try {
    const slot=page.locator('.event-snapshot-slot');
    await expect(slot).toContainText('Snapshot pending');
    const started=Date.now();item.process.stdin.write('snapshot\n');
    const image=slot.locator('img');
    await expect(image).toBeVisible();
    await image.scrollIntoViewIfNeeded();
    await expect.poll(()=>image.evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth>0)).toBe(true);
    console.log(`Synthetic publish-to-browser-decode: ${Date.now()-started} ms`);
    await slot.getByRole('button').click();
    await expect(slot.getByRole('button')).toHaveAttribute('aria-expanded','true');
    const full=page.locator('.snapshot-inspection img');
    await expect.poll(()=>full.evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth>0)).toBe(true);
    await stop(item.process);
    const response=await page.request.get((await image.getAttribute('src'))!);
    expect(response.ok()).toBe(true);expect(response.headers()['content-type']).toContain('image/jpeg');
    const review=await page.request.get(`/api/v1/attempts/${item.attempt_id}/review`);
    expect((await review.json()).sync.receipt_complete).toBe(false);
  } finally {await page.goto('/#/exams');await stop(item.process);}
});

test('real status, deduplicated event, command acknowledgement and independent pause semantics',async({page},info)=>{
  const item=await setup(page);
  try{
    await expect(page.locator('.live-time')).toHaveText('9:50');await page.waitForTimeout(1200);await expect(page.locator('.live-time')).toHaveText('9:50');
    item.process.stdin.write('event\n');await expect(page.locator('.live-event-group li')).toHaveCount(1);
    const actions=page.locator('.live-actions');await actions.getByLabel('Message to student',{exact:true}).fill('Please keep your phone away.');await actions.getByRole('button',{name:'Send command'}).click();
    await expect(page.locator('.live-history .command-applied')).toHaveCount(1);
    await actions.getByLabel('Teacher actions',{exact:true}).selectOption('pause');await actions.getByLabel('Required reason',{exact:true}).fill('Operator test pause');await actions.getByRole('button',{name:'Send command'}).click();
    await expect(page.getByText('Active pause reasons: Teacher pause · Monitoring unavailable')).toBeVisible();
    await actions.getByLabel('Teacher actions',{exact:true}).selectOption('resume');await actions.getByLabel('Required reason',{exact:true}).fill('Clear teacher reason only');await actions.getByRole('button',{name:'Send command'}).click();
    await expect(page.getByText('Active pause reasons: Monitoring unavailable',{exact:true})).toBeVisible();
    await expect(page.locator('.live-history .command-applied')).toHaveCount(3);
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:info.outputPath('live-en.png'),fullPage:true});
    await page.getByLabel('Language',{exact:true}).selectOption('kk');await page.setViewportSize({width:375,height:900});await page.screenshot({path:info.outputPath('live-kk-mobile.png'),fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.getByLabel('Тіл',{exact:true}).selectOption('en');item.process.stdin.write('no_status\n');
    await expect(page.getByText('Stale device status — timer is not advancing here')).toBeVisible({timeout:10000});await expect(actions.getByRole('button',{name:'Send command'})).toBeDisabled();
  }finally{try{if(!page.isClosed())await page.goto('/#/exams',{timeout:3000});}finally{await stop(item.process);}}
});

test('direct production sender RTC uses authenticated signaling and teacher canvas acknowledgement',async({page})=>{
  const item=await setup(page,'direct');let bridge:ReturnType<typeof setInterval>|undefined;
  try{
    await page.exposeBinding('syntheticTransportSend',(_,packet)=>{
      if(packet.type==='signal'&&item.starts[0])item.process.stdin.write(JSON.stringify({type:'stream_send',packet:{...packet,viewer_id:item.starts[0].viewer_id}})+'\n');
    });
    await page.evaluate(()=>{
      const state={acks:0,ready:false,listener:((value:unknown)=>{})};
      (window as any).screenTransport={listen:(cb:(value:unknown)=>void)=>{state.listener=cb;},send:(packet:any)=>{
        if(packet.type==='frame_ack')state.acks++;if(packet.type==='direct.ready')state.ready=true;
        void (window as any).syntheticTransportSend(packet);
      }};
      (window as any).syntheticScreen=state;
    });
    await page.addScriptTag({path:path.resolve('../desktop/build-electron/screen-transport.js')});
    await page.getByRole('button',{name:'View exam monitor',exact:true}).click();await expect.poll(()=>item.starts.length).toBe(1);
    bridge=setInterval(()=>{for(const packet of item.packets.splice(0))void page.evaluate(packet=>(window as any).syntheticScreen.listener(packet),packet).catch(()=>{});},20);
    await page.evaluate(()=>(window as any).syntheticScreen.listener({type:'start'}));
    await expect.poll(()=>page.evaluate(()=>(window as any).syntheticScreen.ready)).toBe(true);
    await page.evaluate(viewer_id=>{
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;const ctx=canvas.getContext('2d')!;
      ctx.fillStyle='#31563c';ctx.fillRect(0,0,640,360);ctx.fillStyle='white';ctx.font='24px sans-serif';ctx.fillText('SYNTHETIC DIRECT MONITOR',40,160);
      const jpeg_base64=canvas.toDataURL('image/jpeg',.85).split(',')[1];let sequence=0;
      (window as any).syntheticScreen.interval=setInterval(()=>{const state=(window as any).syntheticScreen;if(!state.paused){state.sequence=++sequence;state.listener({type:'frame',viewer_id,sequence,captured_at:Date.now(),width:640,height:360,jpeg_base64});}},300);
    },item.starts[0].viewer_id);
    await expect(page.getByText(/Receiving screen frames.*Direct WebRTC/)).toBeVisible({timeout:15000});
    await expect.poll(()=>page.evaluate(()=>(window as any).syntheticScreen.acks)).toBeGreaterThan(0);
    expect(await page.locator('canvas').evaluate((c:HTMLCanvasElement)=>c.getContext('2d')!.getImageData(50,50,1,1).data[3])).toBe(255);
    for(const answered of [0,1,0,1,0]) {
      item.process.stdin.write(JSON.stringify({type:'quiz_progress',answered})+'\n');
      await expect(page.locator('.live-facts')).toContainText(`${answered} /`);
      await expect(page.getByText(/Receiving screen frames.*Direct WebRTC/)).toBeVisible();
      expect(item.starts.length).toBe(1);
    }
    const barrier=await page.evaluate(()=>{const s=(window as any).syntheticScreen;s.paused=true;return s.sequence;});
    item.process.stdin.write(JSON.stringify({type:'stream_send',packet:{type:'capture.recovering',viewer_id:item.starts[0].viewer_id,through_sequence:barrier}})+'\n');
    await expect(page.getByText('Temporarily recovering — waiting for a fresh safe frame',{exact:true}).first()).toBeVisible();
    expect(await page.locator('canvas').evaluate((c:HTMLCanvasElement)=>c.getContext('2d')!.getImageData(50,50,1,1).data[3])).toBe(0);
    await expect(page.getByRole('button',{name:'View exam monitor',exact:true})).toBeDisabled();
    await page.evaluate(()=>(window as any).syntheticScreen.paused=false);
    await expect(page.getByText(/Receiving screen frames.*Direct WebRTC/)).toBeVisible();
    expect(item.starts.length).toBe(1);
    // The real sender reports failure before teardown; teacher must retain it.
    item.process.stdin.write(JSON.stringify({type:'stream_send',packet:{type:'transport',viewer_id:item.starts[0].viewer_id,transport:'unavailable',reason:'privacy_mask_unavailable'}})+'\n');
    await expect(page.getByText(/Technical code: privacy_mask_unavailable/)).toBeVisible();
    const metrics=JSON.parse((await page.locator('[data-stream-metrics]').getAttribute('data-stream-metrics'))!);
    expect(metrics.frames).toBeGreaterThan(1);expect(metrics.lastPresentedAt).toBeGreaterThan(metrics.firstPresentedAt);
    expect(metrics.stoppedAt).toBeGreaterThanOrEqual(metrics.lastPresentedAt);
    await expect(page.getByRole('button',{name:'View exam monitor',exact:true})).toBeEnabled();
    await page.getByRole('button',{name:'Stop viewing',exact:true}).click();await expect(page.getByRole('button',{name:'Stop viewing',exact:true})).toBeDisabled();
  }finally{clearInterval(bridge);await page.evaluate(()=>{clearInterval((window as any).syntheticScreen?.interval);(window as any).syntheticScreen?.listener({type:'stop'});}).catch(()=>{});await stop(item.process);}
});

test('authenticated relay shows synthetic monitor, acknowledges presentation, hides stale pixels and releases on navigation',async({page})=>{
  const item=await setup(page);
  try{
    await page.getByRole('button',{name:'View exam monitor',exact:true}).click();
    await expect(page.getByText(/Receiving screen frames · Server relay/)).toBeVisible({timeout:15000});
    await expect.poll(item.acks).toBeGreaterThan(0);
    await expect(page.getByText('Adaptive quality reduced',{exact:true})).toBeVisible();
    await expect(page.getByText(/Last capture-to-display-ACK round trip: 120 ms/)).toBeVisible();
    await expect(page.locator('canvas')).toBeVisible();
    expect(await page.locator('canvas').evaluate((canvas:HTMLCanvasElement)=>canvas.width===640&&canvas.height===360&&canvas.getContext('2d')!.getImageData(80,80,1,1).data[3]===255)).toBe(true);
    item.process.stdin.write('no_frames\n');await expect(page.getByText('No fresh frame — stale image hidden',{exact:true}).first()).toBeVisible({timeout:7000});
    expect(await page.locator('canvas').evaluate((canvas:HTMLCanvasElement)=>canvas.getContext('2d')!.getImageData(80,80,1,1).data[3])).toBe(0);
    item.process.stdin.write('frames\n');await expect(page.getByText(/Receiving screen frames · Server relay/)).toBeVisible();
    await page.getByRole('button',{name:'Stop viewing',exact:true}).click();await expect(page.getByRole('button',{name:'View exam monitor',exact:true})).toBeEnabled();
    await expect(page.getByRole('button',{name:'Stop viewing',exact:true})).toBeDisabled();
    await page.getByRole('button',{name:'View exam monitor',exact:true}).click();await expect(page.getByText(/Receiving screen frames · Server relay/)).toBeVisible();
    await page.goto('/#/exams');
  }finally{await stop(item.process);}
});
test('saved preparation extension and same-device interruption authorization reuse existing routes',async({page})=>{
  const prep=await setup(page,'preparation');
  try{
    const getAttempts=async()=>{const r=await page.request.get(`/api/v1/exams/${prep.exam_id}/attempts`);return (await r.json()).items;};
    const before=(await getAttempts())[0].preparation_deadline;
    const recorded=page.locator('.live-recorded');await recorded.getByRole('button',{name:'Add 5 minutes of preparation',exact:true}).click();
    await recorded.getByLabel('Required reason').fill('Synthetic preparation allowance');await recorded.getByRole('button',{name:'Confirm action',exact:true}).click();
    await expect(recorded.getByRole('status')).toBeVisible();
    const after=(await getAttempts())[0].preparation_deadline;expect(new Date(after).getTime()-new Date(before).getTime()).toBe(300000);
  }finally{await stop(prep.process);}
  const interrupted=await setup(page);
  try{
    interrupted.process.stdin.write('interrupted\n');const recorded=page.locator('.live-recorded');
    await recorded.getByRole('button',{name:'Authorize same-device recovery',exact:true}).click();
    await recorded.getByLabel('Required reason').fill('Synthetic same-device restart');await recorded.getByRole('button',{name:'Confirm action',exact:true}).click();
    await expect(recorded.getByText('Recovery authorized; student readiness checks still apply')).toBeVisible();
    const detail=await (await page.request.get(`/api/v1/attempts/${interrupted.attempt_id}/sync`)).json();expect(detail.recovery.grant_id).toBeTruthy();
    expect(detail.lifecycle).toBe('interrupted');
  }finally{await stop(interrupted.process);}
});
