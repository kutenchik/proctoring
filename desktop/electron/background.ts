import type { BackendState, CommandResult } from '../shared/contracts';
export function canUploadInBackground(state?: BackendState): boolean {
  return !!state?.workflow?.session.ended && !state.protection.enabled && !!state.synchronization?.can_background &&
    !state.audio.running && !['live','opening'].includes(state.camera.state);
}
export function backgroundFinished(state?: BackendState): boolean {
  return !!state?.synchronization?.fully_synchronized && state.synchronization.pending_attempts === 0;
}
/** Main-process handler: re-check the backend acknowledgement before hiding. */
export async function requestBackgroundUpload(
  state: BackendState | undefined,
  request: () => Promise<CommandResult>,
  enter: (confirmed: BackendState) => void,
): Promise<CommandResult> {
  if (!canUploadInBackground(state)) return {version:1,id:'background',ok:false,error:{code:'background_not_ready',message:'Monitoring must stop before background upload'}};
  const result = await request();
  if (result.ok && canUploadInBackground(result.result)) enter(result.result);
  return result;
}

/** Closing a completed exam is not proof that its evidence is synchronized. */
export function pendingReceiptOnClose(state?:BackendState):boolean {
  return !!state?.workflow?.session.ended && !!state.synchronization && !state.synchronization.fully_synchronized;
}
