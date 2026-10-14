import { BrowserWindow, ipcMain, session, type IpcMainEvent } from 'electron';
import path from 'node:path';
import type { BackendState } from '../shared/contracts';
import type { PythonBridge } from './bridge';
import { MAX_SCREEN_BYTES, MAX_SCREEN_JSON, type ScreenFrame } from '../../shared/live-screen';
import { captureExamMonitor, TransientMonitorCapture } from './screen_capture';
import { captureGeometry, CaptureGeometryError, CaptureGeometryTrace } from './screen_geometry';
import { screenCode, type ScreenCode, type ScreenDiagnostic } from '../../shared/screen-diagnostic';
import { StreamTrace } from '../../shared/stream-trace';
import { CaptureBudget, captureAllowed, safeAcknowledgement, streamURL, validLease, type ScreenLease } from './screen_policy';

/** Trusted host broker: capability stays here; transport renderer only gets pixels/SDP. */
export class LiveScreen {
  private lease?: ScreenLease; private socket?: WebSocket; private rtc?: BrowserWindow;
  private deadline = 0; private state?: BackendState; private timer?: NodeJS.Timeout;
  private inFlight = false; private pollBusy = false; private generation = 0; private disposed = false;
  private transport: 'direct'|'relay'|null = null; private ready = false; private peerConnected = false; private lastCapture = 0;
  private lastAck = 0; private lastAckSequence = -1; private sequence = 0; private negotiationAt = 0;
  private lastReport = 0; private lastPoll = 0; private budget = new CaptureBudget();
  private sentTimes = new Map<number,number>(); private acknowledgements:number[] = []; private roundtrip:number|null = null; private actualWidth = 0;
  // One terminal record, replaced only by the next lease's terminal transition.
  private diagnostic?: ScreenDiagnostic; private lastFallback: ScreenCode|null = null;
  private geometryTrace:CaptureGeometryTrace;
  private recovering=false; private recoveryAttempts=0; private retryAt=0;
  private monitorBaseline?: ReturnType<typeof captureGeometry>;
  private deliveryTrace = new StreamTrace();
  constructor(private owner: BrowserWindow, private bridge: PythonBridge) {
    this.geometryTrace=new CaptureGeometryTrace(owner);
    ipcMain.on('screen:transport-out',this.fromRTC);
    this.timer = setInterval(() => { void this.tick(); },100); this.timer.unref();
  }
  update(state: BackendState): void { this.state = state; if (this.lease && !this.allowed()) this.stopLease(this.authorizationReason()); }
  private authorizationReason(): ScreenCode {
    if (this.owner.isDestroyed() || this.owner.webContents.isDestroyed()) return 'owner_destroyed';
    if (this.bridge.status.state !== 'connected') return 'backend_disconnected';
    if (this.state?.live_teacher?.connection !== 'online') return 'control_disconnected';
    if (!this.state?.live_teacher?.consent.accepted || this.state.live_teacher.consent.version!==3 || !this.state.live_teacher.consent.acknowledged) return 'consent_lost';
    if (performance.now() >= this.deadline) return 'authorization_expired';
    if (this.state?.workflow?.session.ended) return 'session_ended';
    return 'session_not_active';
  }
  private allowed(): boolean {
    const s = this.state;
    return !this.disposed && !this.owner.isDestroyed() && !this.owner.webContents.isDestroyed() && this.bridge.status.state === 'connected' &&
      s?.live_teacher?.connection === 'online' && captureAllowed(this.lease,{consent:s.live_teacher.consent.accepted && s.live_teacher.consent.version===3 && s.live_teacher.consent.acknowledged,
        attempt:s.admission?.attempt_id ?? null,session:s.workflow?.session_id ?? null,
        active:!!s.workflow?.session.started && !s.workflow.session.ended},this.deadline,performance.now());
  }
  private send(value: unknown): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN || this.socket.bufferedAmount > MAX_SCREEN_JSON) return false;
    try { this.socket.send(JSON.stringify(value)); return true; }
    catch { this.stopLease('stream_send_failed'); return false; }
  }
  private async tick(): Promise<void> {
    if (this.disposed) return;
    if (!this.pollBusy && performance.now() - this.lastPoll >= 500 && this.bridge.status.state === 'connected') {
      this.lastPoll = performance.now();
      this.pollBusy = true;
      void this.bridge.host('live.poll').then(result => {
        if (this.disposed || !result.ok) return;
        const messages = (result.data as {messages?: unknown[]})?.messages;
        if (!Array.isArray(messages) || messages.length > 32) return;
        for (const m of messages) { const v = m as any;
          if (!v || typeof v !== 'object' || Array.isArray(v)) { this.stopLease('invalid_host_message'); return; }
          if (v.type === 'view.start' && validLease(v)) void this.start(v);
          else if (['view.stop','view.expired'].includes(v.type) && v.viewer_id === this.lease?.viewer_id) this.stopLease(v.reason || 'authorization_ended');
        }
      }).catch(() => { this.stopLease('host_channel_unavailable'); }).finally(() => { this.pollBusy = false; });
    }
    if (!this.lease) return;
    if (!this.allowed()) { this.stopLease(this.authorizationReason()); return; }
    const now = performance.now();
    if (this.ready && !this.transport && now - this.negotiationAt >= 5000) this.fallback('direct_timeout');
    if (now - this.lastReport >= 1000) { this.lastReport = now;
      const live = !this.recovering && this.lastAck > 0 && now - this.lastAck < 3000;
      void this.report(this.recovering ? 'recovering' : live ? this.budget.degraded ? 'degraded' : 'live' : 'starting',this.recovering ? 'monitor_capture_failed' : live ? '' : 'waiting_for_verified_frame');
      this.acknowledgements = this.acknowledgements.filter(t => now-t < 1000);
      if (this.peerConnected && this.actualWidth > 0) this.send({type:'quality',viewer_id:this.lease.viewer_id,ack_roundtrip_ms:live ? this.roundtrip:null,
        send_fps:this.acknowledgements.length,width:this.actualWidth,jpeg_quality:this.budget.quality,degraded:this.budget.degraded || !live});
      if (this.transport && now - Math.max(this.lastAck,this.negotiationAt) > 12000) { this.stopLease('frame_delivery_unavailable'); return; }
    }
    if (!this.ready || !this.peerConnected || !this.transport || this.socket?.readyState!==WebSocket.OPEN || this.inFlight || now<this.retryAt || now - this.lastCapture < this.budget.interval) return;
    this.inFlight = true; this.lastCapture = now; const generation = this.generation;
    this.deliveryTrace.record('capture_start',this.sequence+1);
    try {
      this.monitorBaseline??=captureGeometry(this.owner,true);
      const capturedAt = Date.now(), frame = await captureExamMonitor(this.owner,this.budget.width,this.budget.quality,this.geometryTrace,
        ()=>generation===this.generation && this.allowed() && this.ready && this.peerConnected && this.socket?.readyState===WebSocket.OPEN,this.monitorBaseline);
      if (generation !== this.generation || !this.allowed() || !this.peerConnected || this.socket?.readyState!==WebSocket.OPEN) return;
      this.deliveryTrace.record('capture_ready',this.sequence+1,frame.jpeg.length);
      if (frame.jpeg.length > MAX_SCREEN_BYTES || performance.now() - now > 1500) { this.deliveryTrace.record('capture_discard',this.sequence+1);this.budget.congested(); return; }
      const packet: ScreenFrame = {type:'frame',viewer_id:this.lease!.viewer_id,sequence:++this.sequence,captured_at:capturedAt,width:frame.width,height:frame.height,jpeg_base64:frame.jpeg.toString('base64')};
      this.actualWidth = frame.width;
      const sent=this.transport==='direct' ? !!this.rtc && (this.rtc.webContents.send('screen:transport-in',packet),true) : this.send(packet);
      this.deliveryTrace.record(sent?'send':'send_blocked',packet.sequence,this.socket?.bufferedAmount??0);
      if(sent) this.sentTimes.set(packet.sequence,now); else this.budget.congested();
      // Keep the entire existing 12s delivery window at the maximum 5 FPS.
      // A 32-entry cache evicted still-valid delayed ACKs after only 6.4s.
      for(const [seq,at] of this.sentTimes) if(now-at>12000 || this.sentTimes.size>64) {
        this.sentTimes.delete(seq);this.deliveryTrace.record('ack_evicted',seq);
      }
    } catch (error) {
      if (generation===this.generation && this.lease && !this.allowed() && !(error instanceof CaptureGeometryError)) {this.stopLease(this.authorizationReason());return;}
      if (generation === this.generation && this.lease && error instanceof TransientMonitorCapture) {
        if (!this.allowed()) {this.stopLease(this.authorizationReason());return;}
        // No lease/generation/deadline reset. Each next attempt rereads native
        // monitor geometry and the source through the full production guards.
        this.recovering=true; this.recoveryAttempts=Math.min(4,this.recoveryAttempts+1);
        this.retryAt=performance.now()+Math.min(1000,250*2**(this.recoveryAttempts-1));
        this.sentTimes.clear(); // Late acknowledgements of pre-recovery frames cannot extend delivery.
        if(!this.send({type:'capture.recovering',viewer_id:this.lease.viewer_id,through_sequence:this.sequence})) {
          this.stopLease('stream_send_failed');return;
        }
        void this.report('recovering','monitor_capture_failed');
      } else if (generation === this.generation) {
        const code = screenCode(error instanceof Error ? error.message : null);
        this.stopLease(code === 'unknown_failure' ? 'capture_unavailable' : code, {component:'capture',phase:'capture',...(error instanceof CaptureGeometryError?{geometry:error.geometry}:{})});
      }
    }
    finally { this.inFlight = false; }
  }
  private async start(lease: ScreenLease): Promise<void> {
    this.stopLease('viewer_changed'); if (this.disposed) return;
    let url: string; try { url = streamURL(lease.server_url); } catch { return; }
    this.lease = lease; this.deadline = performance.now() + lease.lease_seconds * 1000;
    this.geometryTrace.start();
    this.recovering=false;this.recoveryAttempts=0;this.retryAt=0;this.monitorBaseline=undefined;
    this.budget = new CaptureBudget(); this.lastAck = 0; this.lastAckSequence = -1; this.lastReport = 0; this.sequence = 0;
    this.lastFallback = null;
    this.deliveryTrace = new StreamTrace();
    this.sentTimes.clear(); this.acknowledgements = []; this.roundtrip = null; this.actualWidth = 0;
    if (!this.allowed()) { this.stopLease('session_not_active'); return; }
    const generation = this.generation;
    const ws = this.socket = new WebSocket(url);
    ws.onopen = () => { if (generation !== this.generation) return; this.send({role:'student',viewer_id:lease.viewer_id,token:lease.sender_token}); };
    ws.onmessage = e => {
      if (generation !== this.generation || typeof e.data !== 'string' || e.data.length > 65536) return;
      let m: any; try { m = JSON.parse(e.data); } catch { this.stopLease('invalid_stream_message'); return; }
      if (!m || typeof m !== 'object' || Array.isArray(m) || typeof m.type !== 'string') { this.stopLease('invalid_stream_message'); return; }
      if (m.viewer_id && m.viewer_id !== this.lease?.viewer_id) return;
      if (m.type === 'stream.ready') {
        if (this.ready || m.viewer_id !== this.lease?.viewer_id || m.role !== 'student' || typeof m.peer_connected !== 'boolean' ||
          !Number.isFinite(m.lease_seconds) || m.lease_seconds <= 0 || m.lease_seconds > 30) { this.stopLease('invalid_stream_ready'); return; }
        this.ready = true; this.peerConnected = m.peer_connected; this.negotiationAt = performance.now();
        this.deadline = Math.min(this.deadline,performance.now()+m.lease_seconds*1000);
        void this.startRTC(generation); }
      else if (m.type === 'peer.ready' && this.ready && m.viewer_id === this.lease?.viewer_id) this.peerConnected = true;
      else if (m.type === 'renewed') {
        if (!this.ready || m.viewer_id !== this.lease?.viewer_id || !Number.isFinite(m.lease_seconds) || m.lease_seconds <= 0 || m.lease_seconds > 30) { this.stopLease('invalid_stream_renewal'); return; }
        this.deadline = performance.now() + m.lease_seconds * 1000;
      }
      else if (m.type === 'signal') this.rtc?.webContents.send('screen:transport-in',m);
      else if (m.type === 'transport' && m.transport === 'relay') this.fallback('direct_unavailable',false);
      else if (safeAcknowledgement(m,this.sequence)) this.ack(m.sequence);
      else if (['view.stop','view.expired','error'].includes(m.type)) this.stopLease(screenCode(m.reason ?? m.code) === 'unknown_failure' ? 'stream_authorization_ended' : screenCode(m.reason ?? m.code));
    };
    ws.onerror = () => { if (generation === this.generation) this.stopLease('stream_network_error'); };
    ws.onclose = event => { if (generation === this.generation) this.stopLease('stream_disconnected', {
      component:'stream_socket', ws_close_code:event.code,
      ws_close_reason:!event.reason ? '' : screenCode(event.reason) === 'unknown_failure' ? 'redacted' : screenCode(event.reason),
    }); };
  }
  private async startRTC(generation: number): Promise<void> {
    const partition = session.fromPartition(`screen-transport-${generation}-${Date.now()}`);
    partition.setPermissionRequestHandler((_w,_p,cb) => cb(false)); partition.setPermissionCheckHandler(() => false);
    partition.on('will-download', e => e.preventDefault());
    const rtc = new BrowserWindow({show:false,width:1,height:1,focusable:false,skipTaskbar:true,
      webPreferences:{preload:path.join(__dirname,'screen_rtc_preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,
        webSecurity:true,webviewTag:false,devTools:false,backgroundThrottling:false,session:partition}});
    this.rtc = rtc; rtc.webContents.setWindowOpenHandler(() => ({action:'deny'}));
    rtc.webContents.on('will-navigate',e => e.preventDefault()); rtc.webContents.on('will-attach-webview',e => e.preventDefault());
    rtc.webContents.on('render-process-gone',() => { if (generation === this.generation) this.fallback('direct_renderer_unavailable'); });
    try { await rtc.loadFile(path.join(__dirname,'screen-transport.html'));
      if (generation !== this.generation || rtc.isDestroyed()) return;
      rtc.webContents.send('screen:transport-in',{type:'start'});
    } catch { if (generation === this.generation) this.fallback('direct_start_failed'); }
  }
  private fromRTC = (event: IpcMainEvent, message: any): void => {
    if (!this.rtc || this.rtc.isDestroyed() || event.sender !== this.rtc.webContents || event.senderFrame !== this.rtc.webContents.mainFrame || !this.allowed()) return;
    if (!message || Buffer.byteLength(JSON.stringify(message),'utf8') > 65536) return;
    if (message.type === 'signal') this.send({...message,viewer_id:this.lease!.viewer_id});
    else if (message.type === 'direct.ready' && this.transport !== 'relay') { this.transport = 'direct'; this.send({type:'transport',viewer_id:this.lease!.viewer_id,transport:'direct',reason:'connected'}); }
    else if (message.type === 'direct.failed') this.fallback(screenCode(message.reason) === 'unknown_failure' ? 'direct_failed' : screenCode(message.reason));
    else if (message.type === 'congested') this.budget.congested();
    else if (safeAcknowledgement(message,this.sequence)) this.ack(message.sequence);
  };
  private ack(sequence: number): void {
    this.deliveryTrace.record('ack_received',sequence);
    if (sequence <= this.lastAckSequence || !this.sentTimes.has(sequence) || performance.now()-this.sentTimes.get(sequence)!>12000) {this.deliveryTrace.record('ack_rejected',sequence);return;}
    this.deliveryTrace.record('ack_accepted',sequence,performance.now()-this.sentTimes.get(sequence)!);
    this.recovering=false;this.recoveryAttempts=0;this.retryAt=0;
    this.lastAckSequence = sequence; this.lastAck = performance.now(); this.roundtrip = this.lastAck-this.sentTimes.get(sequence)!;
    this.sentTimes.delete(sequence); this.acknowledgements.push(this.lastAck); this.budget.delivered();
  }
  private fallback(reason: string, notify = true): void {
    if (!this.lease || !this.ready) return;
    this.lastFallback ??= screenCode(reason);
    this.deliveryTrace.record('fallback',this.sequence);
    if (this.transport !== 'relay') { this.transport = 'relay'; this.rtc?.webContents.send('screen:transport-in',{type:'stop'}); }
    if (notify) this.send({type:'transport',viewer_id:this.lease.viewer_id,transport:'relay',reason});
  }
  private report(state: string, reason: string, viewer = this.lease?.viewer_id, transport = this.transport, diagnostic?: ScreenDiagnostic): Promise<unknown> {
    if (!viewer || this.bridge.terminated) return Promise.resolve();
    return this.bridge.host('live.capture',{viewer_id:viewer,state,transport,reason,...(diagnostic ? {diagnostic} : {})}).then(result => {
      if (!result.ok && diagnostic && diagnostic.secondary.length < 4) diagnostic.secondary.push('diagnostic_delivery_failed');
      return result;
    }).catch(() => {
      if (diagnostic && diagnostic.secondary.length < 4) diagnostic.secondary.push('diagnostic_delivery_failed');
    });
  }
  stopLease(reason = 'stopped', detail: Partial<Pick<ScreenDiagnostic,'component'|'phase'|'ws_close_code'|'ws_close_reason'|'geometry'>> = {}): void {
    const old = this.lease;
    if (!old) return; // Generic/duplicate cleanup cannot replace the first transition.
    const code = screenCode(reason), transport = this.transport;
    const diagnostic: ScreenDiagnostic = this.diagnostic = {
      timestamp:new Date().toISOString(),generation:this.generation,viewer_id:old.viewer_id,
      component:detail.component ?? 'sender',phase:detail.phase ?? 'stop',code,description:code.replaceAll('_',' '),
      transport,capture_state:this.inFlight ? 'in_flight':'idle',viewer_state:this.peerConnected ? 'attached':'pending',
      requested:['stopped','viewer_changed','viewer_switched','viewer_replaced','teacher_stopped','session_ended','application_shutdown'].includes(code),
      ws_close_code:detail.ws_close_code ?? null,ws_close_reason:detail.ws_close_reason ?? null,
      transition:'lease_revoked',fallback:this.lastFallback,secondary:[],
      delivery_trace:this.deliveryTrace.snapshot(),
      ...(detail.geometry?{geometry:detail.geometry}:{}),
    };
    // Snapshot before clearing transport/lease or closing the peer. No arbitrary errors.
    this.geometryTrace.stop();
    this.generation++; this.lease = undefined; this.deadline = 0; this.ready = false; this.peerConnected = false; this.transport = null;
    this.sentTimes.clear(); this.acknowledgements=[]; this.roundtrip=null;
    const ws = this.socket; this.socket = undefined;
    if (ws) {
      ws.onclose = null; ws.onerror = null; ws.onmessage = null; ws.onopen = null;
      try {
        if (!diagnostic.requested && ws.readyState === WebSocket.OPEN && ws.bufferedAmount <= MAX_SCREEN_JSON)
          ws.send(JSON.stringify({type:'transport',viewer_id:old.viewer_id,transport:'unavailable',reason:code}));
        // Close reason is a second ordered route for the classification, never free text.
        ws.close(1000,code);
      } catch { diagnostic.secondary.push('socket_cleanup_failed'); }
    }
    const rtc = this.rtc; this.rtc = undefined;
    try { if (rtc && !rtc.isDestroyed()) rtc.destroy(); } catch { diagnostic.secondary.push('rtc_cleanup_failed'); }
    void this.report(diagnostic.requested ? 'stopped':'unavailable',code,old.viewer_id,transport,diagnostic);
  }
  close(): void { if (this.disposed) return; this.disposed = true; if (this.timer) clearInterval(this.timer); this.timer = undefined; ipcMain.removeListener('screen:transport-out',this.fromRTC); this.stopLease('stopped');this.geometryTrace.close(); }
}
