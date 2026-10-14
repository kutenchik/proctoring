"""Actual bounded WebSocket + HTTP routes, synthetic desktop readiness only.

Temporary SQLite/server, no Electron window, hardware, hooks or remote hosts.
"""
import json
import time
from uuid import uuid4

import requests

from proctoring.connected.live import LiveWorker
from proctoring.connected.live_workflow import LiveWorkflow
from test_connected_live_api import real_server
from test_connected_stage2_api import real_workflow
from test_connected_workflow import prepare,start


def pump(b,predicate,seconds=7):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        b.tick()
        if predicate():return
        time.sleep(.03)
    assert predicate(),(b.live_teacher.public(),b.admission_client.error)


def attach_live(b):
    live=LiveWorkflow(b,display_count_provider=lambda:1);b.live_teacher=live
    b.tick();b.dispatch('screen.consent',{'accepted':True})
    pump(b,lambda:live.consent_acknowledged)
    prepare(b);b._geometry={'geometry_id':'test-geometry'};b.flow.baseline_geometry_id='test-geometry'
    start(b);assert b.controller.session.running,b.admission_client.error
    # Actual local-start confirmation, with the original durable timestamp.
    b.connected_sync.worker.once(b.connected_sync.row())
    return live


def teacher(server):
    session=requests.Session()
    session.headers['Origin']='http://127.0.0.1:50175'
    response=session.post(server['origin']+'/api/v1/auth/login',json={
        'email':'contract@example.test','password':'test-only-password-12345'},timeout=2)
    assert response.status_code==200,response.text
    session.headers['X-CSRF-Token']=response.json()['csrf_token']
    return session


def remote_command(b,server,http,kind,payload):
    base=server['origin']+'/api/v1/attempts/'+b.connected_sync.row()['attempt_id']+'/commands'
    rid=uuid4().hex
    deadline=time.monotonic()+5
    while True:
        b.tick()
        response=http.post(base,json={'request_id':rid,'type':kind,'payload':payload},timeout=2)
        if response.status_code==200:break
        assert response.status_code==409 and time.monotonic()<deadline,response.text
        time.sleep(.1)
    command=response.json()['command']
    result=[]
    def acknowledged():
        history=http.get(base,timeout=2);assert history.status_code==200
        row=next(v for v in history.json()['items'] if v['command_id']==command['command_id'])
        result[:]=[row]
        return row['status'] in ('applied','rejected')
    pump(b,acknowledged)
    assert result[0]['status']=='applied',result[0]
    return result[0]


def close_owned(b):
    workers=[b.live_teacher.worker]
    b.close()
    for worker in workers:
        if worker.thread:worker.thread.join(6);assert not worker.thread.is_alive()


def test_real_control_commands_consent_reconnect_and_terminal_end(tmp_path,real_server):
    b,j=real_workflow(tmp_path,real_server)
    http=teacher(real_server)
    try:
        live=attach_live(b)
        warning=remote_command(b,real_server,http,'warning',{'text':'Actual local command'})
        assert b.controller.session.running and live.public()['messages'][0]['text']=='Actual local command'
        b.clock.advance(2);b.tick();assert b.controller.session.elapsed_seconds==2
        remote_command(b,real_server,http,'pause',{'reason':'Check student'})
        b.dispatch('proctor.pause',{'pin':b.config.proctor_pin})
        remote_command(b,real_server,http,'resume',{'reason':'Teacher check complete'})
        assert b.controller.session.pause_reasons=={'proctor'}
        b.dispatch('proctor.resume',{'pin':b.config.proctor_pin})
        allowance=b.controller.session.duration_seconds
        added=remote_command(b,real_server,http,'add_time',{'seconds':60,'reason':'Additional working time'})
        assert added['result']['new_duration_seconds']==allowance+60
        assert j.attempts()[0]['checkpoint']['time_adjustment_ids']==[added['command_id']]
        old=live.worker;old_generation=old.connection_id
        old.close();old.thread.join(6);assert not old.thread.is_alive()
        b.tick();assert b.controller.session.running and not b.controller.session.pause_reasons
        live.worker=LiveWorker(b.admission_client);live.worker.consent(True);live.worker.start()
        pump(b,lambda:live.worker.connection_id not in (None,old_generation) and live.consent_acknowledged)
        assert b.controller.session.duration_seconds==allowance+60
        assert len(live.messages)==1  # no command replay after reconnect
        assert 'sender_token' not in json.dumps(b.state())
        end=remote_command(b,real_server,http,'end',{'reason':'Finish actual source workflow','confirm':True})
        assert end['result']['state']=='ended' and b.controller.summary['end_reason']=='teacher_ended'
        assert b.controller.summary['duration_seconds']==allowance+60
        assert b.controller.summary['time_adjustment_ids']==[added['command_id']]
        assert b.connected_sync.row()['phase']=='ended_locally'
    finally:http.close();close_owned(b)


def test_real_server_disconnect_does_not_pause_or_generate_misconduct(tmp_path,real_server):
    b,j=real_workflow(tmp_path,real_server)
    try:
        live=attach_live(b)
        process=real_server['process'];process.terminate();process.wait(timeout=3)
        pump(b,lambda:live.worker.connection_id is None)
        for _ in range(10):b.clock.advance(.5);b.tick()
        assert b.controller.session.running and b.controller.session.elapsed_seconds==5
        assert not b.controller.session.pause_reasons and not b.controller.review_events
        assert live.public()['viewing']['state']=='stopped'
        b.dispatch('emergency.end',{})
        assert b.controller.summary['end_reason']=='emergency_shortcut'
    finally:close_owned(b)
