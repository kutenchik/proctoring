import argparse
from dataclasses import replace
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

from .config import DEFAULT_CONFIG, load_config
from .i18n import set_language
from .controller import AppController
from .ui.window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Local proctoring with offline camera monitoring")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic inputs without opening a camera")
    parser.add_argument("--calibration-debug", action="store_true",
                        help="Show local numerical calibration diagnostics (requires safe mode)")
    args = parser.parse_args()
    # Required before QApplication when WebEngine is imported lazily later.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Local Proctoring")
    controller = None
    try:
        config = load_config(args.config)
        set_language(config.ui.language)
        if args.calibration_debug:
            config = replace(config, vision=replace(config.vision, calibration_debug=True))
        if config.vision.calibration_debug and config.protection.enabled:
            raise ValueError("Calibration diagnostics require protection.enabled=false; use the safe default configuration")
        controller = AppController(config, mode="synthetic" if args.synthetic else "camera")
        window = MainWindow(controller)
    except (OSError, ValueError, RuntimeError) as error:
        if controller is not None:
            controller.protection.release("startup_failure")
            controller.protection.close()
            controller.monitor.stop()
            controller.close_remote(timeout=2.0)
        print(f"Startup failed: {error}", file=sys.stderr)
        return 2

    def fail_safe(kind, value, tb):
        controller.protection.release("unhandled_error")
        traceback.print_exception(kind, value, tb)
        try:
            controller.emergency_end("unhandled_error")
        finally:
            app.exit(1)

    sys.excepthook = fail_safe
    window.show()
    try:
        return app.exec()
    finally:
        controller.protection.release("application_exit")
        try:
            if controller.session.started and not controller.session.ended:
                controller.end("application_exit")
        finally:
            # QTextDocument/QPdfWriter use Qt font services in the report worker.
            # Keep QApplication alive if Qt quit without a normal closeEvent.
            if controller.report_status == "running":
                completion_loop = QEventLoop()
                report_timer = QTimer()
                report_timer.timeout.connect(lambda: completion_loop.quit()
                                             if controller.report_status != "running" else None)
                report_timer.start(100)
                completion_loop.exec()
                report_timer.stop()
            window.shutdown_ui()


if __name__ == "__main__":
    raise SystemExit(main())

