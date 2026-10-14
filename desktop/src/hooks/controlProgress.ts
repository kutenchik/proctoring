import { useEffect, useRef, useState } from 'react';
import type { BackendState, ControlChallenge } from '../../shared/contracts';

/** A committed trusted React view must answer each independent helper challenge.
 * Ordinary IPC/status/preview polling cannot call this acknowledgement for it.
 */
export function useControlProgress(state: BackendState | null, live: boolean) {
  const [challenge, setChallenge] = useState<ControlChallenge | null>(null);
  const generation = useRef(0);
  const answered = useRef('');
  const api = window.proctoring;
  useEffect(() => {
    if (!live || !api?.onControlChallenge) return;
    return api.onControlChallenge(next => setChallenge(previous =>
      previous && previous.lease_id === next.lease_id && previous.sequence === next.sequence &&
      previous.nonce === next.nonce && previous.session_id === next.session_id &&
      previous.required_snapshot_seq === next.required_snapshot_seq ? previous : next));
  }, [api, live]);
  const workflow = state?.workflow;
  useEffect(() => {
    if (!live || !api?.acknowledgeControlProgress || !challenge || !workflow ||
        workflow.session_id !== challenge.session_id ||
        workflow.snapshot_seq < challenge.required_snapshot_seq) return;
    const key = `${challenge.lease_id}:${challenge.sequence}:${challenge.nonce}:${challenge.session_id}`;
    if (answered.current === key) return;
    // This effect runs after the corresponding authoritative view commits.
    // Two animation frames give that commit a paint opportunity before reply.
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        answered.current = key;
        void api.acknowledgeControlProgress({ lease_id: challenge.lease_id,
          sequence: challenge.sequence, nonce: challenge.nonce,
          snapshot_seq: workflow.snapshot_seq, session_id: workflow.session_id,
          render_generation: ++generation.current }).catch(() => { /* no manufactured renewal */ });
      });
    });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, [api, live, challenge, workflow?.snapshot_seq, workflow?.session_id]);
}
