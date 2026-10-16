CREATE TABLE configuration_profiles (
 id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL REFERENCES teachers(id), name TEXT NOT NULL,
 policy TEXT NOT NULL, version INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX configuration_profiles_owner ON configuration_profiles(teacher_id);
CREATE TABLE monitoring_policy_changes (
 command_id TEXT PRIMARY KEY REFERENCES live_commands(id), attempt_id TEXT NOT NULL REFERENCES attempts(id),
 revision INTEGER NOT NULL, old_policy TEXT NOT NULL, new_policy TEXT NOT NULL,
 teacher_id TEXT NOT NULL REFERENCES teachers(id), reason TEXT NOT NULL, created_at REAL NOT NULL
);
