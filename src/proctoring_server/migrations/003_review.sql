CREATE TABLE event_review_versions (
 attempt_id TEXT NOT NULL REFERENCES attempts(id), event_id TEXT NOT NULL,
 version INTEGER NOT NULL, decision TEXT NOT NULL, comment TEXT NOT NULL,
 teacher_id TEXT NOT NULL REFERENCES teachers(id), created_at REAL NOT NULL,
 PRIMARY KEY(attempt_id,event_id,version)
);
CREATE TABLE manual_observation_versions (
 observation_id TEXT NOT NULL, attempt_id TEXT NOT NULL REFERENCES attempts(id),
 version INTEGER NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL,
 cancelled INTEGER NOT NULL, phase TEXT NOT NULL,
 author_id TEXT NOT NULL REFERENCES teachers(id), created_at REAL NOT NULL,
 changed_by TEXT NOT NULL REFERENCES teachers(id), updated_at REAL NOT NULL,
 PRIMARY KEY(observation_id,version)
);
CREATE INDEX manual_observations_attempt ON manual_observation_versions(attempt_id);
CREATE TABLE attempt_conclusions (
 attempt_id TEXT NOT NULL REFERENCES attempts(id), version INTEGER NOT NULL,
 id TEXT NOT NULL UNIQUE, decision TEXT NOT NULL, comment TEXT NOT NULL,
 unreviewed_count INTEGER NOT NULL, teacher_id TEXT NOT NULL REFERENCES teachers(id),
 created_at REAL NOT NULL, receipt_id TEXT NOT NULL, review_snapshot TEXT NOT NULL,
 needs_reconsideration INTEGER NOT NULL DEFAULT 0,
 report_status TEXT NOT NULL DEFAULT 'pending', report_sha256 TEXT, report_size INTEGER,
 report_error TEXT,
 PRIMARY KEY(attempt_id,version)
);
