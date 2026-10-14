// Local-only test driver: production viewer, real Edge decode/canvas/ACK.
import {createRequire} from 'node:module';
import {createInterface} from 'node:readline';
import path from 'node:path';
const require=createRequire(path.resolve('teacher-web/package.json'));
const {chromium}=require('@playwright/test');
const input=createInterface({input:process.stdin});
for await (const line of input) {
  const c=JSON.parse(line),u=new URL(c.origin);
  if(u.protocol!=='https:'||u.hostname!=='127.0.0.1')throw Error('Local TLS only');
  const browser=await chromium.launch({channel:'msedge',headless:true,args:[`--ignore-certificate-errors-spki-list=${c.spki}`]});
  try {
    const page=await browser.newPage();
    await page.goto(c.origin+'/fixture');
    const result=await page.evaluate(async c=>{
      const login=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:c.email,password:c.password})});
      if(!login.ok)throw Error('login_failed');const auth=await login.json();
      const headers={'Content-Type':'application/json','X-CSRF-Token':auth.csrf_token};
      const response=await fetch('/api/v1/attempts/'+c.attempt+'/view',{method:'POST',headers,body:'{}'});
      if(!response.ok)throw Error('lease_failed');const lease=await response.json();
      let latest; const viewer=new window.LiveViewer(lease,auth.csrf_token,document.querySelector('canvas'),s=>latest=s,()=>{});
      const end=performance.now()+16000;
      while((latest?.delivery?.frames??0)<8&&performance.now()<end)await new Promise(r=>setTimeout(r,100));
      const before=latest;
      await fetch('/api/v1/live/view/stop',{method:'POST',headers,body:JSON.stringify({viewer_id:lease.viewer_id})});
      await new Promise(r=>setTimeout(r,400));
      const diagnostics=await (await fetch('/api/v1/live/view/'+lease.viewer_id+'/diagnostics')).json();
      viewer.close('teacher_stopped');
      return {before,after:latest,diagnostics};
    },c);
    process.stdout.write(JSON.stringify(result)+'\n');
  } finally {await browser.close();}
  break;
}
