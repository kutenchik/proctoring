import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir:'./tests/ui',testMatch:'live-teacher.spec.ts',workers:1,timeout:30000,
  reporter:'list',outputDir:'./test-results/stream-fix',
  use:{baseURL:'http://127.0.0.1:5183',channel:'msedge',headless:true,viewport:{width:1280,height:720},trace:'off',screenshot:'off',video:'off'},
  webServer:{command:'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5183 --strictPort',url:'http://127.0.0.1:5183',reuseExistingServer:false},
});
