import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import path from 'node:path';

export interface Inspection {
  identity: unknown; config_sha256: string; report_path: string; language: string; valid: boolean; audit_required?: boolean;
}
export interface StartupDependencies {
  directory: string; portableIdentity: string;
  inspect: (report?: string) => Promise<Inspection>;
  run: (report: string) => Promise<{ status: string; exit_code: number | null }>;
  confirmRetry: (reason: string) => Promise<boolean>;
  cancelled: () => boolean;
}
const hash = (data: string | Buffer) => createHash('sha256').update(data).digest('hex');
async function atomic(file: string, data: string | Buffer) {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${randomUUID()}.tmp`;
  await writeFile(temporary, data, { flag: 'wx' }); await rename(temporary, file);
}
/** Join is authorized only after independent report validation AND drained child close.
 * An interrupted startup leaves a durable failure latch. Historical attempts are immutable.
 */
export async function authorizeStartup(d: StartupDependencies): Promise<boolean> {
  const initial = await d.inspect();
  // Only the trusted backend inspection of immutable package defaults can opt out.
  // No report or successful audit receipt is fabricated for this edition.
  if (initial.audit_required === false) return !d.cancelled();
  const key = hash(JSON.stringify([initial.identity, initial.config_sha256, d.portableIdentity]));
  const directory = path.join(d.directory, key);
  const receiptPath = path.join(directory, 'receipt.json');
  await mkdir(directory, { recursive: true });
  let receipt: any;
  try { receipt = JSON.parse(await readFile(receiptPath, 'utf8')); } catch { /* First launch. */ }
  if (receipt?.status === 'completed' && initial.valid && receipt.key === key &&
      receipt.report_sha256 === hash(await readFile(initial.report_path))) return !d.cancelled();
  if (receipt && receipt.status !== 'completed' && !await d.confirmRetry(receipt.first_failure || 'Previous check did not finish')) return false;
  if (d.cancelled()) return false;
  const report = path.join(directory, `${Date.now()}-${randomUUID()}.json`);
  const pending = { status: 'incomplete', key, report, first_failure: 'Security check interrupted before completion' };
  await atomic(receiptPath, JSON.stringify(pending));
  try {
    const exit = await d.run(report);
    if (exit.status !== 'exited' || exit.exit_code !== 0 || d.cancelled()) throw Error('Audit process did not finish successfully; review its saved diagnostics');
    const final = await d.inspect(report);
    if (!final.valid || JSON.stringify(final.identity) !== JSON.stringify(initial.identity) ||
        final.config_sha256 !== initial.config_sha256) throw Error('Completed audit does not match this runtime and configuration');
    const bytes = await readFile(report);
    // The current prerequisite is a replaceable pointer copy; the original stays in history.
    await atomic(initial.report_path, bytes);
    await atomic(receiptPath, JSON.stringify({ status: 'completed', key, report, report_sha256: hash(bytes), exit_code: 0 }));
    return true;
  } catch (error) {
    await atomic(receiptPath, JSON.stringify({ ...pending, status: 'failed', first_failure: String(error) }));
    throw error; // Never retry within this launch.
  }
}
