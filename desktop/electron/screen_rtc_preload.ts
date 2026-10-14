import { contextBridge, ipcRenderer } from 'electron';
// Only this isolated local transport page receives frames. No credentials or devices.
contextBridge.exposeInMainWorld('screenTransport', Object.freeze({
  listen: (listener: (message: unknown) => void) => ipcRenderer.on('screen:transport-in', (_e, value) => listener(value)),
  send: (message: unknown) => ipcRenderer.send('screen:transport-out', message),
}));
