from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import time

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.devices import InputDevice, microphones, resolve_microphone, restore_device
from proctoring.ui.devices import DevicesWidget


class CatalogBackend:
    def __init__(self):
        self.apis = [dict(name='MME', default_input_device=0),
                     dict(name='Windows WASAPI', default_input_device=1),
                     dict(name='Windows WDM-KS', default_input_device=2)]
        self.rows = [self.row('Микрофон Fifine', 0), self.row('Микрофон Fifine', 1),
                     self.row('Микрофон Fifine', 2), self.row('Құлаққап микрофоны', 1),
                     dict(self.row('Speakers', 1), max_input_channels=0)]
        self.default = SimpleNamespace(device=(0, 4))

    @staticmethod
    def row(name, api):
        return dict(name=name, hostapi=api, max_input_channels=1, default_samplerate=48000)

    def query_hostapis(self):
        return self.apis

    def query_devices(self, index=None, kind=None):
        return self.rows if index is None else self.rows[index]

    def check_input_settings(self, device, **kwargs):
        if self.rows[device].get('unsupported'):
            raise ValueError('Device no longer available')


def test_normal_catalog_prefers_supported_wasapi_without_cross_api_name_merging():
    backend = CatalogBackend()
    all_inputs = microphones(backend)
    normal = [item for item in all_inputs[1:] if not item.advanced]
    assert [item.label for item in normal] == ['Микрофон Fifine', 'Құлаққап микрофоны']
    assert all(item.backend == 'Windows WASAPI' for item in normal)
    assert len(all_inputs) == 5  # All input routes retained; playback excluded.
    assert len({item.key for item in all_inputs}) == 5
    assert all('WASAPI' not in item.label and 'input ' not in item.label for item in normal)
    assert 'WASAPI' in normal[0].details


def test_default_name_and_opened_route_are_the_same_actual_wasapi_input():
    backend = CatalogBackend()
    default = microphones(backend)[0]
    resolved = resolve_microphone(default, backend)
    assert default.name == resolved.name == backend.rows[1]['name']
    assert default.default_target_key == resolved.key
    assert resolved.index == 1 and resolved.backend == 'Windows WASAPI'
    backend.apis[1]['default_input_device'] = -1
    assert resolve_microphone(None, backend).index == 0  # Explicit PortAudio fallback default.
    backend.default.device = (-1, 4)
    with pytest.raises(RuntimeError, match='unavailable'):
        resolve_microphone(None, backend)


def test_distinct_same_name_inputs_stay_distinct_and_cannot_restore_ambiguously():
    backend = CatalogBackend()
    backend.rows.append(backend.row('Микрофон Fifine', 1))
    matching = [item for item in microphones(backend)[1:]
                if item.backend == 'Windows WASAPI' and item.name == 'Микрофон Fifine']
    assert len(matching) == 2
    assert matching[0].label != matching[1].label
    assert matching[0].key != matching[1].key
    assert all(item.ambiguous for item in matching)
    assert all(restore_device(item.key, matching) is None for item in matching)
    assert resolve_microphone(matching[1], backend).index == 5


def test_supported_routes_and_reliable_loopback_flags_not_english_name_filters():
    backend = CatalogBackend()
    backend.rows.extend([
        dict(backend.row('Неактивный вход', 1), unsupported=True),
        dict(backend.row('Системный звук', 1), is_loopback=True),
        backend.row('Stereo Mix microphone product name', 1),
    ])
    choices = {item.name: item for item in microphones(backend)[1:]}
    assert choices['Неактивный вход'].advanced and not choices['Неактивный вход'].supported
    assert choices['Системный звук'].advanced
    # PortAudio does not expose all endpoint types: do not guess from English substrings.
    assert not choices['Stereo Mix microphone product name'].advanced


def test_without_wasapi_prefer_default_supported_api_and_preserve_old_key():
    import hashlib
    import json
    backend = CatalogBackend()
    backend.apis[1]['name'] = 'Windows DirectSound'
    choices = microphones(backend)
    normal = [item for item in choices[1:] if not item.advanced]
    assert [item.index for item in normal] == [0]
    old_signature = json.dumps(['MME', 'Микрофон Fifine', 1], ensure_ascii=True)
    old_key = hashlib.sha256(old_signature.encode()).hexdigest()
    assert restore_device(old_key, choices).index == 0


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def controller():
    config = load_config()
    audio = SimpleNamespace(_thread=None, _switching=False, _device_refresh=False,
                            selection=None, _selection_error=None, stop=Mock(), start=Mock(),
                            select_device=Mock(return_value=True), _set_status=Mock(),
                            unavailable_selection=Mock())
    return SimpleNamespace(config=config, audio=audio, clock=FakeClock(),
                           monitor=SimpleNamespace(select_camera=Mock(return_value=True),
                                                   unavailable_selection=Mock()),
                           session=SimpleNamespace(started=False), select_camera=Mock(return_value=True))


def test_dropdown_advanced_toggle_preserves_selection_unicode_and_legacy_preference(app, tmp_path):
    ctl = controller()
    prefs = QSettings(str(tmp_path/'catalog.ini'), QSettings.Format.IniFormat)
    choices = microphones(CatalogBackend())
    # Saved legacy WDM-KS route remains explicit; never substitute the WASAPI same-name route.
    saved = next(item for item in choices if item.backend == 'Windows WDM-KS')
    prefs.setValue('microphone', saved.key)
    widget = DevicesWidget(ctl, settings=prefs)
    widget._loaded((0, {'cameras': [], 'microphones': choices}))
    assert widget.advanced_audio.isChecked()
    assert widget.microphone.currentData() == saved
    assert ctl.audio.selection == saved
    assert widget.microphone.currentData(Qt.ItemDataRole.ToolTipRole) == saved.details
    widget.advanced_audio.setChecked(False)
    assert widget.microphone.currentData() == saved
    assert 'Микрофон Fifine' in widget.microphone.currentText()
    ctl.audio.select_device.assert_not_called()
    widget.shutdown(); widget.deleteLater(); app.processEvents()


def test_active_refresh_does_not_stop_or_restart_unchanged_microphone(app, monkeypatch, tmp_path):
    from proctoring.ui import devices as ui
    ctl = controller()
    ctl.audio._thread = SimpleNamespace(is_alive=lambda: True)
    scanned = Mock(return_value={'cameras': [], 'microphones': microphones(CatalogBackend()), 'audio_cached': True})
    monkeypatch.setattr(ui, 'scan_active_inputs', scanned)
    reinit = Mock(side_effect=AssertionError('No PortAudio reinitialization while active'))
    monkeypatch.setattr(ui, 'scan_inputs', reinit)
    widget = DevicesWidget(ctl, settings=QSettings(str(tmp_path/'refresh.ini'), QSettings.Format.IniFormat))
    end = time.monotonic()+2
    while not widget._initialized and time.monotonic() < end:
        app.processEvents()
        time.sleep(.005)
    assert widget._initialized and scanned.called
    reinit.assert_not_called()
    ctl.audio.stop.assert_not_called()
    ctl.audio.start.assert_not_called()
    assert 'Microphone test continues' in widget.message.text()
    widget.shutdown(); widget.deleteLater(); app.processEvents()


def test_camera_selection_uses_controller_consent_path_not_direct_capture(app, tmp_path):
    ctl = controller()
    widget = DevicesWidget(ctl, settings=QSettings(str(tmp_path/'camera.ini'), QSettings.Format.IniFormat))
    widget.camera.addItem('Selected camera', InputDevice('qt-exact-id', 'Selected camera'))
    widget._camera_selected(0)
    ctl.select_camera.assert_called_once_with('qt-exact-id')
    ctl.monitor.select_camera.assert_not_called()
    widget.shutdown(); widget.deleteLater(); app.processEvents()


def test_reselecting_same_route_keeps_mic_calibration(app, tmp_path):
    ctl = controller()
    selected = microphones(CatalogBackend())[2]
    ctl.audio.selection = selected
    widget = DevicesWidget(ctl, settings=QSettings(str(tmp_path/'same.ini'), QSettings.Format.IniFormat))
    widget.microphone.addItem(selected.label, selected)
    widget._microphone_selected(0)
    ctl.audio.select_device.assert_not_called()
    assert widget.settings.value('microphone') == selected.key
    ctl.audio._selection_error = 'Previously unavailable'
    widget._microphone_selected(0)
    ctl.audio.select_device.assert_called_once_with(selected)
    widget.shutdown(); widget.deleteLater(); app.processEvents()


def test_missing_camera_refresh_invalidates_controller_reference_metadata(app, tmp_path):
    ctl = controller()
    ctl.camera_unavailable = Mock()
    prefs = QSettings(str(tmp_path/'missing.ini'), QSettings.Format.IniFormat)
    prefs.setValue('camera', 'removed-id')
    widget = DevicesWidget(ctl, settings=prefs)
    widget._loaded((0, {'cameras': [], 'microphones': []}))
    ctl.camera_unavailable.assert_called_once()
    ctl.monitor.unavailable_selection.assert_not_called()
    assert widget.camera.currentData() == 'missing'
    widget.shutdown(); widget.deleteLater(); app.processEvents()


def test_changed_system_default_does_not_mislabel_active_stream_and_can_be_selected(app, tmp_path):
    ctl = controller()
    prefs = QSettings(str(tmp_path/'default-change.ini'), QSettings.Format.IniFormat)
    prefs.setValue('microphone', 'system-default')
    old = InputDevice('system-default', 'Default — A', name='A', default_target_key='route-a')
    new = InputDevice('system-default', 'Default — B', name='B', default_target_key='route-b')
    ctl.audio.selection = old
    ctl.audio.device_key = 'route-a'
    ctl.audio.resolved_device = 'A'
    ctl.audio._thread = SimpleNamespace(is_alive=lambda: True)
    widget = DevicesWidget(ctl, settings=prefs)
    widget._initialized = True
    widget._audio_was_running = True
    widget._loaded((0, {'cameras': [], 'microphones': [new], 'audio_cached': True}))
    assert ctl.audio.selection == old
    assert widget.microphone.currentText() == 'System default — currently A; select to use B'
    assert 'currently A' in widget.microphone.toolTip()
    ctl.audio.stop.assert_not_called()
    ctl.audio.start.assert_not_called()
    widget._microphone_selected(widget.microphone.currentIndex())
    ctl.audio.select_device.assert_called_once_with(new)
    # The worker later publishes the actual new source; UI follows that result.
    ctl.audio.selection = new
    ctl.audio.device_key = 'route-b'
    ctl.audio.resolved_device = 'B'
    widget.update_session()
    assert widget.microphone.currentText() == 'System default — B'
    widget.shutdown(); widget.deleteLater(); app.processEvents()
