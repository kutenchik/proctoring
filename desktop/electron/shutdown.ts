/** Terminal cleanup: one failed presentation step cannot skip native recovery. */
export async function finishShutdown(steps: {
  preparation?: Array<() => void | Promise<void>>;
  onStepFailure?: () => void;
  closePresentation: () => void | Promise<void>;
  endSession: () => void | Promise<void>;
  closeBackend: () => void | Promise<void>;
  quit: () => void | Promise<void>;
  reportErrors: (errors: unknown[]) => void;
}): Promise<void> {
  const errors: unknown[] = [];
  for (const step of [...(steps.preparation ?? []), steps.closePresentation, steps.endSession, steps.closeBackend, steps.quit]) {
    try { await step(); } catch (error) {
      errors.push(error);
      try { steps.onStepFailure?.(); } catch { /* Diagnostics cannot skip recovery. */ }
    }
  }
  // Report only after all finalizers ran. Callers do not receive a rejected
  // void stop() promise for a teardown error, and failures remain explicit.
  if (errors.length) steps.reportErrors(errors);
}
