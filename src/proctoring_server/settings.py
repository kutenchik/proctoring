"""Explicit deployment settings: HTTPS by default, opt-in loopback HTTP only."""
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit


def validated_origin(value: str, allow_local_http: bool = False) -> str:
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError("Invalid origin port") from error
    if (not parts.hostname or parts.username or parts.password or parts.query
            or parts.fragment or parts.path not in ("", "/")):
        raise ValueError("Server and teacher origins must be absolute origins without paths or credentials")
    host = parts.hostname.lower()
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if parts.scheme != "https" and not (allow_local_http and parts.scheme == "http" and loopback):
        raise ValueError("HTTPS is required; development HTTP is permitted only on explicit loopback origins")
    host = f"[{host}]" if ":" in host else host
    if port is not None and port != (443 if parts.scheme == "https" else 80):
        host += f":{port}"
    return f"{parts.scheme}://{host}"


@dataclass(frozen=True)
class Settings:
    database: Path = Path("server/data/teacher.sqlite3")
    public_url: str = "https://localhost:8443"
    teacher_origin: str = "https://localhost:5174"
    allow_local_http: bool = False
    session_seconds: int = 43200
    token_seconds: int = 3600
    attempt_retention_seconds: int = 30 * 86400
    max_upload_bytes: int = 2 * 1024 * 1024
    evidence_root: Path | None = None

    def __post_init__(self):
        object.__setattr__(self, "database", Path(self.database))
        object.__setattr__(self, "evidence_root", Path(self.evidence_root) if self.evidence_root else Path(self.database).parent / "evidence")
        object.__setattr__(self, "public_url", validated_origin(self.public_url, self.allow_local_http))
        object.__setattr__(self, "teacher_origin", validated_origin(self.teacher_origin, self.allow_local_http))
        if not 60 <= self.session_seconds <= 7 * 86400 or not 60 <= self.token_seconds <= 86400:
            raise ValueError("Invalid session or invitation/reset token lifetime")

    @property
    def secure_cookie(self) -> bool:
        return self.public_url.startswith("https:")

    @classmethod
    def from_env(cls):
        return cls(
            database=Path(os.environ.get("PROCTOR_SERVER_DATABASE", "server/data/teacher.sqlite3")),
            public_url=os.environ.get("PROCTOR_SERVER_URL", "https://localhost:8443"),
            teacher_origin=os.environ.get("PROCTOR_TEACHER_ORIGIN", "https://localhost:5174"),
            allow_local_http=os.environ.get("PROCTOR_ALLOW_LOOPBACK_HTTP") == "1",
            session_seconds=int(os.environ.get("PROCTOR_SESSION_SECONDS", "43200")),
            token_seconds=int(os.environ.get("PROCTOR_TOKEN_SECONDS", "3600")),
            evidence_root=Path(os.environ["PROCTOR_EVIDENCE_ROOT"]) if os.environ.get("PROCTOR_EVIDENCE_ROOT") else None,
        )
