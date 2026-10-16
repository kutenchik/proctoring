import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { StringDecoder } from 'node:string_decoder';
import type { BackendState, Command, HostCommand, CommandResult, ConnectionStatus } from '../shared/contracts';
import { validateCommand, validateState } from './security';
import { PreviewPipe } from './preview';
import { Lifecycle } from './lifecycle';
import { OwnedProcess } from './owned_process';

export class PythonBridge {
  private child?: ChildProcessWithoutNullStreams;
  private decoder = new StringDecoder('utf8');
  private buffer = '';
  private pending = new Map<string, { command: string; resolve: (result: CommandResult) => void; timer: NodeJS.Timeout }>();
  private state: ConnectionStatus = { state: 'disconnected', reason: 'not_started' };
  private closing = false;
  private startAttempted = false;
  private closePromise?: Promise<void>;
  private startupFailure?: string;
  private firstDisconnect?: string;
  private owned?: OwnedProcess;
  readonly diagnostics: Lifecycle;
  latestState?: BackendState;
  onState?: (state: BackendState) => void;
  onDisconnected?: (reason: string) => void;
  readonly preview = new PreviewPipe();
  constructor(private python: string, private config: string, private cwd: string,
    private launchId = randomUUID().replaceAll('-', ''),
    private supervisorPrefix = ['-u', '-m', 'proctoring.desktop_bridge.supervisor'], private packageRoot?: string,
    diagnosticFile?: string) { this.diagnostics = new Lifecycle(diagnosticFile); }
  async start(): Promise<void> {
    // A bridge identifies one backend lifetime. Reconnect reconciles that
    // lifetime; it must never silently replace a dead exam with a fresh one.
    if (this.child || this.closing || this.startAttempted) return;
    this.startAttempted = true;
    this.state = { state: 'connecting' };
    try { await this.preview.listen(); }
    catch { this.state = { state: 'disconnected', reason: 'preview_transport_unavailable' }; return; }
    if (this.closing) { this.preview.close(); return; }
    this.child = spawn(this.python, [...this.supervisorPrefix, '--host-pid', String(process.pid), '--config', this.config,
      '--preview-pipe', this.preview.path, '--preview-token', this.preview.token], {
      cwd: this.cwd, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONUTF8: '1', QT_LOGGING_RULES: '*.debug=false',
        PROCTORING_PACKAGE_ROOT: this.packageRoot || '',
        ...(this.launchId ? { PROCTORING_HOST_LAUNCH_ID: this.launchId } : {}) },
    });
    this.observeChild(this.child);
    await this.command('state.get');
  }
  private observeChild(child: ChildProcessWithoutNullStreams): void {
    this.owned = new OwnedProcess(child);
    child.stdout.on('data', chunk => this.receive(chunk));
    const transportLost = () => {
      if (!this.closing) { this.disconnected('backend_pipe_closed'); void this.close(); }
    };
    child.stdout.on('end', transportLost);
    child.stdout.on('close', transportLost);
    child.stdout.on('error', transportLost);
    child.stdin.on('error', transportLost);
    child.stdin.on('close', transportLost);
    child.stderr.on('error', () => this.diagnostics.record('diagnostic_pipe_closed'));
    // Drain native diagnostics without forwarding private paths/credentials to renderer.
    child.stderr.on('data', chunk => {
      this.diagnostics.stderr(chunk);
      // Only a fixed operational marker is exposed, never arbitrary native logs.
      if (String(chunk).includes('ELECTRON_PROTECTION_UNSUPPORTED')) this.startupFailure = 'protection_unsupported_stage3';
    });
    child.on('error', () => this.disconnected('python_start_failed'));
    child.on('exit', (code) => {
      this.diagnostics.record('supervisor_exited', code ?? undefined);
      this.child = undefined;
      this.disconnected(this.startupFailure ?? (this.closing ? 'closed' : 'python_exited'));
    });
  }
  get status(): ConnectionStatus { return { ...this.state }; }
  get terminated(): boolean { return !this.child || this.child.exitCode !== null || this.child.signalCode !== null; }
  private receive(chunk: Buffer): void {
    this.buffer += this.decoder.write(chunk);
    if (Buffer.byteLength(this.buffer, 'utf8') > 1024 * 1024) { this.disconnected('protocol_limit'); void this.close(); return; }
    let end: number;
    while ((end = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, end); this.buffer = this.buffer.slice(end + 1);
      let result: CommandResult;
      let pending: { command: string; resolve: (result: CommandResult) => void; timer: NodeJS.Timeout } | undefined;
      try {
        result = JSON.parse(line) as CommandResult;
        if (result.version !== 1 || typeof result.id !== 'string' || typeof result.ok !== 'boolean') throw new Error();
        pending = this.pending.get(result.id);
        if (!pending) continue;
        if (result.ok) validateState(result.result);
        if (!result.ok && (!result.error || typeof result.error.code !== 'string' || typeof result.error.message !== 'string')) throw new Error();
      } catch { this.disconnected('invalid_backend_message'); void this.close(); return; }
      clearTimeout(pending.timer); this.pending.delete(result.id);
      this.diagnostics.received(pending.command);
      if (this.firstDisconnect || this.closing) { pending.resolve(result); continue; }
      this.state = { state: 'connected' };
      const publish = result.ok && (!this.latestState?.workflow || !result.result.workflow || result.result.workflow.snapshot_seq >= this.latestState.workflow.snapshot_seq);
      if (publish && result.ok) this.latestState = result.result;
      // A native UI teardown callback must not strand an already validated RPC.
      pending.resolve(result);
      if (publish && result.ok) {
        try { this.onState?.(result.result); }
        catch (error) {
          console.error('Bridge presentation callback failed');
          this.disconnected('presentation_callback_failed'); void this.close(); return;
        }
      }
    }
  }
  command(command: Command, payload: Record<string, unknown> = {}): Promise<CommandResult> {
    return this.request(command, payload, false);
  }
  host(command: Command | HostCommand, payload: Record<string, unknown> = {}): Promise<CommandResult> {
    return this.request(command, payload, true);
  }
  private request(command: Command | HostCommand, payload: Record<string, unknown>, host: boolean): Promise<CommandResult> {
    const id = randomUUID();
    const failure = (code: string): CommandResult => ({ version: 1, id, ok: false, error: { code, message: code } });
    try { validateCommand(command, payload, host); } catch { return Promise.resolve(failure('invalid_command')); }
    if (!this.child || this.child.stdin.destroyed || this.pending.size >= 32 || (this.closing && command !== 'shutdown')) return Promise.resolve(failure('backend_unavailable'));
    return new Promise(resolve => {
      const timer = setTimeout(() => {
        this.pending.delete(id); this.disconnected('backend_timeout');
        resolve(failure('backend_timeout'));
        // A responsive renderer must not keep a wedged media backend alive.
        void this.close();
      }, 8000);
      this.pending.set(id, { command, resolve, timer });
      this.diagnostics.sent(command);
      this.child!.stdin.write(JSON.stringify({ version: 1, id, command, payload }) + '\n', error => {
        if (error) { this.disconnected('backend_pipe_closed'); void this.close(); }
        else this.diagnostics.written(command);
      });
    });
  }
  private disconnected(reason: string): void {
    if (!['closed', 'cleanup_pending'].includes(reason)) {
      this.firstDisconnect ??= reason; this.diagnostics.fail(reason);
    }
    reason = this.firstDisconnect ?? reason;
    this.state = { state: 'disconnected', reason }; this.preview.close();
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.resolve({ version: 1, id, ok: false, error: { code: 'backend_disconnected', message: reason } });
    }
    this.pending.clear();
    try { this.onDisconnected?.(reason); }
    catch (error) {
      this.state = { state: 'disconnected', reason: 'presentation_callback_failed' };
      this.diagnostics.fail('presentation_callback_failed');
      console.error('Bridge disconnection callback failed');
    }
  }
  close(): Promise<void> {
    if (this.closePromise) return this.closePromise;
    this.closing = true;
    this.closePromise = this.closeOwnedProcess();
    return this.closePromise;
  }
  private async closeOwnedProcess(): Promise<void> {
    this.preview.close();
    const child = this.child;
    if (child && child.exitCode === null && child.signalCode === null) {
      // Shutdown lets the backend finalize interrupted records/report work.
      let shutdownTimer: NodeJS.Timeout | undefined;
      try { await Promise.race([this.host('shutdown'), new Promise(r => { shutdownTimer = setTimeout(r, 5000); })]); }
      finally { clearTimeout(shutdownTimer); }
      try { child.stdin.end(); } catch { this.diagnostics.fail('shutdown_pipe_closed'); }
      // The independent supervisor permits the configured helper recovery bound
      // before terminating a wedged backend by retained process HANDLE.
      const grace = child.pid ? 38000 : 1500;
      await new Promise<void>(resolve => {
        if (child.exitCode !== null || child.signalCode !== null) { resolve(); return; }
        const finish = () => { clearTimeout(timer); child.removeListener('exit', finish); resolve(); };
        const timer = setTimeout(finish, grace); child.once('exit', finish);
      });
      if (child.exitCode === null && child.pid) {
        // Node retains this launcher's native process handle. Its supervisor
        // independently owns the verified backend handle; no PID-tree taskkill.
        this.diagnostics.fail('cleanup_pending');
        if (await this.owned?.terminate()) this.diagnostics.record('supervisor_forced_by_main');
        else this.diagnostics.record('supervisor_force_refused');
      }
    }
    this.disconnected(this.terminated ? 'closed' : 'cleanup_pending');
  }
}
