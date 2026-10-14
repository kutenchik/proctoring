import { build } from 'esbuild';
await build({ entryPoints: ['electron/main.ts', 'electron/preload.ts', 'electron/screen_rtc_preload.ts'], bundle: true,
  platform: 'node', format: 'cjs', outdir: 'build-electron', outExtension: { '.js': '.cjs' },
  external: ['electron'], target: 'node22', sourcemap: false });
await build({ entryPoints: ['electron/recovery_renderer.tsx'], bundle: true, platform: 'browser',
  format: 'iife', outfile: 'build-electron/recovery-renderer.js', target: 'chrome140',
  define: { 'process.env.NODE_ENV': '"production"' } });
const { writeFile } = await import('node:fs/promises');
await build({ entryPoints: ['electron/screen_rtc_renderer.ts'], bundle:true, platform:'browser',format:'iife',outfile:'build-electron/screen-transport.js',target:'chrome140' });
await writeFile('build-electron/screen-transport.html', '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'self\'; connect-src \'none\'"><title>Private screen transport</title></head><body><script src="screen-transport.js"></script></body></html>');
await writeFile('build-electron/recovery-renderer.html', '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'self\'; style-src \'unsafe-inline\'"><title>Native recovery audit</title></head><body><div id="root"></div><script src="recovery-renderer.js"></script></body></html>');
