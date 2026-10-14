"""One outstanding helper-clock challenge. Polls/queued heartbeats never renew it."""
import math
import re
import secrets


class ControlLease:
    def __init__(self, now, timeout):
        if isinstance(timeout, bool) or not math.isfinite(timeout) or not .5 <= timeout <= 30:
            raise ValueError('Control lease timeout must be between 0.5 and 30 seconds')
        self.timeout = timeout
        self.lease_id = secrets.token_hex(16)
        self.sequence = 0
        self.main_sequence = 0
        self.confirmed_at = None
        self.stopped = False
        self._rotate(now)

    def _rotate(self, now):
        self.sequence += 1
        self.nonce = secrets.token_hex(16)
        self.issued_at = now

    @property
    def challenge(self):
        if self.stopped: return None
        return {'lease_id': self.lease_id, 'sequence': self.sequence, 'nonce': self.nonce}

    def expired(self, now):
        return self.stopped or now - self.issued_at >= self.timeout

    def fresh(self, now):
        return self.confirmed_at is not None and not self.expired(now)

    def acknowledge(self, payload, now):
        if self.expired(now):
            self.stopped = True
            raise ValueError('Control progress deadline expired')
        if not isinstance(payload, dict) or set(payload) != {'lease_id','sequence','nonce','main_sequence'}:
            raise ValueError('Invalid control progress fields')
        if any(type(payload[k]) is not int or not 1 <= payload[k] <= 2**53-1 for k in ('sequence','main_sequence')):
            raise ValueError('Invalid control progress sequence')
        if any(not isinstance(payload[k],str) or not re.fullmatch('[a-f0-9]{32}',payload[k]) for k in ('lease_id','nonce')):
            raise ValueError('Invalid control progress identity')
        if any(payload[k] != self.challenge[k] for k in ('lease_id','sequence','nonce')) or payload['main_sequence'] <= self.main_sequence:
            raise ValueError('Control progress is stale, replayed, or belongs to another launch')
        self.main_sequence = payload['main_sequence']
        self.confirmed_at = now
        self._rotate(now)

    def stop(self): self.stopped = True
