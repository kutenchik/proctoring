"""Pre-exam device preferences; enumeration and native switching never run on Qt UI."""
from dataclasses import replace
import threading
from PySide6.QtCore import QSettings, Signal, QTimer, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QPushButton
from .. import devices
from ..i18n import t, manager


def preferences():
    return QSettings('LocalProctoring', 'InputDevices')


def _scan_inputs(refresh_audio):
    result = {}
    audio_scan = devices.refresh_microphones if refresh_audio else devices.microphones
    for name, function in (('cameras', devices.cameras), ('microphones', audio_scan)):
        try:
            result[name] = function()
        except Exception as error:
            result[name] = []
            result[name+'_error'] = type(error).__name__
    return result


def scan_inputs():
    return _scan_inputs(refresh_audio=True)


def scan_active_inputs():
    # PortAudio cannot rebuild its device cache without closing active streams.
    # A normal refresh must not interrupt an unchanged microphone test.
    result = _scan_inputs(refresh_audio=False)
    result['audio_cached'] = True
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
        self._microphones = []
        self.camera = QComboBox()
        self.microphone = QComboBox()
        self.camera.setMinimumContentsLength(24)
        self.microphone.setMinimumContentsLength(24)
        self.camera.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.microphone.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.advanced_audio = QCheckBox()
        self.rescan_audio = QPushButton()
        self.rescan_audio.hide()
        self.camera_label, self.microphone_label = QLabel(), QLabel()
        self.refresh_button = QPushButton()
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout = QFormLayout(self)
        layout.addRow(self.camera_label, self.camera)
        layout.addRow(self.microphone_label, self.microphone)
        layout.addRow(self.advanced_audio)
        layout.addRow(self.rescan_audio)
        layout.addRow(self.refresh_button)
        layout.addRow(self.message)
        layout.addRow(self.notice)
        self.camera.activated.connect(self._camera_selected)
        self.microphone.activated.connect(self._microphone_selected)
        self.refresh_button.clicked.connect(self.refresh_devices)
        self.rescan_audio.clicked.connect(lambda: self.refresh_devices(force_audio=True))
        self.advanced_audio.toggled.connect(self._advanced_toggled)
        self.camera.currentIndexChanged.connect(lambda _: self._update_tooltip(self.camera))
        self.microphone.currentIndexChanged.connect(lambda _: self._update_tooltip(self.microphone))
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
        self.advanced_audio.setText(t('devices.advanced_audio'))
        self.rescan_audio.setText(t('devices.rescan_audio'))
        self.notice.setText(t('devices.preview_only') if self.preview_only else t('devices.local'))
        if self._microphones:
            self._populate_microphones(self.microphone.currentData())

    @staticmethod
    def _update_tooltip(combo):
        combo.setToolTip(combo.currentData(Qt.ItemDataRole.ToolTipRole) or combo.currentText())

    def _advanced_toggled(self, enabled):
        self.rescan_audio.setVisible(enabled)
        self._populate_microphones(self.microphone.currentData())

    def _default_target_changed(self, device):
        return (device.key == 'system-default' and bool(getattr(self.audio, 'device_key', None))
                and device.default_target_key != self.audio.device_key)

    def _microphone_label(self, device):
        if device.key != 'system-default':
            return device.details if self.advanced_audio.isChecked() and device.details else device.label
        current_default = getattr(self.audio.selection, 'key', 'system-default') == 'system-default'
        active = bool(self.audio._thread and self.audio._thread.is_alive())
        if current_default and active and self._default_target_changed(device):
            return t('devices.default_changed', current=getattr(self.audio, 'resolved_device', None)
                     or t('devices.previous_input'), next=device.name or t('devices.unavailable'))
        return (t('devices.default_named', name=device.name) if device.name else
                t('devices.default_unavailable') if not device.supported else t('devices.default_mic'))

    def _populate_microphones(self, current=None):
        self.microphone.clear()
        for device in self._microphones:
            if device.advanced and not self.advanced_audio.isChecked() and device != current:
                continue
            label = self._microphone_label(device)
            self.microphone.addItem(label, device)
            tooltip = (label+'\n'+device.details if device.details else label) if device.key == 'system-default' else (device.details or label)
            self.microphone.setItemData(self.microphone.count()-1, tooltip,
                                        Qt.ItemDataRole.ToolTipRole)
        if current == 'missing':
            self.microphone.addItem(t('devices.missing', device=t('devices.microphone')), 'missing')
            self.microphone.setCurrentIndex(self.microphone.count()-1)
        elif current is not None:
            for index in range(self.microphone.count()):
                if self.microphone.itemData(index) == current:
                    self.microphone.setCurrentIndex(index)
                    break
        self._update_tooltip(self.microphone)

    def refresh_devices(self, _checked=False, *, force_audio=False):
        if self._closed or self.controller.session.started or self._busy:
            return
        if getattr(self.controller.monitor, '_switching', False) or self.audio._switching:
            return
        self._busy = True
        self._audio_was_running = bool(self.audio._thread and self.audio._thread.is_alive())
        self._restart_audio = self._audio_was_running and force_audio
        self.audio._device_refresh = True
        self.controller.device_selection_ready = False
        self.setEnabled(False)
        self.message.setText(t('devices.scanning'))
        self._generation += 1
        generation = self._generation
        def scan():
            if force_audio:
                self.audio.stop(timeout=2.)
            if force_audio and self.audio._thread and self.audio._thread.is_alive():
                result = {'cameras': [], 'microphones': [], 'microphones_error': 'Previous input still releasing; restart after reconnecting it'}
            else:
                result = scan_active_inputs() if self._audio_was_running and not force_audio else scan_inputs()
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
        cfg = self.controller.config.vision
        self.camera.addItem(f'Configured OpenCV input {cfg.camera_index} ({cfg.camera_backend})', None)
        for device in result['cameras']:
            self.camera.addItem(device.label, device)
            self.camera.setItemData(self.camera.count()-1, device.label, Qt.ItemDataRole.ToolTipRole)
        self._microphones = result['microphones']
        saved_mic = devices.restore_device(self.settings.value('microphone', '', str), self._microphones)
        if saved_mic is not None and saved_mic.advanced:
            self.advanced_audio.setChecked(True)
        self._populate_microphones()
        warnings = []
        for kind, combo, choices in (('camera', self.camera, result['cameras']),
                                     ('microphone', self.microphone, result['microphones'])):
            saved = self.settings.value(kind, '', str)
            if saved:
                device = devices.restore_device(saved, choices)
                if device is None:
                    missing = t('devices.missing', device=t('devices.'+kind))
                    combo.addItem(missing, 'missing')
                    combo.setCurrentIndex(combo.count()-1)
                    warnings.append(missing)
                    if kind == 'camera':
                        unavailable = getattr(self.controller, 'camera_unavailable',
                                              self.controller.monitor.unavailable_selection)
                        unavailable()
                        self.camera_changing.emit()
                    else:
                        self.audio.unavailable_selection()
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
        if result.get('audio_cached'):
            warnings.append(t('devices.cached_audio'))
        self.message.setText('\n'.join(warnings) if warnings else t('devices.choose'))
        self._initialized = True
        self.controller.device_selection_ready = True
        if getattr(self, '_restart_audio', False):
            self.audio.start()
        elif not self.preview_only and not getattr(self, '_audio_was_running', False):
            self.audio._set_status('not_started')

    def _camera_selected(self, index, persist=True):
        if self.controller.session.started or self._closed:
            return
        device = self.camera.itemData(index)
        if device == 'missing':
            return
        key = device.key if device else None
        select = getattr(self.controller, 'select_camera', self.controller.monitor.select_camera)
        if select(key):
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
        existing = self.audio.selection
        if (not self.audio._selection_error and not self._default_target_changed(device) and
                ((existing is None and device.key == 'system-default') or
                 (existing is not None and existing.key == device.key and existing.signature == device.signature))):
            self.audio.selection = device
            self.settings.setValue('microphone', device.key)
            self.settings.sync()
            return
        if self.audio.select_device(device):
            self.settings.setValue('microphone', device.key)
            self.settings.sync()
            self.message.setText(t('devices.mic_changed'))

    def update_session(self):
        started = self.controller.session.started
        switching = getattr(self.controller.monitor, '_switching', False) or self.audio._switching
        self.setEnabled(not started and not self._busy and not switching)
        for index in range(self.microphone.count()):
            device = self.microphone.itemData(index)
            if isinstance(device, devices.InputDevice) and device.key == 'system-default':
                label = self._microphone_label(device)
                if self.microphone.itemText(index) != label:
                    self.microphone.setItemText(index, label)
                    self.microphone.setItemData(index, label+'\n'+device.details if device.details else label,
                                                Qt.ItemDataRole.ToolTipRole)
                    self._update_tooltip(self.microphone)
        if started and self.preview_only and self.audio.status['state'] not in {'stopped', 'not_started'}:
            self.audio.stop(timeout=0)

    def shutdown(self):
        self._closed = True
        self._generation += 1
        if self.preview_only:
            self.audio.stop(timeout=0)
