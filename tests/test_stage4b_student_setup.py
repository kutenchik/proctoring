import importlib.util
from pathlib import Path
import tomllib
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stage4b_setup', ROOT / 'scripts/prepare_stage4b_student.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

def test_safe_remote_configuration():
    text = setup.prepare_text((ROOT / 'config/connected.example.toml').read_text(), 'https://disposable-check.trycloudflare.com')
    d = tomllib.loads(text)
    assert not d['protection']['enabled'] and not d['security']['blocking_enabled']
    assert not d['security']['system_checks']['clipboard_guard_enabled']
    assert d['security']['system_checks']['block_multimonitor']
    assert not d['connected']['allow_loopback_http']
    assert not d['remote']['enabled']
    assert d['storage']['sessions_dir'].startswith('../build/stage4b-student/')

@pytest.mark.parametrize('origin', ['http://127.0.0.1:8034','https://example.com','https://x.trycloudflare.com.evil','https://x.trycloudflare.com/','https://name:secret@x.trycloudflare.com'])
def test_origin_rejected(origin):
    with pytest.raises(ValueError): setup.prepare_text('', origin)

def test_fail_closed_if_template_policy_changes():
    text = (ROOT / 'config/connected.example.toml').read_text().replace('blocking_enabled = false','blocking_enabled = true')
    with pytest.raises(ValueError): setup.prepare_text(text, 'https://x.trycloudflare.com')
