CREATE TABLE event_snapshots (
 attempt_id TEXT NOT NULL REFERENCES attempts(id),
 event_id TEXT NOT NULL,
 item_id TEXT NOT NULL,
 PRIMARY KEY(attempt_id,event_id),
 UNIQUE(attempt_id,item_id)
);
CREATE INDEX sync_records_event ON sync_records(attempt_id,json_extract(payload,'$.event_id'),sequence);
