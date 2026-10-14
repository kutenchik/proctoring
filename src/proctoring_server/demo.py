"""Single-origin demo boundary. No tunnel is created by importing this module.

The transport is loopback HTTP from cloudflared; external TLS origin is pinned
configuration, never inferred from forwarded headers. Application auth remains
inside the one authoritative FastAPI instance.
"""
import asyncio
import ipaddress
import mimetypes
import os
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

from starlette.responses import Response, JSONResponse

from .app import create_app
from .settings import Settings


def quick_origin(value):
    if not isinstance(value, str) or not re.fullmatch(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com', value):
        raise ValueError('An exact HTTPS Quick Tunnel origin without path or port is required')
    return value


class DemoGateway:
    def __init__(self, api, origin, frontend, *, clock=time.monotonic):
        self.api, self.origin, self.clock = api, quick_origin(origin), clock
        self.host = urlsplit(origin).netloc.encode('ascii')
        self.frontend = Path(frontend).resolve(strict=True)
        self.files = {}
        # Explicit built-output inventory, never a mount of the repository.
        for path in self.frontend.rglob('*'):
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(self.frontend):
                continue
            name = path.relative_to(self.frontend).as_posix()
            if (name == 'index.html' or
                (name.startswith(('assets/', 'licenses/', 'samples/')) and
                 not any(part.startswith('.') for part in Path(name).parts) and
                 path.suffix.lower() in {'.js','.css','.woff','.woff2','.svg','.png','.txt','.json','.xlsx'})):
                if path.stat().st_size > 16*1024*1024:
                    raise ValueError('Frontend asset exceeds demo size limit')
                self.files['/'+name] = path
        if '/index.html' not in self.files:
            raise ValueError('Build the teacher frontend first')
        self.http_active = self.ws_active = 0
        self.requests, self.auth_requests = deque(), deque()

    def budget(self, queue, maximum):
        now = self.clock()
        while queue and queue[0] <= now-60:
            queue.popleft()
        if len(queue) >= maximum:
            return False
        queue.append(now)
        return True

    async def __call__(self, scope, receive, send):
        kind = scope['type']
        if kind not in ('http', 'websocket'):
            return await self.api(scope, receive, send)
        async def reject(status, code):
            if kind == 'websocket':
                await send({'type':'websocket.close','code':1008,'reason':code})
            else:
                await JSONResponse({'detail':{'code':code,'message':'Request rejected'}},status_code=status,
                                   headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})(scope,receive,send)
        headers = scope.get('headers', [])
        def values(name):
            return [v for k,v in headers if k.lower()==name]
        try:
            local = ipaddress.ip_address(scope['client'][0]).is_loopback
        except (ValueError, KeyError, TypeError):
            local = False
        # A local process can reach this listener; it is not a local-user security
        # boundary. No client-provided forwarded identity is used for privileges.
        if not local or values(b'host') != [self.host]:
            return await reject(400,'host_rejected')
        if values(b'x-forwarded-proto') != [b'https']:
            return await reject(400,'https_required')
        if values(b'origin') and values(b'origin') != [self.origin.encode()]:
            return await reject(403,'origin_rejected')
        path = scope['path']
        if not self.budget(self.requests,600):
            return await reject(429,'demo_request_limit')
        if (path.startswith('/api/v1/auth/') and scope.get('method')=='POST' or path=='/api/v1/student/admit'):
            if not self.budget(self.auth_requests,30):
                return await reject(429,'demo_admission_limit')
        counter = 'ws_active' if kind=='websocket' else 'http_active'
        if getattr(self,counter) >= (32 if kind=='websocket' else 16):
            return await reject(429,'demo_connection_limit')
        setattr(self,counter,getattr(self,counter)+1)
        started = False
        async def safe_send(message):
            nonlocal started
            if message['type']=='http.response.start':
                started = True
                pairs = [(k,v) for k,v in message.get('headers',[]) if k.lower() not in
                         (b'content-security-policy',b'cache-control',b'strict-transport-security')]
                csp = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                       "font-src 'self'; img-src 'self' blob: data:; connect-src 'self' wss://"+self.host.decode()+
                       "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
                message={**message,'headers':pairs+[(b'content-security-policy',csp.encode()),
                    (b'cache-control',b'no-store'),(b'strict-transport-security',b'max-age=86400'),
                    (b'referrer-policy',b'no-referrer'),(b'x-content-type-options',b'nosniff')]}
            await send(message)
        # Discard all forwarded headers. Logical scheme comes solely from pinned
        # deployment configuration after the transport boundary checks above.
        clean={**scope,'scheme':'wss' if kind=='websocket' else 'https','headers':[
            (k,v) for k,v in headers if not k.lower().startswith((b'x-forwarded-',b'cf-')) and k.lower()!=b'forwarded']}
        try:
            if path.startswith('/api/v1/'):
                if kind=='http':
                    async with asyncio.timeout(30):
                        await self.api(clean,receive,safe_send)
                else:
                    await self.api(clean,receive,safe_send)
            elif kind=='http' and scope['method'] in ('GET','HEAD') and (path=='/' or path in self.files):
                target=self.files['/index.html' if path=='/' else path]
                # Recheck containment in case build output was replaced after startup.
                if target.is_symlink() or not target.resolve().is_relative_to(self.frontend):
                    return await reject(404,'not_found')
                with target.open('rb') as source:
                    data=source.read(16*1024*1024+1)
                if len(data)>16*1024*1024:
                    return await reject(503,'asset_limit')
                await Response(data,media_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream')(clean,receive,safe_send)
            else:
                await reject(404,'not_found')
        except Exception:
            if kind=='websocket':
                await send({'type':'websocket.close','code':1011,'reason':'service_unavailable'})
            elif not started:
                await reject(503,'service_unavailable')
            # No public traceback or exception string. No frame/body logging.
        finally:
            setattr(self,counter,getattr(self,counter)-1)


def create_demo_app():
    settings=Settings.from_env()
    origin=quick_origin(settings.public_url)
    if settings.teacher_origin!=origin or settings.allow_local_http:
        raise ValueError('Demo requires one exact HTTPS origin and no HTTP exception')
    frontend=Path(os.environ['PROCTOR_DEMO_FRONTEND'])
    return DemoGateway(create_app(settings, public_errors=True),origin,frontend)
