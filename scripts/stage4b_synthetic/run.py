"""Disposable synthetic protocol harness. Public execution requires a separate approval.

No device/controller imports. Credentials stay in a dedicated DPAPI journal;
generated live images exist only in bounded pipes/memory, never in evidence logs.
"""
import argparse
import asyncio
import base64
from collections import deque
from io import BytesIO
import json
from pathlib import Path
import secrets
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from proctoring.connected.client import ConnectedClient, ConnectedError
from proctoring.connected.durable import DurableJournal
from proctoring.connected.settings import ConnectedConfig
from proctoring.connected.sync import SyncWorker, verify_receipt
from proctoring_server.service import Service, iso
from proctoring_server.settings import Settings


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def isolated(path):
    path = Path(path).resolve()
    if path.parent != ROOT/'build/stage4b' or not path.is_dir():
        raise ValueError('isolated_run_required')
    config = json.loads((path/'config.json').read_text(encoding='utf-8-sig'))
    if Path(config['repository']).resolve() != ROOT:
        raise ValueError('repository_mismatch')
    return path, config


def prepare(run):
    run, config = isolated(run)
    if (run/'teacher.sqlite3').exists() or (run/'synthetic.json').exists():
        raise ValueError('fresh_database_required')
    # Offline seed has no public authority. Runtime must use the subsequently pinned origin.
    service = Service(Settings(database=run/'teacher.sqlite3', public_url='https://localhost', teacher_origin='https://localhost'))
    journal = DurableJournal(run/'fixture-private.sqlite3')
    token = service.issue_account_token('invite', 'stage4b-synthetic@example.invalid')
    password = secrets.token_urlsafe(24)
    owner = service.consume_account_token('invite', {'token':token,'name':'Synthetic relay teacher','password':password})['teacher']['id']
    library = service.save_library(owner, {'title':'Synthetic fixture', 'questions':[{'id':'q1','type':'single_choice','prompt':'Synthetic fixture only',
        'options':[{'id':'a','text':'A'},{'id':'b','text':'B'}], 'correct_option_ids':['a']}]})
    journal.put('fixture', {'owner':owner,'password':password,'email':'stage4b-synthetic@example.invalid','library_id':library['id']})
    write(run/'synthetic.json', {'schema':1,'synthetic_only':True,'created_at':time.time(),'public_executed':False})
    print('Fresh database/account prepared offline; private credentials are DPAPI encrypted.')


def gate(run, approved):
    run, config = isolated(run)
    import re
    if not approved or not re.fullmatch(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com', config.get('origin') or ''):
        raise ValueError('explicit_approval_and_pinned_origin_required')
    deadline = json.loads((run/'deadline.json').read_text())['deadline']-60
    if not 0 < deadline-time.time() <= 900 or (run/'closed.json').exists():
        raise ValueError('active_deadline_required')
    if not (run/'synthetic.json').exists():
        raise ValueError('prepared_synthetic_run_required')
    return run, config, deadline


def admit(run, origin, kind):
    marker = run/(kind+'-started.json')
    with marker.open('x') as f: json.dump({'at':time.time()}, f)  # one attempt per mode, never resume under another origin
    private = DurableJournal(run/'fixture-private.sqlite3').get('fixture')
    service = Service(Settings(database=run/'teacher.sqlite3',public_url=origin,teacher_origin=origin))
    exam = service.create_exam(private['owner'], {'title':'SYNTHETIC '+kind, 'exam_type':'native','library_id':private['library_id'],
        'admission_start':iso(time.time()-60),'admission_close':iso(time.time()+900),'duration_seconds':900,'timezone':'UTC',
        'shuffle_questions':False,'shuffle_options':False,'audio_monitoring':False,'save_snapshots':False,'protection_mode':'unprotected'})
    journal = DurableJournal(run/(kind+'-outbox.sqlite3'))
    client = ConnectedClient(ConnectedConfig(enabled=True), journal=journal, remember_path=run/'unused-remember.json')
    identity = {'full_name':'SYNTHETIC '+kind,'group':'SYNTHETIC','student_id':uuid4().hex[:12]}
    pending = journal.prepare_admission(origin, identity)
    payload = {**identity,'exam_code':exam['code'],**{k:pending[k] for k in ('admission_id','device_id','device_secret','credential')}}
    try:
        admission = client._request('POST',origin,'/student/admit',payload,None)
    finally:
        write(run/(kind+'-admission-http.json'),list(client.request_diagnostics))
    row = journal.admit(origin, admission, identity, pending['credential'])
    return client, journal, row


def start(client, row):
    payload = {k:row[k] for k in ('session_id','start_key')}
    client._request('POST',row['server'],'/student/start',payload,row['credential'])
    row['fixture_started_at']=iso(time.time())
    client._request('POST',row['server'],'/student/start/confirm',{**payload,'started_at':row['fixture_started_at']},row['credential'])


def frame(sequence):
    from PIL import Image, ImageDraw
    image = Image.new('RGB',(640,360),(sequence%128,60,100))
    ImageDraw.Draw(image).text((30,150),f'SYNTHETIC FRAME {sequence:08d} - NO CAPTURE',fill='white')
    data = BytesIO(); image.save(data, 'JPEG', quality=65)
    return base64.b64encode(data.getvalue()).decode('ascii')


def bundle(run, journal, row):
    """Valid synthetic bundle, >2 chunks of event journal, no physical evidence."""
    from reportlab.pdfgen.canvas import Canvas
    base = run/'synthetic-evidence'; root = base/row['session_id']; root.mkdir(parents=True)
    identity = {'session_id':row['session_id'],'connected_attempt':{'attempt_id':row['attempt_id']}}
    now = iso(time.time())
    write(root/'session.json', {**identity,'reference_face':'reference_face.jpg'})
    with (root/'events.jsonl').open('w',encoding='utf-8',newline='\n') as f:
        for sequence in range(1400):
            f.write(json.dumps({'session_id':row['session_id'],'record_kind':'lifecycle','event_type':'synthetic_fixture',
                'timestamp':now,'synthetic_sequence':sequence,'synthetic_padding':'x'*400})+'\n')
    write(root/'summary.json', {**identity,'started_at':row['fixture_started_at'],'ended_at':now,'end_reason':'completed','elapsed_seconds':1,
        'remaining_seconds':899,'score':0,'total_questions':1,'events':[],'snapshot_errors':[],'storage_error':None})
    write(root/'answers.json', {'session_id':row['session_id'],'attempt_id':row['attempt_id'],'answers':{}})
    canvas = Canvas(str(root/'report.pdf')); canvas.drawString(50,780,'SYNTHETIC protocol fixture - no physical evidence'); canvas.save()
    from PIL import Image
    Image.new('RGB',(80,60),(90,120,80)).save(root/'reference_face.jpg','JPEG')  # artificial reference artifact, never a camera/frame source
    journal.update('attempt:'+row['attempt_id'],phase='ended_locally',checkpoint={},media_released=True,report_filename='report.pdf',identity_required=True)
    journal.update('attempt:'+row['attempt_id'],checkpoint={'synthetic':True})
    return base


def synchronize(run, client, journal, row, deadline):
    base = bundle(run,journal,row)
    observations = deque(maxlen=256); first_failure = None; injected = False; verified_before_cleanup = False
    def transport(method, origin, endpoint, payload, credential):
        nonlocal injected, verified_before_cleanup
        try:
            reply = client._request(method,origin,endpoint,payload,credential)
        finally:
            if client.request_diagnostics: observations.append({**client.request_diagnostics[-1], 'fixture_operation':'chunk' if endpoint.endswith('/chunks') else endpoint.rsplit('/',1)[-1]})
        if endpoint.endswith('/status'):
            observations.append({'phase':'server_progress','files_complete':sum(x.get('complete') is True for x in reply.get('files',[])),
                'received_bytes':sum(x.get('received_bytes',0) for x in reply.get('files',[]))})
        if endpoint.endswith('/complete'):
            current = journal.attempts()[0]
            verify_receipt(current, reply.get('receipt'))
            # Verify the server's committed receipt independently before the worker can delete.
            from proctoring_server.sync import SyncService
            service = Service(Settings(database=run/'teacher.sqlite3',public_url=origin,teacher_origin=origin))
            actual = SyncService(service).status(credential,row['device_secret'])
            if actual.get('receipt') != reply.get('receipt'): raise ValueError('independent_receipt_mismatch')
            verified_before_cleanup = True
        if '/files/events/chunks' in endpoint and not injected:
            injected = True
            duplicate = client._request(method,origin,endpoint,payload,credential)
            observations.append({**client.request_diagnostics[-1], 'fixture_operation':'chunk' if endpoint.endswith('/chunks') else endpoint.rsplit('/',1)[-1]})
            if duplicate != reply: raise ValueError('duplicate_chunk_mismatch')
            observations.append({'phase':'injected_lost_successful_chunk_response','offset':payload['offset']})
            raise ConnectedError('fixture_injected_response_loss')
        return reply
    worker = SyncWorker(journal,base,transport)
    try:
        for _ in range(80):
            if time.time() >= deadline: raise ValueError('fixture_deadline')
            current = journal.attempts()[0]
            if current.get('cleanup'): break
            try: worker.once(current)
            except ConnectedError as error:
                if str(error) != 'fixture_injected_response_loss': raise
        current = journal.attempts()[0]
        if not current.get('cleanup') or not verified_before_cleanup or not injected: raise ValueError('sync_not_verified')
        verify_receipt(current,current['receipt'])
    except Exception as error:
        first_failure = {'code':str(error) if isinstance(error,ConnectedError) else 'fixture_verification_failed',
                         'diagnostic':getattr(error,'diagnostic',None),'at':time.time()}
        raise
    finally:
        current = journal.attempts()[0]
        write(run/'sync-results.json', {'schema':1,'synthetic_only':True,'first_failure':first_failure,'requests':list(observations),
            'attempt_id':row['attempt_id'],'session_id':row['session_id'],'injected_response_loss':injected,
            'independent_receipt_before_cleanup':verified_before_cleanup,'cleanup':current.get('cleanup'), 'receipt':current.get('receipt'),
            'retained_file_count':sum(p.is_file() for p in (base/row['session_id']).glob('*'))})


async def relay(run, client, journal, row, deadline):
    from websockets.asyncio.client import connect
    observations = deque(maxlen=900); first_failure = None; generated = 0; child = None
    finished = asyncio.Event(); ready = asyncio.Event(); starts = 0; completed_stop = False
    wsurl = row['server'].replace('https://','wss://')+'/api/v1/live/student'
    async with connect(wsurl,additional_headers={'Authorization':'Bearer '+row['credential'],'X-Device-Secret':row['device_secret']},
                       proxy=None,max_size=65536,max_queue=8,open_timeout=5) as control:
        await control.send(json.dumps({'type':'hello','protocol':1,'attempt_id':row['attempt_id'],'session_id':row['session_id']}))
        if json.loads(await control.recv()).get('type') != 'hello': raise ValueError('hello_failed')
        await control.send(json.dumps({'type':'consent','accepted':True,'version':2}))
        consent = json.loads(await control.recv())
        if consent.get('accepted') is not True or consent.get('version') != 2: raise ValueError('consent_failed')
        await asyncio.to_thread(start,client,row)
        child = await asyncio.create_subprocess_exec('node',str(Path(__file__).with_name('sender.mjs')),'--operator-approved-public',
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=400000)
        async def send(m):
            child.stdin.write((json.dumps(m)+'\n').encode()); await child.stdin.drain()
        await send({'type':'init','origin':row['server'],'deadline':deadline*1000,'attempt_id':row['attempt_id'],'session_id':row['session_id']})
        async def output():
            nonlocal first_failure, generated, completed_stop
            while line := await child.stdout.readline():
                m = json.loads(line)
                if m['type']=='ready': ready.set(); continue
                if m['type']=='generate':
                    generated += 1; await send({'type':'frame','id':m['id'],'jpeg_base64':frame(generated)}); continue
                observations.append({'at':time.time(),**m})
                if m['type']=='sender_status':
                    if m.get('diagnostic',{}):
                        d = m['diagnostic']
                        if not d.get('requested') and not first_failure:
                            first_failure = m; finished.set()
                    if m.get('reason')=='teacher_stopped': completed_stop=True; finished.set()
                if m['type']=='fatal': first_failure=first_failure or {'at':time.time(),'code':'fixture_protocol_failed'}
                if m['type']=='closed' and not finished.is_set(): first_failure=first_failure or {'at':time.time(),'code':'fixture_closed_before_teacher_stop'}
                if m['type'] in ('fatal','closed'): finished.set()
            finished.set()
        async def receive():
            nonlocal starts, first_failure
            async for raw in control:
                m = json.loads(raw)
                if m['type']=='view.start':
                    starts += 1
                    if starts>1: raise ValueError('one_viewer_only')
                    await ready.wait(); await send(m)
                elif m['type'] in ('view.stop','view.expired'): await send(m)
                elif m['type']=='command': raise ValueError('unexpected_command_no_execution')
                elif m['type']=='error': raise ValueError('control_error')
            if not finished.is_set(): first_failure=first_failure or {'at':time.time(),'code':'control_disconnected'}
            finished.set()
        async def heartbeat():
            sequence = 0
            while time.time()<deadline:
                sequence += 1
                await control.send(json.dumps({'type':'status','sequence':sequence,'state':'running','elapsed_seconds':1,'remaining_seconds':899,
                    'duration_seconds':900,'answered':0,'total':1,'monitoring_healthy':True,'pause_reasons':[],'monitoring_outage':None,
                    'display':{'count':1,'incident_id':None,'ready':True,'calibration_ready':True,'approval_required':False},'screen_consent':True}))
                await asyncio.sleep(.5)
            finished.set()
        tasks = [asyncio.create_task(f()) for f in (output,receive,heartbeat)]
        waiter = asyncio.create_task(finished.wait())
        try:
            done,_ = await asyncio.wait([*tasks,waiter],timeout=max(0,deadline-time.time()),return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception(): raise task.exception()
        except Exception:
            first_failure = first_failure or {'code':'fixture_transport_failure','at':time.time()}
            raise
        finally:
            try: await send({'type':'exit'})
            except (ConnectionError,BrokenPipeError): pass
            try: await asyncio.wait_for(child.wait(),5)
            except asyncio.TimeoutError: child.kill(); await child.wait()
            for task in [*tasks,waiter]: task.cancel()
            await asyncio.gather(*tasks,waiter,return_exceptions=True)
            if not completed_stop and first_failure is None: first_failure={'at':time.time(),'code':'fixture_incomplete_before_intentional_stop'}
            write(run/'relay-results.json', {'schema':1,'synthetic_only':True,'generated':generated,'first_failure':first_failure,
                'attempt_id':row['attempt_id'],'session_id':row['session_id'],'direct_unavailability':'simulated native RTC adapter', 'records':list(observations)})
    if first_failure: raise ValueError('relay_fixture_failed')


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('mode',choices=['prepare','relay','sync'])
    p.add_argument('--run',type=Path,required=True); p.add_argument('--operator-approved-public',action='store_true'); args=p.parse_args()
    if args.mode=='prepare': prepare(args.run); return
    run,config,deadline = gate(args.run,args.operator_approved_public)
    client,journal,row = admit(run,config['origin'],args.mode)
    try:
        if args.mode=='relay': asyncio.run(relay(run,client,journal,row,deadline))
        else: start(client,row); synchronize(run,client,journal,row,deadline)
    except Exception as error:
        if not (run/(args.mode+'-results.json')).exists():
            write(run/(args.mode+'-results.json'),{'schema':1,'synthetic_only':True,'first_failure':{
                'at':time.time(),'phase':'setup_or_control_handshake','exception_type':type(error).__name__,
                'diagnostic':getattr(error,'diagnostic',None)}})
        raise
    finally:
        write(run/(args.mode+'-http-diagnostics.json'),list(client.request_diagnostics))


if __name__=='__main__':
    try: main()
    except Exception: print('Synthetic fixture stopped; inspect bounded results. No automatic restart.',file=sys.stderr); sys.exit(1)
