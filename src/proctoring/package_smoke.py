"""Explicit, local-only frozen-package smoke test; never starts an exam.

This mode exercises bundled native libraries and assets without opening a camera
or microphone, arming restrictions, or contacting a remote service.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import threading
import time

from .config import AppConfig


def _safe_config(config: AppConfig, output_dir: Path) -> AppConfig:
    """Override every operational feature regardless of operator preferences."""
    return replace(
        config, sessions_dir=output_dir / "unused-sessions", external_url="", allowed_domains=(),
        snapshots_enabled=False, blocking_enabled=False,
        protection=replace(config.protection, enabled=False),
        remote=replace(config.remote, enabled=False, telegram_enabled=False, webhook_url="",
                       webhook_token="", telegram_bot_token="", telegram_chat_id=""),
        registration=replace(config.registration, enabled=False),
        identity=replace(config.identity, selfie_verification_enabled=False),
        audio=replace(config.audio, enabled=False),
        system_checks=replace(config.system_checks, block_multimonitor=False,
                              clipboard_guard_enabled=False, vm_check_enabled=False),
        reporting=replace(config.reporting, generate_pdf_report=False, send_pdf_to_telegram=False),
        vision=replace(config.vision, prefer_gpu=False, calibration_debug=False,
                       accessories=replace(config.vision.accessories, earphone_detection_enabled=False)),
    )


def _native_checks(config: AppConfig, output_dir: Path, checks: dict, lock: threading.Lock) -> None:
    """Keep expensive imports/inference/PDF layout off the GUI thread."""
    def record(name, action):
        try:
            details = action()
            result = {"ok": True, **(details or {})}
        except Exception as error:
            # Exception messages and config dumps can contain operator secrets.
            result = {"ok": False, "error_type": type(error).__name__}
        with lock:
            checks[name] = result

    def audio_import():
        import sounddevice
        return {"version": sounddevice.__version__, "device_opened": False}

    def yolo():
        import numpy as np
        from .vision.yolo import YoloDetector
        detector = YoloDetector(config.vision)
        try:
            persons, phones = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))
            return {"provider": detector.provider, "persons": len(persons), "phones": len(phones)}
        finally:
            detector.close()

    def face():
        import numpy as np
        from .vision.face import FaceAnalyzer
        detector = FaceAnalyzer(config.vision)
        try:
            result = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8), time.monotonic())
            return {"face_present": result.face_present, "frame_size": list(result.frame_size)}
        finally:
            detector.close()

    def pdf():
        from .storage.report_generator import generate_report
        directory = output_dir / "sample-report"
        directory.mkdir(parents=True, exist_ok=True)
        summary = {"session_id": "package-smoke", "candidate": None, "events": [],
                   "security_events": [], "end_reason": "package_smoke_no_exam"}
        (directory / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        destination = generate_report(directory, summary)
        return {"bytes": destination.stat().st_size}

    record("sounddevice", audio_import)
    record("yolo_cpu", yolo)
    record("mediapipe", face)
    record("pdf", pdf)


def run_package_smoke(config: AppConfig, output_dir: Path, *, timeout_seconds: float = 45.0) -> int:
    """Write ``package-smoke.json`` and return 0 only if all checks complete.

    The event loop is bounded. Native inference runs in a daemon thread; a
    timeout fails verification and the calling CLI should exit immediately.
    """
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, Qt
    from PySide6.QtWidgets import QApplication

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config = _safe_config(config, output_dir)
    if QApplication.instance() is None:
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication([])
    checks: dict = {}
    lock = threading.Lock()
    expected = {"window", "webengine", "sounddevice", "yolo_cpu", "mediapipe", "pdf"}
    window = controller = browser = profile = page = interceptor = None
    timer = None
    worker = None
    try:
        from .controller import AppController
        from .ui.window import MainWindow
        controller = AppController(config, mode="synthetic")
        window = MainWindow(controller, enable_watchdog=False)
        window.show()
        app.processEvents()
        checks["window"] = {"ok": window.isVisible(), "mode": "synthetic", "exam_started": False}

        try:
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
            from PySide6.QtWebEngineWidgets import QWebEngineView

            class LocalRequestsOnly(QWebEngineUrlRequestInterceptor):
                def interceptRequest(self, info):
                    if info.requestUrl().scheme() not in {"data", "about", "qrc"}:
                        info.block(True)

            browser = QWebEngineView()
            profile = QWebEngineProfile(browser)  # unnamed / off the record
            interceptor = LocalRequestsOnly(profile)
            profile.setUrlRequestInterceptor(interceptor)
            page = QWebEnginePage(profile, browser)
            browser.setPage(page)
            browser.loadFinished.connect(lambda ok: checks.__setitem__(
                "webengine", {"ok": bool(ok), "local_html_only": True}))
            browser.setHtml("<!doctype html><html><body><p>Local package smoke test</p></body></html>")
        except Exception as error:
            checks["webengine"] = {"ok": False, "error_type": type(error).__name__}

        worker = threading.Thread(target=_native_checks, args=(config, output_dir, checks, lock),
                                  daemon=True, name="package-smoke")
        worker.start()
        loop = QEventLoop()
        started = time.monotonic()

        def poll():
            with lock:
                if "webengine" not in checks and time.monotonic() - started >= min(15.0, timeout_seconds):
                    checks["webengine"] = {"ok": False, "error_type": "Timeout"}
                complete = expected <= checks.keys()
            if (complete and time.monotonic() - started >= .25) or time.monotonic() - started >= timeout_seconds:
                loop.quit()

        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(50)
        loop.exec()
    except Exception as error:
        checks.setdefault("window", {"ok": False, "error_type": type(error).__name__})
    finally:
        if timer is not None:
            timer.stop()
        if window is not None:
            window.close()
            window.shutdown_ui()
        elif controller is not None:
            controller.monitor.stop()
            controller.protection.release("package_smoke")
            controller.protection.close()
            controller.close_optional_workers()
            controller.close_remote(timeout=0)
        if browser is not None:
            browser.stop()
            browser.close()
            # Destroy the page before its off-the-record profile.
            if page is not None:
                import shiboken6
                shiboken6.delete(page)
            browser.deleteLater()
        app.processEvents()

    with lock:
        for name in expected - checks.keys():
            checks[name] = {"ok": False, "error_type": "Timeout"}
        report = {"ok": all(result["ok"] for result in checks.values()), "checks": dict(checks),
                  "camera_opened": False, "microphone_opened": False, "network_enabled": False,
                  "restrictions_enabled": False, "exam_started": False}
    (output_dir / "package-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
