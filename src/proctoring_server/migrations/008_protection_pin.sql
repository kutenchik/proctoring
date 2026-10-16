CREATE TABLE protection_pins (
 teacher_id TEXT PRIMARY KEY REFERENCES teachers(id),
 verifier TEXT NOT NULL, revision INTEGER NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE protection_pin_attempts (
 teacher_id TEXT NOT NULL REFERENCES teachers(id), attempt_id TEXT NOT NULL,
 created_at REAL NOT NULL
);
CREATE INDEX protection_pin_rate ON protection_pin_attempts(teacher_id,created_at);
