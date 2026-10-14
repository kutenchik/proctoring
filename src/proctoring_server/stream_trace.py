"""Bounded numerical transport evidence, never frames or message bodies."""
from collections import Counter, deque
import time
import threading


class StreamTrace:
    def __init__(self):
        self.records = deque(maxlen=128)
        self.counts = Counter()
        self.lock = threading.Lock()

    def record(self, stage, sequence=-1, value=0):
        assert stage in {'received','accepted','rejected','rate_dropped','budget_dropped','replaced','send_started',
                         'send_completed','send_timeout','ack_received','ack_forwarded','ack_rejected','closed'}
        with self.lock:
            self.counts[stage] = min(2**53-1, self.counts[stage]+1)
            self.records.append(dict(stage=stage, sequence=sequence, at_ms=round(time.monotonic()*1000), value=value))

    def snapshot(self):
        with self.lock:
            return {'counts':dict(self.counts), 'records':[dict(r) for r in self.records]}
