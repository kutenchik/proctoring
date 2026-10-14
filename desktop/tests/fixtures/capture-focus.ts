import { app, BrowserWindow, desktopCapturer, nativeImage, screen, session } from 'electron';
import { captureExamMonitor } from '../../electron/screen_capture';
import { CaptureGeometryTrace } from '../../electron/screen_geometry';

// Isolated software test: no backend, exam, devices, protection or real capture.
app.whenReady().then(async () => {
  const isolated=session.fromPartition('capture-focus-test');
  isolated.setPermissionRequestHandler((_w,_p,cb)=>cb(false));
  isolated.setPermissionCheckHandler(()=>false);
  const options={width:800,height:600,minWidth:480,minHeight:400,autoHideMenuBar:true,
    webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true,backgroundThrottling:false,session:isolated}};
  const owner=new BrowserWindow({...options,title:'Synthetic capture geometry test',x:40,y:40});owner.removeMenu();
  const other=new BrowserWindow({...options,title:'Synthetic focus target',x:160,y:100});other.removeMenu();
  await owner.loadURL('data:text/html,'+encodeURIComponent('<button id="click" onclick="window.testClicks=(window.testClicks||0)+1">Synthetic button</button><div class="camera-preview" style="position:fixed;right:20px;top:40px;width:80px;height:60px;background:green"></div><div style="height:3000px">Synthetic scroll content</div>'));
  await other.loadURL('data:text/html,<p>Synthetic focus target</p>');
  const trace=new CaptureGeometryTrace(owner);trace.start();
  owner.once('closed',()=>trace.close());
  const events:any[]=[];
  const snapshot=()=>({bounds:owner.getContentBounds(),zoom:owner.webContents.getZoomFactor(),focus:owner.isFocused(),maximized:owner.isMaximized(),displayCount:screen.getAllDisplays().length});
  for(const name of ['focus','blur','resize','move','maximize','unmaximize','restore'] as const) (owner as NodeJS.EventEmitter).on(name,()=>{if(events.length<64)events.push({event:name,...snapshot()});});
  owner.webContents.on('zoom-changed',()=>{if(events.length<64)events.push({event:'zoom-changed',...snapshot()});});
  let release:()=>void=()=>{}, reached:()=>void=()=>{}, pending:Promise<any>;
  desktopCapturer.getSources=async (options)=>{
    reached();await new Promise<void>(resolve=>{release=resolve;});
    const {width,height}=options.thumbnailSize!;
    return [{id:'synthetic',name:'synthetic',display_id:String(screen.getAllDisplays()[0].id),appIcon:nativeImage.createEmpty(),
      thumbnail:nativeImage.createFromBitmap(Buffer.alloc(width*height*4),{width,height})}];
  };
  (globalThis as any).captureTest={owner,other,snapshot,events,
    async begin(){const before=snapshot();const ready=new Promise<void>(r=>reached=r);
      pending=captureExamMonitor(owner,800,60,trace).then(f=>({ok:true,width:f.width,height:f.height,before,after:snapshot()}),e=>({ok:false,code:e.message,geometry:e.geometry??null,before,after:snapshot()}));await ready;},
    async finish(){release();return await pending;},
  };
});
