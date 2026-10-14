import { createHash } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

export function nativeHandleHex(handle: Buffer): string {
  if (handle.length !== 4 && handle.length !== 8) throw new Error('Unsupported native handle width');
  const value = handle.length === 8 ? handle.readBigUInt64LE() : BigInt(handle.readUInt32LE());
  if (value === 0n) throw new Error('Native window handle is null');
  return `0x${value.toString(16)}`;
}
/** Same byte recipe is independently checked by the native binding/audit. */
export async function desktopBuildFingerprint(appRoot: string): Promise<string> {
  const files: string[] = [];
  async function walk(relative: string): Promise<void> {
    for (const item of await readdir(path.join(appRoot, relative), { withFileTypes: true })) {
      const file = `${relative}/${item.name}`;
      if (item.isSymbolicLink()) throw new Error('Unexpected linked desktop artifact');
      if (item.isDirectory()) await walk(file); else if (item.isFile()) files.push(file);
    }
  }
  await walk('build-electron'); await walk('dist');
  const hash = createHash('sha256').update('proctoring-electron-artifacts-v1\0');
  for (const file of files.sort()) hash.update(file, 'utf8').update('\0').update(await readFile(path.join(appRoot, file))).update('\0');
  return hash.digest('hex');
}
