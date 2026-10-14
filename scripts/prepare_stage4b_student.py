"""Configuration preparation only; never imports devices or starts an application."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    'yolo11n.onnx': '7d8fd1717d9d5bbab6986cd134afb620649c7a394303d55b1e09fc00804cc5c1',
    'face_landmarker.task': '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff',
}

def prepare_text(template: str, origin: str) -> str:
    if not re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com', origin):
        raise ValueError('Use the exact assigned HTTPS origin, without path or trailing slash')
    text = template.replace('server_url = "http://127.0.0.1:8000"', f'server_url = "{origin}"')
    text = text.replace('allow_loopback_http = true', 'allow_loopback_http = false')
    text = text.replace('clipboard_guard_enabled = true', 'clipboard_guard_enabled = false')
    text = text.replace('vm_check_enabled = true', 'vm_check_enabled = false')
    text = text.replace('sessions_dir = "../sessions"', 'sessions_dir = "../build/stage4b-student/sessions"')
    data = tomllib.loads(text)
    if not (data['protection']['enabled'] is False and data['security']['blocking_enabled'] is False):
        raise ValueError('Unsafe or unexpected connected template')
    if not (data['security']['system_checks'] == {'block_multimonitor': True, 'clipboard_guard_enabled': False, 'vm_check_enabled': False}):
        raise ValueError('Unsafe or unexpected connected template')
    if not (data['connected']['enabled'] is True and data['connected']['allow_loopback_http'] is False):
        raise ValueError('Unsafe or unexpected connected template')
    if not (data['connected']['server_url'] == origin):
        raise ValueError('Unsafe or unexpected connected template')
    if not (data['remote']['enabled'] is False and data['remote']['telegram_enabled'] is False):
        raise ValueError('Unsafe or unexpected connected template')
    if not (data['exam']['external_url'] == ''):
        raise ValueError('Unsafe or unexpected connected template')
    return text

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    args = parser.parse_args()
    text = prepare_text((ROOT / 'config/connected.example.toml').read_text(encoding='utf-8'), args.origin)
    hashes = {name: hashlib.sha256((ROOT / 'models' / name).read_bytes()).hexdigest() for name in MODELS}
    if hashes != MODELS:
        raise ValueError('Missing or mismatched local model; do not start')
    destination = ROOT / 'config/stage4b-student.toml'
    with destination.open('x', encoding='utf-8') as stream:
        stream.write(text)
    print(json.dumps({'configuration_created': str(destination), 'models_verified': hashes, 'devices_started': False}))

if __name__ == '__main__':
    main()
