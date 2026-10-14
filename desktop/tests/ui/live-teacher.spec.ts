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
