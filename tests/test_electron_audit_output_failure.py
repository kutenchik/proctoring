"""Validation only: no native audit, devices or helper processes."""
from datetime import datetime, timezone
import json
import pytest
from proctoring.security.electron_validation import MANDATORY_CHECKS, require_electron_validation


@pytest.mark.parametrize('status', ['failed', 'pending_or_incomplete', 'cancelled'])
def test_incomplete_status_cannot_authorize_even_with_all_checks_and_pass_flag(tmp_path, status):
    identity = {'fixture': True}
    report = {'schema': 2, 'frontend': 'electron', 'mode': 'audit_only', 'blocking_enabled': False,
              'passed': True, 'status': status, 'identity': identity,
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'checks': [{'name': name, 'passed': True, 'kind': 'native_audit'} for name in MANDATORY_CHECKS]}
    file = tmp_path/'audit.json'
    file.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='incomplete or failed'):
        require_electron_validation(file, identity)
