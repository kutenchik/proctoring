CREATE TABLE sync_attempts (
 attempt_id TEXT PRIMARY KEY REFERENCES attempts(id), admission_id TEXT UNIQUE,
 admission_hash TEXT, device_id TEXT NOT NULL, device_hash TEXT NOT NULL,
 session_id TEXT, lifecycle TEXT NOT NULL DEFAULT 'admitted', start_key TEXT,
 local_started_at REAL, ended_at REAL, end_reason TEXT, interruption_id TEXT,
 checkpoint TEXT, current_manifest TEXT, server_result TEXT, deleted_at REAL,
 deletion_pending INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE sync_records (
 attempt_id TEXT NOT NULL REFERENCES attempts(id), sequence INTEGER NOT NULL,
 payload TEXT NOT NULL, sha256 TEXT NOT NULL, created_at REAL NOT NULL,
 PRIMARY KEY(attempt_id,sequence)
);
CREATE TABLE sync_manifests (
 attempt_id TEXT NOT NULL REFERENCES attempts(id), sha256 TEXT NOT NULL,
 payload TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(attempt_id,sha256)
);
CREATE TABLE sync_files (
 attempt_id TEXT NOT NULL REFERENCES attempts(id), item_id TEXT NOT NULL,
 kind TEXT NOT NULL, relative_path TEXT NOT NULL, size INTEGER NOT NULL,
 sha256 TEXT NOT NULL, received_bytes INTEGER NOT NULL DEFAULT 0,
 complete INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(attempt_id,item_id)
);
CREATE TABLE sync_receipts (
 attempt_id TEXT PRIMARY KEY REFERENCES attempts(id), payload TEXT NOT NULL,
 manifest_sha256 TEXT NOT NULL, verified_at REAL NOT NULL
);
CREATE TABLE recovery_grants (
 id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES attempts(id),
 interruption_id TEXT NOT NULL UNIQUE, teacher_id TEXT NOT NULL REFERENCES teachers(id),
 reason TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL
);
