import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'TEACHER_');
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1', port: 5174, strictPort: true,
      proxy: { '/api': { target: env.TEACHER_API_PROXY || 'http://127.0.0.1:8000', changeOrigin: false, ws: true } },
    },
    build: { sourcemap: false },
  };
});
