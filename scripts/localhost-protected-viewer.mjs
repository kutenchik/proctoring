// Bounded localhost test coordinator. Uses the production teacher viewer unchanged.
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const run=path.join(root,'build/localhost-protected/manual-01');
if(!process.argv.includes('--operator-approved'))throw Error('Explicit readiness for real monitor capture is required');
const attempt=process.argv[process.argv.indexOf('--attempt')+1];
if(!process.argv.includes('--attempt')||!/^[a-f0-9]{32}$/.test(attempt))throw Error('Exact attempt required');
const credentials=JSON.parse(await readFile(path.join(run,'operator-private.json'),'utf8'));
const exam=JSON.parse(await readFile(path.join(run,'exams.json'),'utf8'))['A-normal'];
const require=createRequire(path.join(root,'teacher-web/package.json'));
const {chromium}=require('@playwright/test');
const browser=await chromium.launch({channel:'msedge',headless:true});
const cap=setTimeout(()=>void browser.close(),60000);
const samples=[];
try{
  const context=await browser.newContext({baseURL:'http://127.0.0.1:5174'});
  const login=await context.request.post('/api/v1/auth/login',{headers:{Origin:'http://127.0.0.1:5174'},data:{email:credentials.email,password:credentials.password}});
  if(!login.ok())throw Error('Teacher login failed');
  const attempts=await context.request.get(`/api/v1/exams/${exam.id}/attempts`);
  if(!attempts.ok()||!(await attempts.json()).items.some(a=>(a.attempt_id??a.id)===attempt))throw Error('Attempt does not belong to prepared normal exam');
  const page=await context.newPage();page.setDefaultTimeout(10000);
  await page.goto(`/#/live/${exam.id}`);
  await page.getByRole('button').filter({hasText:'Stage 4C Student A'}).click();
  await page.getByRole('button',{name:'View exam monitor',exact:true}).click();
  const until=Date.now()+35000;
  while(Date.now()<until){
    const sample=await page.locator('[data-stream-observation]').evaluate(el=>({at:Date.now(),view:JSON.parse(el.getAttribute('data-stream-observation')),metrics:JSON.parse(el.getAttribute('data-stream-metrics')||'null')}));
    samples.push(sample);
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  await page.screenshot({path:path.join(run,'protected-monitor.png')});
  await page.getByRole('button',{name:'Stop viewing',exact:true}).click();
  await page.getByRole('button',{name:'View exam monitor',exact:true}).waitFor({state:'visible'});
  samples.push(await page.locator('[data-stream-observation]').evaluate(el=>({at:Date.now(),view:JSON.parse(el.getAttribute('data-stream-observation'))})));
}finally{
  clearTimeout(cap);await browser.close();
  await writeFile(path.join(run,'viewer-observation.json'),JSON.stringify(samples,null,2));
}
console.log(JSON.stringify({samples:samples.length,received:samples.some(s=>(s.metrics?.frames??0)>0),last:samples.at(-1)}));
