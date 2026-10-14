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
        if(name==='connected.verify') a.verified_server=String(payload?.server_url);
        if(name==='connected.admit'){a.busy='admit';} // No simulated admission success: test pending UI only.
        if(name==='quiz.answer'){w.quiz.answers[String(payload?.question_index)]=payload?.option_indices as number[]; w.quiz.answered=Object.values(w.quiz.answers).filter(v=>!Array.isArray(v)||v.length).length; w.quiz.revision++;}
        if(name==='quiz.navigate') w.quiz.current_index=Number(payload?.question_index);
        w.revision++; w.snapshot_seq++;
        return {version:1,id:'x',ok:true,result:structuredClone(state),...(name==='events.get'?{data:{cursor:0,records:[],has_more:false}}:{})};
      }};
  },{exam});
}

test('connected join is explicit, localized, retains identity and waits for Python', async({page})=>{
  await mock(page); await page.goto('/');
  await expect(page.getByRole('heading',{name:'Join your exam'})).toBeVisible();
  await expect(page.getByText(/teacher server receives your identity/)).toBeVisible();
  await expect(page.getByRole('button',{name:'Join and prepare'})).toBeDisabled();
  await page.getByRole('button',{name:'Verify server'}).click();
  await page.locator('#join-exam_code').fill('ABCD'); await page.locator('#join-full_name').fill('Example Name');
  await page.locator('#join-group').fill('A'); await page.locator('#join-student_id').fill('ID1');
  for(const locale of ['ru','kk','en']) { await page.locator('#language').selectOption(locale); await expect(page.locator('#join-full_name')).toHaveValue('Example Name'); }
  await page.getByRole('button',{name:'Join and prepare'}).click();
  await expect(page.getByText('Contacting teacher server…')).toBeVisible();
  await expect(page.locator('#join-full_name')).toBeDisabled();
  await expect(page.getByRole('heading',{name:'Join your exam'})).toBeVisible();
  await page.screenshot({path:'../artifacts/teacher-stage1-student-join.png',fullPage:true});
});

test('multiple choices submit indices, free navigation and early submit confirm unanswered count',async({page})=>{
  await mock(page,true); await page.goto('/');
  await page.getByRole('checkbox',{name:/Alpha/}).check(); await page.getByRole('checkbox',{name:/Gamma/}).check();
  const calls = await page.evaluate(()=>(window as unknown as {__connected:{calls:unknown[]}}).__connected.calls);
  expect(calls).toContainEqual({name:'quiz.answer',payload:{question_index:0,option_indices:[0,2],revision:1}});
  await page.getByRole('button',{name:'Submit answers',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('Unanswered questions: 1');
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.getByRole('combobox',{name:'Question',exact:true}).selectOption({value:'1'});
  await expect(page.getByText('Choose one', {exact:true}).first()).toBeVisible();
  await page.getByRole('combobox',{name:'Question',exact:true}).selectOption({value:'0'});
  await expect(page.getByRole('checkbox',{name:/Alpha/})).toBeChecked();
});

test('connected join fits narrow layout and has no page errors',async({page})=>{
  const errors:string[]=[]; page.on('pageerror',e=>errors.push(e.message)); await mock(page);
  await page.setViewportSize({width:640,height:720}); await page.goto('/');
  await page.locator('#language').selectOption('kk');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.locator('#teacher-server')).toBeVisible();
  expect(errors).toEqual([]);
});

test('summary reports best-effort delivery failure and never says remote delivery disabled', async({page})=>{
  await mock(page,true); await page.goto('/');
  await page.evaluate(()=>{
    const state=(window as unknown as {__connected:{state:BackendState}}).__connected.state;
    state.admission!.finish_status='failed';
    const w=state.workflow!; w.step='summary'; w.session.ended=true; w.session.running=false;
    w.summary={score:1,total_questions:2,event_count:0,elapsed_seconds:20,events:[],lifecycle:[],security_events:[],end_reason:'completed'};
  });
  await expect(page.getByText(/Result delivery failed/)).toBeVisible();
  await expect(page.getByText(/teacher server receives your identity/)).toBeVisible();
  await expect(page.getByText(/Remote delivery is not enabled/)).toHaveCount(0);
  await page.evaluate(()=>{(window as unknown as {__connected:{state:BackendState}}).__connected.state.admission!.finish_status='sent';});
  await expect(page.getByText(/Teacher server acknowledged the client-reported result/)).toBeVisible();
});

for(const [locale,title,pending,background] of [
  ['en','Evidence synchronization','Pending synchronization','Continue uploading in background'],
  ['ru','Синхронизация материалов','Ожидает синхронизации','Продолжить отправку в фоне'],
  ['kk','Материалдарды синхрондау','Синхрондауды күтуде','Жіберуді фондық режимде жалғастыру'],
]) test(`Stage 2 ${locale}: pending completion is not a receipt, release gates background`,async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await mock(page,true);await page.goto('/');
  await page.evaluate(()=>{
    const state=(window as unknown as {__connected:{state:BackendState}}).__connected.state;
    const w=state.workflow!;w.step='summary';w.session.ended=true;w.session.running=false;
    w.summary={score:1,total_questions:2,event_count:0,elapsed_seconds:20,events:[],lifecycle:[],security_events:[],end_reason:'completed'};
    state.synchronization={status:'pending',error:null,phase:'ended_locally',pending_attempts:1,fully_synchronized:false,background:false,can_background:false,recovery_required:false,recovery_state:null,remaining_seconds:100};
  });
  await page.locator('#language').selectOption(locale);
  await expect(page.getByRole('region',{name:title})).toContainText(pending);
  await expect(page.getByRole('button',{name:background,exact:true})).toBeDisabled();
  await page.evaluate(()=>{(window as unknown as {__connected:{state:BackendState}}).__connected.state.synchronization!.can_background=true;});
  await page.getByRole('button',{name:background,exact:true}).click();
  const calls=await page.evaluate(()=>(window as unknown as {__connected:{calls:unknown[]}}).__connected.calls);
  expect(calls).toContainEqual({name:'sync.background',payload:undefined});
  expect(errors).toEqual([]);
});

test('Stage 2: receipt cleanup and recovery approval are distinct visible states',async({page})=>{
  await mock(page,true);await page.goto('/');
  await page.evaluate(()=>{
    const s=(window as unknown as {__connected:{state:BackendState}}).__connected.state;
    s.workflow!.step='setup';s.workflow!.session.started=false;s.workflow!.session.running=false;
    s.synchronization={status:'needs_attention',error:'invalid_credential',phase:'unexpected_interruption',pending_attempts:1,fully_synchronized:false,background:false,can_background:false,recovery_required:true,recovery_state:'pending',remaining_seconds:87};
  });
  await expect(page.getByText('Interrupted attempt — teacher approval required')).toBeVisible();
  await expect(page.getByText('invalid_credential',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Refresh recovery approval'}).click();
  await page.evaluate(()=>{
    const s=(window as unknown as {__connected:{state:BackendState}}).__connected.state;
    Object.assign(s.synchronization!,{status:'fully_synchronized',error:null,fully_synchronized:true,pending_attempts:0,recovery_required:false});
  });
  await expect(page.getByText('Fully synchronized — matching receipt verified')).toBeVisible();
  await expect(page.getByText(/Local uploaded evidence has been removed/)).toBeVisible();
  await expect(page.getByRole('button',{name:'Continue uploading in background'})).toHaveCount(0);
});
