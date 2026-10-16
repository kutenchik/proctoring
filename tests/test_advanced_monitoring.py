from dataclasses import replace
import time
import pytest
from proctoring.advanced.settings import AdvancedConfig, consent_version
from proctoring.advanced.remote import classify
from proctoring.advanced.remote_monitor import RemoteMonitor
from proctoring.advanced.face_monitor import FaceMonitor
from proctoring.clock import FakeClock
from proctoring.exam_policy import default_policy,validate_policy,LEGACY_KEYS,live_patch,apply_policy
from proctoring.config import load_config


def test_narrow_remote_signatures_and_installed_only():
    r=classify(['AnyDesk.EXE','unknown.exe','not-anydesk.exe'],installed=['teamviewer'],rdp=False)
    assert r['matches']==[
        {'category':'anydesk','state':'process_running','active_control':'unverified'},
        {'category':'teamviewer','state':'installed_not_running','active_control':'unverified'}]
    assert r['not_proof_of_absence']
    assert classify([],rdp=True)['matches'][0]['active_control']=='os_verified'
    assert classify([])['status']=='partial'


def test_remote_repeated_dedup_disappears_reappears_unknown():
    clock=FakeClock();monitor=RemoteMonitor(AdvancedConfig(),clock)
    positive=classify(['rustdesk.exe'],rdp=False)
    def sample(value):
        records=monitor.consume(clock.monotonic(),value,active=True);clock.advance(5);return records
    assert not sample(positive);assert not sample(positive)
    assert sample(positive)[0]['action']=='activated'
    first=monitor.engine.events[0]['event_id']
    for _ in range(5): sample(positive)
    assert len(monitor.engine.events)==1
    sample(classify([],rdp=False));sample(classify([],rdp=False))
    for _ in range(3):sample(positive)
    assert len(monitor.engine.events)==2 and monitor.engine.events[-1]['event_id']!=first
    sample(classify([],process_complete=False))
    assert monitor.engine.events[-1]['close_reason']=='remote_observation_incomplete'


def test_installed_only_and_setup_do_not_seed_events():
    clock=FakeClock();monitor=RemoteMonitor(AdvancedConfig(),clock)
    for _ in range(6):
        monitor.consume(clock.monotonic(),classify([],installed=['anydesk'],rdp=False),active=True);clock.advance(5)
    assert not monitor.engine.events
    for _ in range(6):
        monitor.consume(clock.monotonic(),classify(['anydesk.exe'],rdp=False),active=False);clock.advance(5)
    assert not monitor.engine.events and not monitor.counts


def face_monitor(**overrides):
    clock=FakeClock();config=replace(AdvancedConfig(),identity_enabled=True,**overrides)
    return FaceMonitor(config,clock,'exact-session:attempt'),clock


def feed(m,clock,identity='suspected',**values):
    result={'session':m.session,'generation':m.generation,'timestamp':clock.monotonic(),
            'identity':identity,'distance':.6,'model':'Facenet512','revision':'0.0.102',**values}
    records=m.consume(result,True);clock.advance(m.interval)
    return records


def test_identity_after_absence_original_reference_and_stale_binding():
    m,c=face_monitor();m.enrolled=True
    assert not feed(m,c,'match')
    assert not feed(m,c,'face_missing')
    assert m.enrolled
    assert not feed(m,c);assert not feed(m,c)
    records=feed(m,c);assert records[0]['event_type']=='identity_mismatch_suspected'
    event_id=m.events[0]['event_id']
    feed(m,c,'multiple_faces')
    assert m.events[0]['event_id']==event_id and m.events[0]['state']=='closed'
    assert m.enrolled
    assert not m.consume({'session':'other','timestamp':c.monotonic(),'generation':m.generation},True)
    assert not m.consume({'session':m.session,'timestamp':c.monotonic()-6,'generation':m.generation},True)


@pytest.mark.parametrize('state',['low_quality','multiple_faces','face_missing','inconclusive','unavailable','liveness_inconclusive'])
def test_unknown_interrupts_streak_never_passes(state):
    m,c=face_monitor(liveness_enabled=True)
    feed(m,c,liveness='suspected');feed(m,c,liveness='suspected')
    feed(m,c,state,liveness='inconclusive')
    assert not m.ready and not m.events
    assert not feed(m,c,liveness='suspected')


def test_sustained_spoof_and_no_embedding_in_events():
    m,c=face_monitor(liveness_enabled=True)
    for _ in range(3): records=feed(m,c,'liveness_inconclusive',liveness='suspected',antispoof_score=.97,embedding=[9]*512)
    assert len(m.events)==1 and m.events[0]['event_type']=='presentation_attack_suspected'
    assert 'embedding' not in str(records)


def test_disabled_policy_and_v1_explicit_migration():
    policy=default_policy()
    legacy={'schema_version':1,'values':{k:v for k,v in policy['values'].items() if k in LEGACY_KEYS}}
    upgraded=validate_policy(legacy)
    assert upgraded['schema_version']==3 and consent_version({'monitoring_policy':upgraded})==3
    for k,v in legacy['values'].items():assert upgraded['values'][k]==v
    for feature in ('remote','identity','liveness'):
        current=default_policy();current['values']['advanced.'+feature+'_enabled']=True
        assert consent_version({'monitoring_policy':current})==4
        assert getattr(apply_policy(load_config(),current).advanced,feature+'_enabled')
        with pytest.raises(ValueError):live_patch(policy,{'advanced.'+feature+'_enabled':True})
    with pytest.raises(ValueError): validate_policy({'schema_version':1,'values':{}})


def test_missing_resources_fail_readiness_without_camera(monkeypatch):
    monkeypatch.delenv('PROCTOR_FACE_PYTHON',raising=False)
    monkeypatch.delenv('PROCTOR_FACE_RESOURCES',raising=False)
    m,c=face_monitor();assert m.thread is None
    m.start();m.thread.join(2)
    assert m.state=='unavailable' and not m.ready and m.process is None
    m.close()


def test_no_worker_when_disabled_and_protection_released_first(tmp_path):
    from proctoring.controller import AppController
    config=replace(load_config(),sessions_dir=tmp_path)
    controller=AppController(config)
    assert controller.face_observer is None and controller.remote_observer is None
    order=[]
    class Protection:
        def release(self,reason):order.append('release')
        def drain_events(self):return []
    class Face:
        def close(self):order.append('face_close');return []
    controller.protection=Protection();controller.face_observer=Face()
    controller.end('test')
    assert order[:2]==['release','face_close']


def test_real_offline_worker_generated_nonface_and_process_exit(monkeypatch):
    import json,subprocess,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    python=root/'.venv-face/Scripts/python.exe'
    if not python.is_file():pytest.skip('deliberately prepared optional runtime required')
    monkeypatch.setenv('PROCTOR_FACE_PYTHON',str(python))
    monkeypatch.setenv('PROCTOR_FACE_RESOURCES',str(root/'build/advanced-face'))
    m,c=face_monitor(liveness_enabled=True);m.start()
    deadline=time.monotonic()+10
    while m.state=='initializing' and time.monotonic()<deadline:time.sleep(.02)
    assert m.state=='ready'
    assert not m.ready # model readiness cannot fabricate a reference
    import numpy as np
    from proctoring.vision.types import Box
    m.inputs.put((np.random.default_rng(2).integers(0,256,(240,320,3),dtype=np.uint8),Box(.2,.2,.8,.8),
        {'session':m.session,'sequence':1,'timestamp':c.monotonic(),'generation':m.generation,
         'identity_due':True,'liveness_due':True,'enroll':False}))
    result=m.outputs.get(timeout=6)
    assert result['state']=='result' and result['session']==m.session
    assert result['identity'] in ('inconclusive','low_quality','multiple_faces','ambiguous_face','liveness_inconclusive','reference_required')
    assert not any(k in result for k in ('embedding','reference'))
    assert not m.enrolled
    m.close();m.thread.join(4)
    assert not m.thread.is_alive() and m.process.poll()==0


@pytest.mark.parametrize('behavior',['crash','slow'])
def test_worker_failure_is_bounded_and_poll_never_blocks(monkeypatch,tmp_path,behavior):
    import subprocess,sys
    script=tmp_path/'fake_worker.py'
    script.write_text("import sys,json,time\njson.loads(sys.stdin.readline())\nprint('{\"state\":\"ready\"}',flush=True)\n"+
                     ("raise SystemExit(7)\n" if behavior=='crash' else "time.sleep(30)\n"))
    original=subprocess.Popen
    monkeypatch.setattr(subprocess,'Popen',lambda command,**kw:original([sys.executable,'-u',str(script)],**kw))
    monkeypatch.setenv('PROCTOR_FACE_PYTHON',sys.executable)
    monkeypatch.setenv('PROCTOR_FACE_RESOURCES',str(tmp_path))
    m,c=face_monitor();m.start()
    deadline=time.monotonic()+2
    while m.state=='initializing' and time.monotonic()<deadline:time.sleep(.01)
    began=time.monotonic()
    for _ in range(100):m.poll(True)
    assert time.monotonic()-began<.2 and not m.ready
    if behavior=='slow':
        import numpy as np
        from proctoring.vision.types import Box
        m.inputs.put((np.zeros((240,320,3),dtype=np.uint8),Box(.2,.2,.8,.8),
            {'session':m.session,'sequence':1,'timestamp':0.,'generation':0}))
    deadline=time.monotonic()+7
    while m.state=='ready' and time.monotonic()<deadline:time.sleep(.02)
    assert m.state=='unavailable'
    m.close();m.thread.join(4)
    assert not m.thread.is_alive() and m.process.poll() is not None


def test_adapter_enrollment_match_replacement_and_liveness_score_semantics(monkeypatch):
    import sys
    from pathlib import Path
    import numpy as np
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'src/proctoring/advanced'))
    import face_runtime
    class API:
        real=True;score=.95
        vector=[1.]+[0.]*511
        def extract_faces(self,image,**kwargs):
            assert kwargs['anti_spoofing'] is True
            return [{'face':image[60:180,100:200],'facial_area':{'x':100,'y':60,'w':100,'h':120},
                     'is_real':self.real,'antispoof_score':self.score}]
        def represent(self,image,**kwargs):return [{'embedding':self.vector}]
    api=API();monkeypatch.setattr(face_runtime,'initialize',lambda *args:api)
    config={'identity_enabled':True,'liveness_enabled':True,'facenet_cosine_threshold':.3}
    analyzer=face_runtime.Analyzer('unused',config,'session:attempt')
    image=np.random.default_rng(1).integers(0,256,(240,320,3),dtype=np.uint8)
    request={'session':'session:attempt','box':[100,60,100,120],'enroll':True,'identity_due':True,'liveness_due':True}
    assert analyzer.analyze(image,request)['identity']=='enrolled'
    request['enroll']=False
    assert analyzer.analyze(image,request)['identity']=='match'
    api.vector=[0.,1.]+[0.]*510
    assert analyzer.analyze(image,request)['identity']=='suspected'
    api.real=False
    result=analyzer.analyze(image,request)
    assert result['liveness']=='suspected' and result['identity']=='liveness_inconclusive'
    api.score=.6
    assert analyzer.analyze(image,request)['liveness']=='inconclusive'
    assert analyzer.analyze(np.zeros_like(image),request)['identity']=='low_quality'
    assert not any(key in result for key in ('embedding','reference','face'))
    with pytest.raises(ValueError):analyzer.analyze(image,{**request,'session':'wrong'})


def test_generation_change_breaks_streak_but_keeps_reference():
    m,c=face_monitor();m.state='ready';m.enrolled=True;m.running=True
    feed(m,c);feed(m,c)
    m.generation+=1;m.last_valid=c.monotonic()
    m.poll(True)
    assert m.enrolled and not m.counts
    assert not feed(m,c)


def test_v3_ack_cannot_start_new_monitoring(tmp_path):
    from test_connected_stage3 import make_live
    b,t,j,w,count=make_live(tmp_path)
    try:
        b.controller.session.started=False
        b.config=replace(b.config,advanced=AdvancedConfig(remote_enabled=True))
        b.controller.config=b.config;b.controller.configure_advanced()
        b.admission_client.admission['exam']['monitoring_policy']=default_policy()
        b.admission_client.admission['exam']['monitoring_policy']['values']['advanced.remote_enabled']=True
        b.live_teacher.consent_acknowledged=False
        assert b.live_teacher.consent_version==4
        b.readiness()
        assert b.controller.remote_observer.thread is None and not b.controller.advanced_ready
    finally:b.close()


def test_missing_or_corrupt_resource_fails_closed(tmp_path):
    from proctoring.advanced.resources import verify
    name='haarcascade_eye.xml'
    with pytest.raises(ValueError,match='model_missing'):verify(tmp_path,name)
    directory=tmp_path/'.deepface/weights';directory.mkdir(parents=True)
    (directory/name).write_bytes(b'wrong detector')
    with pytest.raises(ValueError,match='model_hash_mismatch'):verify(tmp_path,name)


def test_worker_parent_handle_observes_owned_process_exit():
    import os,sys,subprocess
    from pathlib import Path
    if os.name!='nt':pytest.skip('Windows process handle')
    directory=Path(__file__).resolve().parents[1]/'src/proctoring/advanced'
    parent=subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'])
    code="import sys,time;sys.path.insert(0,sys.argv[1]);from face_worker import watch_parent;watch_parent(int(sys.argv[2]));print('ready',flush=True);time.sleep(30)"
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(directory),str(parent.pid)],stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='ready'
        parent.wait(timeout=4)
        assert child.wait(timeout=3)==2
    finally:
        for process in (parent,child):
            if process.poll() is None:process.kill();process.wait(timeout=2)
        child.stdout.close()
