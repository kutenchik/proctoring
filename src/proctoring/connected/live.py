"""Bounded control socket only. No screen pixels, devices or domain mutation.

TLS uses the library default verifying context. The synchronous client rejects
redirects; proxies are disabled so OS proxy credentials never join this channel.
GUI code drains generation-bound messages and supplies authoritative snapshots.
"""
from copy import deepcopy
import json
import logging
import queue
import threading
import time

from .client import _time, server_origin


class LiveWorker:
    def __init__(self, client, *, connector=None, monotonic=time.monotonic):
        self.client, self.clock, self.connector = client, monotonic, connector
        self.incoming = queue.Queue(maxsize=32)
        self.outgoing = queue.Queue(maxsize=32)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = self.socket = None
        self.connection_id = None
        self.connection = 'offline'
        self.error = None
        self.latest = None
        self.accepted_consent = False
        self.consent_revision = 0

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run,daemon=True,name='teacher-live-control')
            self.thread.start()

    def close(self):
        self.stop_event.set()
        self.connection_id = None
        self.connection = 'offline'
        # Never wait for a TCP/TLS/socket close on the controller/Qt thread.
        # recv is bounded at100ms, handshake at5s; the daemon owns cleanup.

    def publish(self, status):
        with self.lock:
            self.latest = (self.clock(),deepcopy(status))

    def consent(self, accepted):
        with self.lock:
            self.accepted_consent = accepted
            self.consent_revision += 1

    def send(self, message, connection_id=None):
        generation = connection_id or self.connection_id
        if generation is None or generation != self.connection_id:
            return False
        try:
            self.outgoing.put_nowait((generation,deepcopy(message)))
            return True
        except queue.Full:
            self.close()
            self.error = 'live_queue_full'
            return False

    def drain(self):
        result=[]
        for _ in range(32):
            try:result.append(self.incoming.get_nowait())
            except queue.Empty:break
        return result

    def send_notification(self, message):
        # Journal catch-up must leave room for command ACKs. The caller retains
        # its durable cursor if this bounded queue is busy; nothing is dropped.
        if self.outgoing.qsize() >= 16 or self.connection_id is None:
            return False
        return self.send(message)

    @staticmethod
    def decode(value):
        if not isinstance(value,str) or len(value.encode())>65536:
            raise ValueError('invalid_live_message')
        data=json.loads(value,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(data,dict):raise ValueError('invalid_live_message')
        return data

    def _run(self):
        from websockets.sync.client import connect
        connect = self.connector or connect
        delay=1.
        while not self.stop_event.is_set():
            self.connection='reconnecting'
            try:
                client=self.client
                origin=server_origin(client.server,client.settings.allow_loopback_http)
                uri=('wss'+origin[5:] if origin.startswith('https:') else 'ws'+origin[4:])+'/api/v1/live/student'
                headers={'Authorization':'Bearer '+client.credential,'X-Device-Secret':client.device['device_secret']}
                logger=logging.Logger('proctoring-live-redacted');logger.disabled=True
                with connect(uri,additional_headers=headers,proxy=None,compression=None,open_timeout=5,
                             close_timeout=.2,ping_interval=2,ping_timeout=3,max_size=65536,max_queue=8,logger=logger) as ws:
                    self.socket=ws
                    ws.send(json.dumps({'type':'hello','protocol':1,'attempt_id':client.admission['attempt_id'],
                                        'session_id':client.durable['session_id']}))
                    before=self.clock();hello=self.decode(ws.recv(timeout=5))
                    if hello.get('type')!='hello' or not isinstance(hello.get('connection_id'),str):
                        raise ValueError('invalid_live_handshake')
                    epoch=_time(hello['server_time'])
                    generation=hello['connection_id'];self.connection_id=generation
                    self.connection='online';self.error=None;delay=1.
                    consent_revision=-1;last_status=float('-inf');sequence=0
                    while not self.stop_event.is_set():
                        now=self.clock()
                        with self.lock:
                            latest=self.latest;consent=self.accepted_consent;revision=self.consent_revision
                        if consent_revision!=revision:
                            ws.send(json.dumps({'type':'consent','version':3,'accepted':consent}))
                            consent_revision=revision
                        if latest and now-last_status>=1 and 0<=now-latest[0]<2:
                            sequence+=1
                            ws.send(json.dumps({'type':'status','sequence':sequence,**latest[1]},allow_nan=False))
                            last_status=now
                        for _ in range(8):
                            try:target,message=self.outgoing.get_nowait()
                            except queue.Empty:break
                            if target==generation:ws.send(json.dumps(message,allow_nan=False))
                        try:data=self.decode(ws.recv(timeout=.1))
                        except TimeoutError:continue
                        deadline=None
                        if data.get('type')=='command':
                            deadline=min(before+_time(data['expires_at'])-epoch,self.clock()+10.)
                        self.incoming.put_nowait((generation,data,deadline))
            except Exception:
                if not self.stop_event.is_set():self.error='live_connection_unavailable'
            finally:
                self.socket=None;self.connection_id=None;self.connection='offline'
            if self.stop_event.wait(delay):break
            delay=min(10.,delay*2)
