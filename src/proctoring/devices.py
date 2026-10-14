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
    name: str = ""
    backend: str = ""
    advanced: bool = False
    supported: bool = True
    details: str = ""
    default_target_key: str = ""


def cameras():
    from PySide6.QtMultimedia import QMediaDevices
    return [InputDevice(bytes(d.id()).hex(), f"{d.description()} [{hashlib.sha256(bytes(d.id())).hexdigest()[:6]}]")
            for d in QMediaDevices.videoInputs()]


def microphones(backend=None):
    """Preferred-backend catalog, without pretending API aliases are endpoints.

    PortAudio does not expose Windows endpoint IDs through sounddevice. Keep the
    existing API/name/channel signature keys (including ambiguity protection),
    and prefer supported WASAPI routes rather than merging friendly names.
    Checking the format does not open a stream or change Windows input volume.
    """
    if backend is None:
        import sounddevice as backend
    apis = backend.query_hostapis()
    rows = [(i, d) for i, d in enumerate(backend.query_devices()) if d['max_input_channels'] > 0]
    signatures = [json.dumps([apis[d['hostapi']]['name'], d['name'], d['max_input_channels']],
                             ensure_ascii=True) for _, d in rows]
    result = []
    for (index, device), signature in zip(rows, signatures):
        duplicate = signatures.count(signature) > 1
        key = hashlib.sha256(signature.encode()).hexdigest()
        if duplicate:
            key += f':ambiguous:{index}'
        api = apis[device['hostapi']]['name']
        supported = not (device.get('disabled', False) or device.get('is_present') is False
                         or device.get('is_active') is False)
        # Optional backend metadata is trustworthy; English-name heuristics are
        # not. Standard sounddevice lacks endpoint form-factor/loopback metadata.
        loopback = bool(device.get('is_loopback', False) or device.get('isLoopbackDevice', False))
        candidate = InputDevice(key, str(device['name']), index, signature, duplicate,
                                name=str(device['name']), backend=api)
        if supported:
            try:
                input_format(candidate, int(device['default_samplerate']), backend)
            except (RuntimeError, KeyError, TypeError, ValueError):
                supported = False
        detail = f"{candidate.name} · {api} · input {index}"
        if not supported:
            detail += ' · unavailable / unsupported format'
        if loopback:
            detail += ' · loopback input'
        result.append((candidate, supported, loopback, detail, device['hostapi']))

    # WASAPI default_input_device is the default route of that actual API, not
    # an index borrowed from Qt or a guessed same-name alias on another API.
    default_index = int(backend.default.device[0])
    for api_index, api in enumerate(apis):
        if 'WASAPI' in api['name'].upper():
            index = int(api.get('default_input_device', -1))
            if any(item.index == index and supported and not loopback
                   for item, supported, loopback, _, _ in result):
                default_index = index
                break
    default = next((item for item, supported, loopback, _, _ in result
                    if item.index == default_index and supported and not loopback), None)
    preferred = next((api for _, supported, loopback, _, api in result
                      if supported and not loopback and 'WASAPI' in apis[api]['name'].upper()), None)
    if preferred is None:
        preferred = next((api for item, supported, loopback, _, api in result
                          if supported and not loopback and item.index == default_index), None)
    if preferred is None:
        preferred = next((api for _, supported, loopback, _, api in result if supported and not loopback), None)
    from dataclasses import replace
    choices = []
    names = [item.name for item, supported, loopback, _, api in result
             if supported and not loopback and api == preferred]
    for item, supported, loopback, detail, api in result:
        advanced = api != preferred or not supported or loopback
        label = item.name
        if not advanced and names.count(item.name) > 1:
            label += f" [{hashlib.sha256(item.key.encode()).hexdigest()[:6]}]"
        choices.append(replace(item, label=label, supported=supported,
                               advanced=advanced, details=detail))
    default_entry = InputDevice(
        'system-default', f"System default — {default.name if default else 'unavailable'}",
        name=default.name if default else '', backend=default.backend if default else '',
        supported=default is not None, default_target_key=default.key if default else '',
        details=(f'{default.name} · {default.backend} · input {default.index}' if default else
                 'No supported default input device'))
    return [default_entry, *choices]


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
        key = choices[0].default_target_key
        selected = next((d for d in choices[1:] if d.key == key), None)
    else:
        selected = next((d for d in choices if d.key == selection.key and
                         d.signature == selection.signature), None)
    if selected is None or not selected.supported:
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
