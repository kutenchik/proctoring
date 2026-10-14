"""Consent-v3 synthetic snapshot validation. CLI execution requires fresh public approval.
No device, controller, detector, Electron or capture imports.
"""
import argparse
from collections import deque
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import time
from uuid import uuid4

from run import ROOT, isolated, gate, write
from proctoring.connected.client import ConnectedClient, ConnectedError
from proctoring.connected.durable import DurableJournal
from proctoring.connected.settings import ConnectedConfig
from proctoring.connected.sync import SyncWorker, verify_receipt
from proctoring_server.service import Service, iso
from proctoring_server.settings import Settings


def prepare(path):
    run, _ = isolated(path)
    if any((run/n).exists() for n in ('teacher.sqlite3','synthetic.json')): raise ValueError('fresh_run_required')
    service=Service(Settings(database=run/'teacher.sqlite3'))
    private=DurableJournal(run/'fixture-private.sqlite3')
    accounts={}
    for role in ('owner','other'):
        email=f'snapshot-{role}-{run.name}@example.invalid'; password=secrets.token_urlsafe(24)
        token=service.issue_account_token('invite',email)
        teacher=service.consume_account_token('invite',{'token':token,'name':'Synthetic snapshot '+role,'password':password})['teacher']
        accounts[role]={'email':email,'password':password,'id':teacher['id']}
    private.put('snapshot_accounts',accounts)
    write(run/'synthetic.json',{'schema':2,'scenario':'active_event_snapshot','consent_version':3,'synthetic_only':True,'public_executed':False})


def teacher(origin, account, teacher_origin):
    import requests
    session=requests.Session();session.trust_env=False
    session.headers['Origin']=teacher_origin
    reply=session.post(origin+'/api/v1/auth/login',json={k:account[k] for k in ('email','password')},timeout=10,allow_redirects=False)
    if reply.status_code!=200: session.close();raise ValueError('teacher_login_failed')
    session.headers['X-CSRF-Token']=reply.json()['csrf_token']
    return session


def generated_jpeg(path):
    from PIL import Image, ImageDraw
    # Seeded generated texture, large enough to exercise more than one chunk.
    import random
    rng=random.Random(4303)
    image=Image.frombytes('RGB',(900,600),rng.randbytes(900*600*3))
    ImageDraw.Draw(image).rectangle((0,0,899,70),fill='white')
    ImageDraw.Draw(image).text((20,25),'SYNTHETIC EVENT SNAPSHOT - NO CAMERA',fill='black')
    temporary=path.with_suffix('.partial');path.parent.mkdir(exist_ok=True)
    with temporary.open('wb') as f: image.save(f,'JPEG',quality=90);f.flush();os.fsync(f.fileno())
    temporary.replace(path)


def execute(run, origin, accounts, deadline, confirm, *, teacher_origin=None, now=time.time, vault=None, interrupt=True):
    """Local tests supply temporary roots; public entry point applies approval/deadline gates."""
    from websockets.sync.client import connect
    run=Path(run);teacher_origin=teacher_origin or origin
    # Refuse reuse before opening journals or touching the first run's results.
    with (run/'snapshot-started.json').open('x') as f: json.dump({'at':time.time()},f)
    result={'schema':1,'synthetic_only':True,'consent_version':3,'phase':'teacher_setup','first_failure':None,'requests':[]}
    client=None;control=None;heartbeat=None;stop=threading.Event();control_errors=[];sessions=[]
    journal=DurableJournal(run/'snapshot-outbox.sqlite3',**({'vault':vault} if vault else {}))
    def check():
        if time.time()>=deadline: raise ValueError('scenario_deadline')
        if control_errors: raise ValueError('student_control_failed')
    def phase(name):
        check();result['phase']=name;write(run/'snapshot-progress.json',result)
    try:
        owner=teacher(origin,accounts['owner'],teacher_origin);sessions.append(owner)
        other=teacher(origin,accounts['other'],teacher_origin);sessions.append(other)
        def post(path,body):
            check();r=owner.post(origin+'/api/v1'+path,json=body,timeout=10,allow_redirects=False)
            if r.status_code not in (200,201): raise ValueError('teacher_setup_request_failed')
            return r.json()
        library=post('/libraries',{'title':'Synthetic snapshot fixture','questions':[{'id':'q1','type':'single_choice','prompt':'Synthetic only','options':[{'id':'a','text':'A'},{'id':'b','text':'B'}],'correct_option_ids':['a']}]})
        exam=post('/exams',{'title':'SYNTHETIC live snapshots v3','exam_type':'native','library_id':library['id'],'admission_start':iso(now()-60),'admission_close':iso(now()+900),'duration_seconds':900,'timezone':'UTC','shuffle_questions':False,'shuffle_options':False,'audio_monitoring':False,'save_snapshots':True,'protection_mode':'unprotected'})
        result['exam_id']=exam['id'];phase('admission')
        client=ConnectedClient(ConnectedConfig(enabled=True),journal=journal,remember_path=run/'unused-remember.json')
        identity={'full_name':'SYNTHETIC snapshot student','group':'SYNTHETIC','student_id':uuid4().hex[:12]}
        pending=journal.prepare_admission(origin,identity)
        admission=client._request('POST',origin,'/student/admit',{**identity,'exam_code':exam['code'],**{k:pending[k] for k in ('admission_id','device_id','device_secret','credential')}},None)
        row=journal.admit(origin,admission,identity,pending['credential']);key='attempt:'+row['attempt_id']
        result.update(attempt_id=row['attempt_id'],session_id=row['session_id'],admission='passed')
        phase('consent_and_start')
        control=connect(origin.replace('https://','wss://').replace('http://','ws://')+'/api/v1/live/student',additional_headers={'Authorization':'Bearer '+row['credential'],'X-Device-Secret':row['device_secret']},proxy=None,open_timeout=5,max_size=65536)
        control.send(json.dumps({'type':'hello','protocol':1,'attempt_id':row['attempt_id'],'session_id':row['session_id']}))
        assert json.loads(control.recv(timeout=5))['type']=='hello'
        control.send(json.dumps({'type':'consent','version':3,'accepted':True}))
        consent=json.loads(control.recv(timeout=5));assert consent['accepted'] and consent['version']==3
        payload={k:row[k] for k in ('session_id','start_key')}
        client._request('POST',origin,'/student/start',payload,row['credential'])
        started=iso(now());row=journal.update(key,phase='locally_started',checkpoint={'elapsed_seconds':0},screen_consent={'version':3,'accepted':True},identity_required=False,report_filename='report.pdf')
        client._request('POST',origin,'/student/start/confirm',{**payload,'started_at':started},row['credential'])
        def beat():
            sequence=0
            try:
                while not stop.is_set() and time.time()<deadline:
                    sequence+=1
                    control.send(json.dumps({'type':'status','sequence':sequence,'state':'running','elapsed_seconds':sequence,'remaining_seconds':max(0,900-sequence),'duration_seconds':900,'answered':0,'total':1,'monitoring_healthy':True,'pause_reasons':[],'monitoring_outage':None,'display':{'count':1,'incident_id':None,'ready':True,'calibration_ready':True,'approval_required':False},'screen_consent':True}))
                    try:
                        packet=json.loads(control.recv(timeout=.2))
                        if packet.get('type') in ('error','command','view.start'): raise ValueError('unexpected_control')
                    except TimeoutError: pass
                    stop.wait(.8)
            except Exception: control_errors.append(True)
        heartbeat=threading.Thread(target=beat,daemon=True);heartbeat.start()
        base=run/'synthetic-evidence';root=base/row['session_id'];root.mkdir(parents=True)
        binding={'session_id':row['session_id'],'connected_attempt':{'attempt_id':row['attempt_id']}}
        write(root/'session.json',binding)
        event={'session_id':row['session_id'],'event_id':'snapshot-'+uuid4().hex,'event_type':'phone_visible','action':'activated','start_timestamp':iso(now()),'duration_seconds':1,'snapshot_status':'pending'}
        event['snapshot_path']='snapshots/'+event['event_id']+'.jpg';result['event_id']=event['event_id']
        def append(record):
            with (root/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n');f.flush();os.fsync(f.fileno())
        append(event);injected=False
        requests=deque(maxlen=256)
        def transport(method, server, endpoint, body, credential):
            nonlocal injected
            check()
            try: reply=client._request(method,server,endpoint,body,credential)
            finally:
                if client.request_diagnostics: requests.append(dict(client.request_diagnostics[-1]))
            if endpoint.endswith('/complete'):
                current=journal.get(key);verify_receipt(current,reply.get('receipt'))
                # Separate read-only connection, no Service construction or migration.
                with sqlite3.connect('file:'+str((run/'teacher.sqlite3').resolve()).replace('\\','/')+'?mode=ro',uri=True) as db:
                    persisted=db.execute('SELECT payload FROM sync_receipts WHERE attempt_id=?',(row['attempt_id'],)).fetchone()
                if not persisted or json.loads(persisted[0])!=reply['receipt']: raise ValueError('independent_receipt_mismatch')
                assert (root/event['snapshot_path']).is_file()
                result['independent_receipt_before_cleanup']=True
            if '/student/sync/snapshots/' in endpoint and interrupt and not injected and time.time()+120<deadline:
                injected=True;result['controlled_interruption']={'kind':'lost_successful_chunk_response','offset':body['offset'],'received_bytes':reply['received_bytes']}
                raise ConnectedError('fixture_response_loss')
            return reply
        worker=SyncWorker(journal,base,transport);worker.once(journal.get(key))
        phase('await_remote_pending');confirm('pending',result,deadline,check)
        phase('delayed_publication');time.sleep(3);check()
        path=root/event['snapshot_path'];generated_jpeg(path);published=time.monotonic()
        result['published_at_ms']=round(time.time()*1000)
        append({**event,'record_kind':'snapshot_result','snapshot_status':'ready'})
        phase('early_upload')
        for _ in range(40):
            try: worker.once(journal.get(key))
            except ConnectedError as error:
                if str(error)!='fixture_response_loss':raise
                # Reconstruct production worker/outbox, preserving exact identity.
                worker=SyncWorker(journal,base,transport)
            current=journal.get(key);item=current.get('early_snapshots',{}).get(event['event_id'],{})
            if item.get('complete'):break
            check();time.sleep(.2)
        if not item.get('complete'):raise ValueError('early_upload_incomplete')
        result.update(early_upload='passed',item_id=item['item_id'],publish_to_upload_ack_ms=round((time.monotonic()-published)*1000))
        status=client._request('GET',origin,'/student/sync/status',None,row['credential'])
        assert status['receipt'] is None and not current.get('cleanup') and path.is_file()
        result['no_early_receipt_or_cleanup']=True
        with sqlite3.connect('file:'+str((run/'teacher.sqlite3').resolve()).replace('\\','/')+'?mode=ro',uri=True) as db:
            stored=db.execute('SELECT complete,received_bytes,size,sha256 FROM sync_files WHERE attempt_id=? AND item_id=?',(row['attempt_id'],item['item_id'])).fetchone()
            lifecycle=db.execute('SELECT lifecycle,ended_at FROM sync_attempts WHERE attempt_id=?',(row['attempt_id'],)).fetchone()
            receipt_count=db.execute('SELECT COUNT(*) FROM sync_receipts WHERE attempt_id=?',(row['attempt_id'],)).fetchone()[0]
        assert stored==(1,item['size'],item['size'],item['sha256']) and lifecycle[1] is None and receipt_count==0
        result['durable_active_snapshot_verified']=True
        url=origin+'/api/v1/attempts/'+row['attempt_id']+'/evidence/'+item['item_id']
        own=owner.get(url,timeout=10,allow_redirects=False);foreign=other.get(url,timeout=10,allow_redirects=False)
        assert own.status_code==200 and sha256(own.content).hexdigest()==item['sha256'] and foreign.status_code==404
        result.update(owner_http=own.status_code,cross_teacher_http=foreign.status_code,image_sha256=item['sha256'])
        phase('await_remote_image');confirm('image',result,deadline,check)
        phase('finalization');stop.set();heartbeat.join(3);check();control.close();control=None
        ended=iso(now())
        write(root/'summary.json',{**binding,'started_at':started,'ended_at':ended,'end_reason':'completed','elapsed_seconds':20,'remaining_seconds':880,'score':0,'total_questions':1,'events':[event],'snapshot_errors':[],'storage_error':None})
        write(root/'answers.json',{'session_id':row['session_id'],'attempt_id':row['attempt_id'],'answers':{}})
        from reportlab.pdfgen.canvas import Canvas
        pdf=Canvas(str(root/'report.pdf'));pdf.drawString(20,700,'SYNTHETIC ONLY - no captured evidence');pdf.save()
        journal.update(key,phase='ended_locally',media_released=True)
        for _ in range(40):
            check();worker.once(journal.get(key))
            if journal.get(key).get('cleanup'):break
        final=journal.get(key);verify_receipt(final,final.get('receipt'))
        assert final.get('cleanup') and result.get('independent_receipt_before_cleanup')
        assert not any(p.is_file() for p in root.rglob('*'))
        result.update(phase='complete',receipt=final['receipt'],local_cleanup=True,controlled_interruption_performed=injected)
    except Exception as error:
        result['first_failure']={'phase':result['phase'],'exception_type':type(error).__name__,'diagnostic':getattr(error,'diagnostic',None),'at_ms':round(time.time()*1000)}
        raise
    finally:
        stop.set()
        if control:control.close()
        if heartbeat:heartbeat.join(3)
        for session in sessions:session.close()
        result['requests']=list(requests) if 'requests' in locals() else []
        result['recent_client_diagnostics']=list(client.request_diagnostics) if client else []
        write(run/'snapshot-results.json',result)
    return result


def operator_confirm(stage,result,deadline,run,check=lambda:None):
    path=run/('operator-'+stage+'.json')
    while time.time()<deadline:
        check()
        if path.exists():
            value=json.loads(path.read_text())
            required=('separate_network','pending_visible','no_refresh') if stage=='pending' else ('available_active','full_image_opened','no_refresh','no_certificate_warning','export_saved')
            if value.get('attempt_id')!=result['attempt_id'] or not all(value.get(k) is True for k in required):raise ValueError('operator_confirmation_incomplete')
            return
        time.sleep(.5)
    raise ValueError('operator_confirmation_deadline')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','run']);p.add_argument('--run',type=Path,required=True);p.add_argument('--operator-approved-public',action='store_true');p.add_argument('--skip-interruption',action='store_true');args=p.parse_args()
    if args.mode=='prepare':prepare(args.run);return
    run,config,deadline=gate(args.run,args.operator_approved_public)
    if json.loads((run/'synthetic.json').read_text()).get('consent_version')!=3:raise ValueError('fresh_v3_fixture_required')
    accounts=DurableJournal(run/'fixture-private.sqlite3').get('snapshot_accounts')
    try:
        execute(run,config['origin'],accounts,deadline,lambda s,r,d,c:operator_confirm(s,r,d,run,c),interrupt=not args.skip_interruption)
    finally:
        # Close this run's verified owned ingress on success or critical failure.
        # Independent guard remains the fallback if this process terminates.
        import subprocess
        with (run/'scenario-stop.log').open('x') as log:
            closed=subprocess.run(['powershell.exe','-NoProfile','-File',str(ROOT/'scripts/stage4b-demo.ps1'),'-Action','Stop','-RunDirectory',str(run)],stdout=log,stderr=log,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        write(run/'scenario-stop-result.json',{'at':time.time(),'returncode':closed.returncode})
        if closed.returncode:raise ValueError('owned_shutdown_requires_attention')

if __name__=='__main__':
    try:main()
    except Exception:print('Snapshot scenario stopped. Preserve results; no automatic experiment retry.',file=sys.stderr);sys.exit(1)

