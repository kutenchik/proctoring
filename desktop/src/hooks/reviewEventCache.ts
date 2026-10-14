import type { ReviewEvent } from '../../shared/contracts';
/** Journal sequence and snapshot cursor share one authoritative ordering. */
export class ReviewEventCache {
  private rows=new Map<string,{record:ReviewEvent;through:number}>();
  snapshot(records:ReviewEvent[],cursor:number) {for(const record of records)this.merge(record,cursor-1);}
  journal(rows:{sequence:number;record:Record<string,unknown>}[]) {
    for(const {sequence,record} of rows) {
      if(record.record_kind==='review_event'&&typeof record.event_id==='string'&&typeof record.event_type==='string')this.merge(record as ReviewEvent,sequence);
      else if(record.record_kind==='snapshot'&&typeof record.event_id==='string') {
        const prior=this.rows.get(record.event_id);
        if(prior)this.rows.set(record.event_id,{...prior,record:{...prior.record,snapshot_path:record.snapshot_path}});
      }
    }
  }
  private merge(record:ReviewEvent,through:number) {
    const old=this.rows.get(record.event_id);
    if(old&&old.through>=through)return;
    this.rows.set(record.event_id,{record:{...record},through});
  }
  values() {return [...this.rows.values()].map(v=>v.record).sort((a,b)=>String(a.activated_timestamp??a.start_timestamp??'').localeCompare(String(b.activated_timestamp??b.start_timestamp??''))||a.event_id.localeCompare(b.event_id));}
}
