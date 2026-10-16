CREATE TABLE event_audio (
 attempt_id TEXT NOT NULL REFERENCES attempts(id),
 event_id TEXT NOT NULL, item_id TEXT NOT NULL,
 PRIMARY KEY(attempt_id,event_id), UNIQUE(attempt_id,item_id)
);
