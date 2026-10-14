import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir:'./tests/ui',testMatch:'live.spec.ts',fullyParallel:false,workers:1,timeout:60000,
  reporter:'list',outputDir:'./test-results/live',
  use:{baseURL:'http://127.0.0.1:5177',channel:'msedge',headless:true,viewport:{width:1360,height:900},trace:'off'},
  webServer:[
    {command:'..\\.venv-server\\Scripts\\python.exe tests\\start_server.py',url:'http://127.0.0.1:8013/api/v1/health',reuseExistingServer:false,timeout:30000,env:{TEACHER_TEST_API_PORT:'8013',TEACHER_TEST_ORIGIN:'http://127.0.0.1:5177'}},
    {command:'npx vite --host 127.0.0.1 --port 5177 --strictPort',url:'http://127.0.0.1:5177',reuseExistingServer:false,timeout:30000,env:{TEACHER_API_PROXY:'http://127.0.0.1:8013'}},
  ],
});
