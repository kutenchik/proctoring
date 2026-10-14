import { contextBridge,ipcRenderer } from 'electron';
contextBridge.exposeInMainWorld('captureFixture',{
  start:(consent:boolean)=>ipcRenderer.invoke('fixture:start',consent),
  stop:()=>ipcRenderer.invoke('fixture:stop'),
  status:()=>ipcRenderer.invoke('fixture:status'),
  onStatus:(fn:(value:unknown)=>void)=>{ipcRenderer.on('fixture:status',(_event,value)=>fn(value));},
});
