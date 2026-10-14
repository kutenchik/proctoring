from types import SimpleNamespace
from proctoring.controller import AppController
from proctoring.clock import FakeClock


def controller(enabled=True):
    c=object.__new__(AppController)
    c.mode='camera';c.config=SimpleNamespace(snapshots_enabled=enabled)
    c._event_metadata={};c._snapshots={};c.remote=None;c.clock=FakeClock()
    c._pending_remote_alerts={};c.records=[];c._append=c.records.append
    return c


def test_disabled_policy_records_event_without_invoking_capture():
    c=controller(False)
    def forbidden(_):raise AssertionError('No snapshot capture when disabled')
    c._save_snapshot=forbidden
    c._write_events([{'event_id':'e','event_type':'phone_visible','action':'activated','duration_seconds':1}])
    assert c.records[0]['snapshot_status']=='disabled'
    assert c.records[0]['snapshot_path'] is None


def test_completion_and_production_failure_keep_original_canonical_event():
    for path,status in [('snapshots/e.jpg','ready'),(None,'unavailable')]:
        c=controller();c._save_snapshot=lambda _:True
        c._write_events([{'event_id':'e','event_type':'phone_visible','action':'activated','duration_seconds':1}])
        c.store=SimpleNamespace(snapshot_results=lambda:[{'event_id':'e','snapshot_path':path}])
        c._drain_snapshot_results()
        assert [r['event_id'] for r in c.records]==['e','e']
        assert c.records[0]['snapshot_status']=='pending'
        assert c.records[1]['snapshot_status']==status
        assert c.records[1]['record_kind']=='snapshot_result'
