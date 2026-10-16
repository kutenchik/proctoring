"""Consent-gated bounded remote observation worker and review lifecycle."""
from uuid import uuid4
import queue
import threading
from .remote import probe, installed_categories
from ..domain import EventType, Observation
from ..events import EventEngine


class RemoteMonitor:
    def __init__(self, config, clock, collector=probe):
        self.config, self.clock, self.collector = config, clock, collector
        self.prefix="remote-"+uuid4().hex+"-"
        self.stop_event = threading.Event()
        self.queue = queue.Queue(maxsize=1)
        self.thread = None
        self.status = 'awaiting_consent'
        self.last = None
        self.counts = {}
        self.engine = EventEngine({EventType.REMOTE_ACCESS_DETECTED: .001},
                                  config.remote_interval_seconds, clock,
                                  max_observation_gap=config.remote_interval_seconds * 2.5,
                                  accumulate_sample_durations=True)

    def start(self):
        if self.thread is not None or self.stop_event.is_set(): return
        self.status = 'initializing'
        self.thread = threading.Thread(target=self._run, daemon=True, name='remote-observations')
        self.thread.start()

    def _run(self):
        installed=()
        if self.collector is probe:
            try: installed=installed_categories()
            except (OSError,ImportError): pass
        while not self.stop_event.is_set():
            stamp = self.clock.monotonic()
            try: result = probe(installed=installed) if self.collector is probe else self.collector()
            except Exception: result = {'status':'unavailable', 'matches':[]}
            if self.stop_event.is_set(): return
            try: self.queue.get_nowait()
            except queue.Empty: pass
            self.queue.put_nowait((stamp, result))
            self.stop_event.wait(self.config.remote_interval_seconds)

    def consume(self, stamp, result, *, active):
        if self.last is not None and stamp <= self.last: return []
        gap = self.last is not None and stamp-self.last > self.config.remote_interval_seconds*2.5
        self.last = stamp
        self.status = result['status']
        if gap or not active: self.counts.clear()
        matches = {(m['category'],m['state']): m for m in result.get('matches', [])
                   if m['state'] in ('process_running','active_session')}
        self.counts = {key:self.counts.get(key,0)+1 for key in matches}
        if not active:
            self.counts.clear()
            return []
        confirmed = [matches[key] for key,count in self.counts.items()
                     if count >= self.config.remote_confirmations]
        # Partial observations can establish a positive signal, never absence.
        if not confirmed and result['status'] != 'complete':
            return self.engine.interrupt('remote_observation_incomplete')
        changes = self.engine.observe(Observation(stamp,
            {EventType.REMOTE_ACCESS_DETECTED:None} if confirmed else {},
            'windows_remote_observation', .001))
        return [{**item,'details':{'matches':confirmed,'coverage':'explicit_signatures_only',
                                  'not_proof_of_absence':True,'confirmations':self.config.remote_confirmations,
                                  'interval_seconds':self.config.remote_interval_seconds,'observed_monotonic':stamp}} for item in changes]

    def poll(self, *, active):
        if self.stop_event.is_set(): return []
        changes = []
        try:
            stamp,result = self.queue.get_nowait()
            if 0 <= self.clock.monotonic()-stamp <= self.config.remote_interval_seconds*2.5:
                changes += self.consume(stamp,result,active=active)
        except queue.Empty: pass
        if self.last is not None and self.clock.monotonic()-self.last > self.config.remote_interval_seconds*2.5:
            self.status='unavailable'; self.counts.clear()
            changes += self.engine.interrupt('remote_observation_stale')
        return changes

    def close(self):
        self.stop_event.set()
        self.counts.clear()
        self.status='stopped'
        return self.engine.close_all('monitor_stopped')
