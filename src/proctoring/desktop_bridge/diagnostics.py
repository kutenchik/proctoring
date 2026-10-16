"""Bounded metadata markers. Never serialize exception text or request bodies."""
import json
import sys
import threading

_lock = threading.Lock()
EVENTS = frozenset(('supervisor_started', 'backend_spawned', 'backend_bound', 'backend_ready',
                   'camera_received', 'camera_opening', 'camera_started', 'camera_failed',
                   'camera_cleanup_failed', 'request_failed', 'backend_transport_closed',
                   'backend_shutdown', 'backend_exited', 'supervisor_draining',
                   'supervisor_forced', 'ownership_failed'))


def emit(event, *, error=None, code=None):
    if event not in EVENTS:
        return
    value = {'event': event}
    if error is not None:
        value['classification'] = ('memory' if isinstance(error, MemoryError) else
                                   'os' if isinstance(error, OSError) else
                                   'value' if isinstance(error, ValueError) else
                                   'runtime' if isinstance(error, RuntimeError) else 'other')
    if type(code) is int and -(2**31) <= code <= 2**32-1:
        value['code'] = code
    try:
        with _lock:
            sys.stderr.write('PROCTORING_LIFECYCLE:' + json.dumps(value, separators=(',', ':')) + '\n')
            sys.stderr.flush()
    except (OSError, ValueError):
        pass
