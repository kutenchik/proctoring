CREATE TABLE teachers (
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE account_tokens (
 token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('invite','reset')),
 email TEXT NOT NULL, expires_at REAL NOT NULL, consumed_at REAL, created_at REAL NOT NULL
);
CREATE TABLE sessions (
 token_hash TEXT PRIMARY KEY, teacher_id TEXT NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
 csrf_hash TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE INDEX sessions_teacher ON sessions(teacher_id);
CREATE TABLE login_throttle (
 bucket TEXT PRIMARY KEY, window_start REAL NOT NULL, failures INTEGER NOT NULL,
 blocked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE libraries (
 id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL REFERENCES teachers(id),
 title TEXT NOT NULL, document TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX libraries_owner ON libraries(teacher_id);
CREATE TABLE exams (
 id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL REFERENCES teachers(id),
 code TEXT NOT NULL UNIQUE, title TEXT NOT NULL, exam_type TEXT NOT NULL,
 admission_start REAL NOT NULL, admission_close REAL NOT NULL,
 duration_seconds INTEGER NOT NULL, timezone TEXT NOT NULL,
 external_url TEXT NOT NULL DEFAULT '', quiz_snapshot TEXT,
 policy_snapshot TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX exams_owner ON exams(teacher_id);
CREATE TABLE attempts (
 id TEXT PRIMARY KEY, exam_id TEXT NOT NULL REFERENCES exams(id),
 student_id TEXT NOT NULL COLLATE BINARY, sequence INTEGER NOT NULL CHECK(sequence > 0),
 full_name TEXT NOT NULL, student_group TEXT NOT NULL,
 credential_hash TEXT NOT NULL UNIQUE, credential_expires_at REAL NOT NULL,
 admitted_at REAL NOT NULL, preparation_deadline REAL NOT NULL, started_at REAL,
 finished_at REAL, quiz_snapshot TEXT, policy_snapshot TEXT NOT NULL,
 score INTEGER, total INTEGER, end_reason TEXT,
 UNIQUE(exam_id, student_id, sequence)
);
CREATE INDEX attempts_exam ON attempts(exam_id);
CREATE TABLE repeat_grants (
 id TEXT PRIMARY KEY, exam_id TEXT NOT NULL REFERENCES exams(id), student_id TEXT NOT NULL COLLATE BINARY,
 source_attempt_id TEXT NOT NULL REFERENCES attempts(id), teacher_id TEXT NOT NULL REFERENCES teachers(id),
 reason TEXT NOT NULL, created_at REAL NOT NULL, consumed_at REAL, new_attempt_id TEXT REFERENCES attempts(id)
);
CREATE UNIQUE INDEX repeat_grants_pending ON repeat_grants(exam_id, student_id) WHERE consumed_at IS NULL;
CREATE TABLE audit_log (
 id TEXT PRIMARY KEY, actor_teacher_id TEXT REFERENCES teachers(id), action TEXT NOT NULL,
 resource_id TEXT NOT NULL, reason TEXT, details TEXT NOT NULL, created_at REAL NOT NULL
);
