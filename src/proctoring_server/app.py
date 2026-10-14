"""FastAPI transport: strict origins/CSRF, opaque sessions and bounded imports."""
from __future__ import annotations

import sqlite3
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .imports import parse_import
from .service import Problem, Service, iso
from .settings import Settings
from .sync import SyncService

COOKIE = "proctor_teacher_session"
PREFIX = "/api/v1"


class BodyLimitMiddleware:
    """Bound the raw request before multipart parsing, including chunked bodies."""
    def __init__(self, app, limit=3 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse({"detail": {"code": "body_too_large", "message": "Request exceeds the 3 MiB limit"}}, status_code=413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(chunks)

        async def replay():
            try:
                return next(iterator)
            except StopIteration:
                return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None, *, clock=None, public_errors=False) -> FastAPI:
    settings = settings or Settings.from_env()
    service = Service(settings, **({"clock": clock} if clock is not None else {}))
    app = FastAPI(title="Local Proctoring Teacher Service", version="1", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.state.settings = settings
    sync = SyncService(service)
    app.state.sync = sync
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.public_url).hostname])
    app.add_middleware(CORSMiddleware, allow_origins=[settings.teacher_origin], allow_credentials=True,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-CSRF-Token", "Authorization", "X-Device-Secret"])

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if settings.secure_cookie:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, error):
        return JSONResponse({"detail": {"code": error.code, "message": error.message}}, status_code=error.status)

    @app.exception_handler(ValueError)
    async def value_handler(request, error):
        return JSONResponse({"detail": {"code": "invalid_input", "message": "Invalid request" if public_errors else str(error)}}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        # Do not echo supplied passwords, tokens or complete body values.
        return JSONResponse({"detail": {"code": "invalid_request", "message": "Request body or required fields are invalid"}}, status_code=422)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_handler(request, error):
        return JSONResponse({"detail": {"code": "database_unavailable", "message": "The service is temporarily unavailable; retry"}}, status_code=503)

    def origin(request):
        if request.headers.get("origin") != settings.teacher_origin:
            raise Problem("origin_rejected", "This request did not originate from the configured teacher website", 403)

    def teacher(request: Request, mutate=False):
        if mutate:
            origin(request)
        return service.authenticate(request.cookies.get(COOKIE), request.headers.get("x-csrf-token"), mutate)

    def owner(request: Request, mutate=False):
        return teacher(request, mutate)["teacher"]["id"]

    def credential(request):
        value = request.headers.get("authorization", "")
        if not value.startswith("Bearer "):
            raise Problem("invalid_credential", "An attempt bearer credential is required", 401)
        return value[7:]

    @app.get(PREFIX + "/health")
    def health():
        return {"service": "local-proctoring-teacher", "api_version": 1, "server_time": iso(service.clock())}

    @app.post(PREFIX + "/auth/accept-invite")
    def accept_invite(request: Request, data: dict):
        origin(request)
        return service.consume_account_token("invite", data)

    @app.post(PREFIX + "/auth/reset-password")
    def reset_password(request: Request, data: dict):
        origin(request)
        return service.consume_account_token("reset", data)

    @app.post(PREFIX + "/auth/login")
    def login(request: Request, response: Response, data: dict):
        origin(request)
        raw, result = service.login(data, request.client.host if request.client else "unknown")
        response.set_cookie(COOKIE, raw, max_age=settings.session_seconds, path=PREFIX,
                            secure=settings.secure_cookie, httponly=True, samesite="strict")
        return result

    @app.get(PREFIX + "/auth/me")
    def me(request: Request):
        return teacher(request)

    @app.post(PREFIX + "/auth/logout")
    def logout(request: Request, response: Response):
        teacher(request, True)
        service.logout(request.cookies[COOKIE])
        response.delete_cookie(COOKIE, path=PREFIX, secure=settings.secure_cookie, httponly=True, samesite="strict")
        return {"logged_out": True}

    @app.get(PREFIX + "/libraries")
    def libraries(request: Request):
        return service.libraries(owner(request))

    @app.post(PREFIX + "/libraries/preview")
    def preview(request: Request, file: UploadFile = File(...)):
        owner(request, True)
        try:
            return parse_import(file.filename or "", file.file.read(settings.max_upload_bytes + 1), settings.max_upload_bytes)
        finally:
            file.file.close()

    @app.post(PREFIX + "/libraries", status_code=201)
    def save_library(request: Request, data: dict):
        return service.save_library(owner(request, True), data)

    @app.get(PREFIX + "/libraries/{library_id}")
    def library(request: Request, library_id: str):
        return service.library(owner(request), library_id)

    @app.get(PREFIX + "/exams")
    def exams(request: Request):
        return service.exams(owner(request))

    @app.post(PREFIX + "/exams", status_code=201)
    def create_exam(request: Request, data: dict):
        return service.create_exam(owner(request, True), data)

    @app.get(PREFIX + "/exams/{exam_id}")
    def exam(request: Request, exam_id: str):
        return service.exam(owner(request), exam_id)

    @app.get(PREFIX + "/exams/{exam_id}/attempts")
    def attempts(request: Request, exam_id: str):
        return service.attempts(owner(request), exam_id)

    @app.post(PREFIX + "/attempts/{attempt_id}/extend")
    def extend(request: Request, attempt_id: str, data: dict):
        return service.extend(owner(request, True), attempt_id, data)

    @app.post(PREFIX + "/attempts/{attempt_id}/allow-repeat")
    def repeat(request: Request, attempt_id: str, data: dict):
        return service.allow_repeat(owner(request, True), attempt_id, data)

    @app.post(PREFIX + "/student/admit", status_code=201)
    def admit(data: dict):
        return service.admit(data)

    @app.get(PREFIX + "/student/attempt")
    def student_attempt(request: Request):
        raw = credential(request)
        return sync.attempt(raw, request.headers.get("x-device-secret")) if sync.bound(raw) else service.student_attempt(raw)

    @app.post(PREFIX + "/student/start")
    def start(request: Request, data: dict | None = None):
        raw = credential(request)
        return sync.authorize_start(raw, request.headers.get("x-device-secret"), data or {}) if sync.bound(raw) else service.start(raw)

    @app.post(PREFIX + "/student/finish")
    def finish(request: Request, data: dict):
        raw = credential(request)
        if sync.bound(raw):
            raise Problem("sync_required", "Device-bound completion requires its durable evidence manifest and receipt", 409)
        return service.finish(raw, data)

    from .sync_routes import install_sync_routes
    from .review_routes import install_review_routes
    from .live_routes import install_live_routes
    install_sync_routes(app, service, sync, owner, credential)
    install_review_routes(app, service, sync, owner)
    install_live_routes(app, service, sync, owner)

    return app
