"""Isolated real API for this web suite; never uses a configured user database."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from proctoring_server.app import create_app
from proctoring_server.settings import Settings
import uvicorn

runtime = ROOT / "teacher-web" / ".test-runtime"
runtime.mkdir(exist_ok=True)
database = runtime / f"teacher-ui-{uuid4().hex}.sqlite3"
port = int(os.environ.get("TEACHER_TEST_API_PORT", "8011"))
origin = os.environ.get("TEACHER_TEST_ORIGIN", "http://127.0.0.1:5174")
public_url = f"http://127.0.0.1:{port}"
(runtime / "current.json").write_text(json.dumps({"database": str(database), "public_url":public_url,"teacher_origin":origin}), encoding="utf-8")
settings = Settings(database=database, public_url=public_url, teacher_origin=origin, allow_local_http=True)
uvicorn.run(create_app(settings), host="127.0.0.1", port=port, access_log=False)
