/** Isolated maximum-lease scenario; dependencies permit non-native regression tests. */
export async function runMaximumLeaseCheck(steps: {
  focus(): Promise<void>;
  enable(seconds: number): Promise<void>;
  normalInput(): Promise<void>;
  state(): Promise<any>;
}): Promise<string> {
  await steps.focus();
  await steps.enable(2);
  await steps.normalInput();
  const state = await steps.state();
  // Fixed diagnostic fields only: no input contents, PINs or arbitrary payloads.
  const evidence = JSON.stringify({ native_reason: state.native?.reason,
    public_reason: state.protection?.reason, released_at: state.native?.released_at,
    control_confirmed_at: state.native?.control_confirmed_at,
    armed: state.native?.armed, blocking_enabled: state.native?.blocking_enabled,
    hook_installed: state.native?.hook_installed, hotkey_registered: state.native?.hotkey_registered });
  if (state.native?.reason !== 'lease_expired') throw new Error(`Maximum lease was not the release cause: ${evidence}`);
  if (['armed', 'blocking_enabled', 'hook_installed', 'hotkey_registered'].some(key => state.native?.[key] !== false)) {
    throw new Error(`Maximum lease did not confirm native release: ${evidence}`);
  }
  return `Maximum lease released protection and ordinary input was restored: ${evidence}`;
}
