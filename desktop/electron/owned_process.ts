import { execFile, type ChildProcess } from 'node:child_process';
import path from 'node:path';

type Identity = { pid: number; created: string; executable: string; owner: string; command: string };
async function readIdentity(pid: number): Promise<Identity | undefined> {
  if (process.platform !== 'win32' || !Number.isSafeInteger(pid) || pid <= 0) return;
  // Private output stays in memory: command line can contain preview credentials.
  const script = `$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); ` +
    `$p=Get-CimInstance Win32_Process -Filter 'ProcessId=${pid}'; if(!$p){exit 2}; ` +
    `$o=Invoke-CimMethod -InputObject $p -MethodName GetOwner; if($o.ReturnValue -ne 0){exit 3}; ` +
    `@{pid=[int]$p.ProcessId;created=$p.CreationDate.ToUniversalTime().ToString('o');executable=$p.ExecutablePath;owner=($o.Domain+'\\'+$o.User);command=$p.CommandLine}|ConvertTo-Json -Compress`;
  return new Promise(resolve => {
    execFile(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32/WindowsPowerShell/v1.0/powershell.exe'),
      ['-NoProfile', '-NonInteractive', '-Command', script], { windowsHide: true, timeout: 3000, maxBuffer: 65536, encoding: 'utf8' },
      (error, stdout) => {
        if (error) { resolve(undefined); return; }
        try {
          const value = JSON.parse(stdout);
          if (value.pid !== pid || !['created', 'executable', 'owner', 'command'].every(k => typeof value[k] === 'string' && value[k].length > 0)) { resolve(undefined); return; }
          resolve({ pid, created: value.created, executable: value.executable, owner: value.owner, command: value.command });
        } catch { resolve(undefined); }
      });
  });
}

/** A complete identity check supplements Node's retained native child handle. */
export class OwnedProcess {
  private initial: Promise<Identity | undefined>;
  constructor(private child: ChildProcess, private read = readIdentity) {
    this.initial = child.pid ? read(child.pid).catch(() => undefined) : Promise.resolve(undefined);
  }
  async terminate(): Promise<boolean> {
    const initial = await this.initial;
    if (!initial || this.child.exitCode !== null || this.child.signalCode !== null) return false;
    const current = await this.read(initial.pid).catch(() => undefined);
    if (!current || (Object.keys(initial) as Array<keyof Identity>).some(k => current[k] !== initial[k]) ||
      this.child.exitCode !== null || this.child.signalCode !== null) return false;
    try { return this.child.kill(); } catch { return false; }
  }
}
