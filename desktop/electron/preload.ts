import { contextBridge, ipcRenderer } from 'electron';
import type { Command, ControlChallenge, ControlReceipt, DesktopAPI, EvidenceIntent, ExternalIntent, PresentationReceipt } from '../shared/contracts';
const mode = process.argv.includes('--proctoring-fixture') ? 'fixture' : 'live';
const api: DesktopAPI = Object.freeze({
  mode,
  onControlChallenge: (listener: (challenge: ControlChallenge) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, challenge: ControlChallenge) => listener(challenge);
    ipcRenderer.on('proctoring:control-challenge', handler);
    return () => ipcRenderer.removeListener('proctoring:control-challenge', handler);
  },
  acknowledgeControlProgress: (receipt: ControlReceipt) => ipcRenderer.invoke('proctoring:control-progress', receipt),
  command: (command: Command, payload: Record<string, unknown> = {}) => ipcRenderer.invoke('proctoring:command', command, payload),
  connection: () => ipcRenderer.invoke('proctoring:connection'),
  preview: () => ipcRenderer.invoke('proctoring:preview'),
  reconnect: () => ipcRenderer.invoke('proctoring:reconnect'),
  geometry: () => ipcRenderer.invoke('proctoring:geometry'),
  external: (intent: ExternalIntent) => ipcRenderer.invoke('proctoring:external', intent),
  evidence: (intent: EvidenceIntent) => ipcRenderer.invoke('proctoring:evidence', intent),
  acknowledgePresentation: (receipt: PresentationReceipt) => ipcRenderer.invoke('proctoring:acknowledge-presentation', receipt),
  onEndRequested: (listener: () => void) => {
    const handler = () => listener();
    ipcRenderer.on('proctoring:request-end', handler);
    return () => ipcRenderer.removeListener('proctoring:request-end', handler);
  },
});
contextBridge.exposeInMainWorld('proctoring', api);
