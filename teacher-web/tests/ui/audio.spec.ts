import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {randomUUID,createHash} from 'node:crypto';
import path from 'node:path';
const origin='http://127.0.0.1:5179';

test('authenticated synthetic audio plays, seeks, amplifies, resets and remains immutable',async({page})=>{
 const email=`audio-${randomUUID()}@example.invalid`,password='Synthetic-audio-9362!';
 const python=path.resolve('../.venv-server/Scripts/python.exe');
 const token=execFileSync(python,[path.resolve('tests/issue_test_token.py'),'invite',email],{encoding:'utf8'}).trim();
 expect((await page.request.post('/api/v1/auth/accept-invite',{headers:{Origin:origin},data:{token,name:'Audio Teacher',password}})).ok()).toBe(true);
 expect((await page.request.post('/api/v1/auth/login',{headers:{Origin:origin},data:{email,password}})).ok()).toBe(true);
 await page.addInitScript(()=>{
   const original=AudioContext.prototype.createGain;
   (window as any).__gains=[];
   AudioContext.prototype.createGain=function(){const gain=original.call(this);(window as any).__gains.push(gain);return gain;};
 });
 await page.goto('/#/configuration/new');
 const editor=page.locator('.configuration-editor');
 await editor.getByLabel('Configuration name',{exact:true}).fill('Audio profile');
 const toggle=editor.getByLabel('Save audio evidence',{exact:true});
 await expect(toggle).not.toBeChecked();
 await editor.getByLabel('Microphone energy monitoring',{exact:true}).check();await toggle.check();
 await editor.getByRole('button',{name:'Advanced',exact:true}).click();
 await editor.getByLabel('Audio before event',{exact:true}).fill('2.5');
 await editor.getByLabel('Audio after event',{exact:true}).fill('4');
 await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await expect(page.getByText('Configuration saved',{exact:true})).toBeVisible();
 await page.reload();await editor.getByRole('button',{name:'Advanced',exact:true}).click();
 await expect(editor.getByLabel('Audio before event',{exact:true})).toHaveValue('2.5');
 await editor.getByRole('button',{name:'Basic',exact:true}).click();
 await editor.getByLabel('Microphone energy monitoring',{exact:true}).uncheck();
 await expect(toggle).toBeEnabled();await toggle.uncheck();
 await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await expect(page.getByText('Configuration saved',{exact:true})).toBeVisible();
 const seed=JSON.parse(execFileSync(python,[path.resolve('tests/audio_seed.py'),email],{encoding:'utf8'}));
 const url=`/api/v1/attempts/${seed.attempt_id}/evidence/${seed.item_id}`;
 const before=await page.request.get(url);expect(before.ok()).toBe(true);
 expect(createHash('sha256').update(await before.body()).digest('hex')).toBe(seed.sha256);
 await page.goto(`/#/live/${seed.exam_id}`);
 await page.getByRole('button',{name:/Synthetic Audio Student/}).click();
 const audio=page.locator('audio');await expect(audio).toHaveCount(1);
 await expect.poll(()=>audio.evaluate((e:HTMLAudioElement)=>e.readyState)).toBeGreaterThan(0);
 expect(await audio.evaluate((e:HTMLAudioElement)=>e.paused)).toBe(true);
 expect(await audio.evaluate((e:HTMLAudioElement)=>e.duration)).toBe(8);
 await audio.click();await audio.evaluate((e:HTMLAudioElement)=>e.play());
 await expect.poll(()=>audio.evaluate((e:HTMLAudioElement)=>e.currentTime)).toBeGreaterThan(.05);
 await page.getByRole('slider').fill('4');
 await expect.poll(()=>page.evaluate(()=>(window as any).__gains[0]?.gain.value)).toBe(4);
 expect(await audio.evaluate((e:HTMLAudioElement)=>e.playbackRate)).toBe(1);
 await audio.evaluate((e:HTMLAudioElement)=>{e.pause();e.currentTime=4;});
 await expect.poll(()=>audio.evaluate((e:HTMLAudioElement)=>e.currentTime)).toBe(4);
 await page.getByRole('button',{name:'Reset to normal volume'}).click();
 expect(await page.evaluate(()=>(window as any).__gains[0].gain.value)).toBe(1);
 // Render the production gain/compression graph and measure actual PCM output.
 const ratio=await page.evaluate(async()=>{
   const modulePath='/src/audio-playback.ts';
   const {gainChain}=await import(/* @vite-ignore */ modulePath);
   async function render(value:number){
     const c=new OfflineAudioContext(1,16000,16000),source=c.createBufferSource();
     source.buffer=c.createBuffer(1,16000,16000);source.buffer.getChannelData(0).fill(.01);
     gainChain(c,source).set(value);source.start();const b=await c.startRendering();
     return Math.sqrt(b.getChannelData(0).reduce((sum,x)=>sum+x*x,0)/16000);
   }
   return await render(4)/await render(1);
 });expect(ratio).toBeGreaterThan(3.8);expect(ratio).toBeLessThan(4.2);
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'test-results/audio/player-mobile.png',fullPage:true});
 await page.goto(`/#/attempt/${seed.attempt_id}`);
 await expect(page.locator('audio')).toHaveCount(1);
 for(const [locale,label] of [['ru','Аудио события'],['kk','Оқиға аудиосы'],['en','Event audio']]){
   await page.locator('select').first().selectOption(locale);
   await expect(page.getByRole('region',{name:label})).toBeVisible();
 }
 const after=await page.request.get(url);expect(createHash('sha256').update(await after.body()).digest('hex')).toBe(seed.sha256);
});
