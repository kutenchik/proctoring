import net from 'node:net';
import { randomBytes } from 'node:crypto';
import type { PreviewFrame } from '../shared/contracts';
const MAX_PACKET = 768 * 1024;
/** Dedicated, authenticated, pull-only pipe. Camera pixels never go to disk/stdout. */
export class PreviewPipe {
  readonly token = randomBytes(32).toString('hex');
  readonly path = `\\\\.\\pipe\\local-proctoring-${randomBytes(16).toString('hex')}`;
  private server?: net.Server;
  private socket?: net.Socket;
  private pending?: { resolve: (frame: PreviewFrame | null) => void; timer: NodeJS.Timeout };
  private buffer: Buffer = Buffer.alloc(0);
  private authenticated = false;
  private closed = false;
  async listen(): Promise<void> {
    if (this.closed) return;
    if (process.platform !== 'win32') throw new Error('Stage 1 native preview requires Windows');
    this.server = net.createServer(socket => {
      if (this.socket) { socket.destroy(); return; }
      this.socket = socket;
      const authTimeout = setTimeout(() => { if (!this.authenticated) socket.destroy(); }, 3000);
      socket.on('data', chunk => this.receive(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
      socket.on('error', () => socket.destroy());
      socket.on('close', () => {
        clearTimeout(authTimeout); this.socket = undefined; this.authenticated = false;
        this.buffer = Buffer.alloc(0); this.finish(null);
      });
    });
    await new Promise<void>((resolve, reject) => { this.server!.once('error', reject); this.server!.listen(this.path, resolve); });
    if (this.closed) this.server.close();
  }
  private receive(chunk: Buffer): void {
    if (this.buffer.length + chunk.length > MAX_PACKET + 4) { this.socket?.destroy(); return; }
    this.buffer = Buffer.concat([this.buffer, chunk]);
    if (!this.authenticated) {
      const end = this.buffer.indexOf(10);
      if (end < 0) { if (this.buffer.length > 256) this.socket?.destroy(); return; }
      try {
        const hello = JSON.parse(this.buffer.subarray(0, end).toString('utf8'));
        if (hello.token !== this.token || end > 256) throw new Error();
      } catch { this.socket?.destroy(); return; }
      this.authenticated = true; this.buffer = this.buffer.subarray(end + 1);
    }
    if (this.buffer.length < 4) return;
    const length = this.buffer.readUInt32BE(0);
    if (length > MAX_PACKET || !this.pending) { this.socket?.destroy(); return; }
    if (this.buffer.length < 4 + length) return;
    const packet = this.buffer.subarray(4, 4 + length);
    this.buffer = this.buffer.subarray(4 + length);
    try {
      const frame = length === 0 ? null : JSON.parse(packet.toString('utf8'));
      this.finish(frame === null ? null : validatePreview(frame));
    } catch { this.socket?.destroy(); this.finish(null); }
  }
  private finish(frame: PreviewFrame | null): void {
    if (this.pending) { clearTimeout(this.pending.timer); this.pending.resolve(frame); this.pending = undefined; }
  }
  next(): Promise<PreviewFrame | null> {
    if (!this.authenticated || !this.socket || this.pending) return Promise.resolve(null);
    return new Promise(resolve => {
      this.pending = { resolve, timer: setTimeout(() => { this.socket?.destroy(); this.finish(null); }, 2000) };
      this.socket!.write(Buffer.from([1]));
    });
  }
  close(): void { this.closed = true; this.finish(null); this.socket?.destroy(); if (this.server?.listening) this.server.close(); }
}
export function validatePreview(frame: unknown): PreviewFrame {
  if (!frame || typeof frame !== 'object') throw new Error('Invalid preview');
  const f = frame as PreviewFrame;
  if (f.mime !== 'image/jpeg' || typeof f.jpeg_base64 !== 'string' || f.jpeg_base64.length > 700000 ||
      !/^[A-Za-z0-9+/]*={0,2}$/.test(f.jpeg_base64) || !Array.isArray(f.overlays) || f.overlays.length > 128 ||
      !Number.isInteger(f.sequence) || f.sequence < 0 || !Number.isFinite(f.captured_at) ||
      ![f.width, f.height, f.source_width, f.source_height].every(v => Number.isInteger(v) && v > 0 && v <= 8192)) throw new Error('Invalid preview');
  return f;
}
