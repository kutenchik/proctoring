/** Wire format shared by both first-party endpoints; no audio, video file or disk cache. */
export interface ScreenFrame {
  type: 'frame'; viewer_id: string; sequence: number; width: number; height: number;
  captured_at: number; jpeg_base64: string;
}
export const MAX_SCREEN_BYTES = 256 * 1024;
export const MAX_SCREEN_JSON = 384 * 1024;
export function validFrame(v: unknown): v is ScreenFrame {
  const f = v as ScreenFrame;
  return !!f && f.type === 'frame' && typeof f.viewer_id === 'string' && f.viewer_id.length <= 128 &&
    Number.isSafeInteger(f.sequence) && f.sequence >= 0 && Number.isFinite(f.captured_at) &&
    Number.isInteger(f.width) && f.width > 0 && f.width <= 1920 && Number.isInteger(f.height) && f.height > 0 && f.height <= 1920 &&
    typeof f.jpeg_base64 === 'string' && f.jpeg_base64.length <= Math.ceil(MAX_SCREEN_BYTES / 3) * 4 &&
    f.jpeg_base64.startsWith('/9j/') && /^[A-Za-z0-9+/]+={0,2}$/.test(f.jpeg_base64);
}
/** Small SCTP messages avoid relying on a browser's large-message support. */
export function frameChunks(frame: ScreenFrame): string[] {
  if (!validFrame(frame)) throw new Error('invalid_frame');
  const text = JSON.stringify(frame), size = 12000, count = Math.ceil(text.length / size);
  return Array.from({ length: count }, (_, index) => JSON.stringify({ type: 'frame_chunk',
    sequence: frame.sequence, index, count, data: text.slice(index * size, (index + 1) * size) }));
}
/** One incomplete frame only; new sequence replaces old, one-second expiry. */
export class FrameAssembler {
  private partial?: { sequence: number; count: number; at: number; chunks: Map<number, string>; bytes: number };
  private last = -1;
  constructor(private viewer: string, private now: () => number = () => performance.now()) {}
  clear(): void { this.partial = undefined; }
  receive(text: string): ScreenFrame | null {
    if (typeof text !== 'string' || text.length > MAX_SCREEN_JSON) return null;
    let value: any; try { value = JSON.parse(text); } catch { return null; }
    if (value.type === 'frame') return this.accept(value);
    if (value.type !== 'frame_chunk' || !Number.isSafeInteger(value.sequence) || value.sequence <= this.last ||
      !Number.isInteger(value.count) || value.count < 1 || value.count > 32 || !Number.isInteger(value.index) ||
      value.index < 0 || value.index >= value.count || typeof value.data !== 'string' || value.data.length > 12000) return null;
    if (this.partial && (this.now() - this.partial.at > 1000 || value.sequence > this.partial.sequence)) this.clear();
    if (!this.partial) this.partial = { sequence: value.sequence, count: value.count, at: this.now(), chunks: new Map(), bytes: 0 };
    const p = this.partial;
    if (value.sequence !== p.sequence || value.count !== p.count || p.chunks.has(value.index)) return null;
    p.chunks.set(value.index, value.data); p.bytes += value.data.length;
    if (p.bytes > MAX_SCREEN_JSON) { this.clear(); return null; }
    if (p.chunks.size !== p.count) return null;
    this.clear();
    try { return this.accept(JSON.parse(Array.from({ length: p.count }, (_, i) => p.chunks.get(i)).join(''))); } catch { return null; }
  }
  private accept(frame: unknown): ScreenFrame | null {
    if (!validFrame(frame) || frame.viewer_id !== this.viewer || frame.sequence <= this.last) return null;
    this.last = frame.sequence; return frame;
  }
}

/** Local receive age, never a claim of synchronized end-to-end latency. */
export function frameFresh(receivedAt: number | null, now: number, maxAge = 3000): boolean {
  return receivedAt !== null && now >= receivedAt && now - receivedAt < maxAge;
}
