from dataclasses import asdict, replace
from pathlib import Path
import pytest

from proctoring.config import load_config
from proctoring.settings import SystemChecksConfig, IdentityConfig, AudioConfig, ReportingConfig


def test_optional_features_default_disabled():
    config = load_config()
    assert not any(asdict(config.system_checks).values())
    assert not config.identity.selfie_verification_enabled
    assert config.exam.identity is config.identity
    assert not config.audio.enabled
    assert not config.reporting.generate_pdf_report
    assert not config.reporting.send_pdf_to_telegram
    assert not config.vision.accessories.earphone_detection_enabled
    assert config.identity.periodic_check_interval_seconds == 30
    assert config.audio.sample_rate == 16000
    assert config.audio.voice_duration_threshold == 2


@pytest.mark.parametrize("type_,values", [
    (SystemChecksConfig, {"block_multimonitor": 1}),
    (IdentityConfig, {"selfie_verification_enabled": "true"}),
    (IdentityConfig, {"impersonation_threshold": float("nan")}),
    (IdentityConfig, {"periodic_check_interval_seconds": 0}),
    (AudioConfig, {"sample_rate": True}), (AudioConfig, {"sample_rate": 0}),
    (AudioConfig, {"energy_threshold": float("inf")}),
    (AudioConfig, {"voice_duration_threshold": -1}),
    (ReportingConfig, {"report_filename": "../outside.pdf"}),
    (ReportingConfig, {"report_filename": "C:\\outside.pdf"}),
    (ReportingConfig, {"report_filename": "report.html"}),
    (ReportingConfig, {"generate_pdf_report": "false"}),
])
def test_new_settings_reject_invalid_types_and_unsafe_values(type_, values):
    with pytest.raises(ValueError):
        type_(**values)


def test_public_settings_expose_opt_in_configuration():
    config = replace(load_config(), system_checks=SystemChecksConfig(True, True, True),
                     identity=IdentityConfig(True), audio=AudioConfig(True),
                     reporting=ReportingConfig(True, True))
    public = config.public_dict()
    assert public["system_checks"]["clipboard_guard_enabled"]
    assert public["identity"]["selfie_verification_enabled"]
    assert public["audio"]["enabled"]
    assert public["reporting"]["send_pdf_to_telegram"]
