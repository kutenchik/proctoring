import { validCaptureGeometry, type CaptureGeometryDiagnostic } from '../../../../shared/screen-geometry';
import { screenCode } from '../../../../shared/screen-diagnostic';

export const PHASES=[{name:'untouched',seconds:30},{name:'click_background',seconds:20},
  {name:'click_controls',seconds:20},{name:'scroll',seconds:20},{name:'focus_unfocus',seconds:20},
  {name:'other_application',seconds:20},{name:'return_focus',seconds:20}] as const;
type Phase=typeof PHASES[number]['name'];
type MaskSample={stage:'initial_mask'|'final_mask';count:number;rectangles:(number|null)[][]};
type Attempt={sequence:number;started_at:number;phase:Phase;guards:CaptureGeometryDiagnostic[];masks:MaskSample[];completed_at:number|null;result:'pending'|'captured'|'rejected'};
export class Recorder {
  state:'awaiting_consent'|'running'|'failed'|'stopped'|'complete'='awaiting_consent';
  private startTime=0;
  private startedAt=0;
  private stoppedTime:number|null=null;
  private attempts=0;
  private captured=0;
  private current?:Attempt;
  private recent:Attempt[]=[];
  private firstFailure:unknown=null;
  private secondary:string[]=[];
  private phaseCounts=new Map<Phase,number>();
  constructor(private approved:boolean,private mode:'real'|'mock',private clock=()=>performance.now()){}
  start(consent:unknown):boolean {
    if(!this.approved||consent!==true||this.state!=='awaiting_consent')return false;
    this.startTime=this.clock();this.startedAt=Date.now();this.state='running';return true;
  }
  phase():Phase {
    let elapsed=Math.max(0,((this.stoppedTime??this.clock())-this.startTime-5000)/1000);
    for(const p of PHASES){if(elapsed<p.seconds)return p.name;elapsed-=p.seconds;}
    return 'return_focus';
  }
  begin():boolean {
    if(this.state!=='running'||this.current||this.clock()-this.startTime<5000)return false;
    if(this.clock()-this.startTime>=155000||this.attempts>=750){this.stop('complete');return false;}
    this.current={sequence:++this.attempts,started_at:Date.now(),phase:this.phase(),guards:[],masks:[],completed_at:null,result:'pending'};
    this.recent.push(this.current);if(this.recent.length>12)this.recent.shift();return true;
  }
  boundary(value:CaptureGeometryDiagnostic):void {
    if(this.state!=='running'||!this.current||this.current.guards.length>=4)return;
    // Success probes have an empty failure list; validate the same closed schema.
    if(!validCaptureGeometry({...value,failed:value.failed?.length?value.failed:['invalid_geometry']}))throw Error('fixture_invalid_numeric_diagnostic');
    this.current.guards.push(structuredClone(value));
  }
  mask(stage:MaskSample['stage'],value:unknown):void {
    if(this.state!=='running'||!this.current||this.current.masks.length>=2)return;
    const list=Array.isArray(value)?value:[];
    this.current.masks.push({stage,count:Array.isArray(value)?Math.min(list.length,1024):-1,
      rectangles:list.slice(0,16).map(r=>['x','y','width','height'].map(k=>{
        const v=r&&typeof r==='object'?r[k]:null;
        return typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=Number.MAX_SAFE_INTEGER?v:null;
      }))});
  }
  success():void {
    if(this.state!=='running'){this.current=undefined;return;}
    if(this.current){this.current.result='captured';this.current.completed_at=Date.now();
      this.captured++;this.phaseCounts.set(this.current.phase,(this.phaseCounts.get(this.current.phase)??0)+1);}
    this.current=undefined;
  }
  fail(code:unknown,geometry?:CaptureGeometryDiagnostic):void {
    const safe=code==='privacy_mask_changed'||code==='fixture_capture_timeout'||code==='fixture_window_destroyed'||code==='fixture_invalid_numeric_diagnostic'?code:screenCode(code);
    if(this.state!=='running'){if(this.secondary.length<4)this.secondary.push(safe);this.current=undefined;return;}
    if(this.current){this.current.result='rejected';this.current.completed_at=Date.now();}
    this.firstFailure={timestamp:Date.now(),code:safe,terminal_in_production:!['privacy_mask_changed','monitor_capture_failed'].includes(safe),
      phase:this.phase(),geometry:geometry&&validCaptureGeometry(geometry)?structuredClone(geometry):null,
      attempt:this.current?structuredClone(this.current):null};
    this.current=undefined;this.state='failed';this.stoppedTime=this.clock();
  }
  stop(state:'stopped'|'complete'='stopped'):void {
    if(this.state==='running'||this.state==='awaiting_consent'){this.state=state;this.stoppedTime=this.clock();}
  }
  status(){return {state:this.state,phase:this.phase(),seconds:this.startedAt?Math.max(0,Math.floor(((this.stoppedTime??this.clock())-this.startTime)/1000)):0,attempts:this.attempts,captured:this.captured,
    failure_code:(this.firstFailure as {code:string}|null)?.code??null};}
  report(){return {schema:1,mode:this.mode,started_at:this.startedAt||null,...this.status(),
    phase_counts:PHASES.map(p=>({phase:p.name,captured:this.phaseCounts.get(p.name)??0})),
    first_failure:this.firstFailure,recent:structuredClone(this.recent),secondary:[...this.secondary]};}
}
