"""Pre-exam device preferences; enumeration and native switching never run on Qt UI."""
from dataclasses import replace
import threading
from PySide6.QtCore import QSettings, Signal, QTimer
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QPushButton
from .. import devices
from ..i18n import t, manager


def preferences():
    return QSettings('LocalProctoring', 'InputDevices')


def scan_inputs():
    result = {}
    for name, function in (('cameras', devices.cameras), ('microphones', devices.refresh_microphones)):
        try:
            result[name] = function()
        except Exception as error:
            result[name] = []
            result[name+'_error'] = type(error).__name__
    return result


class DevicesWidget(QGroupBox):
    scanned = Signal(object)
    camera_changing = Signal()

    def __init__(self, controller, parent=None, settings=None):
        super().__init__(parent)
        self.controller = controller
        self.settings = settings if settings is not None else preferences()
        self.audio = controller.audio
        self.preview_only = self.audio is None
        if self.preview_only:
            from ..audio.monitor import AudioMonitor
            self.audio = AudioMonitor(replace(controller.config.audio, enabled=True), controller.clock)
        self._busy = self._closed = False
        self._initialized = False
        self._generation = 0
        self.camera = QComboBox()
        self.microphone = QComboBox()
        self.camera_label, self.microphone_label = QLabel(), QLabel()
        self.refresh_button = QPushButton()
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout = QFormLayout(self)
        layout.addRow(self.camera_label, self.camera)
        layout.addRow(self.microphone_label, self.microphone)
        layout.addRow(self.refresh_button)
        layout.addRow(self.message)
        layout.addRow(self.notice)
        self.camera.activated.connect(self._camera_selected)
        self.microphone.activated.connect(self._microphone_selected)
        self.refresh_button.clicked.connect(self.refresh_devices)
        self.scanned.connect(self._loaded)
        manager.language_changed.connect(self.retranslate_ui)
        self.controller.device_selection_ready = False
        self.retranslate_ui()
        QTimer.singleShot(0, self.refresh_devices)

    def retranslate_ui(self, *_):
        self.setTitle(t('devices.title'))
        self.camera_label.setText(t('devices.camera'))
        self.microphone_label.setText(t('devices.microphone'))
        self.refresh_button.setText(t('devices.refresh'))
        self.notice.setText(t('devices.preview_only') if self.preview_only else t('devices.local'))

    def refresh_devices(self):
        if self._closed or self.controller.session.started or self._busy:
            return
        if getattr(self.controller.monitor, '_switching', False) or self.audio._switching:
            return
        self._busy = True
        self._audio_was_running = bool(self.audio._thread and self.audio._thread.is_alive())
        self.audio._device_refresh = True
        self.controller.device_selection_ready = False
        self.setEnabled(False)
        self.message.setText(t('devices.scanning'))
        self._generation += 1
        generation = self._generation
        def scan():
            self.audio.stop(timeout=2.)
            if self.audio._thread and self.audio._thread.is_alive():
                result = {'cameras': [], 'microphones': [], 'microphones_error': 'Previous input still releasing; restart after reconnecting it'}
            else:
                result = scan_inputs()
            try:
                if not self._closed:
                    self.scanned.emit((generation, result))
            except RuntimeError:
                pass  # Window closed while the driver enumerated devices.
        threading.Thread(target=scan, name='input-device-list', daemon=True).start()
        QTimer.singleShot(5000, lambda: self._timeout(generation))

    def _timeout(self, generation):
        if not self._closed and self._busy and generation == self._generation:
            self.message.setText(t('devices.timeout'))
            # Do not start competing enumeration if a native driver is stuck.

    def _loaded(self, value):
        generation, result = value
        if self._closed or generation != self._generation:
            return
        self._busy = False
        self.audio._device_refresh = False
        self.setEnabled(not self.controller.session.started)
        self.camera.clear()
        self.microphone.clear()
        cfg = self.controller.config.vision
        self.camera.addItem(f'Configured OpenCV input {cfg.camera_index} ({cfg.camera_backend})', None)
        for device in result['cameras']:
            self.camera.addItem(device.label, device)
        for device in result['microphones']:
            self.microphone.addItem(t('devices.default_mic') if device.key == 'system-default' else device.label, device)
        warnings = []
        for kind, combo, choices in (('camera', self.camera, result['cameras']),
                                     ('microphone', self.microphone, result['microphones'])):
            saved = self.settings.value(kind, '', str)
            if saved:
                device = devices.restore_device(saved, choices)
                if device is None:
                    combo.addItem(t('devices.missing', device=kind), 'missing')
                    combo.setCurrentIndex(combo.count()-1)
                    warnings.append(t('devices.missing', device=kind))
                    source = self.controller.monitor if kind == 'camera' else self.audio
                    source.unavailable_selection()
                else:
                    combo.setCurrentIndex(next(i for i in range(combo.count()) if combo.itemData(i) == device))
                    if not self._initialized:
                        if kind == 'camera':
                            self._camera_selected(combo.currentIndex(), persist=False)
                        else:
                            self.audio.selection = device  # Open only when testing is active.
                            self.audio._selection_error = None
            elif kind == 'microphone' and choices:
                combo.setCurrentIndex(0)
        warnings += [f'{name}: {result[name]}' for name in result if name.endswith('_error')]
        self.message.setText('\n'.join(warnings) if warnings else t('devices.choose'))
        self._initialized = True
        self.controller.device_selection_ready = True
        if getattr(self, '_audio_was_running', False):
            self.audio.start()
        elif not self.preview_only:
            self.audio._set_status('not_started')

    def _camera_selected(self, index, persist=True):
        if self.controller.session.started or self._closed:
            return
        device = self.camera.itemData(index)
        if device == 'missing':
            return
        key = device.key if device else None
        if self.controller.monitor.select_camera(key):
            self.camera_changing.emit()
            if persist:
                self.settings.setValue('camera', key or '')
                self.settings.sync()
            self.message.setText(t('devices.camera_changed'))

    def _microphone_selected(self, index):
        if self.controller.session.started or self._closed:
            return
        device = self.microphone.itemData(index)
        if device is None or device == 'missing':
            return
        if self.audio.select_device(device):
            self.settings.setValue('microphone', device.key)
            self.settings.sync()
            self.message.setText(t('devices.mic_changed'))

    def update_session(self):
        started = self.controller.session.started
        switching = getattr(self.controller.monitor, '_switching', False) or self.audio._switching
        self.setEnabled(not started and not self._busy and not switching)
        if started and self.preview_only and self.audio.status['state'] not in {'stopped', 'not_started'}:
            self.audio.stop(timeout=0)

    def shutdown(self):
        self._closed = True
        self._generation += 1
        if self.preview_only:
            self.audio.stop(timeout=0)
