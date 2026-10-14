/** Numeric, bounded, memory-only transport evidence. Never accept message bodies. */
export const TRACE_STAGES = ['capture_start','capture_ready','capture_discard','send','send_blocked','ack_received','ack_accepted','ack_rejected','ack_evicted','frame_received','frame_replaced','decode_start','decode_discard','decode_failed','presented','ack_sent','fallback'] as const;
export type TraceStage = typeof TRACE_STAGES[number];
export interface TraceRow {stage:TraceStage;sequence:number;at_ms:number;value:number;}
export interface StreamTraceSnapshot {counts:Partial<Record<TraceStage,number>>;records:TraceRow[];}
export class StreamTrace {
  private counts:StreamTraceSnapshot['counts']={}; private records:TraceRow[]=[];
  record(stage:TraceStage,sequence=-1,value=0) {
    this.counts[stage]=Math.min(Number.MAX_SAFE_INTEGER,(this.counts[stage]??0)+1);
    this.records.push({stage,sequence,at_ms:Math.round(performance.now()),value:Math.max(0,Math.min(1e9,Math.round(value)))});
    if(this.records.length>128)this.records.shift();
  }
  snapshot():StreamTraceSnapshot {return {counts:{...this.counts},records:this.records.map(r=>({...r}))};}
}
export function validStreamTrace(v:any):v is StreamTraceSnapshot {
  const number=(n:any)=>Number.isSafeInteger(n)&&n>=0&&n<=Number.MAX_SAFE_INTEGER;
  return !!v&&Object.keys(v).sort().join(',')==='counts,records'&&v.counts&&typeof v.counts==='object'&&!Array.isArray(v.counts)&&
    Object.entries(v.counts).every(([k,n])=>TRACE_STAGES.includes(k as TraceStage)&&number(n))&&Array.isArray(v.records)&&v.records.length<=128&&
    v.records.every((r:any)=>r&&Object.keys(r).sort().join(',')==='at_ms,sequence,stage,value'&&TRACE_STAGES.includes(r.stage)&&Number.isSafeInteger(r.sequence)&&r.sequence>=-1&&number(r.at_ms)&&number(r.value)&&r.value<=1e9);
}
