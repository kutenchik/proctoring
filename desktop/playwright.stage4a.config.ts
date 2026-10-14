import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./tests/ui',testMatch:'live-teacher.spec.ts',workers:1,timeout:30000,reporter:'list',
 outputDir:'../build/stage4a-stream-fix/followup/ui-results',
 use:{baseURL:'http://127.0.0.1:5196',channel:'msedge',headless:true,viewport:{width:1280,height:720},screenshot:'off',video:'off',trace:'off'},
 webServer:{command:'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5196 --strictPort',url:'http://127.0.0.1:5196',reuseExistingServer:false}});
