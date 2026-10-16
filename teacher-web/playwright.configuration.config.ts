import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests/ui',testMatch:'configuration.spec.ts',workers:1,timeout:45000,reporter:'list',outputDir:'./test-results/configuration',use:{baseURL:'http://127.0.0.1:5179',channel:'msedge',headless:true,viewport:{width:1280,height:800},trace:'off'},webServer:[
{command:'..\\.venv-server\\Scripts\\python.exe tests\\start_server.py',url:'http://127.0.0.1:8019/api/v1/health',reuseExistingServer:false,env:{TEACHER_TEST_API_PORT:'8019',TEACHER_TEST_ORIGIN:'http://127.0.0.1:5179'}},
{command:'npm run dev -- --port 5179',url:'http://127.0.0.1:5179',reuseExistingServer:false,env:{TEACHER_API_PROXY:'http://127.0.0.1:8019'}}]});
