import { writeFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import type { BackendState } from '../../shared/contracts';

async function mock(page: Page, exam = false) {
  await page.addInitScript(({exam}) => {
    const state = {
      version:1,mode:'exam_workflow',connected:true,language:'en',consent_accepted:false,
      protection:{enabled:false,reason:'development_mode'},
      config:{audio_exam_enabled:false,remote_enabled:false,remote_destinations:[],external_exam_configured:false,registration_enabled:true},
      devices:{scanning:false,cameras:[],microphones:[],errors:{}},
      camera:{selected_key:null,state:'not_started',error:null,fps:0,frame_age_seconds:null,source_width:null,source_height:null,preview_sequence:null},
      audio:{selected_key:null,state:'not_started',error:null,running:false,processed_level:0,frame_age_seconds:null,check:{state:'idle',reason:'',progress:0}},
      unavailable_actions:[],
      admission:{enabled:true,server_url:'https://school.example',verified_server:'',busy:null,error:null,admitted:exam,policy_applied:exam,attempt_id:exam?'a1':null,exam_title:'Example',preparation_remaining_seconds:300,preparation_deadline:null,identity:null,start_authorized:exam},
      workflow:{version:2,step:exam?'exam':'setup',revision:1,snapshot_seq:1,session_id:exam?'session-test':null,config_path:'test',
        registration:{enabled:true,require_group:true,complete:exam,candidate:exam?{first_name:'',last_name:'',group_id:'A',full_name:'Example Name',student_id:'ID1'}:null},
        reference:{enabled:false,ready:false,can_capture:false,status:''},
        calibration:{attempt_id:'c1',phase:'idle',target:'CENTER',presentation_token:null,cue_sequence:0,cue:null,message:'',accepted_samples:0,required_samples:20,completed_targets:[],alignment:{ready:false,reason:'none',message:'',progress:0,guide:[.18,.08,.82,.92]},ready:false,prepare_remaining:0,collection_progress:0,geometry_id:null,diagnostics:{},last_attempt:null,retained_attempts:[]},
        readiness:{ready:false,checks:[]},session:{started:exam,ended:false,running:exam,elapsed_seconds:0,remaining_seconds:120,duration_seconds:120,pause_reasons:[],monitoring_healthy:true,recovery_pin_required:false,end_reason:null},
        quiz:{mode:'native',current_index:0,total:2,answered:0,revision:0,questions:[{id:'q1',type:'multiple_choice',prompt:'Choose two',options:['Alpha','Beta','Gamma'],option_ids:['a','b','c']},{id:'q2',type:'single_choice',prompt:'Choose one',options:['One','Two']}],answers:{}},
        monitoring:{healthy:true,reason:'',gaze_direction:'UNKNOWN',head_pose:null,person_count:1,phone_visible:false,latency_ms:{face:null,yolo:null},fps:0},events:{cursor:0,records:[]},summary:null,report:{status:'disabled',error:null,file_name:'report.pdf',available:false}}
    } as unknown as BackendState;
    state.live_teacher={connection:'online',error:null,consent:{accepted:false,version:3,acknowledged:false},viewing:{viewer_id:null,state:'stopped',transport:null,reason:null},messages:[],display:{count:1,incident_id:null,ready:true,calibration_ready:true,approval_required:false},monitoring_outage:null};
    if(!exam){state.admission!.admitted=true;state.admission!.policy_applied=true;}
    const calls:unknown[]=[]; const controls = {state,calls};
    (window as unknown as { __connected:typeof controls }).__connected=controls;
    if(navigator.mediaDevices) navigator.mediaDevices.getUserMedia=async()=>{throw Error('No hardware in UI tests');};
    window.proctoring={mode:'live',async connection(){return{state:'connected'};},async preview(){return null;},
      onControlChallenge(){return()=>{};},async acknowledgeControlProgress(){return{accepted:false};},onEndRequested(){return()=>{};},
      async reconnect(){return{state:'connected'};},async evidence(){return{ok:false};},async external(){return{configured:false,state:'idle',visible:false,message:''};},
      async geometry(){return{geometry_id:'test',content_bounds:{x:0,y:0,width:1280,height:720},display_bounds:{x:0,y:0,width:1280,height:720},scale_factor:1,zoom_factor:1,center_client:{x:640,y:360},center_visible:true};},
      async acknowledgePresentation(){return{version:1,id:'x',ok:true,result:state};},
      async command(name,payload){
        calls.push({name,payload}); const w=state.workflow!; const a=state.admission!;
        if(name==='screen.consent'){state.live_teacher!.consent.accepted=Boolean(payload?.accepted);}
        if(name==='connected.verify') a.verified_server=String(payload?.server_url);
        if(name==='connected.admit'){a.busy='admit';} // No simulated admission success: test pending UI only.
        if(name==='quiz.answer'){w.quiz.answers[String(payload?.question_index)]=(payload?.option_indices ?? payload?.option_index) as number[]|number; w.quiz.answered=Object.values(w.quiz.answers).filter(v=>!Array.isArray(v)||v.length).length; w.quiz.revision++;}
        if(name==='quiz.navigate') w.quiz.current_index=Number(payload?.question_index);
        w.revision++; w.snapshot_seq++;
        return {version:1,id:'x',ok:true,result:structuredClone(state),...(name==='events.get'?{data:{cursor:0,records:[],has_more:false}}:{})};
      }};
  },{exam});
}


for(const locale of ['en','ru','kk'] as const) test(`live consent and actual viewing state ${locale}`,async({page})=>{
  await mock(page);await page.goto('/');await page.locator('#language').selectOption(locale);
  await expect(page.getByText(({en:'including your live webcam preview',ru:'включая ваше живое превью веб-камеры',kk:'веб-камераңыздың тікелей көрінісін'} as const)[locale],{exact:false})).toBeVisible();
  const consent=page.getByTestId('screen-consent');await expect(consent).toBeVisible();await consent.check();await expect(consent).toBeChecked();
  await expect(page.getByTestId('teacher-viewing')).toHaveCount(0);
  await page.evaluate(()=>{const s=(window as any).__connected.state;s.workflow.step='exam';s.workflow.session.started=true;s.workflow.session.running=true;s.live_teacher.viewing={viewer_id:'v',state:'starting',transport:null,reason:null};});
  await expect(page.getByTestId('exam-time')).toBeVisible();await expect(page.getByTestId('teacher-viewing')).toHaveCount(0);
  await page.evaluate(()=>{const s=(window as any).__connected.state;s.live_teacher.viewing.state='live';s.live_teacher.viewing.transport='relay';s.live_teacher.messages=[{command_id:'c',teacher_id:'t',text:'Please keep your phone away.',timestamp:'2026-10-14T12:00:00Z'}];});
  await expect(page.getByTestId('teacher-viewing')).toBeVisible();await expect(page.getByText('Please keep your phone away.',{exact:true}).first()).toBeVisible();
  await page.screenshot({path:`test-results/live-teacher-${locale}.png`,fullPage:true});
  await page.evaluate(()=>{(window as any).__connected.state.live_teacher.viewing.state='unavailable';});await expect(page.getByTestId('teacher-viewing')).toHaveCount(0);
});

test('native quiz interaction retains preview DOM and active viewing across answers navigation and rapid progress',async({page})=>{
  await mock(page,true);await page.goto('/');await page.locator('#language').selectOption('en');
  await page.evaluate(()=>{
    const s=(window as any).__connected.state;
    s.live_teacher.consent.accepted=true;s.live_teacher.viewing={viewer_id:'a'.repeat(32),state:'live',transport:'direct',reason:null};
  });
  await expect(page.getByTestId('teacher-viewing')).toBeVisible();
  await page.locator('.camera-preview').evaluate(e=>(window as any).__previewIdentity=e);
  for(let i=0;i<4;i++) {
    await page.locator('.answer input').nth(0).check();
    await page.locator('.answer input').nth(1).check();
    await page.locator('.answer input').nth(0).uncheck();
    await page.getByRole('button',{name:'Next',exact:true}).click();
    await page.locator('.answer input').nth(0).check();
    await page.locator('.answer input').nth(1).check();
    await page.getByRole('button',{name:'Previous',exact:true}).click();
    await page.evaluate(()=>{const w=(window as any).__connected.state.workflow;for(let j=0;j<20;j++){w.revision++;w.snapshot_seq++;w.session.remaining_seconds-=.1;}});
    await page.setViewportSize({width:1100+i*40,height:720});
    await expect(page.getByTestId('teacher-viewing')).toBeVisible();
    expect(await page.locator('.camera-preview').evaluate(e=>e===(window as any).__previewIdentity)).toBe(true);
    const r=await page.locator('.camera-preview').boundingBox();expect(r!.width).toBeGreaterThan(0);expect(r!.height).toBeGreaterThan(0);
  }
  const commands=await page.evaluate(()=>(window as any).__connected.calls.filter((c:any)=>!['state.get','events.get'].includes(c.name)));
  expect(commands.every((c:any)=>['quiz.answer','quiz.navigate'].includes(c.name))).toBe(true);
  expect(commands.filter((c:any)=>c.name==='quiz.answer').length).toBeGreaterThan(10);
});


test('webcam preview stays in viewport during quiz and sidebar scroll without opening a device',async({page})=>{
  await mock(page,true);await page.goto('/');await page.locator('#language').selectOption('en');
  await page.locator('.camera-preview').evaluate(e=>(window as any).__previewIdentity=e);
  for(const width of [1280,760,600]) {
    await page.setViewportSize({width,height:720});
    await page.locator('.question-panel').evaluate(e=>(e as HTMLElement).style.minHeight='2000px');
    await page.evaluate(()=>window.scrollTo(0,800));
    const preview=page.locator('.camera-preview');const r=await preview.boundingBox();
    expect(r!.y).toBeGreaterThanOrEqual(0);expect(r!.y+r!.height).toBeLessThanOrEqual(720);
    expect(await preview.evaluate(e=>e===(window as any).__previewIdentity)).toBe(true);
    await page.locator('.monitor-panel').evaluate(e=>e.scrollTop=300);
    const after=await preview.boundingBox();expect(after!.y).toBeGreaterThanOrEqual(0);
    expect(after!.y+after!.height).toBeLessThanOrEqual(720);
    await page.evaluate(()=>window.scrollTo(0,0));
  }
  expect(await page.locator('.camera-preview').count()).toBe(1);
  expect(await page.evaluate(()=>(window as any).__connected.calls.some((c:any)=>/camera|audio/.test(c.name)))).toBe(false);
});


for (const [width,height] of [[360,640],[600,620],[1100,720],[1920,1080]]) for (const locale of ['en','ru','kk']) {
  test(`monitor layout stability ${width} ${locale}`, async ({page}, info) => {
    await page.setViewportSize({width,height}); await mock(page,true); await page.goto('/');
    await page.locator('#language').selectOption(locale);
    await expect(page.locator('.monitor-panel')).toBeVisible();
    await page.evaluate(() => { const s=(window as any).__connected.state; s.config.audio_exam_enabled=true;
      const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=720;
      const ctx=canvas.getContext('2d')!;ctx.fillStyle='#47634b';ctx.fillRect(0,0,1280,720);ctx.fillStyle='#fff';ctx.font='42px sans-serif';ctx.fillText('Synthetic preview - no device',100,350);
      s.camera.state='live';s.camera.selected_key='synthetic';
      window.proctoring!.preview=async()=>({sequence:1,captured_at:1,width:1280,height:720,source_width:1280,source_height:720,mime:'image/jpeg',jpeg_base64:canvas.toDataURL('image/jpeg').split(',')[1],overlays:[]}); });
    await expect(page.locator('.live-audio-meter')).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.locator('.question-panel').evaluate(e=>(e as HTMLElement).style.minHeight='1200px');
    await page.evaluate(() => window.scrollTo(0,150));
    const samples:any[]=[];
    const measure=async(tag:string)=> {
      const value=await page.evaluate(() => {
        const selectors=['.camera-preview','.monitor-title','.module-status','.review-warning-slot','.recent-events','.question-panel','.timer'];
        const bounds=Object.fromEntries(selectors.map(s=>{const e=document.querySelector(s)!;const r=e.getBoundingClientRect();return [s,{x:r.x,y:r.y,width:r.width,height:r.height}];}));
        const panel=document.querySelector('.monitor-panel')!;
        return {bounds,scroll:window.scrollY, panelScroll:panel.scrollTop,recentScroll:document.querySelector('.recent-events')!.scrollTop,scrollHeight:document.documentElement.scrollHeight,panelHeight:panel.scrollHeight,overflow:document.documentElement.scrollWidth>innerWidth};
      }); samples.push({tag,...value});return value;
    };
    await page.locator('.camera-preview').evaluate(e=>(window as any).__stablePreview=e);
    await page.waitForTimeout(500);
    let baseline=await measure('normal');
    for(let i=1;i<=12;i++) {
      if(i===6) {
        await page.locator('.monitor-panel').evaluate(e=>e.scrollTop=80);
        await page.locator('.recent-events').evaluate(e=>e.scrollTop=30);
        await page.evaluate(()=>window.scrollBy(0,30));
        baseline=await measure('user-scroll');
      }
      await page.evaluate(i=>{
        const w=(window as any).__connected.state.workflow;
        const events=Array.from({length:Math.min(5,Math.ceil(i/2))},(_,n)=>({event_id:'event-'+n,event_type:n%2?'VOICE_DETECTED':'phone_raised',record_kind:'review_event',state:n===0&&i<9?'active':'closed',action:'updated',start_timestamp:`2026-10-15T12:00:0${n}Z`,timestamp:'2026-10-15T12:00:10Z',duration_seconds:i}));
        if(i>=11)events.push({ ...events[0],event_id:'next-event',state:'active',start_timestamp:'2026-10-15T12:01:00Z'});
        w.events={cursor:i,records:events};w.monitoring.gaze_direction=i%2?'DOWN':'UNKNOWN';w.snapshot_seq++;
      },i);
      await expect.poll(()=>page.evaluate(()=>(window as any).__connected.calls.filter((c:any)=>c.name==='state.get').length)).toBeGreaterThan(0);
      await expect(page.locator('[data-event-id]')).not.toHaveCount(0);
      await page.waitForTimeout(220);
      const current=await measure('update-'+i);
      expect.soft(current.overflow).toBe(false);
      expect.soft(current.scroll).toBe(baseline.scroll);
      expect.soft(current.panelScroll).toBe(baseline.panelScroll);
      expect.soft(current.recentScroll).toBe(baseline.recentScroll);
      expect.soft(current.scrollHeight).toBe(baseline.scrollHeight);
      for(const selector of ['.camera-preview','.monitor-title','.review-warning-slot','.recent-events','.question-panel','.timer']) {
        for(const axis of ['x','y','width','height'] as const)expect.soft(Math.abs(current.bounds[selector][axis]-baseline.bounds[selector][axis]),selector+' '+axis+' '+i).toBeLessThan(1);
      }
      expect.soft(await page.locator('.camera-preview').evaluate(e=>e===(window as any).__stablePreview)).toBe(true);
      if(i===1)await page.locator('[data-active-event-id]').evaluate(e=>(window as any).__stableWarning=e);
      if(i<9)expect.soft(await page.locator('[data-active-event-id]').evaluate(e=>e===(window as any).__stableWarning)).toBe(true);
    }
    await page.locator('.question-panel').evaluate(e=>(e as HTMLElement).style.minHeight='');
    await page.locator('.monitor-panel').evaluate(e=>e.scrollTop=0);
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:info.outputPath('monitor.png'),fullPage:true});
    for(const size of [{width:1920,height:1080},{width,height}]) {
      await page.setViewportSize(size);await page.waitForTimeout(250);
      expect(await page.locator('.camera-preview').evaluate(e=>e===(window as any).__stablePreview)).toBe(true);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
    }
    expect(await page.evaluate(()=>(window as any).__connected.calls.some((c:any)=>/camera.start|audio.start|exam.start/.test(c.name)))).toBe(false);
    writeFileSync(info.outputPath('measurements.json'),JSON.stringify(samples,null,2));
    await info.attach('measurements',{body:JSON.stringify(samples,null,2),contentType:'application/json'});
  });
}
