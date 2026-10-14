"""Synthetic Stage 2 bundles through real admission/upload services; no devices."""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import secrets
from uuid import uuid4

from proctoring_server.service import iso
from proctoring_server.sync import SyncService, checksum


def build_review_bundle(service, owner, exam_data, *, complete=True):
    from PIL import Image
    from reportlab.pdfgen.canvas import Canvas
    data=deepcopy(exam_data); data['save_snapshots']=True
    exam=service.create_exam(owner,data)
    device=secrets.token_urlsafe(32); credential=secrets.token_urlsafe(32)
    admitted=service.admit({'exam_code':exam['code'],'full_name':'Әлия Иванова','group':'=1+1',
        'student_id':'00123','admission_id':uuid4().hex,'device_id':uuid4().hex,
        'device_secret':device,'credential':credential})
    sync=SyncService(service); attempt=admitted['attempt_id']; session='session-'+uuid4().hex
    start={'start_key':uuid4().hex,'session_id':session}
    sync.authorize_start(credential,device,start)
    started=iso(service.clock())
    sync.confirm_start(credential,device,{**start,'started_at':started})
    events=[{'event_id':'event-1','event_type':'phone_visible','action':'activated','start_timestamp':started,'duration_seconds':1,'snapshot_path':'snapshots/event-1.jpg'},
            {'event_id':'event-1','event_type':'phone_visible','action':'closed','start_timestamp':started,'duration_seconds':2,'snapshot_path':'snapshots/event-1.jpg'},
            {'event_id':'event-2','event_type':'phone_visible','action':'closed','start_timestamp':iso(service.clock()+5),'duration_seconds':1},
            {'record_kind':'lifecycle','event_type':'monitoring_failed','timestamp':iso(service.clock()+7),'reason':'Camera disconnected','elapsed_seconds':7}]
    records=[{'session_id':session,**e} for e in events]
    sync.records_upload(credential,device,{'session_id':session,'records':[{'sequence':i,'record':r} for i,r in enumerate(records)]})
    ended=iso(service.clock()+20)
    summary={'session_id':session,'connected_attempt':{'attempt_id':attempt},'started_at':started,'ended_at':ended,
             'end_reason':'completed','elapsed_seconds':17,'remaining_seconds':data['duration_seconds']-17,
             'score':1,'total_questions':2,'events':events[:3],'snapshot_errors':[],'storage_error':None}
    metadata={'session_id':session,'connected_attempt':{'attempt_id':attempt},'reference_face':'reference_face.jpg'}
    answers={'session_id':session,'attempt_id':attempt,'answers':{'single':['two'],'multi':['two','four']}}
    pdf=BytesIO(); canvas=Canvas(pdf); canvas.drawString(50,780,'Original local report — preserved');canvas.save()
    jpeg=BytesIO();Image.new('RGB',(80,60),(90,120,80)).save(jpeg,format='JPEG')
    raw={'session':json.dumps(metadata).encode(),'events':b''.join(json.dumps(r).encode()+b'\n' for r in records),
         'summary':json.dumps(summary).encode(),'answers':json.dumps(answers).encode(),
         'original_pdf':pdf.getvalue(),'reference':jpeg.getvalue(),'snapshot':jpeg.getvalue()}
    paths={'session':'session.json','events':'events.jsonl','summary':'summary.json','answers':'answers.json',
           'original_pdf':'exam_integrity_report.pdf','reference':'reference_face.jpg','snapshot':'snapshots/event-1.jpg'}
    manifest={'version':1,'attempt_id':attempt,'session_id':session,'ended_at':ended,'end_reason':'completed',
              'record_count':len(records),'identity_required':True,'items':[{'id':key,'kind':key,'relative_path':paths[key],
              'required':True,'status':'present','size':len(value),'sha256':sha256(value).hexdigest(),'error':None} for key,value in raw.items()]}
    result=sync.manifest_upload(credential,device,{'manifest':manifest}); digest=result['manifest_sha256']
    for item,value in raw.items():
        sync.chunk(credential,device,item,{'manifest_sha256':digest,'offset':0,'data_base64':base64.b64encode(value).decode()})
    receipt=sync.complete(credential,device,{'manifest_sha256':digest})['receipt'] if complete else None
    return {'sync':sync,'attempt_id':attempt,'exam_id':exam['id'],'credential':credential,'device_secret':device,
            'manifest':manifest,'raw':raw,'receipt':receipt,'session_id':session}
