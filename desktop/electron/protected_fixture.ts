/** Private protected-test extension; deliberately absent from production preload. */
import { BrowserWindow, type WebContents } from 'electron';
import { runRecoveryFixture } from './recovery_fixture';
import { nativeHandleHex } from './host_binding';

export async function runProtectedFixture(): Promise<void> {
  let target: WebContents | undefined;
  const extra: BrowserWindow[] = [];
  await runRecoveryFixture(true, async (command, payload, context) => {
    const { window } = context;
    if (command === 'request_foreground') {
      // An unbound second Fixture is a separate owned OS process. This is only
      // a request; the independent native observer must prove actual focus.
      window.show(); window.focus(); window.webContents.focus();
      return { pid: process.pid, hwnd: nativeHandleHex(window.getNativeWindowHandle()), requested: true };
    }
    if (command === 'focus_context') {
      if (!['trusted', 'pin', 'external'].includes(payload.kind)) throw new Error('Unknown owned focus context');
      if (payload.kind === 'external') {
        const external = context.getExternal();
        if (!external?.status.visible || !external.ownedContents || !external.ownedContents.getURL().startsWith('http://127.0.0.1:')) throw new Error('Controlled external fixture must be loaded first');
        target = external.ownedContents;
      } else {
        context.getExternal()?.hide(); target = window.webContents;
      }
      window.show(); window.focus(); target.focus();
      const kind = payload.kind;
      const focused = await target.executeJavaScript(`(() => {
        const kind=${JSON.stringify(kind)};
        if (kind==='trusted') document.getElementById('audit-pin-modal')?.close();
        let field=kind==='pin'?document.getElementById('audit-pin'):document.getElementById('protected-probe');
        if(!field){field=document.createElement('input');field.id='protected-probe';field.setAttribute('aria-label','Owned key probe');document.body.append(field);}
        if(!window.__protectedProbeInstalled){
          const allowed=new Set(['KeyA','KeyC','KeyV','Tab','Insert','PrintScreen','F4','Escape','MetaLeft','MetaRight','ControlLeft','ControlRight','AltLeft','AltRight','ShiftLeft','ShiftRight','Unidentified','']);
          const allowedKeys=new Set(['a','A','c','C','v','V','Insert','Tab','PrintScreen','F4','Escape','Meta','Control','Alt','Shift','Unidentified','']);
          window.__protectedProbe={counts:{},ups:{},events:[]};
          for(const type of ['keydown','keyup'])document.addEventListener(type,event=>{
            if(!allowed.has(event.code))return;
            const p=window.__protectedProbe,bucket=type==='keydown'?p.counts:p.ups;
            bucket[event.code]=(bucket[event.code]||0)+1;
            if(p.events.length<24)p.events.push({type,code:event.code,key:allowedKeys.has(event.key)?event.key:'[other]',ctrl:event.ctrlKey,shift:event.shiftKey,alt:event.altKey,meta:event.metaKey,repeat:event.repeat});
          },true);
          window.__protectedProbeInstalled=true;
        }
        field.focus();return document.activeElement===field;
      })()`);
      if (!focused || !target.isFocused()) throw new Error('Owned input did not acquire focus');
      return { focused: true, kind };
    }
    if (command === 'key_probe_reset' || command === 'key_probe') {
      if (!target || target.isDestroyed()) throw new Error('No owned input target');
      return target.executeJavaScript(command === 'key_probe_reset' ? '(window.__protectedProbe={counts:{},ups:{},events:[]})' : '({...window.__protectedProbe,focused:document.activeElement?.id||null,value_length:document.activeElement instanceof HTMLInputElement?document.activeElement.value.length:null})');
    }
    if (command === 'focus_foreign_owned') {
      const foreign = new BrowserWindow({ width: 380, height: 160, show: false, title: 'Owned unregistered foreground fixture',
        webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
      extra.push(foreign);
      if (extra.length === 1) window.once('closed', () => { for (const owned of extra) if (!owned.isDestroyed()) owned.destroy(); });
      await foreign.loadURL('data:text/html,' + encodeURIComponent('<p>Temporary owned containment target; no keyboard input is sent here.</p>'));
      foreign.show(); foreign.focus();
      return { hwnd: nativeHandleHex(foreign.getNativeWindowHandle()) };
    }
    if (command === 'focused_exam') return BrowserWindow.getFocusedWindow() === window;
    throw new Error('Unknown private protected-fixture action');
  });
}
