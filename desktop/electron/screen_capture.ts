import { desktopCapturer, type BrowserWindow } from 'electron';
import { assertMonitorGeometry, captureGeometry, CaptureGeometryError, type CaptureGeometryTrace } from './screen_geometry';
import type { GeometrySnapshot } from '../../shared/screen-geometry';

/** Retry an API rejection only after fresh authorization and monitor validation. */
export class TransientMonitorCapture extends Error {
  constructor() { super('monitor_capture_failed'); }
}
/** Full monitor pixels, including the existing preview. The broker enforces
 * consent v2. No DOM query, camera device, media track or persistent frame here. */
export async function captureExamMonitor(window: BrowserWindow, maxWidth: number, quality: number, trace?:CaptureGeometryTrace,
  authorized:()=>boolean=()=>false, baseline?:GeometrySnapshot): Promise<{width:number;height:number;jpeg:Buffer}> {
  const requireAuthorization=()=>{if(!authorized())throw new Error('authorization_ended');};
  requireAuthorization();
  if(baseline)assertMonitorGeometry(window,baseline,'before_capture',trace);
  const before=captureGeometry(window,true);
  assertMonitorGeometry(window,before,'before_capture',trace);
  const [displayWidth,displayHeight]=before.display_size!;
  const width=Math.round(Math.min(maxWidth,displayWidth*before.display_scale!,maxWidth*displayWidth/displayHeight));
  const height=Math.round(width*displayHeight/displayWidth);
  let sources;
  try {
    sources=await desktopCapturer.getSources({types:['screen'],thumbnailSize:{width,height},fetchWindowIcons:false});
  } catch {
    requireAuthorization();
    assertMonitorGeometry(window,before,'after_sources',trace);
    throw new TransientMonitorCapture();
  }
  requireAuthorization();
  const matches=sources.filter(s=>s.display_id===String(before.display_id)),source=matches[0];
  const size=source?.thumbnail.getSize();
  const evidence={matches:Math.min(matches.length,1024),width:size?.width??null,height:size?.height??null,empty:source?.thumbnail.isEmpty()??null};
  assertMonitorGeometry(window,before,'after_sources',trace,evidence);
  // Allow one-pixel thumbnail rounding, never a different aspect or oversized source.
  const validSize=size&&Number.isInteger(size.width)&&Number.isInteger(size.height)&&size.width>0&&size.height>0&&
    size.width<=maxWidth&&size.height<=maxWidth&&Math.abs(size.width*displayHeight-size.height*displayWidth)<=Math.max(displayWidth,displayHeight);
  if(matches.length!==1||!source||source.thumbnail.isEmpty()||!validSize)
    throw new CaptureGeometryError({stage:'source_selection',failed:[!source?'source_missing':matches.length!==1?'source_ambiguous':source.thumbnail.isEmpty()?'source_empty':'source_size'],
      before,after:captureGeometry(window,true),events:trace?.snapshot()??[],source:evidence},'monitor_capture_unavailable');
  requireAuthorization();
  try { return {width:size!.width,height:size!.height,jpeg:source.thumbnail.toJPEG(quality)}; }
  catch { throw new Error('image_encode_failed'); }
}
