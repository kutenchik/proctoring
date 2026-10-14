import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';
import { DEVELOPMENT_CSP, PRODUCTION_CSP } from './electron/security';
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss(), {
    name: 'local-application-csp',
    transformIndexHtml(html, context) {
      return { html, tags: [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy',
        content: context.server ? DEVELOPMENT_CSP : PRODUCTION_CSP }, injectTo: 'head-prepend' }] };
    },
  }],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  build: { target: 'es2022', sourcemap: false },
});
