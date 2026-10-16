"""Synthetic Stage 2 materials via real services, for isolated browser tests only.

No fixture path is imported by the production website or server. This uses the
unique database selected by start_server.py, never the normal configured DB.
"""
import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import secrets
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from proctoring_server.service import Service, iso
from proctoring_server.settings import Settings
from proctoring_server.sync import SyncService, canonical
from PIL import Image, ImageDraw
from reportlab.pdfgen.canvas import Canvas

runtime = json.loads((ROOT / "teacher-web" / ".test-runtime" / "current.json").read_text(encoding="utf-8"))
database = Path(runtime["database"])
if not database.resolve().is_relative_to((ROOT / "teacher-web" / ".test-runtime").resolve()):
    raise RuntimeError("Test database must stay inside the isolated test runtime")
settings = Settings(database=database, public_url=runtime["public_url"], teacher_origin=runtime["teacher_origin"], allow_local_http=True)
service = Service(settings)
sync = SyncService(service)
with service.database.connect() as connection:
    teacher = connection.execute("SELECT id FROM teachers WHERE email=?", (sys.argv[1],)).fetchone()[0]
mode = sys.argv[2]
now = time.time()
quiz = service.save_library(teacher, {"title": "Synthetic review quiz", "questions": [{"id":"q1","type":"single_choice","prompt":"Choose the first option.","options":[{"id":"a","text":"First"},{"id":"b","text":"Second"}],"correct_option_ids":["a"]}]})
exam = service.create_exam(teacher, {"title":"Review workflow · synthetic exam", "exam_type":"native", "library_id":quiz["id"],"admission_start":iso(now-120),"admission_close":iso(now+3600),"duration_seconds":600,"timezone":"Asia/Qyzylorda","shuffle_questions":False,"shuffle_options":False,"audio_monitoring":False,"save_snapshots":True,"protection_mode":"unprotected"})
credential, device_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
admission = service.admit({"exam_code":exam["code"],"full_name":"Synthetic Review Student", "group":"TEST-2","student_id":uuid4().hex[:12],"admission_id":uuid4().hex,"device_id":uuid4().hex,"credential":credential,"device_secret":device_secret})
attempt_id, session_id, start_key = admission["attempt_id"], "session-"+uuid4().hex, uuid4().hex
start = {"session_id":session_id,"start_key":start_key}
sync.authorize_start(credential,device_secret,start)
sync.confirm_start(credential,device_secret,{**start,"started_at":iso(now-60)})
if mode == "interrupted":
    sync.interrupted(credential,device_secret,{"session_id":session_id,"interruption_id":uuid4().hex,"reason":"Synthetic unexpected process interruption","checkpoint":{"elapsed_seconds":40,"remaining_seconds":560,"answers":{"q1":["a"]},"pause_reasons":[]}})
    print(json.dumps({"attempt_id":attempt_id,"exam_id":exam["id"]}));sys.exit(0)

snapshot_path="snapshots/test-observation.jpg"
records=[]
for index,event_type in enumerate(["phone_visible","phone_visible","gaze_down","monitoring_failure"]):
    records.append({"session_id":session_id,"event_id":f"event-{index+1}","event_type":event_type,"state":"closed","timestamp":iso(now-50+index*8),"start_timestamp":iso(now-50+index*8),"duration_seconds":2.0,**({"snapshot_path":snapshot_path} if index<2 else {})})
sync.records_upload(credential,device_secret,{"session_id":session_id,"records":[{"sequence":i,"record":record} for i,record in enumerate(records)]})
summary={"started_at":iso(now-60),"session_id":session_id,"connected_attempt":{"attempt_id":attempt_id},"ended_at":iso(now),"end_reason":"submitted","elapsed_seconds":60,"remaining_seconds":540,"score":0,"total_questions":1,"events":records,"storage_error":None,"snapshot_errors":[]}
image=Image.new("RGB",(400,220),(234,234,224));ImageDraw.Draw(image).text((20,95),"SYNTHETIC TEST EVIDENCE",fill=(45,73,49));jpeg=BytesIO();image.save(jpeg,"JPEG")
pdf=BytesIO();canvas=Canvas(pdf);canvas.drawString(72,750,"Synthetic original report - unchanged");canvas.save()
files={
  "session":("session","session.json",canonical({"session_id":session_id,"connected_attempt":{"attempt_id":attempt_id}})),
  "events":("events","events.jsonl",b"".join(canonical(record)+b"\n" for record in records)),
  "summary":("summary","summary.json",canonical(summary)),
  "answers":("answers","answers.json",canonical({"attempt_id":attempt_id,"session_id":session_id,"answers":{"q1":["a"]}})),
  "pdf":("original_pdf","exam_integrity_report.pdf",pdf.getvalue()),
  "snapshot":("snapshot",snapshot_path,jpeg.getvalue()),
  "reference":("reference","reference-face.jpg",jpeg.getvalue()),
}
items=[]
for item_id,(kind,relative,raw) in files.items():
    missing=mode=="pending" and kind=="original_pdf"
    items.append({"id":item_id,"kind":kind,"relative_path":relative,"required":kind!="snapshot","status":"missing_error" if missing else "present","size":None if missing else len(raw),"sha256":None if missing else sha256(raw).hexdigest(),"error":"Synthetic PDF generation failure" if missing else None})

manifest={"version":1,"attempt_id":attempt_id,"session_id":session_id,"ended_at":iso(now),"end_reason":"submitted","record_count":len(records),"identity_required":False,"items":items}
manifest_sha=sync.manifest_upload(credential,device_secret,{"manifest":manifest})["manifest_sha256"]
for item in items:
    if item["status"]!="present":continue
    raw=files[item["id"]][2]
    sync.chunk(credential,device_secret,item["id"],{"manifest_sha256":manifest_sha,"offset":0,"data_base64":base64.b64encode(raw).decode("ascii")})
if mode=="complete":sync.complete(credential,device_secret,{"manifest_sha256":manifest_sha})
print(json.dumps({"attempt_id":attempt_id,"exam_id":exam["id"]}))
