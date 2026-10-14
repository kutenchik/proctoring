import { FrameAssembler, frameFresh, type ScreenFrame } from '../../shared/live-screen';
import { screenOnlyOffer, socketUrl, type ViewerLease } from './live-model';
import { screenCode } from '../../shared/screen-diagnostic';
import { StreamTrace, type StreamTraceSnapshot } from '../../shared/stream-trace';

export interface ViewQuality {ack_roundtrip_ms:number|null;send_fps:number;width:number;jpeg_quality:number;degraded:boolean;}
export interface ViewState {viewer_id?:string;state: 'starting'|'live'|'degraded'|'recovering'|'unavailable'|'stopped'; transport: 'direct'|'relay'|null; receivedAt: number|null; reason?: string;quality?:ViewQuality;
  trace?:StreamTraceSnapshot;
  delivery?: {frames:number;firstPresentedAt:number|null;lastPresentedAt:number|null;stoppedAt:number|null};}
/** Owns one lease's in-memory decoder, sockets and RTC. Never persists pixels. */
export class LiveViewer {
  private ws: WebSocket; private pc: RTCPeerConnection|null=null; private channel: RTCDataChannel|null=null;
  private assembler: FrameAssembler; private closed=false; private decoding=false;
  private latest: {frame:ScreenFrame; transport:'direct'|'relay'; at:number}|null=null;
  private pendingIce: RTCIceCandidateInit[]=[]; private receivedAt:number|null=null; private transport:'direct'|'relay'|null=null;
  private interval: ReturnType<typeof setInterval>; private fallbackTimer: ReturnType<typeof setTimeout>;
  private lastRenew=0; private deadline=performance.now()+30_000; private lastPaint=-1;
  private quality?:ViewQuality;
  private recoveryBarrier=-1; private recovering=false;
  private trace=new StreamTrace();
  private delivery:NonNullable<ViewState['delivery']>={frames:0,firstPresentedAt:null,lastPresentedAt:null,stoppedAt:null};
  constructor(private lease:ViewerLease,csrf:string,private canvas:HTMLCanvasElement,private notify:(s:ViewState)=>void,private onStopped:()=>void) {
    this.assembler=new FrameAssembler(lease.viewer_id); this.ws=new WebSocket(socketUrl('/api/v1/live/stream'));
    this.ws.onopen=()=>this.send({role:'teacher',viewer_id:lease.viewer_id,csrf_token:csrf});
    this.ws.onmessage=e=>{if(typeof e.data==='string') void this.message(e.data).catch(()=>this.close('invalid_stream'));};
    this.ws.onerror=()=>this.close('connection_lost'); this.ws.onclose=()=>this.close('connection_lost');
    this.fallbackTimer=setTimeout(()=>this.relay('direct_timeout'),8000);
    this.interval=setInterval(()=>{
      const now=performance.now();
      if(now>=this.deadline) {this.close('lease_expired'); return;}
      if(now-this.lastRenew>=5000 && this.ws.readyState===WebSocket.OPEN) {this.send({type:'renew'});this.lastRenew=now;}
      if(!frameFresh(this.receivedAt,now)) this.clearImage();
      this.emit(this.recovering?'recovering':this.receivedAt===null?'starting':frameFresh(this.receivedAt,now)?'live':'degraded');
    },250); this.emit('starting');
  }
  private send(value:unknown) {if(!this.closed&&this.ws.readyState===WebSocket.OPEN) {this.ws.send(JSON.stringify(value));return true;}return false;}
  private emit(state:ViewState['state'],reason?:string) {this.notify({viewer_id:this.lease.viewer_id,state,transport:this.transport,receivedAt:this.receivedAt,reason,quality:this.quality,delivery:{...this.delivery},trace:this.trace.snapshot()});}
  private async message(text:string) {
    if(this.closed || text.length>384*1024) return;
    const value=JSON.parse(text);
    if(value.type==='capture.recovering') {
      if(value.viewer_id!==this.lease.viewer_id || !Number.isSafeInteger(value.through_sequence) || value.through_sequence<0) {this.close('invalid_stream');return;}
      this.recoveryBarrier=Math.max(this.recoveryBarrier,value.through_sequence);
      // A direct fresh frame may arrive before this ordered socket notification.
      if(this.lastPaint<=this.recoveryBarrier) {
        this.recovering=true;this.latest=null;this.assembler.clear();this.clearImage();this.receivedAt=null;this.emit('recovering');
      }
      return;
    }
    if(value.type==='quality'&&value.viewer_id===this.lease.viewer_id){
      if((value.ack_roundtrip_ms===null||Number.isFinite(value.ack_roundtrip_ms)&&value.ack_roundtrip_ms>=0)&&Number.isFinite(value.send_fps)&&Number.isFinite(value.width)&&Number.isFinite(value.jpeg_quality)&&typeof value.degraded==='boolean')this.quality=value;
      return;
    }
    if(value.type==='frame') {this.frame(text,'relay');return;}
    if(value.type==='stream.ready'||value.type==='renewed') {this.deadline=performance.now()+Math.min(30,Number(value.lease_seconds)||30)*1000;return;}
    if(value.type==='view.stop'||value.type==='view.expired'||value.type==='error') {this.close(screenCode(value.reason??value.code)==='unknown_failure'?'lease_stopped':screenCode(value.reason??value.code));return;}
    if(value.type==='transport'&&value.transport==='unavailable') {this.close(screenCode(value.reason));return;}
    if(value.type==='transport'&&value.transport==='relay') {this.closeRtc();return;}
    if(value.type!=='signal'||value.viewer_id!==this.lease.viewer_id) return;
    const signal=value.signal;
    if(signal.type==='offer') {
      if(!screenOnlyOffer(signal.sdp)){this.close('unsupported_media_tracks');return;}
      this.closeRtc(); this.pc=new RTCPeerConnection({iceServers:[]}); const pc=this.pc;
      pc.onicecandidate=e=>this.send({type:'signal',viewer_id:this.lease.viewer_id,signal:{type:'ice',candidate:e.candidate?.toJSON()??null}});
      pc.onconnectionstatechange=()=>{if(['failed','disconnected','closed'].includes(pc.connectionState)&&!this.closed) this.relay('direct_lost');};
      pc.ondatachannel=e=>{
        if(e.channel.label!=='screen') {e.channel.close();return;}
        this.channel=e.channel; e.channel.onmessage=message=>{if(typeof message.data==='string') this.frame(message.data,'direct');};
        e.channel.onerror=()=>this.relay('direct_error'); e.channel.onclose=()=>{if(!this.closed) this.relay('direct_closed');};
      };
      try {
        await pc.setRemoteDescription({type:'offer',sdp:signal.sdp});
        for(const ice of this.pendingIce.splice(0)) await pc.addIceCandidate(ice);
        await pc.setLocalDescription(await pc.createAnswer());
        if(!this.closed&&this.pc===pc) this.send({type:'signal',viewer_id:this.lease.viewer_id,signal:{type:'answer',sdp:pc.localDescription?.sdp}});
      } catch {this.relay('direct_unavailable');}
    } else if(signal.type==='ice'&&signal.candidate) {
      if(this.pc?.remoteDescription) await this.pc.addIceCandidate(signal.candidate).catch(()=>this.relay('ice_failed'));
      else if(this.pendingIce.length<32) this.pendingIce.push(signal.candidate);
    }
  }
  private frame(text:string,transport:'direct'|'relay') {
    if(this.closed) return; const frame=this.assembler.receive(text); if(!frame || frame.sequence<=this.recoveryBarrier)return;
    this.trace.record('frame_received',frame.sequence,text.length);
    if(this.latest)this.trace.record('frame_replaced',this.latest.frame.sequence);
    this.latest={frame,transport,at:performance.now()}; if(!this.decoding) void this.decode();
  }
  private async decode() {
    this.decoding=true;
    while(this.latest&&!this.closed) {
      const {frame,transport,at}=this.latest;this.latest=null;
      this.trace.record('decode_start',frame.sequence);
      let bitmap:ImageBitmap|undefined;let phase:'decode'|'ack'='decode';
      try {
        const bytes=Uint8Array.from(atob(frame.jpeg_base64),c=>c.charCodeAt(0));
        bitmap=await createImageBitmap(new Blob([bytes],{type:'image/jpeg'}));
        if(this.closed || frame.sequence<=this.recoveryBarrier || frame.sequence<=this.lastPaint || !frameFresh(at,performance.now()) || bitmap.width!==frame.width || bitmap.height!==frame.height) {this.trace.record('decode_discard',frame.sequence);continue;}
        const context=this.canvas.getContext('2d');if(!context){this.close('canvas_unavailable');continue;}
        this.canvas.width=bitmap.width;this.canvas.height=bitmap.height;context.drawImage(bitmap,0,0);
        this.lastPaint=frame.sequence;this.receivedAt=at;this.transport=transport;
        this.recovering=false;
        const presented=performance.now();this.delivery.frames++;this.delivery.firstPresentedAt??=presented;this.delivery.lastPresentedAt=presented;
        this.trace.record('presented',frame.sequence);
        phase='ack';
        const ack={type:'frame_ack',sequence:frame.sequence};
        if(transport==='direct'&&this.channel?.readyState==='open') {this.channel.send(JSON.stringify(ack));this.trace.record('ack_sent',frame.sequence);}
        else this.trace.record(this.send(ack)?'ack_sent':'send_blocked',frame.sequence);
        this.emit('live');
        if(transport==='direct') {clearTimeout(this.fallbackTimer);this.send({type:'transport',viewer_id:this.lease.viewer_id,transport:'direct',reason:'frame_presented'});}
      } catch {
        this.trace.record(phase==='decode'?'decode_failed':'send_blocked',frame.sequence);
        if(!this.closed && frame.sequence>this.recoveryBarrier) {this.clearImage();this.receivedAt=null;this.emit(this.recovering?'recovering':'degraded','invalid_frame');}
      } finally {bitmap?.close();}
    }
    this.decoding=false;
  }
  private relay(reason:string) {if(this.closed)return;clearTimeout(this.fallbackTimer);this.closeRtc();this.send({type:'transport',viewer_id:this.lease.viewer_id,transport:'relay',reason});}
  private closeRtc() {
    if(this.channel){this.channel.onclose=null;this.channel.onmessage=null;this.channel.onerror=null;this.channel.close();this.channel=null;}
    if(this.pc){this.pc.onconnectionstatechange=null;this.pc.onicecandidate=null;this.pc.ondatachannel=null;this.pc.close();this.pc=null;}
  }
  private clearImage() {this.canvas.getContext('2d')?.clearRect(0,0,this.canvas.width,this.canvas.height);}
  close(reason='stopped') {
    if(this.closed)return;this.closed=true;clearInterval(this.interval);clearTimeout(this.fallbackTimer);this.latest=null;this.assembler.clear();this.pendingIce=[];
    this.delivery.stoppedAt=performance.now();
    if(['stopped','teacher_stopped','viewer_changed'].includes(reason) && this.ws.readyState===WebSocket.OPEN)
      try {this.ws.send(JSON.stringify({type:'view.stop',viewer_id:this.lease.viewer_id}));} catch { /* HTTP stop and lease expiry still revoke authority. */ }
    this.closeRtc();this.ws.onmessage=null;this.ws.onclose=null;this.ws.onerror=null;this.ws.close(1000,['stopped','teacher_stopped','viewer_changed'].includes(reason)?'teacher_stopped':'');this.clearImage();this.receivedAt=null;this.emit(['stopped','teacher_stopped','viewer_changed','session_ended'].includes(reason)?'stopped':'unavailable',reason);this.onStopped();
  }
}
