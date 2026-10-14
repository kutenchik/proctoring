import { useEffect, useState, useSyncExternalStore } from 'react';
import type { BackendState, Command, ConnectionStatus, PreviewFrame } from '../../shared/contracts';

const api = window.proctoring;
export const fixtureMode = !api || api.mode === 'fixture';
type Snapshot = { state: BackendState | null; connection: ConnectionStatus; busy: boolean; error: string | null };
let raw: BackendState | null = null;
let snapshot: Snapshot = { state: null, connection: { state: fixtureMode ? 'fixture' : 'connecting' }, busy: false, error: null };
const listeners = new Set<() => void>();
const audioListeners = new Set<() => void>();
const journalListeners = new Set<(data: unknown) => void>();
let started = false;
let pendingCommands = 0;
let pollGeneration = 0;
let pollTimer: number | undefined;
function emit(patch: Partial<Snapshot>) {
  if (patch.connection && patch.connection.state !== 'connected') {
    raw = null;
    patch = { ...patch, state: null };
    audioListeners.forEach(f => f());
  }
  snapshot = { ...snapshot, ...patch }; listeners.forEach(f => f());
}
function accept(state: BackendState) {
  if (raw?.workflow && state.workflow && state.workflow.revision < raw.workflow.revision) return;
  raw = state;
  audioListeners.forEach(f => f());
  // Fast-changing samples have their own subscriptions. Setup forms keep focus.
  const structural = { ...state, camera: { ...state.camera, fps: 0, frame_age_seconds: null, preview_sequence: null }, audio: { ...state.audio, processed_level: 0, frame_age_seconds: null, check: { ...state.audio.check, progress: 0, applied_gain: 0 } } };
  if (JSON.stringify(structural) !== JSON.stringify(snapshot.state)) emit({ state: structural });
}
async function poll(generation: number) {
  if (!api || fixtureMode) return;
  try {
    const connection = await api.connection();
    if (generation !== pollGeneration) return;
    if (JSON.stringify(connection) !== JSON.stringify(snapshot.connection)) emit({ connection });
    if (connection.state === 'connected') {
      const result = await api.command('state.get');
      if (generation !== pollGeneration) return;
      if (result.ok) accept(result.result);
      else emit({ error: `${result.error.code}: ${result.error.message}` });
    }
  } catch (e) { emit({ connection: { state: 'disconnected' }, error: String(e) }); }
  finally { if (generation === pollGeneration && started) pollTimer = window.setTimeout(() => void poll(generation), 200); }
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!started && !fixtureMode) { started = true; const generation = ++pollGeneration; void poll(generation); }
  return () => { listeners.delete(listener); if (!listeners.size) { started = false; pollGeneration++; window.clearTimeout(pollTimer); } };
}
export function useBackend() { return useSyncExternalStore(subscribe, () => snapshot); }
export function useAudio() { return useSyncExternalStore(f => { audioListeners.add(f); return () => audioListeners.delete(f); }, () => raw?.audio ?? null); }
export async function command(name: Command, payload?: Record<string, unknown>) {
  if (!api || fixtureMode) return false;
  pendingCommands++; emit({ busy: true, error: null });
  try { const result = await api.command(name, payload); if (!result.ok) { emit({ error: `${result.error.code}: ${result.error.message}` }); return false; } accept(result.result); return true; }
  catch (e) { emit({ error: String(e) }); return false; }
  finally { pendingCommands--; emit({ busy: pendingCommands > 0 }); }
}
export async function reconnect() { if (!api || fixtureMode) return; emit({ busy: true, error: null, connection: { state: 'connecting' } }); try { const connection = await api.reconnect(); emit({ connection }); } catch (e) { emit({ connection: { state: 'disconnected' }, error: String(e) }); } finally { emit({ busy: false }); } }
export async function readEventBatch(after: number) {
  if (!api || fixtureMode) return null;
  const result = await api.command('events.get', { after, limit: 100 });
  if (!result.ok) throw new Error(result.error.code);
  accept(result.result);
    const batch = { ...(result.data as object), session_id: result.result.workflow?.session_id ?? null };
    journalListeners.forEach(listener => listener(batch));
    return batch;
}
export function subscribeJournal(listener: (data: unknown) => void) { journalListeners.add(listener); return () => { journalListeners.delete(listener); }; }
export async function synchronizePresentation() {
  if (!api || fixtureMode) return false;
  pendingCommands++; emit({ busy: true, error: null });
  try {
    const connection = await api.reconnect();
    if (connection.state !== 'connected') throw new Error(connection.reason ?? 'Backend unavailable');
    const initial = await api.command('state.get');
    if (!initial.ok || !initial.result.workflow?.session_id) throw new Error('No existing session to synchronize');
    emit({ connection }); accept(initial.result);
    const sessionId = initial.result.workflow.session_id;
    let cursor = 0; let last = initial.result.workflow;
    for (let page = 0; page < 1000; page++) {
      const result = await api.command('events.get', { after: cursor, limit: 100 });
      if (!result.ok || result.result.workflow?.session_id !== sessionId) throw new Error('Session changed while synchronizing');
      const data = result.data as { cursor: number; has_more: boolean; records: unknown[] };
      if (!data || !Number.isFinite(data.cursor) || data.cursor < cursor) throw new Error('Invalid event cursor');
      accept(result.result); journalListeners.forEach(listener => listener({ ...data, session_id: result.result.workflow?.session_id ?? null }));
      last = result.result.workflow; cursor = data.cursor;
      if (!data.has_more && cursor >= last.events.cursor) {
        const acknowledged = await api.acknowledgePresentation({ session_id: sessionId, event_cursor: cursor, snapshot_seq: last.snapshot_seq });
        if (!acknowledged.ok) throw new Error(acknowledged.error.message);
        accept(acknowledged.result); return true;
      }
    }
    throw new Error('Event synchronization did not finish; retry');
  } catch (error) { emit({ error: String(error) }); return false; }
  finally { pendingCommands--; emit({ busy: pendingCommands > 0 }); }
}
export function usePreview(enabled: boolean, sourceKey?: string | null) {
  const [frame, setFrame] = useState<PreviewFrame | null>(null);
  useEffect(() => {
    setFrame(null);
    if (!enabled || !api || fixtureMode) return;
    let cancelled = false; let timer: number; let receivedAt = 0;
    const next = async () => {
      try {
        const image = await api.preview();
        if (!cancelled && image) { receivedAt = performance.now(); setFrame(image); }
        else if (!cancelled && performance.now() - receivedAt > 2000) setFrame(null);
      } catch { if (!cancelled) setFrame(null); }
      if (!cancelled) timer = window.setTimeout(() => void next(), 125);
    };
    void next();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [enabled, sourceKey]);
  return frame;
}
