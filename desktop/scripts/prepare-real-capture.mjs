import {build} from 'esbuild';
import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const desktop=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
export const output=path.resolve(desktop,'../build/stage4a-stream-fix/real-capture-fixture-v2');
export async function prepare(){
  await mkdir(output,{recursive:true});
  const originals={};
  const instrument={name:'numeric-capture-probes',setup(builder){builder.onLoad({filter:/screen_(geometry|capture)\.ts$/},async({path:file})=>{
    let text=await readFile(file,'utf8');originals[path.relative(desktop,file)]=createHash('sha256').update(text).digest('hex');
    const inject=(anchor,addition)=>{if(text.split(anchor).length!==2)throw Error('production_probe_anchor_changed');text=text.replace(anchor,anchor+'\n'+addition);};
    if(file.endsWith('screen_geometry.ts'))inject('const after=captureGeometry(window,true),failed=monitorGeometryFailures(before,after);',
      '(globalThis as any).__captureFixtureBoundary?.({stage,failed,before,after,events:trace?.snapshot()??[],source});');
    return {contents:text,loader:'ts'};
  });}};
  const result=await build({absWorkingDir:desktop,entryPoints:['tests/fixtures/real-capture/main.ts','tests/fixtures/real-capture/preload.ts'],
    bundle:true,platform:'node',format:'cjs',external:['electron'],outdir:output,outExtension:{'.js':'.cjs'},plugins:[instrument],metafile:true});
  const inputs=Object.keys(result.metafile.inputs);
  if(inputs.some(p=>p.includes('electron/main.ts')||p.includes('live_screen.ts')||p.includes('bridge.ts')))throw Error('unexpected_backend_dependency');
  for(const file of ['index.html','renderer.js'])await copyFile(path.join(desktop,'tests/fixtures/real-capture',file),path.join(output,file));
  await writeFile(path.join(output,'build-identity.json'),JSON.stringify({prepared_at:new Date().toISOString(),production_sources:originals,inputs,real_capture_launched:false},null,2));
  return output;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){await prepare();console.log('Fixture built only. No Electron process or capture started.');}
