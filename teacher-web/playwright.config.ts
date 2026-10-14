import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/ui', fullyParallel: false, workers: 1, timeout: 45000,
  reporter: 'list', outputDir: './test-results',
  use: {baseURL: 'http://127.0.0.1:5174', channel: 'msedge', headless: true, viewport: {width:1280,height:800}, trace:'off'},
  webServer: [
    {command: '..\\.venv-server\\Scripts\\python.exe tests\\start_server.py', url:'http://127.0.0.1:8011/api/v1/health', reuseExistingServer:false, timeout:30000},
    {command: 'npm run dev', url:'http://127.0.0.1:5174', reuseExistingServer:false, env:{TEACHER_API_PROXY:'http://127.0.0.1:8011'}, timeout:30000},
  ],
});
