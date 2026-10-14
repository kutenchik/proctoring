import { useEffect, useRef, useState } from 'react';
import { mergeCommands, mergeEvents, socketUrl, type LiveCommand, type LiveStudent } from './live-model';

export function useLive(examId:string,csrf:string,onViewStop:(id:string,reason?:string)=>void) {
  const [students,setStudents]=useState<LiveStudent[]>([]),[connection,setConnection]=useState<'connecting'|'online'|'offline'>('connecting');
  const [commands,setCommands]=useState<LiveCommand[]>([]),[revision,setRevision]=useState(0);
  const [partial,setPartial]=useState({truncated:false,total:0});
  const stop=useRef(onViewStop);stop.current=onViewStop;
  useEffect(()=>{
    let closed=false,rejected=false;let received=performance.now();let retry:ReturnType<typeof setTimeout>|undefined;let socket:WebSocket|null=null;
    const stale=()=>{setConnection('offline');setStudents(old=>old.map(s=>({...s,presence:'offline',capabilities:{commands:false,view:false}})));};
    const connect=()=>{
      if(closed)return;setConnection('connecting');socket=new WebSocket(socketUrl('/api/v1/live/teacher'));
      socket.onopen=()=>socket?.send(JSON.stringify({type:'auth',csrf_token:csrf,exam_id:examId}));
      socket.onmessage=e=>{
        if(closed||typeof e.data!=='string'||e.data.length>2_000_000)return;
        let m;try{m=JSON.parse(e.data);}catch{return;}
        received=performance.now();
        if(m.type==='snapshot'&&Array.isArray(m.students)){setStudents(m.students);setConnection('online');setPartial({truncated:m.truncated===true,total:Number(m.total_students)||m.students.length});}
        if(m.type==='student'&&m.student?.attempt_id){setConnection('online');setStudents(old=>old.some(s=>s.attempt_id===m.student.attempt_id)?old.map(s=>s.attempt_id===m.student.attempt_id?m.student:s):[...old,m.student]);}
        if(m.type==='event'&&m.event?.event_id)setStudents(old=>old.map(s=>s.attempt_id===m.attempt_id?{...s,events:mergeEvents(s.events,[m.event])}:s));
        if(m.type==='command'&&m.command?.command_id)setCommands(old=>mergeCommands(old,[m.command]));
        if(m.type==='view.stop')stop.current(m.viewer_id,m.reason);
        if(m.type==='error'){rejected=true;socket?.close();}
      };
      socket.onclose=e=>{if(closed)return;stale();if(!rejected&&e.code!==4401&&e.code!==4403)retry=setTimeout(connect,3000);};
      socket.onerror=()=>socket?.close();
    };
    connect();
    const interval=setInterval(()=>{if(performance.now()-received>6500)stale();if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'ping'}));},2000);
    const unload=()=>{closed=true;socket?.close();};window.addEventListener('pagehide',unload);
    return()=>{closed=true;clearInterval(interval);clearTimeout(retry);socket?.close();window.removeEventListener('pagehide',unload);};
  },[examId,csrf,revision]);
  return {students,connection,commands,partial,remember:(items:LiveCommand[])=>setCommands(old=>mergeCommands(old,items)),reconnect:()=>setRevision(v=>v+1)};
}
