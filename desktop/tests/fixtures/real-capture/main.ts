import { app, BrowserWindow, desktopCapturer, ipcMain, nativeImage, screen, session } from 'electron';
import { mkdirSync,writeFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { captureExamMonitor,TransientMonitorCapture } from '../../../electron/screen_capture';
import { CaptureGeometryError,CaptureGeometryTrace } from '../../../electron/screen_geometry';
import { Recorder } from './recorder';

const mock=process.argv.includes('--mock-capture');
const approved=process.argv.includes('--operator-approved-real-capture');
const outputIndex=process.argv.indexOf('--output');
// No app/window/device initialization on a missing real-capture approval flag.
if((!mock&&(!approved||process.platform!=='win32'))||outputIndex<0||!path.isAbsolute(process.argv[outputIndex+1]??'')) {
  console.error('fixture_requires_explicit_approval_and_absolute_output');app.exit(2);
} else {
  const output=path.resolve(process.argv[outputIndex+1]);
  mkdirSync(output); // Refuse an existing run directory; never replace evidence.
  app.setPath('userData',path.join(output,'electron-profile'));
  app.whenReady().then(async()=>{
    const isolated=session.fromPartition('real-capture-diagnostic');
    isolated.setPermissionRequestHandler((_w,_p,cb)=>cb(false));
    isolated.setPermissionCheckHandler(()=>false);isolated.setDevicePermissionHandler(()=>false);
    isolated.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*','ws://*/*','wss://*/*']},(_d,cb)=>cb({cancel:true}));
    isolated.on('will-download',e=>e.preventDefault());
    const owner=new BrowserWindow({title:mock?'MOCK capture fixture — no monitor capture':'Real monitor capture diagnostic — awaiting consent',
      width:1280,height:800,minWidth:480,minHeight:400,autoHideMenuBar:true,backgroundColor:'#f8f6f1',show:false,
      webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,
        webSecurity:true,webviewTag:false,backgroundThrottling:false,devTools:false,session:isolated}});
    owner.removeMenu();owner.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    owner.webContents.on('will-navigate',e=>e.preventDefault());owner.webContents.on('will-attach-webview',e=>e.preventDefault());
    const recorder=new Recorder(mock||approved,mock?'mock':'real');
    const trace=new CaptureGeometryTrace(owner);
    let busy=false,saved=false,firstSaved=false,closing=false,timer:NodeJS.Timeout|undefined;
    let getSourcesCalls=0;
    if(mock)desktopCapturer.getSources=async options=>{
      getSourcesCalls++;
      const {width,height}=options.thumbnailSize!;
      return [{id:'synthetic',name:'synthetic',display_id:String(screen.getAllDisplays()[0].id),appIcon:nativeImage.createEmpty(),
        thumbnail:nativeImage.createFromBitmap(Buffer.alloc(width*height*4),{width,height})}];
    };
    // Called only by the preparation build's numeric-only instrumentation.
    (globalThis as any).__captureFixtureBoundary=(value:any)=>recorder.boundary(value);
    (globalThis as any).__captureFixtureMask=(stage:any,value:any)=>recorder.mask(stage,value);
    const save=()=>{
      const report=recorder.report();const json=JSON.stringify(report,null,2);
      if(Buffer.byteLength(json)>512*1024)throw Error('fixture_evidence_bound');
      if(report.first_failure&&!firstSaved){writeFileSync(path.join(output,'first-failure.json'),JSON.stringify(report.first_failure,null,2),{flag:'wx'});firstSaved=true;}
      if(!saved){writeFileSync(path.join(output,'result.json'),json,{flag:'wx'});saved=true;}
    };
    const publish=()=>{if(!owner.isDestroyed()&&!owner.webContents.isDestroyed())owner.webContents.send('fixture:status',{...recorder.status(),mock});};
    const finish=()=>{
      if(timer)clearInterval(timer);timer=undefined;trace.stop();
      try{save();}catch{if(!owner.isDestroyed())owner.setTitle('Diagnostic stopped — evidence write failed');}
      publish();
    };
    const tick=async()=>{
      if(recorder.state!=='running')return;
      publish();
      if(!recorder.begin()){if(recorder.state!=='running')finish();return;}
      busy=true;
      const timeout=setTimeout(()=>{if(recorder.state==='running'){recorder.fail('fixture_capture_timeout');finish();owner.close();}},10000);
      try {
        const frame=await captureExamMonitor(owner,1280,72,trace,()=>recorder.state==='running');
        // Never send, preview, persist or retain any frame. Clear our encoded copy.
        frame.jpeg.fill(0);recorder.success();
      } catch(error) {
        recorder.fail(error instanceof TransientMonitorCapture?'monitor_capture_failed':error instanceof Error?error.message:null,
          error instanceof CaptureGeometryError?error.geometry:undefined);
      } finally {
        clearTimeout(timeout);busy=false;
        if(recorder.state!=='running')finish();
      }
    };
    const rendererURL=pathToFileURL(path.join(__dirname,'index.html')).href;
    const trusted=(event:Electron.IpcMainInvokeEvent)=>event.sender===owner.webContents&&event.senderFrame===owner.webContents.mainFrame&&event.senderFrame.url===rendererURL;
    ipcMain.handle('fixture:start',(event,consent)=>{
      if(!trusted(event)||!recorder.start(consent))return false;
      trace.start();owner.setTitle(mock?'MOCK capture running':'REAL monitor capture running — Stop or close to end');
      timer=setInterval(()=>{if(!busy)void tick();},250);publish();return true;
    });
    ipcMain.handle('fixture:stop',event=>{if(!trusted(event))return;recorder.stop();finish();});
    ipcMain.handle('fixture:status',event=>trusted(event)?{...recorder.status(),mock}:null);
    owner.on('close',()=>{closing=true;recorder.stop();finish();});
    owner.on('closed',()=>{
      if(!closing&&recorder.state==='running')recorder.fail('fixture_window_destroyed');
      finish();trace.close();ipcMain.removeHandler('fixture:start');ipcMain.removeHandler('fixture:stop');ipcMain.removeHandler('fixture:status');
      delete (globalThis as any).__captureFixtureBoundary;delete (globalThis as any).__captureFixtureMask;
      try{writeFileSync(path.join(output,'cleanup.json'),JSON.stringify({timestamp:Date.now(),requested_close:closing,in_flight_at_close:busy,fixture_window_closed:true,mock},null,2),{flag:'wx'});}
      finally{app.quit();}
    });
    // Mock-only hook exposes counters/recorder for tests, never images or real-mode control.
    if(mock)(globalThis as any).__mockCaptureFixture={owner,recorder,getSourcesCalls:()=>getSourcesCalls,report:()=>recorder.report()};
    await owner.loadFile(path.join(__dirname,'index.html'));owner.show();publish();
  }).catch(()=>{console.error('fixture_startup_failed');app.exit(1);});
}
