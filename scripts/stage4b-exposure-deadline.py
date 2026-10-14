"""Independent public-exposure deadline. Run only with operator approval."""
import argparse
import json
from pathlib import Path
import subprocess
import time

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator-approved', action='store_true', required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--deadline', type=float, required=True, help='Unix epoch seconds')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = args.run.resolve()
    if not run.is_relative_to(root / 'build/stage4b') or not run.is_dir():
        raise ValueError('Existing isolated run directory required')
    if not 0 < args.deadline - time.time() <= 900:
        raise ValueError('Deadline must be within 15 minutes')
    # Refuse stale/reused guard evidence.
    with (run / 'deadline.json').open('x') as f:
        json.dump({'started_at': time.time(), 'deadline': args.deadline}, f)
    # Reserve the maximum Stop command timeout inside the public-exposure budget.
    while time.time() < args.deadline - 60:
        if (run / 'closed.json').exists():
            return
        time.sleep(.5)
    with (run / 'deadline-stop.log').open('x') as log:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(root / 'scripts/stage4b-demo.ps1'), '-Action', 'Stop', '-RunDirectory', str(run)],
                                stdout=log, stderr=log, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    (run / 'deadline-result.json').write_text(json.dumps({'at': time.time(), 'returncode': result.returncode}))
    if result.returncode:
        raise RuntimeError('Ownership-aware Stop failed; operator attention required, no unrelated process termination attempted')

if __name__ == '__main__':
    main()
