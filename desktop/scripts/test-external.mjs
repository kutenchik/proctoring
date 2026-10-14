// Controlled local fixture site; never uses a university account or production config.
import { createServer } from 'node:http';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { _electron as electron } from 'playwright';

const output = path.resolve('../artifacts/electron-stage2');
await mkdir(output, { recursive: true });
let port;
const server = createServer((req, res) => {
  if (req.url === '/redirect-out') { res.writeHead(302, { Location: `http://localhost:${port}/outside` }); res.end(); return; }
  if (req.url === '/redirect-in') { res.writeHead(302, { Location: '/next' }); res.end(); return; }
  if (req.url === '/download') { res.writeHead(200, { 'Content-Disposition': 'attachment; filename="fixture.txt"' }); res.end('fixture'); return; }
  res.writeHead(200, { 'Content-Type': 'text/html' });
  res.end('<!doctype html><html><body><h1>Controlled external exam fixture</h1><input id="answer" aria-label="Answer"><div id="route">'+req.url+'</div></body></html>');
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
port = server.address().port;
const fixtureURL = `http://127.0.0.1:${port}/`;
const entry = path.join(output, 'external-fixture.cjs');
await build({ stdin: { contents: `
  const {app,BrowserWindow}=require('electron');
  const {ExternalExam}=require(${JSON.stringify(path.resolve('electron/external.ts'))});
  const uncaught=[];
  process.on('uncaughtException',error=>{uncaught.push(String(error?.stack||error));});
  process.on('unhandledRejection',error=>{uncaught.push(String(error?.stack||error));});
  app.whenReady().then(async()=>{
    const win=new BrowserWindow({width:1280,height:800,show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
    await win.loadURL('data:text/html,<h1>Trusted fixture host</h1>');
    let emergencyCount=0;
    const exam=new ExternalExam(win,()=>{emergencyCount++;});
    exam.configure(${JSON.stringify(fixtureURL)},['127.0.0.1']);
    global.fixture={win,exam,ExternalExam,uncaught,getEmergency:()=>emergencyCount};
    exam.setRunning(true);
    exam.intent({action:'layout',bounds:{x:20,y:150,width:700,height:400},visible:true,modal:false});
  });
  app.on('window-all-closed',()=>app.quit());
`, resolveDir: process.cwd() }, bundle: true, platform: 'node', format: 'cjs', external: ['electron'], outfile: entry });
const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
let application;
const results = {};
try {
  application = await electron.launch({ args: [entry], env, timeout: 30000 });
  await application.firstWindow();
  const wait = async predicate => {
    const start = Date.now();
    while (Date.now() - start < 10000) {
      if (await predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error('External fixture assertion timed out');
  };
  await wait(() => application.evaluate(() => global.fixture?.exam.status.state === 'ready'));
  const details = await application.evaluate(async () => {
    const { exam } = global.fixture;
    const wc = exam.view.webContents;
    const prefs = wc.getLastWebPreferences();
    return { prefs: { nodeIntegration: prefs.nodeIntegration, contextIsolation: prefs.contextIsolation, sandbox: prefs.sandbox, preload: prefs.preload || null, devTools: prefs.devTools },
      globals: await wc.executeJavaScript('({bridge:typeof window.proctoring,node:typeof require})') };
  });
  assert.deepEqual(details.globals, { bridge: 'undefined', node: 'undefined' });
  assert.equal(details.prefs.nodeIntegration, false); assert.equal(details.prefs.contextIsolation, true);
  assert.equal(details.prefs.sandbox, true); assert.equal(details.prefs.preload, null);
  assert.equal(await application.evaluate(() => { global.fixture.exam.view.webContents.openDevTools(); return global.fixture.exam.view.webContents.isDevToolsOpened(); }), false);
  results.remoteIsolation = true;
  await application.evaluate(async () => {
    const { exam } = global.fixture;
    await exam.view.webContents.executeJavaScript('document.querySelector("#answer").value="kept answer"');
    exam.setRunning(false);
    if (exam.status.visible) throw new Error('Paused view stayed visible');
    exam.setRunning(true);
    exam.intent({action:'layout',bounds:{x:20,y:150,width:700,height:400},visible:true,modal:true});
    if (exam.status.visible) throw new Error('View covered modal');
    exam.intent({action:'layout',bounds:{x:20,y:150,width:700,height:400},visible:true,modal:false});
    if (!exam.status.visible) throw new Error('Running view failed to return');
    if (await exam.view.webContents.executeJavaScript('document.querySelector("#answer").value') !== 'kept answer') throw new Error('View lost answers on pause');
  });
  results.pauseModalPreservesPage = true;
  const denied = await application.evaluate(async () => global.fixture.exam.view.webContents.executeJavaScript('navigator.mediaDevices.getUserMedia({audio:true}).then(()=>"allowed",e=>e.name)'));
  assert.notEqual(denied, 'allowed'); results.mediaDenied = denied;
  await application.evaluate(async () => global.fixture.exam.view.webContents.executeJavaScript('window.open("/next","_blank")'));
  await wait(() => application.evaluate(() => global.fixture.exam.status.state === 'blocked'));
  assert.equal(await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 1);
  results.popupDenied = true;
  await application.evaluate(async () => global.fixture.exam.view.webContents.executeJavaScript('location.href="/redirect-in"'));
  await wait(() => application.evaluate(() => global.fixture.exam.view.webContents.getURL().endsWith('/next')));
  results.sameHostRedirect = true;
  await application.evaluate(async () => global.fixture.exam.view.webContents.executeJavaScript('location.href="/redirect-out"'));
  await wait(() => application.evaluate(() => global.fixture.exam.status.state === 'blocked'));
  assert.equal(await application.evaluate(() => global.fixture.exam.view.webContents.getURL().includes('localhost')), false);
  results.crossHostRedirectDenied = true;
  await application.evaluate(async (_electron, fixturePort) => global.fixture.exam.view.webContents.executeJavaScript(`const f=document.createElement('iframe');f.src='http://localhost:${fixturePort}/outside';document.body.append(f);`), port);
  await new Promise(resolve => setTimeout(resolve, 300));
  const frameURLs = await application.evaluate(() => global.fixture.exam.view.webContents.mainFrame.frames.map(f => f.url));
  assert.ok(frameURLs.every(url => !url.includes('localhost'))); results.crossHostFrameDenied = true;
  await application.evaluate(async () => global.fixture.exam.view.webContents.executeJavaScript('location.href="/download"'));
  await wait(() => application.evaluate(() => global.fixture.exam.status.message === 'Downloads are blocked'));
  results.downloadDenied = true;
  await application.evaluate(() => {
    const { win, exam } = global.fixture; win.show(); win.focus(); exam.view.webContents.focus();
    exam.view.webContents.sendInputEvent({type:'keyDown',keyCode:'Q',modifiers:['control','shift','alt']});
  });
  await wait(() => application.evaluate(() => global.fixture.getEmergency() === 1));
  results.externalFocusEmergency = true;
  await application.evaluate(() => { global.fixture.exam.layoutAt=Date.now()-3000; global.fixture.exam.tick(); });
  assert.equal(await application.evaluate(() => global.fixture.exam.status.visible), false); results.staleLayoutHidden = true;
  const teardown = await application.evaluate(async ({ BrowserWindow }, fixtureURL) => {
    const { ExternalExam, uncaught } = global.fixture;
    const completed = [];
    for (const kind of ['native_quiz_no_view', 'remote_owner_destroyed', 'remote_close_then_destroy', 'remote_contents_destroyed']) {
      const owner = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
      const exam = new ExternalExam(owner, () => { throw new Error('Teardown must not invoke emergency'); });
      let contents;
      if (kind !== 'native_quiz_no_view') {
        exam.configure(fixtureURL, ['127.0.0.1']); contents = exam.ownedContents;
        exam.setRunning(true); exam.intent({ action: 'layout', bounds: { x: 20, y: 150, width: 700, height: 400 }, visible: true, modal: false });
      }
      // Queue exactly the callback that used to run after native owner death.
      setTimeout(() => exam.tick(), 0);
      if (kind === 'remote_contents_destroyed') contents.close({ waitForBeforeUnload: false });
      if (kind === 'remote_close_then_destroy') exam.close();
      if (kind !== 'remote_contents_destroyed') owner.destroy();
      await new Promise(resolve => setTimeout(resolve, 100));
      exam.tick(); exam.hide(); exam.setRunning(true);
      exam.intent({ action: 'reload' }); exam.intent({ action: 'focus' });
      exam.configure(fixtureURL, ['127.0.0.1']);
      exam.close(); exam.close();
      if (exam.status.visible || exam.status.configured || exam.ownedContents || (contents && !contents.isDestroyed())) throw new Error('Disposed external page was retained or recreated: '+kind);
      if (!owner.isDestroyed()) {
        if (owner.contentView.children.length) throw new Error('Destroyed remote view stayed attached');
        owner.destroy();
      }
      completed.push(kind);
    }
    await new Promise(resolve => setTimeout(resolve, 100));
    return { completed, uncaught: [...uncaught] };
  }, fixtureURL);
  assert.deepEqual(teardown.uncaught, []);
  assert.equal(teardown.completed.length, 4);
  results.shutdownNoViewSafe = true;
  results.shutdownDestroyedOwnerSafe = true;
  results.shutdownCloseIdempotent = true;
  results.shutdownDestroyedContentsSafe = true;
  results.noUncaughtTeardownErrors = true;
  await writeFile(path.join(output, 'external-fixture-result.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results));
} finally {
  if (application) await application.close();
  await new Promise(resolve => server.close(resolve));
}
