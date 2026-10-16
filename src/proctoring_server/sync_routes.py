"""Stage 2 transport; all material reads are authenticated and owner scoped."""
from fastapi import Request
from fastapi.responses import FileResponse


def install_sync_routes(app, service, sync, owner, credential):
    prefix = "/api/v1"

    def student(request):
        return credential(request), request.headers.get("x-device-secret")

    @app.post(prefix + "/student/start/confirm")
    def confirm_start(request: Request, data: dict):
        return sync.confirm_start(*student(request), data)

    @app.post(prefix + "/student/interrupted")
    def interrupted(request: Request, data: dict):
        return sync.interrupted(*student(request), data)

    @app.post(prefix + "/student/recovery/consume")
    def consume(request: Request, data: dict):
        return sync.recovery(*student(request), data)

    @app.post(prefix + "/student/recovery/confirm")
    def confirm_recovery(request: Request, data: dict):
        return sync.recovery(*student(request), data, confirm=True)

    @app.post(prefix + "/student/sync/records")
    def records(request: Request, data: dict):
        return sync.records_upload(*student(request), data)

    @app.post(prefix + "/student/sync/snapshots")
    def snapshot_declare(request: Request, data: dict):
        return sync.snapshot_declare(*student(request), data)

    @app.post(prefix + "/student/sync/audio")
    def audio_declare(request: Request, data: dict):
        return sync.snapshot_declare(*student(request), data, audio=True)

    @app.post(prefix + "/student/sync/audio/{item_id}/chunks")
    @app.post(prefix + "/student/sync/snapshots/{item_id}/chunks")
    def snapshot_chunk(request: Request, item_id: str, data: dict):
        result = sync.chunk(*student(request), item_id, data, provisional=True)
        # Durable state is committed before notification. Periodic authenticated
        # teacher snapshots also reconcile a lost notification or server restart.
        if result["complete"] and getattr(app.state, "live", None):
            with sync.database.connect() as connection:
                attempt, _ = sync._owned(connection, *student(request), evidence_only=True)
            with app.state.live.lock:
                app.state.live.broadcast_student(attempt["id"])
        return result

    @app.post(prefix + "/student/sync/manifest")
    def manifest(request: Request, data: dict):
        return sync.manifest_upload(*student(request), data)

    @app.post(prefix + "/student/sync/files/{item_id}/chunks")
    def chunk(request: Request, item_id: str, data: dict):
        return sync.chunk(*student(request), item_id, data)

    @app.get(prefix + "/student/sync/status")
    def status(request: Request):
        return sync.status(*student(request))

    @app.post(prefix + "/student/sync/complete")
    def complete(request: Request, data: dict):
        return sync.complete(*student(request), data)

    @app.post(prefix + "/attempts/{attempt_id}/recovery/authorize")
    def authorize_recovery(request: Request, attempt_id: str, data: dict):
        return sync.authorize_recovery(owner(request, True), attempt_id, data)

    @app.get(prefix + "/attempts/{attempt_id}/sync")
    def detail(request: Request, attempt_id: str):
        return sync.teacher_detail(owner(request), attempt_id)

    @app.get(prefix + "/attempts/{attempt_id}/evidence/{item_id}")
    def evidence(request: Request, attempt_id: str, item_id: str):
        path, media, name = sync.evidence_file(owner(request), attempt_id, item_id)
        return FileResponse(path, media_type=media, filename=name, content_disposition_type="inline" if media == "audio/wav" else "attachment", headers={"Cache-Control": "no-store"})

    @app.post(prefix + "/attempts/{attempt_id}/materials/delete")
    def delete(request: Request, attempt_id: str, data: dict):
        return sync.delete_materials(owner(request, True), attempt_id, data)
