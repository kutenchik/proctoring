"""Run the native, audit-only recovery check from the source checkout.

The implementation also ships in the standalone executable so the same checks
validate its actual helper and executable rather than a separate Python tree.
"""
from proctoring.security.audit import main


if __name__ == "__main__":
    raise SystemExit(main())
