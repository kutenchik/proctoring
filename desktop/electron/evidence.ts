import { dialog, shell, type BrowserWindow } from 'electron';
import { copyFile, open, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import type { EvidenceIntent, EvidenceResult } from '../shared/contracts';

export interface EvidenceFile { path: string; file_name: string; mime: string }
/** Only Python's current-session ID resolver supplies a path; never a renderer path. */
export async function verifyEvidence(value: unknown): Promise<EvidenceFile> {
  if (!value || typeof value !== 'object') throw new Error('Evidence unavailable');
  const file = value as EvidenceFile;
  if (typeof file.path !== 'string' || !path.isAbsolute(file.path) ||
      typeof file.file_name !== 'string' || path.basename(file.file_name) !== file.file_name ||
      !['image/jpeg', 'application/pdf'].includes(file.mime)) throw new Error('Invalid evidence metadata');
  const resolved = await realpath(file.path);
  const metadata = await stat(resolved);
  if (!metadata.isFile() || metadata.size < 4 || metadata.size > 64 * 1024 * 1024) throw new Error('Evidence size is unavailable or unsupported');
  const extension = path.extname(resolved).toLowerCase();
  if ((file.mime === 'application/pdf' && extension !== '.pdf') || (file.mime === 'image/jpeg' && !['.jpg', '.jpeg'].includes(extension))) throw new Error('Evidence extension mismatch');
  const handle = await open(resolved, 'r');
  const header = Buffer.alloc(5);
  try { await handle.read(header, 0, header.length, 0); } finally { await handle.close(); }
  if (file.mime === 'application/pdf' ? header.toString('ascii') !== '%PDF-' : header[0] !== 255 || header[1] !== 216) throw new Error('Evidence type mismatch');
  return { ...file, path: resolved };
}
export async function actOnEvidence(window: BrowserWindow, intent: EvidenceIntent, data: unknown): Promise<EvidenceResult> {
  try {
    const file = await verifyEvidence(data);
    if (intent.action === 'open') {
      const error = await shell.openPath(file.path);
      return error ? { ok: false, error: 'No application could open this evidence file.' } : { ok: true };
    }
    const result = await dialog.showSaveDialog(window, {
      title: 'Save session evidence', defaultPath: file.file_name,
      filters: [{ name: file.mime === 'application/pdf' ? 'PDF report' : 'JPEG snapshot', extensions: file.mime === 'application/pdf' ? ['pdf'] : ['jpg'] }],
    });
    if (result.canceled || !result.filePath) return { ok: true, cancelled: true };
    const checked = await verifyEvidence(file);
    if (path.resolve(result.filePath).toLowerCase() !== checked.path.toLowerCase()) await copyFile(checked.path, result.filePath);
    return { ok: true };
  } catch { return { ok: false, error: 'Evidence is missing, invalid, or could not be opened or saved.' }; }
}
