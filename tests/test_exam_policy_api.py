"""Policy HTTP/admission/live-ack contract using an isolated server and mock devices."""
from datetime import datetime, timezone, timedelta
from proctoring.exam_policy import default_policy
from proctoring.domain import EventType, Observation
from test_connected_live_api import real_server
from test_connected_stage2_api import real_workflow
from test_connected_stage3_api import teacher, attach_live, remote_command, close_owned


def test_teacher_profile_exam_admission_python_and_live_ack(tmp_path,real_server):
    http=teacher(real_server);b=None;base=real_server['origin']+'/api/v1'
    try:
        p=default_policy();p['values'].update({'audio.enabled':False,'snapshots_enabled':False,'events.second_person.enabled':False,'events.phone_visible.seconds':.2})
        r=http.post(base+'/configuration/profiles',json={'name':'Classroom','policy':p},timeout=2);assert r.status_code==201,r.text
        policy=r.json()['policy']
        r=http.post(base+'/libraries',json={'title':'Policy quiz','questions':[{'id':'q1','type':'single_choice','prompt':'Choose','options':[{'id':'a','text':'A'},{'id':'b','text':'B'}],'correct_option_ids':['a']}]},timeout=2)
        assert r.status_code==201,r.text
        now=datetime.now(timezone.utc)
        r=http.post(base+'/exams',json={'title':'Policy contract','exam_type':'native','library_id':r.json()['id'],'admission_start':(now-timedelta(minutes=1)).isoformat(),'admission_close':(now+timedelta(hours=1)).isoformat(),'duration_seconds':120,'timezone':'UTC','shuffle_questions':False,'shuffle_options':False,'audio_monitoring':False,'save_snapshots':False,'protection_mode':'unprotected','monitoring_policy':policy},timeout=2)
        assert r.status_code==201,r.text
        b,j=real_workflow(tmp_path,{**real_server,'code':r.json()['code']})
        assert b.effective_policy==policy and b.controller.audio is None and not b.monitor.started
        assert EventType.SECOND_PERSON in b.controller.events.disabled
        attach_live(b)
        engine=b.controller.events
        for _ in range(5):
            engine.observe(Observation(b.clock.monotonic(),{EventType.PHONE_VISIBLE:.9,EventType.SECOND_PERSON:.9},'synthetic'));b.clock.advance(.1)
        assert [e['event_type'] for e in engine.events]==['phone_visible']
        id=engine.events[0]['event_id']
        remote_command(b,real_server,http,'monitoring_policy',{'reason':'Stop phone warnings for demonstration','patch':{'events.phone_visible.enabled':False},'base_revision':0,'revision':1})
        assert b.policy_revision==1 and EventType.PHONE_VISIBLE in engine.disabled
        assert engine.events[0]['event_id']==id and engine.events[0]['close_reason']=='policy_changed'
        r=http.get(base+'/attempts/'+b.connected_sync.row()['attempt_id']+'/monitoring-policy',timeout=2)
        assert r.status_code==200,r.text
        actual=r.json();assert actual['revision']==1 and actual['policy']==b.effective_policy
        assert actual['history'][0]['status']=='applied' and actual['history'][0]['old_policy']==policy
    finally:
        http.close()
        if b:close_owned(b)
