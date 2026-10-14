import { useEffect, useRef, useState } from 'react';
import type { ReviewEvent, WorkflowState } from '../../shared/contracts';
import { readEventBatch, subscribeJournal } from './backend';
import { ReviewEventCache } from './reviewEventCache';
interface EventBatch { session_id: string | null; cursor: number; has_more: boolean; records: { sequence: number; record: Record<string, unknown> }[] }
/** A display cache of authoritative IDs, never a second misconduct engine/log. */
export function useReviewEvents(workflow: WorkflowState) {
  const [records, setRecords] = useState<ReviewEvent[]>(workflow.events.records);
  const [error, setError] = useState(false);
  const current = useRef({ session: workflow.session_id, cursor: 0, busy: false, records: new ReviewEventCache() });
  useEffect(() => subscribeJournal(value => {
    const data = value as EventBatch;
    if (!data || data.session_id !== current.current.session || !Array.isArray(data.records)) return;
    const cache = current.current;
    cache.records.journal(data.records);
    setRecords([...cache.records.values()]);
  }), []);
  useEffect(() => {
    const cache = current.current;
    if (cache.session !== workflow.session_id) current.current = { session: workflow.session_id, cursor: 0, busy: false, records: new ReviewEventCache() };
    const active = current.current;
    active.records.snapshot(workflow.events.records, workflow.events.cursor);
    setRecords([...active.records.values()]);
    if (!workflow.session_id || active.busy || active.cursor >= workflow.events.cursor) return;
    active.busy = true;
    void (async () => {
      try {
        let more = true;
        while (more && active === current.current) {
          const data = await readEventBatch(active.cursor) as EventBatch | null;
          if (!data || active !== current.current || data.session_id !== active.session) return;
          active.records.journal(data.records);
          if (data.cursor <= active.cursor && data.has_more) throw new Error('Event cursor did not advance');
          active.cursor = data.cursor; more = data.has_more;
          setRecords([...active.records.values()]);
        }
        setError(false);
      } catch { setError(true); }
      finally { active.busy = false; }
    })();
  }, [workflow.session_id, workflow.events.cursor, workflow.events.records]);
  useEffect(() => () => { current.current = { session: null, cursor: 0, busy: false, records: new ReviewEventCache() }; }, []);
  return { records, error, pending: current.current.cursor < workflow.events.cursor };
}
