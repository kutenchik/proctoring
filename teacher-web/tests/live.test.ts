import test from 'node:test';
import assert from 'node:assert/strict';
import { commandAllowed, mayExtendPreparation, mayAuthorizeRestart, mergeCommands, mergeEvents, screenOnlyOffer, socketUrl, timerText, type LiveStudent, type LiveCommand } from '../src/live-model';
import { FrameAssembler, frameChunks, frameFresh, validFrame, type ScreenFrame } from '../../shared/live-screen';
import { translate } from '../src/i18n';
import { livePhrases } from '../src/live-i18n';
import { routeFromHash } from '../src/time';

const student:LiveStudent={attempt_id:'a',session_id:'s',student:{full_name:'Test',group:'G',student_id:'1'},presence:'online',last_contact_at:null,events:[],unreviewed_count:0,capabilities:{commands:true,view:true},status:{sequence:1,state:'running',elapsed_seconds:10,remaining_seconds:590,duration_seconds:600,answered:1,total:2,monitoring_healthy:true,pause_reasons:[],monitoring_outage:null,display:{count:1,incident_id:null,ready:true,calibration_ready:true,approval_required:false}}};
test('commands require fresh active authority; recoveries clear only a supported named gate',()=>{
  assert.equal(commandAllowed(student,'warning',true),true);
  assert.equal(commandAllowed({...student,presence:'offline'},'warning',true),false);
  assert.equal(commandAllowed(student,'end',false),false);
  assert.equal(commandAllowed(student,'resume',true),false);
  const paused={...student,status:{...student.status!,state:'paused' as const,pause_reasons:['monitoring','teacher']}};
  assert.equal(commandAllowed(paused,'resume',true),true);assert.equal(commandAllowed(paused,'pause',true),false);
  assert.equal(commandAllowed(paused,'monitoring_recovery',true),false);
  const recovered={...paused,status:{...paused.status,monitoring_outage:{outage_id:'out',duration_seconds:25,healthy:true,recovery_required:true}}};
  assert.equal(commandAllowed(recovered,'monitoring_recovery',true),true);
  const display={...paused,status:{...paused.status,display:{count:1,incident_id:'incident',ready:true,calibration_ready:true,approval_required:true}}};
  assert.equal(commandAllowed(display,'display_recovery',true),true);
  assert.equal(commandAllowed({...display,status:{...display.status,display:{...display.status.display,count:2}}},'display_recovery',true),false);
});
test('canonical identity deduplicates observations and command updates without counting delivery as applied',()=>{
  const event={event_id:'e',event_type:'phone_visible',timestamp:'2026-10-14T12:00:00Z',category:'behavioral' as const};
  assert.equal(mergeEvents([event],[event,{...event,duration_seconds:3}]).length,1);
  const command={command_id:'c',created_at:'2026-10-14',status:'sent'} as LiveCommand;
  const result=mergeCommands([command],[{...command,status:'delivered'}]);assert.equal(result.length,1);assert.equal(result[0].status,'delivered');
  assert.equal(mergeCommands([{...command,status:'applied'}],[command])[0].status,'applied');
  assert.equal(mergeEvents([],Array.from({length:120},(_,i)=>({...event,event_id:`e${i}`}))).length,100);
});
test('screen assembly bounds identity, monotonic sequences, chunks and freshness',()=>{
  let now=0;const assemble=new FrameAssembler('v',()=>now);
  const frame:ScreenFrame={type:'frame',viewer_id:'v',sequence:1,width:320,height:180,captured_at:Date.now(),jpeg_base64:'/9j/'+('AAAA'.repeat(4000))};
  const chunks=frameChunks(frame);assert.ok(chunks.length>1);
  assert.equal(assemble.receive(chunks[1]),null);assert.equal(assemble.receive(chunks[1]),null);
  assert.deepEqual(assemble.receive(chunks[0]),frame);assert.equal(assemble.receive(JSON.stringify(frame)),null);
  assert.equal(assemble.receive(JSON.stringify({...frame,viewer_id:'other',sequence:2})),null);
  assert.equal(validFrame({...frame,width:10000}),false);
  assert.equal(frameFresh(0,2999),true);assert.equal(frameFresh(0,3000),false);assert.equal(frameFresh(null,0),false);
  assert.equal(screenOnlyOffer('v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n'),true);
  assert.equal(screenOnlyOffer('m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'),false);
  const next=frameChunks({...frame,sequence:2});assemble.receive(next[0]);now=1001;assert.equal(assemble.receive(next[1]),null);
});
test('live route, authoritative display and all new translations remain explicit',()=>{
  assert.deepEqual(routeFromHash('#/live/exam-id'),{page:'live',id:'exam-id'});
  assert.equal(timerText(61.2),'1:02');assert.equal(timerText(null),'—');
  assert.equal(socketUrl('/api/v1/live/teacher','https://teacher.example/path'),'wss://teacher.example/api/v1/live/teacher');
  for(const key of Object.keys(livePhrases))for(const language of ['en','ru','kk'] as const)assert.notEqual(translate(language,key),key);
});
test('recorded preparation and restart controls do not substitute for live command or readiness gates',()=>{
  assert.equal(mayExtendPreparation({...student,lifecycle:'admitted',start_authorized:false}),true);
  assert.equal(mayExtendPreparation({...student,lifecycle:'admitted',start_authorized:true}),false);
  assert.equal(mayExtendPreparation({...student,lifecycle:'started',start_authorized:false}),false);
  assert.equal(mayExtendPreparation({...student,lifecycle:'admitted'}),false);
  const interrupted={...student,lifecycle:'interrupted',restart_recovery:{interruption_id:'i',state:'pending'}};
  assert.equal(mayAuthorizeRestart(interrupted),true);
  assert.equal(mayAuthorizeRestart({...interrupted,restart_recovery:{...interrupted.restart_recovery,grant_id:'g'}}),false);
  assert.equal(mayAuthorizeRestart({...interrupted,lifecycle:'ended'}),false);
});
