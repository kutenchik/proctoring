import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runOwnedAudit } from './owned-audit.mjs';
export { runOwnedAudit };

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const value = flag => { const index = process.argv.indexOf(flag); if (index < 0 || !process.argv[index + 1]) throw Error('Missing argument'); return path.resolve(process.argv[index + 1]); };
  try {
    const config = value('--config'), output = value('--audit-output'), profile = value('--user-data-dir');
    if (!process.argv.includes('--native-input') || !existsSync(config) || existsSync(output)) throw Error('Fresh output and explicit native-input opt-in required');
    const controller = new AbortController();
    const cancel = () => controller.abort();
    process.on('SIGINT', cancel); process.on('SIGTERM', cancel);
    const result = await runOwnedAudit(path.join(root, 'desktop/node_modules/electron/dist/electron.exe'),
      [path.join(root, 'desktop'), '--validate-electron-protection', '--native-input', '--config', config,
        '--audit-output', output, '--user-data-dir', profile], { cwd: root, record: `${output}.launcher.json`, signal: controller.signal });
    process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel);
    const report = JSON.parse(readFileSync(output, 'utf8'));
    process.exitCode = result.status === 'exited' && report.passed === true && report.status === 'completed' ? 0 : 1;
  } catch { process.exitCode = 1; }
}
