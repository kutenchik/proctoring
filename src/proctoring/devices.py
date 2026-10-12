"""Device identities belong to the backend that opens them; no cross-API indices."""
from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class InputDevice:
    key: str
    label: str
    index: int | None = None
    signature: str = ""
    ambiguous: bool = False


def cameras():
    from PySide6.QtMultimedia import QMediaDevices
    return [InputDevice(bytes(d.id()).hex(), f"{d.description()} [{hashlib.sha256(bytes(d.id())).hexdigest()[:6]}]")
            for d in QMediaDevices.videoInputs()]


def microphones(backend=None):
    if backend is None:
        import sounddevice as backend
    apis = backend.query_hostapis()
    rows = [(i, d) for i, d in enumerate(backend.query_devices()) if d['max_input_channels'] > 0]
    signatures = [json.dumps([apis[d['hostapi']]['name'], d['name'], d['max_input_channels']],
                             ensure_ascii=True) for _, d in rows]
    result = [InputDevice('system-default', 'System default microphone')]
    for (index, device), signature in zip(rows, signatures):
        duplicate = signatures.count(signature) > 1
        key = hashlib.sha256(signature.encode()).hexdigest()
        if duplicate:
            key += f':ambiguous:{index}'
        result.append(InputDevice(key, f"{device['name']} · {apis[device['hostapi']]['name']} · input {index}",
                                  index, signature, duplicate))
    return result


def refresh_microphones():
    """PortAudio caches devices until reinitialized; caller MUST release our stream.

    sounddevice 0.5.x exposes no public refresh API. These paired lifecycle
    functions are isolated here and are called only by the setup worker, while
    all application audio opens are excluded. No system volume is touched.
    """
    import sounddevice
    sounddevice._terminate()
    sounddevice._initialize()
    return microphones(sounddevice)


def restore_device(saved, available):
    """Ambiguous PortAudio names are selectable now, never silently restored."""
    return next((d for d in available if d.key == saved and not d.ambiguous), None)


def resolve_microphone(selection, backend):
    choices = microphones(backend)
    if selection is None or selection.key == 'system-default':
        index = int(backend.default.device[0])
        selected = next((d for d in choices if d.index == index), None)
    else:
        selected = next((d for d in choices if d.key == selection.key and
                         d.signature == selection.signature), None)
    if selected is None:
        raise RuntimeError('Selected microphone unavailable; choose an input device')
    return selected


def input_format(device, requested_rate, backend):
    info = backend.query_devices(device.index, 'input')
    rates = list(dict.fromkeys([requested_rate, int(info['default_samplerate'])]))
    channels = list(dict.fromkeys([1, min(2, int(info['max_input_channels']))]))
    for rate in rates:
        for count in channels:
            try:
                backend.check_input_settings(device=device.index, samplerate=rate,
                                             channels=count, dtype='float32')
                return rate, count
            except Exception:
                continue
    raise RuntimeError('Microphone format unsupported; choose another input device')
