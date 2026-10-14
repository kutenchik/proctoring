import { screen, type BrowserWindow } from 'electron';
import type { CaptureGeometryDiagnostic, GeometryCheck, GeometryEvent, GeometrySnapshot } from '../../shared/screen-geometry';

const number=(v:number):number|null=>Number.isFinite(v)&&Math.abs(v)<=Number.MAX_SAFE_INTEGER?v:null;
const finiteArray=(v:number[])=>v.every(n=>number(n)!==null)?v:null;
const rectangle=(v:Electron.Rectangle)=>finiteArray([v.x,v.y,v.width,v.height]);
export function captureGeometry(window:BrowserWindow, monitorOnly=false):GeometrySnapshot {
  const destroyed=window.isDestroyed(), wcDestroyed=destroyed||window.webContents.isDestroyed();
  const displays=screen.getAllDisplays(),content=destroyed?null:window.getContentBounds();
  const display=displays.length===1?(monitorOnly?displays[0]:content?screen.getDisplayMatching(content):null):null;
  return {sampled_at:Date.now(),window_destroyed:destroyed,web_contents_destroyed:wcDestroyed,display_count:Math.min(displays.length,1024),
    display_id:display?number(display.id):null,content:content?rectangle(content):null,
    display_bounds:display?rectangle(display.bounds):null,display_size:display?finiteArray([display.size.width,display.size.height]):null,
    display_scale:display?number(display.scaleFactor):null,zoom:wcDestroyed?null:number(window.webContents.getZoomFactor()),
    focused:destroyed?null:window.isFocused(),maximized:destroyed?null:window.isMaximized()};
}
export class CaptureGeometryError extends Error {
  constructor(public readonly geometry:CaptureGeometryDiagnostic,code='capture_geometry_changed') {super(code);}
}
/** Retry a new capture, never accept the rejected frame. Display/zoom changes
 * remain terminal because they may invalidate independent calibration gates. */
export function recoverableGeometry(error:unknown):error is CaptureGeometryError {
  if (!(error instanceof CaptureGeometryError) || error.message!=='capture_geometry_changed') return false;
  const g=error.geometry;
  return g.failed.length>0 && g.failed.every(c=>['content_x','content_y','content_width','content_height'].includes(c)) &&
    geometryFailures(g.before,g.before).length===0 && geometryFailures(g.after,g.after).length===0 &&
    (!g.source || (g.source.matches===1 && g.source.empty===false && (g.source.width??0)>0 && (g.source.height??0)>0));
}
/** At most 16 metadata events in memory, active only for a viewer lease. */
export class CaptureGeometryTrace {
  private active=false;
  private events:GeometryEvent[]=[];
  private cleanup:(()=>void)[]=[];
  constructor(private window:BrowserWindow) {
    const attach=(target:NodeJS.EventEmitter,name:string,event:GeometryEvent['event'])=>{
      const listener=()=>{if(!this.active)return;const s=captureGeometry(window);
        this.events.push({event,at:Date.now(),content:s.content,zoom:s.zoom,focused:s.focused});
        if(this.events.length>16)this.events.shift();};
      target.on(name,listener);this.cleanup.push(()=>target.removeListener(name,listener));
    };
    for(const event of ['focus','blur','resize','move','maximize','unmaximize','restore','minimize','enter-full-screen','leave-full-screen','closed'] as const)attach(window,event,event);
    attach(window.webContents,'destroyed','webcontents-destroyed');
    attach(window.webContents,'zoom-changed','zoom-changed');
  }
  start(){this.events=[];this.active=true;}
  stop(){this.active=false;}
  snapshot(){return this.events.map(e=>({...e,content:e.content?.slice()??null}));}
  close(){this.stop();for(const fn of this.cleanup)fn();this.cleanup=[];this.events=[];}
}
export function geometryFailures(before:GeometrySnapshot,after:GeometrySnapshot):GeometryCheck[] {
  const failed:GeometryCheck[]=[];
  if(after.window_destroyed)failed.push('window_destroyed');
  if(after.web_contents_destroyed)failed.push('web_contents_destroyed');
  if(after.display_count!==1)failed.push('display_count');
  if(before.display_id!==after.display_id)failed.push('display_id');
  if(before.content&&after.content) (['content_x','content_y','content_width','content_height'] as const).forEach((key,i)=>{if(before.content![i]!==after.content![i])failed.push(key);});
  for(const [field,code] of [['display_bounds','display_bounds'],['display_size','display_size'],['display_scale','display_scale'],['zoom','zoom']] as const)
    if(JSON.stringify(before[field])!==JSON.stringify(after[field]))failed.push(code);
  const valid=(s:GeometrySnapshot)=>s.display_id!==null&&s.content&&s.display_bounds&&s.display_size&&s.zoom!==null&&s.zoom>0&&s.display_scale!==null&&s.display_scale>0&&
    [...s.content,...s.display_bounds,...s.display_size].every(Number.isFinite)&&s.content[2]>0&&s.content[3]>0&&s.display_bounds[2]>0&&s.display_bounds[3]>0&&s.display_size.every(n=>n>0);
  if(!after.window_destroyed&&!after.web_contents_destroyed&&after.display_count===1&&(!valid(before)||!valid(after)))failed.push('invalid_geometry');
  return failed;
}
export function assertCaptureGeometry(window:BrowserWindow,before:GeometrySnapshot,stage:CaptureGeometryDiagnostic['stage'],trace?:CaptureGeometryTrace,source:CaptureGeometryDiagnostic['source']=null):void {
  const after=captureGeometry(window),failed=geometryFailures(before,after);
  if(failed.length)throw new CaptureGeometryError({stage,failed,before,after,events:trace?.snapshot()??[],source},
    stage==='before_mask'&&(after.window_destroyed||after.web_contents_destroyed||after.display_count!==1)?'single_display_required':'capture_geometry_changed');
}

/** Monitor capture never relies on minimized native bounds, DOM or zoom coordinates. */
export function monitorGeometryFailures(before:GeometrySnapshot,after:GeometrySnapshot):GeometryCheck[] {
  const failed=geometryFailures(before,after).filter(c=>!['content_x','content_y','content_width','content_height','zoom','invalid_geometry'].includes(c));
  const valid=(s:GeometrySnapshot)=>s.display_count===1&&s.display_id!==null&&s.display_bounds&&s.display_size&&
    s.display_scale!==null&&s.display_scale>0&&[...s.display_bounds,...s.display_size].every(Number.isFinite)&&
    s.display_bounds[2]>0&&s.display_bounds[3]>0&&s.display_size.every(n=>n>0);
  if(!valid(before)||!valid(after))failed.push('invalid_geometry');
  return failed;
}
export function assertMonitorGeometry(window:BrowserWindow,before:GeometrySnapshot,stage:CaptureGeometryDiagnostic['stage'],trace?:CaptureGeometryTrace,source:CaptureGeometryDiagnostic['source']=null):void {
  const after=captureGeometry(window,true),failed=monitorGeometryFailures(before,after);
  if(failed.length)throw new CaptureGeometryError({stage,failed,before,after,events:trace?.snapshot()??[],source});
}
