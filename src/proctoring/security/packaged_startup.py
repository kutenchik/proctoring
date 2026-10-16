"""Read-only packaged startup verification. Never creates a native helper or hook."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from ..config import load_config
from .electron_validation import runtime_identity, protection_policy, require_electron_validation, MANDATORY_CHECKS


def inspect(config_path, runtime, host, report=None):
    # Exercise the real consent/teacher-control import in the frozen runtime.
    # No socket is opened, but an incomplete distribution must fail before Join.
    from websockets.sync.client import connect
    root = Path(sys.executable).resolve().parents[2]
    if not getattr(sys, 'frozen', False) or runtime.get('build_kind') != 'packaged':
        raise ValueError('Packaged runtime required')
    if Path(host).resolve() != root / 'LocalProctoring-Electron.exe':
        raise ValueError('Unexpected packaged host')
    config_path = Path(config_path)
    if config_path.read_bytes() != (root/'resources/default.example.toml').read_bytes():
        raise ValueError('Packaged configuration must match the trusted defaults')
    config = load_config(config_path)
    if not config.connected.enabled:
        raise ValueError('Packaged student requires Connected Mode')
    identity = runtime_identity(SimpleNamespace(runtime=runtime, image_path=host), root)
    identity['protection_policy'] = protection_policy(config.protection)
    result = {'identity': identity, 'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
              'report_path': str(config.protection.validation_report), 'language': config.ui.language,
              'valid': False, 'audit_required': config.protection.enabled and getattr(config.protection,'require_recovery_audit',True)}
    if not result['audit_required']:
        result['reason']='Recovery audit is not required by this trusted edition'
        return result
    try:
        candidate = require_electron_validation(report or config.protection.validation_report, identity,
                                               config.protection.validation_max_age_hours)
        if candidate.get('status') != 'completed' or len(candidate['checks']) != len(MANDATORY_CHECKS):
            raise ValueError('Exactly 21 completed native checks required')
        result['valid'] = True
    except ValueError as error:
        result['reason'] = str(error)
    return result


def main(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--report')
    args = parser.parse_args(arguments)
    try:
        result = inspect(args.config, json.loads(args.runtime), args.host, args.report)
        print(json.dumps(result))
        return 0
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        return 1
