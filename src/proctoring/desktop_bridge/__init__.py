"""Unprotected Electron adapter around the existing Python exam services.

The narrow setup service remains separately testable. WorkflowBridge composes
the actual controller, session, calibration and storage without a hidden legacy
window. Protected Electron mode is rejected before any helper is created.
"""

