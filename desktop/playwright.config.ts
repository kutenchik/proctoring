import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/ui', fullyParallel: false, workers: 1, timeout: 30000,
  reporter: 'list', outputDir: './test-results',
  use: { baseURL: 'http://127.0.0.1:5173', channel: 'msedge', headless: true, viewport: { width: 1280, height: 720 } },
  webServer: { command: 'npm run ui', url: 'http://127.0.0.1:5173', reuseExistingServer: true },
});
