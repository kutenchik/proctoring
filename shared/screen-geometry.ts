/** Numeric-only capture evidence; no window titles, input payloads or source names. */
export const GEOMETRY_STAGES = ['before_capture','before_mask','after_initial_mask','after_sources','after_final_mask','source_selection'] as const;
export const GEOMETRY_CHECKS = ['window_destroyed','web_contents_destroyed','display_count','display_id',
  'content_x','content_y','content_width','content_height','display_bounds','display_size','display_scale',
  'zoom','invalid_geometry','source_missing','source_ambiguous','source_empty','source_size'] as const;
export const GEOMETRY_EVENTS = ['focus','blur','resize','move','maximize','unmaximize','restore','minimize',
  'enter-full-screen','leave-full-screen','closed','webcontents-destroyed','zoom-changed'] as const;
export type GeometryCheck = typeof GEOMETRY_CHECKS[number];
export interface GeometrySnapshot {
  sampled_at:number;
  window_destroyed:boolean; web_contents_destroyed:boolean; display_count:number;
  display_id:number|null; content:number[]|null; display_bounds:number[]|null; display_size:number[]|null;
  display_scale:number|null; zoom:number|null; focused:boolean|null; maximized:boolean|null;
}
export interface GeometryEvent {
  event:typeof GEOMETRY_EVENTS[number]; at:number; content:number[]|null; zoom:number|null; focused:boolean|null;
}
export interface CaptureGeometryDiagnostic {
  stage:typeof GEOMETRY_STAGES[number]; failed:GeometryCheck[];
  before:GeometrySnapshot; after:GeometrySnapshot; events:GeometryEvent[];
  source:{matches:number;width:number|null;height:number|null;empty:boolean|null}|null;
}
const object=(v:any,keys:string[])=>!!v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const numeric=(v:any)=>typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=Number.MAX_SAFE_INTEGER;
const nullableNumber=(v:any)=>v===null||numeric(v);
const numbers=(v:any,n:number)=>v===null||Array.isArray(v)&&v.length===n&&v.every(numeric);
const nullableBool=(v:any)=>v===null||typeof v==='boolean';
export function validGeometrySnapshot(v:any):v is GeometrySnapshot {
  return object(v,['sampled_at','window_destroyed','web_contents_destroyed','display_count','display_id','content','display_bounds','display_size','display_scale','zoom','focused','maximized'])&&numeric(v.sampled_at)&&v.sampled_at>=0&&
    typeof v.window_destroyed==='boolean'&&typeof v.web_contents_destroyed==='boolean'&&Number.isInteger(v.display_count)&&v.display_count>=0&&v.display_count<=1024&&
    nullableNumber(v.display_id)&&numbers(v.content,4)&&numbers(v.display_bounds,4)&&numbers(v.display_size,2)&&nullableNumber(v.display_scale)&&nullableNumber(v.zoom)&&nullableBool(v.focused)&&nullableBool(v.maximized);
}
export function validCaptureGeometry(v:any):v is CaptureGeometryDiagnostic {
  return object(v,['stage','failed','before','after','events','source'])&&GEOMETRY_STAGES.includes(v.stage)&&
    Array.isArray(v.failed)&&v.failed.length>0&&v.failed.length<=GEOMETRY_CHECKS.length&&new Set(v.failed).size===v.failed.length&&v.failed.every((c:any)=>GEOMETRY_CHECKS.includes(c))&&
    validGeometrySnapshot(v.before)&&validGeometrySnapshot(v.after)&&Array.isArray(v.events)&&v.events.length<=16&&
    v.events.every((e:any)=>object(e,['event','at','content','zoom','focused'])&&GEOMETRY_EVENTS.includes(e.event)&&numeric(e.at)&&e.at>=0&&numbers(e.content,4)&&nullableNumber(e.zoom)&&nullableBool(e.focused))&&
    (v.source===null||object(v.source,['matches','width','height','empty'])&&Number.isInteger(v.source.matches)&&v.source.matches>=0&&v.source.matches<=1024&&nullableNumber(v.source.width)&&nullableNumber(v.source.height)&&nullableBool(v.source.empty));
}
