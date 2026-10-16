"""Synthetic buffers only: no microphone stream or native protection."""
from dataclasses import replace
from pathlib import Path
import struct
import threading
import time
import wave
import numpy as np
import pytest
from proctoring.audio.evidence import AudioEvidence, AudioEvidenceConfig, validate_wav, MAX_BYTES
from proctoring.advanced.settings import consent_version
from proctoring.exam_policy import default_policy, validate_policy, V2_KEYS, live_patch, apply_policy
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.clock import FakeClock


def feed(recorder, start, stop):
    for index in range(round(start*20), round(stop*20)):
        recorder.feed(np.full(800,index/1000,dtype=np.float32),(index+1)/20,16000)


def finish(recorder):
    recorder.close(); recorder.thread.join(3)
    assert recorder.finished
    return recorder.drain()


def test_disabled_and_consent_fail_closed(tmp_path):
    assert not AudioEvidenceConfig().enabled
    with pytest.raises(ValueError): AudioEvidence(AudioEvidenceConfig(),tmp_path)
    config=replace(load_config(),audio_evidence=AudioEvidenceConfig(True),sessions_dir=tmp_path)
    c=AppController(config,FakeClock())
    with pytest.raises(RuntimeError,match='consent v5'): c.start()
    assert c.audio_evidence is None and not list(tmp_path.iterdir())
    c.close_optional_workers()


def test_exact_pre_post_duplicate_and_immutable(tmp_path):
    recorder=AudioEvidence(AudioEvidenceConfig(True),tmp_path)
    feed(recorder,0,5);recorder.trigger('audio-event-1',5)
    for _ in range(100): recorder.trigger('audio-event-1',5)
    feed(recorder,5,10)
    results=finish(recorder)
    assert results==[('audio-event-1','audio/audio-event-1.wav',None)]
    path=tmp_path/results[0][1]
    assert validate_wav(path)==8
    with wave.open(str(path),'rb') as wav:
        samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
    assert len(samples)==128000 and samples[0]==int(.040*32767) and samples[-1]==int(.199*32767)
    original=path.read_bytes();recorder.trigger('audio-event-1',20)
    assert path.read_bytes()==original and len(recorder.seen)==1
    assert not list(tmp_path.rglob('*.partial'))


def test_insufficient_audio_interruption_and_shutdown(tmp_path):
    r=AudioEvidence(AudioEvidenceConfig(True),tmp_path)
    r.trigger('empty',0)
    r.feed(np.zeros(800),.05,16000,False)
    feed(r,1,2);r.trigger('short',2);feed(r,2,2.5)
    result={event:(path,reason) for event,path,reason in finish(r)}
    assert result['empty']==(None,'audio_interrupted')
    assert result['short'][1]=='capture_ended_early'
    assert validate_wav(tmp_path/result['short'][0])==1.5
    r.feed(np.ones(800),5,16000)
    assert not r.ring and not r.pending


def test_slow_writer_does_not_block_capture_or_close(tmp_path,monkeypatch):
    import proctoring.audio.evidence as module
    entered=threading.Event();release=threading.Event();fsync=module.os.fsync
    def slow(fd):
        entered.set();assert release.wait(3);fsync(fd)
    monkeypatch.setattr(module.os,'fsync',slow)
    r=AudioEvidence(AudioEvidenceConfig(True,0,1),tmp_path)
    feed(r,0,1);r.trigger('first',1);feed(r,1,2)
    assert entered.wait(2)
    before=time.monotonic()
    for n in range(12):
        r.trigger('event-'+str(n),2+n);feed(r,2+n,3+n)
    r.close()
    assert time.monotonic()-before < 1 and not r.finished
    assert r.jobs.qsize()<=4 and not (tmp_path/'audio/first.wav').exists()
    release.set();r.thread.join(3)
    assert r.finished and any(reason=='writer_capacity' for _,_,reason in r.drain())


def test_limits_and_format(tmp_path):
    r=AudioEvidence(AudioEvidenceConfig(True),tmp_path)
    feed(r,0,30)
    assert len(r.ring)<=82
    for i in range(4):r.trigger(str(i),30)
    assert r.trigger('overflow',30)=='capture_capacity'
    r.seen=set(str(i) for i in range(1900))
    assert r.trigger('limit',30)=='capacity_or_closed' and len(r.seen)==1900
    finish(r)
    path=tmp_path/'bad.wav';path.write_bytes(b'x'*(MAX_BYTES+1))
    with pytest.raises(ValueError):validate_wav(path)
    path.write_bytes(b'RIFF'+b'x'*100)
    with pytest.raises(ValueError):validate_wav(path)


def test_policy_v2_migration_and_no_live_enabling():
    old=default_policy();old['schema_version']=2;old['values']={k:v for k,v in old['values'].items() if k in V2_KEYS}
    migrated=validate_policy(old)
    assert migrated['schema_version']==3 and not migrated['values']['audio_evidence.enabled']
    enabled=default_policy();enabled['values'].update({'audio.enabled':True,'audio_evidence.enabled':True,'audio_evidence.pre_seconds':2.5})
    assert consent_version({'monitoring_policy':enabled})==5
    assert apply_policy(load_config(),enabled).audio_evidence.pre_seconds==2.5
    for patch in ({'audio_evidence.enabled':True},{'audio_evidence.pre_seconds':2}):
        with pytest.raises(ValueError):live_patch(migrated,patch)
    assert consent_version({'monitoring_policy':migrated})==3


def test_controller_publication_end_and_single_canonical_event(tmp_path,monkeypatch):
    from proctoring.settings import AudioConfig
    from proctoring.domain import EventType
    import json
    c=AppController(replace(load_config(),sessions_dir=tmp_path,audio=AudioConfig(enabled=True),audio_evidence=AudioEvidenceConfig(True),snapshots_enabled=False),FakeClock())
    monkeypatch.setattr(c.audio,'start',lambda:None)
    c.audio_evidence_consent=True;c.start()
    recorder=c.audio_evidence
    assert c.audio.evidence_sink is recorder
    feed(recorder,0,5)
    record={'event_id':'event-1','event_type':EventType.VOICE_DETECTED.value,'action':'activated','start_timestamp':c.clock.wall_time(),'duration_seconds':2}
    c._write_audio_events([record],5)
    c._write_audio_events([record],5)
    assert c._event_metadata['audio-event-1']['audio_status']=='pending'
    feed(recorder,5,7)
    c.end('completed')
    assert c.session.ended and not c.protection.armed
    recorder.thread.join(2);c.step()
    assert c.summary is not None and recorder.finished and c.audio.evidence_sink is None
    rows=[json.loads(line) for line in (c.store.path/'events.jsonl').read_text().splitlines()]
    changes=[r for r in rows if r.get('event_id')=='audio-event-1']
    assert sum(r.get('action')=='activated' for r in changes)==1
    assert changes[-1]['audio_status']=='ready' and changes[-1]['audio_reason']=='capture_ended_early'
    assert validate_wav(c.store.path/changes[-1]['audio_path'])==5
    c.close_optional_workers()


def test_no_setup_buffers_and_monitor_stop_closes_writer(tmp_path):
    from proctoring.audio.monitor import AudioMonitor
    from proctoring.settings import AudioConfig
    r=AudioEvidence(AudioEvidenceConfig(True),tmp_path,start_time=5)
    feed(r,0,5);assert not r.ring
    feed(r,5,6);r.trigger('clip',6)
    monitor=AudioMonitor(AudioConfig(enabled=True),FakeClock());monitor.evidence_sink=r
    monitor.stop();r.thread.join(2)
    assert r.finished and monitor.evidence_sink is None and not r.ring


@pytest.mark.parametrize('published',[False,True])
def test_interrupted_result_reconciles_atomic_file(tmp_path,published):
    from types import SimpleNamespace
    from proctoring.connected.workflow import ConnectedWorkflow
    from proctoring.settings import AudioConfig
    c=AppController(replace(load_config(),sessions_dir=tmp_path,audio=AudioConfig(enabled=True)),FakeClock())
    c._ensure_store()
    event={'event_id':'audio-event-1','event_type':'voice_detected','start_timestamp':c.clock.wall_time(),'audio_status':'pending'}
    c._append({'record_kind':'review_event',**event})
    if published:
        r=AudioEvidence(AudioEvidenceConfig(True),c.store.path);feed(r,0,1);r.trigger('audio-event-1',1);finish(r)
    adapter=SimpleNamespace(bridge=SimpleNamespace(controller=c))
    ConnectedWorkflow.restore_events(adapter,{'events':[event]})
    assert c._event_metadata['audio-event-1']['audio_status']==('ready' if published else 'unavailable')
    assert c._event_metadata['audio-event-1']['audio_reason']=='application_interrupted'
    c.close_optional_workers()
