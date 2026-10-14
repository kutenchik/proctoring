const consent=document.querySelector('#consent'),start=document.querySelector('#start');
let started=false,clicks=0;
consent.addEventListener('change',()=>{start.disabled=!consent.checked||started;});
start.addEventListener('click',async()=>{if(await window.captureFixture.start(consent.checked)){started=true;start.disabled=true;consent.disabled=true;}});
document.querySelector('#stop').addEventListener('click',()=>window.captureFixture.stop());
for(const id of ['#button-a','#button-b'])document.querySelector(id).addEventListener('click',()=>{document.querySelector('#local-counter').textContent=`${++clicks} synthetic button clicks`;});
const instructions={untouched:'Leave this window untouched for 30 seconds.',click_background:'Click ordinary background areas inside this window.',click_controls:'Click different buttons, the toggle and the selector.',scroll:'Scroll up and down inside this window.',focus_unfocus:'Switch focus away from this window and back.',other_application:'Interact with another Windows application for 20 seconds.',return_focus:'Return here and click or scroll normally.'};
function render(s){
  document.querySelector('#mode').textContent=s.mock?'MOCK TEST MODE — no real monitor capture':'REAL MONITOR MODE — numerical diagnostics only';
  document.querySelector('#status').textContent=`${s.state} · ${s.seconds}s · ${s.captured} captures completed${s.failure_code?' · '+s.failure_code:''}`;
  document.querySelector('#instruction').textContent=s.state==='running'?(s.seconds<5?'Five-second countdown: release the mouse and leave the window idle.':instructions[s.phase]):s.state==='awaiting_consent'?'Arrange the window, then consent and start.':'Capture stopped. Do not restart. Close the window after evidence is reviewed.';
  if(s.state!=='awaiting_consent'){start.disabled=true;consent.disabled=true;}
}
window.captureFixture.onStatus(render);window.captureFixture.status().then(render);
