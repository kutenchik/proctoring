import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useControlProgress } from '../src/hooks/controlProgress';
import type { BackendState } from '../shared/contracts';

function AuditPresentation() {
  const protectedMode = new URLSearchParams(location.search).get('mode') === 'protected';
  const [state, setState] = useState<BackendState | null>(null);
  useControlProgress(state, true);
  useEffect(() => {
    let alive = true;
    const poll = async () => { const response = await window.proctoring!.command('state.get'); if (alive && response.ok) setState(response.result); };
    void poll(); const timer = setInterval(() => { void poll(); }, 150);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  return <main style={{ fontFamily: 'sans-serif', padding: 32 }}>
    <h1>{protectedMode ? 'Controlled short protection test' : 'Native recovery audit'}</h1>
    <p>{protectedMode ? 'Explicit bounded suppression test. Ctrl+Shift+Alt+Q releases the independent native owner.' : 'No shortcut suppression or foreground containment.'}</p>
    <p>Trusted React commit: {state?.workflow?.snapshot_seq ?? 'waiting'}</p>
    <dialog id="audit-pin-modal"><h2>Proctor PIN · audit focus fixture</h2><label>PIN <input id="audit-pin" type="password" autoComplete="off" /></label><p>No PIN is collected or submitted by this fixture.</p></dialog>
    <p>This temporary window uses the production commit/paint progress hook. No camera, microphone, exam or evidence recording.</p>
  </main>;
}
createRoot(document.getElementById('root')!).render(<AuditPresentation />);
