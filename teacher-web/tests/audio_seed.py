"""Synthetic evidence in the isolated browser-test DB. No devices."""
import base64
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import secrets
import struct
import sys
import time
from uuid import uuid4
import wave
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from proctoring_server.service import Service, iso
from proctoring_server.settings import Settings
from proctoring_server.sync import SyncService
from proctoring_server.live import LiveService
from proctoring.exam_policy import default_policy
runtime=json.loads((ROOT/'teacher-web/.test-runtime/current.json').read_text())
database=Path(runtime['database'])
assert database.resolve().is_relative_to((ROOT/'teacher-web/.test-runtime').resolve())
service=Service(Settings(database=database,public_url=runtime['public_url'],teacher_origin=runtime['teacher_origin'],allow_local_http=True))
with service.database.connect() as c: owner=c.execute('SELECT id FROM teachers WHERE email=?',(sys.argv[1],)).fetchone()[0]
library=service.save_library(owner,{'title':'Synthetic audio','questions':[{'id':'q1','type':'single_choice','prompt':'Synthetic','options':[{'id':'a','text':'A'},{'id':'b','text':'B'}],'correct_option_ids':['a']}]})
policy=default_policy();policy['values'].update({'audio.enabled':True,'audio_evidence.enabled':True,'snapshots_enabled':False})
exam=service.create_exam(owner,{'title':'Synthetic audio exam','exam_type':'native','library_id':library['id'],'admission_start':iso(time.time()-60),'admission_close':iso(time.time()+3600),'duration_seconds':600,'timezone':'UTC','shuffle_questions':False,'shuffle_options':False,'audio_monitoring':True,'save_snapshots':False,'protection_mode':'unprotected','monitoring_policy':policy})
credential,secret=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
admission=service.admit({'exam_code':exam['code'],'full_name':'Synthetic Audio Student','group':'AUDIO-TEST','student_id':'synthetic','admission_id':uuid4().hex,'device_id':uuid4().hex,'credential':credential,'device_secret':secret})
sync=SyncService(service);live=LiveService(service,sync);session='session-'+uuid4().hex
peer=live.student_connect(credential,secret,{'type':'hello','protocol':1,'attempt_id':admission['attempt_id'],'session_id':session})
live.consent(peer,{'version':5,'accepted':True});start={'session_id':session,'start_key':uuid4().hex}
sync.authorize_start(credential,secret,start);sync.confirm_start(credential,secret,{**start,'started_at':iso(time.time())})
event={'record_kind':'review_event','event_type':'voice_detected','event_id':'audio-event-1','action':'activated','start_timestamp':iso(time.time()),'duration_seconds':2,'audio_path':'audio/audio-event-1.wav','audio_status':'ready'}
sync.records_upload(credential,secret,{'session_id':session,'records':[{'sequence':0,'record':event}]})
output=BytesIO()
with wave.open(output,'wb') as f:
 f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b''.join(struct.pack('<h',round(300*math.sin(i*2*math.pi*440/16000))) for i in range(128000)))
raw=output.getvalue();sha=hashlib.sha256(raw).hexdigest()
item=sync.snapshot_declare(credential,secret,{'session_id':session,'event_id':'audio-event-1','size':len(raw),'sha256':sha},audio=True)
for offset in range(0,len(raw),262144):sync.chunk(credential,secret,item['item_id'],{'session_id':session,'offset':offset,'data_base64':base64.b64encode(raw[offset:offset+262144]).decode()},provisional=True)
print(json.dumps({'exam_id':exam['id'],'attempt_id':admission['attempt_id'],'item_id':item['item_id'],'sha256':sha}))
