import { frameChunks, validFrame } from '../../shared/live-screen';
interface TransportAPI { listen(fn: (m: any) => void): void; send(m: unknown): void }
const api = (window as unknown as {screenTransport: TransportAPI}).screenTransport;
let pc: RTCPeerConnection | undefined, channel: RTCDataChannel | undefined;
let generation = 0, pendingIce: RTCIceCandidateInit[] = [];
function stop(): void { generation++; channel?.close(); pc?.close(); channel = undefined; pc = undefined; pendingIce = []; }
async function receive(m: any): Promise<void> {
  if (m.type === 'stop') { stop(); return; }
  if (m.type === 'start') {
    stop(); const current = generation;
    // Direct host candidates only; no external STUN/TURN dependency or credentials.
    const peer = pc = new RTCPeerConnection({iceServers: []});
    channel = peer.createDataChannel('screen', {ordered: false, maxRetransmits: 0});
    channel.onopen = () => { if (current === generation) api.send({type:'direct.ready'}); };
    channel.onclose = () => { if (current === generation) api.send({type:'direct.failed',reason:'rtc_channel_closed'}); };
    channel.onmessage = e => { if (current !== generation || typeof e.data !== 'string' || e.data.length > 2048) return;
      try { const v = JSON.parse(e.data); if (v.type === 'frame_ack' && Number.isSafeInteger(v.sequence)) api.send(v); } catch {} };
    peer.onicecandidate = e => { if (current === generation) api.send({type:'signal',signal:{type:'ice',candidate:e.candidate?.toJSON() ?? null}}); };
    peer.onconnectionstatechange = () => { if (current === generation && ['failed','disconnected','closed'].includes(peer.connectionState)) api.send({type:'direct.failed',reason:'rtc_connection_failed'}); };
    const offer = await peer.createOffer(); if (current !== generation) return;
    await peer.setLocalDescription(offer); if (current !== generation) return;
    api.send({type:'signal',signal:{type:'offer',sdp:offer.sdp}}); return;
  }
  if (m.type === 'signal' && pc) {
    const peer = pc;
    if (m.signal?.type === 'answer') { await peer.setRemoteDescription(m.signal); if (pc !== peer) return; for (const ice of pendingIce.splice(0)) await peer.addIceCandidate(ice); }
    else if (m.signal?.type === 'ice' && m.signal.candidate) { if (peer.remoteDescription) await peer.addIceCandidate(m.signal.candidate); else if (pendingIce.length < 128) pendingIce.push(m.signal.candidate); }
  }
  if (m.type === 'frame' && validFrame(m)) {
    if (channel?.readyState !== 'open' || channel.bufferedAmount > 256 * 1024) { api.send({type:'congested'}); return; }
    for (const chunk of frameChunks(m)) channel.send(chunk);
  }
}
api.listen(m => { void receive(m).catch(() => { stop(); api.send({type:'direct.failed',reason:'rtc_operation_failed'}); }); });
window.addEventListener('pagehide', stop);
