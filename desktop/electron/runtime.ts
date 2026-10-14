import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';

export interface RuntimeOptions {
  packaged: boolean; appRoot: string; resources: string; executable: string;
  cwd: string; argv: string[]; env: NodeJS.ProcessEnv;
}
/** No developer executable, URL or working-directory override survives packaging. */
export function resolveRuntime(options: RuntimeOptions) {
  const { packaged, appRoot, resources, executable, cwd, argv, env } = options;
  const repo = path.resolve(appRoot, '..');
  const configIndex = argv.indexOf('--config');
  if (configIndex >= 0 && (!argv[configIndex + 1] || argv[configIndex + 1].startsWith('--'))) throw new Error('--config requires a path');
  const writable = packaged ? path.join(env.LOCALAPPDATA || path.join(env.USERPROFILE || cwd, 'AppData', 'Local'), 'LocalProctoring', 'Electron') : repo;
  const config = configIndex >= 0 ? path.resolve(packaged ? cwd : repo, argv[configIndex + 1]) :
    packaged ? path.join(writable, 'config.toml') : path.join(repo, 'config/default.example.toml');
  return {
    packaged, appRoot, repo, config, writable,
    python: packaged ? path.join(resources, 'backend', 'ProctoringBackend.exe') : env.PROCTORING_PYTHON || path.join(repo, '.venv', 'Scripts', 'python.exe'),
    backendCwd: packaged ? path.dirname(executable) : repo,
    supervisorPrefix: packaged ? ['--desktop-supervisor'] : ['-u', '-m', 'proctoring.desktop_bridge.supervisor'],
    auditPrefix: packaged ? ['--electron-recovery-audit'] : ['-u', '-m', 'proctoring.security.electron_audit'],
    configTemplate: path.join(resources, 'default.example.toml'),
    createConfig: packaged && configIndex < 0,
    dev: !packaged && env.PROCTORING_DEV_URL === 'http://127.0.0.1:5173',
    auditOutput: packaged ? path.join(writable, 'audits', 'electron-recovery.json') : path.join(repo, 'artifacts', 'electron-protection-validation.json'),
  };
}
export function ensureRuntimeConfig(runtime: ReturnType<typeof resolveRuntime>): void {
  if (!runtime.createConfig || existsSync(runtime.config)) return;
  mkdirSync(path.dirname(runtime.config), { recursive: true });
  // COPYFILE_EXCL: never replace the operator's editable configuration.
  try { copyFileSync(runtime.configTemplate, runtime.config, 1); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error; }
}
