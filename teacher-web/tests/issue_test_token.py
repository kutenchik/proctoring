"""Test-only server-operator CLI bridge. No endpoint or production shortcut."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from proctoring_server.service import Service
from proctoring_server.settings import Settings

database = json.loads((ROOT / "teacher-web" / ".test-runtime" / "current.json").read_text(encoding="utf-8"))["database"]
settings = Settings(database=Path(database), public_url="http://127.0.0.1:8011", teacher_origin="http://127.0.0.1:5174", allow_local_http=True)
print(Service(settings).issue_account_token(sys.argv[1], sys.argv[2]))
