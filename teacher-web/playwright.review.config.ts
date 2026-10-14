import { defineConfig } from '@playwright/test';
/** Stage 2 only, distinct ports from an already-open Stage 1 development preview. */
export default defineConfig({
  testDir:'./tests/ui',testMatch:'review.spec.ts',fullyParallel:false,workers:1,timeout:60000,
  reporter:'list',outputDir:'./test-results/review',
  use:{baseURL:'http://127.0.0.1:5176',channel:'msedge',headless:true,viewport:{width:1280,height:800},trace:'off'},
  webServer:[
    {command:'..\\.venv-server\\Scripts\\python.exe tests\\start_server.py',url:'http://127.0.0.1:8012/api/v1/health',reuseExistingServer:false,timeout:30000,env:{TEACHER_TEST_API_PORT:'8012',TEACHER_TEST_ORIGIN:'http://127.0.0.1:5176'}},
    {command:'npx vite --host 127.0.0.1 --port 5176 --strictPort',url:'http://127.0.0.1:5176',reuseExistingServer:false,timeout:30000,env:{TEACHER_API_PROXY:'http://127.0.0.1:8012'}},
  ],
});
