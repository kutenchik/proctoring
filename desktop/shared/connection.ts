/** These lifetimes cannot be replaced by Reconnect (pending evidence survives). */
export function terminalConnection(reason?: string | null): boolean {
  return new Set(['python_exited', 'python_start_failed', 'backend_pipe_closed', 'backend_timeout',
    'invalid_backend_message', 'protocol_limit', 'presentation_callback_failed', 'closed', 'cleanup_pending']).has(reason ?? '');
}
