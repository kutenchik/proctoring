"""Authenticated WebSockets with bounded in-memory delivery and no frame logs."""
import asyncio
import json

from fastapi import Request, WebSocket, WebSocketDisconnect

from .live import LiveService
from .service import Problem

COOKIE = "proctor_teacher_session"


async def receive(ws, limit=81920, timeout=1):
    raw = await asyncio.wait_for(ws.receive_text(), timeout)
    if len(raw.encode("utf-8")) > limit:
        raise Problem("message_limit", "Live message exceeds limit", 413)
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise Problem("invalid_message", "Live message must be a JSON object") from None
    if not isinstance(data, dict):
        raise Problem("invalid_message", "Live message must be a JSON object")
    return data


def install_live_routes(app, service, sync, owner):
    live = LiveService(service, sync)
    app.state.live = live
    prefix = "/api/v1"

    @app.post(prefix+"/attempts/{attempt_id}/commands")
    def command(request: Request, attempt_id: str, data: dict):
        return live.command(owner(request, True), attempt_id, data)

    @app.get(prefix+"/attempts/{attempt_id}/commands")
    def commands(request: Request, attempt_id: str):
        return live.commands(owner(request), attempt_id)

    @app.post(prefix+"/attempts/{attempt_id}/view")
    def view(request: Request, attempt_id: str):
        return live.start_viewer(owner(request, True), attempt_id)

    @app.post(prefix+"/live/view/stop")
    def stop(request: Request, data: dict):
        return live.stop_viewer(data.get("viewer_id"), "teacher_stopped", owner(request, True))

    @app.get(prefix+"/live/view/{viewer_id}/diagnostics")
    def diagnostics(request: Request, viewer_id: str):
        return live.diagnostics(owner(request), viewer_id)

    @app.post(prefix+"/exams/{exam_id}/close-admissions")
    def close(request: Request, exam_id: str, data: dict):
        return live.close_admissions(owner(request, True), exam_id, data)

    def origin(ws):
        if ws.headers.get("origin") != service.settings.teacher_origin:
            raise Problem("origin_rejected", "Teacher WebSocket origin rejected", 403)

    def dispatch(peer, data):
        live.revalidate(peer)
        kind = data.get("type")
        if peer.role == "student":
            if kind == "consent":
                live.consent(peer, data)
            elif kind == "status":
                live.status(peer, data)
            elif kind == "event":
                live.event(peer, data)
            elif kind == "command_ack":
                live.acknowledge(peer, data)
            else:
                raise Problem("invalid_live_message", "Unsupported student control message")
        elif peer.role == "teacher":
            if kind != "ping":
                raise Problem("invalid_live_message", "Teacher socket mutations use authenticated HTTP commands")
            peer.put(live.snapshot(peer.identity, peer.exam_id))
        else:
            live.stream(peer, data)

    async def run(ws, peer):
        async def sender():
            while not peer.closed:
                with live.lock:
                    packet = peer.pop()
                if packet is None:
                    await asyncio.sleep(.02)
                else:
                    traced = peer.trace and packet.get('type') in ('frame','frame_ack')
                    if traced:
                        peer.trace.record('send_started', packet['sequence'], 1 if packet['type']=='frame_ack' else 0)
                    try:
                        await asyncio.wait_for(ws.send_json(packet), 2)
                    except asyncio.TimeoutError:
                        if traced:
                            peer.trace.record('send_timeout', packet['sequence'])
                        raise Problem('stream_send_failed', 'Stream send deadline exceeded', 503) from None
                    if traced:
                        peer.trace.record('send_completed', packet['sequence'], 1 if packet['type']=='frame_ack' else 0)

        async def receiver():
            limit = 393216 if peer.role.startswith("viewer_") else 81920
            rate_started, count = live.monotonic(), 0
            while not peer.closed:
                try:
                    data = await receive(ws, limit=limit)
                except asyncio.TimeoutError:
                    await asyncio.to_thread(live.revalidate, peer)
                    await asyncio.to_thread(live.sweep)
                    continue
                if live.monotonic()-rate_started >= 1:
                    rate_started, count = live.monotonic(), 0
                count += 1
                if count > 40:
                    raise Problem("message_rate", "Live message rate exceeded", 429)
                await asyncio.to_thread(dispatch, peer, data)
                await asyncio.to_thread(live.sweep)

        jobs = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for job in done:
                job.result()
        finally:
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)

    async def socket(ws, role):
        peer = None
        stop_reason = 'disconnected'
        try:
            if role == "teacher":
                origin(ws)
            if role == "student" and ws.headers.get("origin"):
                raise Problem("origin_rejected", "Student control belongs to the Python backend", 403)
            await ws.accept()
            data = await receive(ws, limit=8192, timeout=5)
            if role == "student":
                header = ws.headers.get("authorization", "")
                if not header.startswith("Bearer "):
                    raise Problem("invalid_credential", "Attempt authentication required", 401)
                peer = await asyncio.to_thread(live.student_connect, header[7:], ws.headers.get("x-device-secret"), data)
            elif role == "teacher":
                if data.get("type") != "auth":
                    raise Problem("invalid_live_auth", "Teacher authentication required", 401)
                peer = await asyncio.to_thread(live.teacher_connect, ws.cookies.get(COOKIE), data.get("csrf_token"), data.get("exam_id"))
            else:
                if data.get("role") == "teacher":
                    origin(ws)
                elif ws.headers.get("origin"):
                    raise Problem("origin_rejected", "Student stream belongs to trusted Electron main", 403)
                peer = await asyncio.to_thread(live.stream_connect, data, ws.cookies.get(COOKIE))
            await run(ws, peer)
        except Problem as error:
            # A protocol failure used to become generic disconnected in finally.
            stop_reason = error.code
            try:
                await ws.send_json({"type": "error", "code": error.code})
            except (RuntimeError, WebSocketDisconnect):
                pass
        except WebSocketDisconnect as error:
            if peer and peer.role == 'viewer_teacher' and error.code == 1000 and error.reason == 'teacher_stopped':
                stop_reason = 'teacher_stopped'
            if peer and peer.role == 'viewer_student':
                from proctoring.connected.screen_diagnostic import safe_code
                code = safe_code(error.reason)
                if code != 'unknown_failure':
                    stop_reason = code
        except (asyncio.TimeoutError, RuntimeError, OSError):
            pass
        finally:
            if peer:
                await asyncio.to_thread(live.disconnect, peer, stop_reason)
            # Stream stop classification precedes close, independent of control polling.
            if peer and peer.stop_message:
                try:
                    await asyncio.wait_for(ws.send_json(peer.stop_message), 2)
                except (RuntimeError, WebSocketDisconnect, asyncio.TimeoutError, OSError):
                    pass
            try:
                await ws.close(code=1000)
            except (RuntimeError, WebSocketDisconnect, OSError):
                pass

    @app.websocket(prefix+"/live/student")
    async def student_socket(ws: WebSocket):
        await socket(ws, "student")

    @app.websocket(prefix+"/live/teacher")
    async def teacher_socket(ws: WebSocket):
        await socket(ws, "teacher")

    @app.websocket(prefix+"/live/stream")
    async def stream_socket(ws: WebSocket):
        await socket(ws, "stream")
