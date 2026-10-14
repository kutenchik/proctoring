ALTER TABLE exams ADD COLUMN admissions_closed_at REAL;
CREATE TABLE live_attempts (
 attempt_id TEXT PRIMARY KEY REFERENCES attempts(id), session_id TEXT NOT NULL,
 consent_version INTEGER, consent_accepted_at REAL
);
CREATE TABLE live_commands (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL, teacher_id TEXT NOT NULL REFERENCES teachers(id),
 exam_id TEXT NOT NULL REFERENCES exams(id), attempt_id TEXT NOT NULL REFERENCES attempts(id),
 session_id TEXT NOT NULL, connection_id TEXT NOT NULL, command_type TEXT NOT NULL,
 payload TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
 status TEXT NOT NULL, result TEXT,
 UNIQUE(teacher_id,request_id)
);
CREATE INDEX live_commands_attempt ON live_commands(attempt_id,created_at);
CREATE TABLE live_command_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, command_id TEXT NOT NULL REFERENCES live_commands(id),
 phase TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL
);
