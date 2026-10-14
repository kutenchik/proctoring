"""No devices/network: exercise production HTTP classification and bounded durable failures."""
import json
import pytest
import requests
from proctoring.connected.client import ConnectedClient, ConnectedError
from proctoring.connected.settings import ConnectedConfig
from proctoring.connected.sync import SyncWorker


def test_nested_transport_causes_are_fixed_codes_not_exception_messages():
    import socket
    import ssl
    from urllib3.exceptions import MaxRetryError, NewConnectionError
    from proctoring.connected.client import transport_failure
    for cause, expected in [(socket.gaierror(-2, 'private-host'), 'dns_failed'),
                            (ConnectionResetError('private-url'), 'connection_reset'),
                            (ConnectionRefusedError('private-url'), 'connection_refused'),
                            (ssl.SSLCertVerificationError('private-cert'), 'tls_certificate_failed')]:
        middle=NewConnectionError(None,'private-endpoint');middle.__cause__=cause
        outer=requests.ConnectionError(MaxRetryError(None,'private-url',middle))
        assert transport_failure(outer)==expected
    assert transport_failure(requests.ConnectionError('opaque'))=='connection_failed'


class Reply:
    status_code = 200
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def iter_content(self,size): yield b'not JSON: private body'


@pytest.mark.parametrize('failure,code,phase',[(None,'invalid_response','response_parse'),
    (requests.exceptions.ConnectTimeout('private URL/token'),'connect_timeout','request'),
    (requests.exceptions.ReadTimeout('private URL/token'),'read_timeout','request'),
    (requests.exceptions.SSLError('private certificate detail'),'tls_failed','request')])
def test_http_failures_preserve_safe_stage_without_body_or_secret(tmp_path,monkeypatch,failure,code,phase):
    class Session:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def request(self,*args,**kwargs):
            assert kwargs['verify'] is True and kwargs['allow_redirects'] is False
            if failure: raise failure
            return Reply()
    monkeypatch.setattr(requests,'Session',Session)
    client=ConnectedClient(ConnectedConfig(),remember_path=tmp_path/'remember')
    for i in range(40):
        with pytest.raises(ConnectedError) as error:
            client._request('POST','https://example.invalid','/student/sync/files/events/chunks',{'private':'content'},'secret')
    assert str(error.value)==('connection_failed' if failure else 'invalid_response')
    assert len(client.request_diagnostics)==32
    diagnostic=client.request_diagnostics[-1]
    assert diagnostic['code']==code and diagnostic['phase']==phase
    assert diagnostic['operation']=='sync_chunk'
    assert all(word not in json.dumps(list(client.request_diagnostics)) for word in ['private','secret','example.invalid'])


def test_first_sync_failure_is_not_overwritten_and_original_origin_is_retained(tmp_path):
    row={'attempt_id':'a','server':'https://original.invalid','credential':'original-secret'}
    class Journal:
        def attempts(self): return [dict(row)]
        def update(self,key,**kwargs): row.update(kwargs);return dict(row)
    count=0
    def transport(method,origin,endpoint,payload,credential):
        nonlocal count
        assert origin=='https://original.invalid' and credential=='original-secret'
        count+=1
        e=ConnectedError('connection_failed');e.diagnostic={'code':'read_timeout','elapsed_ms':count};raise e
    worker=SyncWorker(Journal(),tmp_path,transport)
    for i in range(40):
        with pytest.raises(ConnectedError): worker._call(row,'/student/sync/status')
    assert row['first_sync_failure']['elapsed_ms']==1
    assert len(row['sync_diagnostics'])==32 and row['sync_diagnostics'][-1]['elapsed_ms']==40
    assert 'receipt' not in row and not row.get('cleanup')

def test_delivery_trace_rejects_unbounded_and_private_fields():
    from proctoring.connected.screen_diagnostic import valid_delivery_trace
    value={'counts':{'ack_received':1},'records':[{'stage':'ack_received','sequence':1,'at_ms':1,'value':0}]}
    assert valid_delivery_trace(value)
    assert not valid_delivery_trace({**value,'secret':'never'})
    assert not valid_delivery_trace({**value,'records':value['records']*129})
    assert not valid_delivery_trace({**value,'records':[{**value['records'][0],'stage':['bad']}]})


def test_durable_worker_retries_connection_loss_after_backoff_without_new_identity(tmp_path):
    row={'attempt_id':'same','server':'https://original.invalid'};now=[0.];calls=[]
    class Journal:
        def attempts(self):return [dict(row)]
        def update(self,key,**values):row.update(values);return dict(row)
    worker=SyncWorker(Journal(),tmp_path,None,clock=lambda:now[0])
    class Step:
        stopped=False
        def wait(self,seconds):now[0]+=seconds;return self.stopped or now[0]>10
        def is_set(self):return self.stopped
    step=Step();worker.stop_event=step
    def once(current):
        calls.append(now[0]);assert current['attempt_id']=='same' and current['server']==row['server']
        if len(calls)==1:raise ConnectedError('connection_failed')
        assert row['sync_status']=='offline';step.stopped=True
    worker.once=once;worker._run()
    assert len(calls)==2 and calls[1]-calls[0]>=2
    assert 'receipt' not in row and 'cleanup' not in row
