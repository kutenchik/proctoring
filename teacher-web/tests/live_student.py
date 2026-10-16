"""Synthetic student for Stage 3 browser tests. Real admission, consent and sockets.

Only the unique ignored test DB is allowed; no hardware or production state.
"""
import asyncio
import base64
from io import BytesIO
import json
from pathlib import Path
import secrets
import sys
import time
from uuid import uuid4
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from proctoring_server.service import Service, iso
from proctoring_server.settings import Settings
from PIL import Image, ImageDraw
from websockets.asyncio.client import connect

runtime = json.loads((ROOT / "teacher-web/.test-runtime/current.json").read_text())
database = Path(runtime["database"])
if not database.resolve().is_relative_to((ROOT / "teacher-web/.test-runtime").resolve()):
    raise RuntimeError("Not an isolated test database")
service = Service(Settings(database=database, public_url=runtime["public_url"], teacher_origin=runtime["teacher_origin"], allow_local_http=True))
with service.database.connect() as c:
    owner = c.execute("SELECT id FROM teachers WHERE email=?", (sys.argv[1],)).fetchone()[0]
library = service.save_library(owner, {"title":"Synthetic live questions", "questions":[{"id":"q1","type":"single_choice","prompt":"Synthetic question", "options":[{"id":"a","text":"A"},{"id":"b","text":"B"}],"correct_option_ids":["a"]}]})
exam = service.create_exam(owner, {"title":"Synthetic live exam", "exam_type":"native", "library_id":library["id"], "admission_start":iso(time.time()-60), "admission_close":iso(time.time()+3600), "duration_seconds":600, "timezone":"UTC", "shuffle_questions":False, "shuffle_options":False, "audio_monitoring":False, "save_snapshots":len(sys.argv)>2 and sys.argv[2]=="snapshots", "protection_mode":"unprotected"})
credential, secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
admission = service.admit({"exam_code":exam["code"],"full_name":"Synthetic Live Student", "group":"LIVE-TEST","student_id":uuid4().hex[:10],"admission_id":uuid4().hex,"device_id":uuid4().hex,"credential":credential,"device_secret":secret})
session_id="session-"+uuid4().hex
headers={"Authorization":"Bearer "+credential,"X-Device-Secret":secret}
wsroot=runtime["public_url"].replace("http://","ws://")+"/api/v1"
def post(path, data):
    request=urllib.request.Request(runtime["public_url"]+"/api/v1"+path,data=json.dumps(data).encode(),headers={**headers,"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(request,timeout=5) as r:return json.load(r)
def emit(value): print(json.dumps(value),flush=True)

async def main():
    async with connect(wsroot+"/live/student",additional_headers=headers) as ws:
        await ws.send(json.dumps({"type":"hello","protocol":1,"attempt_id":admission["attempt_id"],"session_id":session_id}))
        hello=json.loads(await ws.recv())
        if hello.get("type")!="hello":raise RuntimeError(str(hello))
        await ws.send(json.dumps({"type":"consent","version":3,"accepted":True}))
        consent=json.loads(await ws.recv())
        if not consent.get("accepted"):raise RuntimeError(str(consent))
        start={"session_id":session_id,"start_key":uuid4().hex}
        if len(sys.argv)<3 or sys.argv[2]!="preparation":
            await asyncio.to_thread(post,"/student/start",start)
            await asyncio.to_thread(post,"/student/start/confirm",{**start,"started_at":iso(time.time())})
        state={"type":"status","sequence":0,"state":"running","elapsed_seconds":10,"remaining_seconds":590,"duration_seconds":600,"answered":1,"total":1,"monitoring_healthy":True,"pause_reasons":[],"monitoring_outage":None,"display":{"count":1,"incident_id":None,"ready":True,"calibration_ready":True,"approval_required":False},"screen_consent":True}
        if len(sys.argv)>2 and sys.argv[2]=="preparation":state.update(state="preparation",elapsed_seconds=0,remaining_seconds=600)
        streaming=set(); channels={}; frames_on=True; control_on=True
        image=Image.new("RGB",(640,360),(47,87,60));ImageDraw.Draw(image).text((50,160),"SYNTHETIC EXAM MONITOR - NOT A WEBCAM",fill="white");raw=BytesIO();image.save(raw,"JPEG");jpeg=base64.b64encode(raw.getvalue()).decode()
        async def status():
            while True:
                state["sequence"]+=1
                if control_on:await ws.send(json.dumps(state))
                await asyncio.sleep(.5)
        async def stream(message):
            async with connect(wsroot+"/live/stream") as channel:
                await channel.send(json.dumps({"role":"student","viewer_id":message["viewer_id"],"token":message["sender_token"]}))
                await channel.recv()
                channels[message["viewer_id"]]=channel
                if len(sys.argv)>2 and sys.argv[2]=="direct":
                    emit({"type":"direct_ready","viewer_id":message["viewer_id"]})
                    try:
                        async for reply in channel:
                            packet=json.loads(reply)
                            if packet.get("type") in ("signal","view.stop"):emit({"type":"direct_packet","packet":packet})
                    finally:channels.pop(message["viewer_id"],None)
                    return
                async def send_frames():
                    seq=0
                    while True:
                        if frames_on:
                            seq+=1;await channel.send(json.dumps({"type":"frame","viewer_id":message["viewer_id"],"sequence":seq,"width":640,"height":360,"captured_at":time.time()*1000,"jpeg_base64":jpeg}))
                            if seq%4==0:await channel.send(json.dumps({"type":"quality","viewer_id":message["viewer_id"],"ack_roundtrip_ms":120.0,"send_fps":3.3,"width":640,"jpeg_quality":65,"degraded":True}))
                        await asyncio.sleep(.3)
                sender=asyncio.create_task(send_frames())
                try:
                    async for reply in channel:
                        if json.loads(reply).get("type")=="frame_ack":emit({"type":"frame_ack"})
                finally:sender.cancel()
        async def receive():
            async for raw_message in ws:
                m=json.loads(raw_message)
                if m["type"]=="command":
                    await ws.send(json.dumps({"type":"command_ack","command_id":m["command_id"],"phase":"received","result":{}}))
                    kind=m["command_type"]
                    if kind=="pause":state.update(state="paused",pause_reasons=["teacher","monitoring"])
                    if kind=="resume":state.update(state="paused",pause_reasons=["monitoring"])
                    if kind=="add_time":state["remaining_seconds"]+=m["payload"]["seconds"];state["duration_seconds"]+=m["payload"]["seconds"]
                    if kind=="end":state.update(state="ended")
                    if m["payload"].get("text")!="NO_ACK":await ws.send(json.dumps({"type":"command_ack","command_id":m["command_id"],"phase":"applied","result":{"state":state["state"],"pause_reasons":state["pause_reasons"]}}))
                elif m["type"]=="view.start":
                    task=asyncio.create_task(stream(m));streaming.add(task);task.add_done_callback(streaming.discard)
        if len(sys.argv)>2 and sys.argv[2]=="snapshots":
            # Production client dependencies live in the separate student venv.
            sys.path.append(str(ROOT/'.venv/Lib/site-packages'))
            from proctoring.connected.durable import DurableJournal
            from proctoring.connected.client import ConnectedClient
            from proctoring.connected.settings import ConnectedConfig
            from proctoring.connected.sync import SyncWorker
            root=database.parent/session_id;root.mkdir()
            (root/'session.json').write_text(json.dumps({'session_id':session_id,'connected_attempt':{'attempt_id':admission['attempt_id']}}))
            event={'session_id':session_id,'event_id':'event-live-1','event_type':'phone_visible','action':'activated',
                'start_timestamp':iso(time.time()),'snapshot_path':'snapshots/event-live-1.jpg','snapshot_status':'pending'}
            (root/'events.jsonl').write_text(json.dumps(event)+'\n')
            journal=DurableJournal(root/'outbox.db')
            key='attempt:'+admission['attempt_id']
            journal.put(key,{'attempt_id':admission['attempt_id'],'session_id':session_id,'server':runtime['public_url'],
                'credential':credential,'device_secret':secret,'checkpoint':{'elapsed_seconds':10},'phase':'locally_started',
                'screen_consent':{'version':3,'accepted':True},'admission':admission,'identity_required':False,'report_filename':'report.pdf'})
            client=ConnectedClient(ConnectedConfig(allow_loopback_http=True),remember_path=root/'remember.json')
            client.device={'device_secret':secret}
            worker=SyncWorker(journal,root.parent,client.transport)
            await asyncio.to_thread(worker.once,journal.get(key))
        async def instructions():
            nonlocal frames_on,control_on
            while True:
                command=(await asyncio.to_thread(sys.stdin.readline)).strip()
                if not command or command=="exit":return
                if command.startswith('{'):
                    data=json.loads(command)
                    if data.get('type')=='stream_send':
                        packet=data['packet'];channel=channels.get(packet.get('viewer_id'))
                        if channel:await channel.send(json.dumps(packet))
                    if data.get('type')=='quiz_progress':
                        state['answered']=int(data['answered'])
                    continue
                if command=="snapshot":
                    target=root/'snapshots/event-live-1.jpg';target.parent.mkdir(exist_ok=True)
                    partial=target.with_suffix('.partial');partial.write_bytes(raw.getvalue());partial.replace(target)
                    await asyncio.to_thread(worker.once,journal.get(key))
                if command=="no_frames":frames_on=False
                if command=="frames":frames_on=True
                if command=="no_status":control_on=False
                if command=="interrupted":
                    await asyncio.to_thread(post,"/student/interrupted",{"session_id":session_id,"interruption_id":uuid4().hex,"reason":"Synthetic interruption","checkpoint":{"elapsed_seconds":10,"remaining_seconds":590,"answers":{},"pause_reasons":[]}})
                    control_on=False
                if command=="event":
                    notice={"type":"event","sequence":1,"record":{"session_id":session_id,"event_id":"event-live-1","event_type":"phone_visible","start_timestamp":iso(time.time()),"duration_seconds":3}}
                    await ws.send(json.dumps(notice));await ws.send(json.dumps(notice))
        tasks=[asyncio.create_task(status()),asyncio.create_task(receive())]
        emit({"type":"ready","attempt_id":admission["attempt_id"],"exam_id":exam["id"]})
        try:await instructions()
        finally:
            for task in tasks+list(streaming):task.cancel()
            await asyncio.gather(*tasks,*list(streaming),return_exceptions=True)

asyncio.run(main())

