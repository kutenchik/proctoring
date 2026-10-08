"""PyInstaller starts here; helper modes must be routed before importing Qt UI."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from proctoring.desktop import main
    raise SystemExit(main())
