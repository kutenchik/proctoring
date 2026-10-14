from copy import deepcopy
from dataclasses import replace
import json
import threading
import pytest

from proctoring.connected.client import ConnectedError
from proctoring.desktop_bridge.protocol import BridgeError
from test_connected_client import ADMISSION, IDENTITY, ready_client, settle
from test_desktop_workflow import make_workflow, make_ready


def connected_workflow(tmp_path):
    bridge = make_workflow(tmp_path)
    client, _ = ready_client(tmp_path, bridge.clock)
    bridge.admission_client = client
    bridge.config = replace(bridge.config, connected=client.settings)
    return bridge


def admit(bridge):
    bridge.dispatch('connected.admit', IDENTITY)
    bridge.admission_client._thread.join(2)
    bridge.tick()
    assert bridge._admission_applied


def prepare(bridge):
    # Reuse the existing synthetic calibration fixture without re-registering
    # the immutable server identity or opening hardware.
    candidate = bridge.controller.session.candidate
    bridge.config = replace(bridge.config, registration=replace(bridge.config.registration, enabled=False))
    make_ready(bridge)
    assert bridge.controller.session.candidate == candidate


def start(bridge):
    bridge.dispatch('exam.start', {})
    bridge.admission_client._thread.join(2)
    bridge.tick()


def test_admission_blocks_preparation_and_fixes_policy_before_setup(tmp_path):
    bridge = connected_workflow(tmp_path)
    try:
        with pytest.raises(BridgeError, match='admission'): bridge.dispatch('camera.start', {})
        assert not bridge.monitor.started
        admit(bridge)
        assert bridge.config.duration_seconds == 120 and not bridge.config.audio.enabled
        assert bridge.controller.session.candidate.full_name == IDENTITY['full_name']
        with pytest.raises(BridgeError): bridge.dispatch('registration.submit', {'first_name':'Other','last_name':'User','group_id':'B'})
        assert not bridge.controller.session.started
    finally: bridge.close()


def test_start_requires_both_existing_readiness_and_server_then_runs_offline(tmp_path):
    bridge = connected_workflow(tmp_path)
    try:
        admit(bridge)
        with pytest.raises(BridgeError): bridge.dispatch('exam.start', {})
        assert not bridge.admission_client.start_attempted
        prepare(bridge); start(bridge)
        assert bridge.controller.session.running
        bridge.admission_client.transport = lambda *args: (_ for _ in ()).throw(ConnectedError('connection_failed'))
        bridge.clock.advance(2); bridge.tick()
        assert bridge.controller.session.running and bridge.controller.session.elapsed_seconds == 2
        assert not bridge.controller.session.pause_reasons
        bridge.dispatch('quiz.answer', {'question_index':0,'option_indices':[0,2],'revision':0})
        assert bridge.controller.quiz.score == 1
        bridge.dispatch('exam.submit', {})
        public = json.dumps(bridge.state())
        assert 'correct_option_ids' not in public and 'credential' not in public
        assert bridge.controller.summary['connected_attempt']['attempt_id'] == 'attempt-1'
        for path in bridge.controller.store.path.rglob('*.json*'):
            assert ADMISSION['credential'] not in path.read_text(encoding='utf-8')
        assert bridge.controller.summary['score'] == 1
    finally: bridge.close()


def test_expired_preparation_blocks_first_start_and_auth_extension_restores(tmp_path):
    bridge = connected_workflow(tmp_path)
    try:
        admit(bridge); prepare(bridge)
        bridge.clock.advance(301)
        with pytest.raises(BridgeError): bridge.dispatch('exam.start', {})
        assert not bridge.controller.session.started
        original = bridge.admission_client.transport
        def extended(*args):
            result = original(*args)
            result['server_time'] = '2026-10-13T10:05:10+00:00'
            result['preparation_deadline'] = '2026-10-13T10:10:00+00:00'
            return result
        bridge.admission_client.transport = extended
        bridge.dispatch('connected.refresh', {})
        bridge.admission_client._thread.join(2); bridge.tick()
        start(bridge)
        assert bridge.controller.session.running
    finally: bridge.close()


def test_server_rejection_cannot_start_even_when_local_ready(tmp_path):
    bridge = connected_workflow(tmp_path)
    try:
        admit(bridge); prepare(bridge)
        bridge.admission_client.transport = lambda *args: (_ for _ in ()).throw(ConnectedError('preparation_expired'))
        start(bridge)
        assert bridge.admission_client.error == 'preparation_expired'
        assert not bridge.controller.session.started
    finally: bridge.close()


def test_camera_loss_during_authorization_does_not_bypass_local_readiness(tmp_path):
    bridge = connected_workflow(tmp_path)
    try:
        admit(bridge); prepare(bridge)
        release = threading.Event()
        original = bridge.admission_client.transport
        def delayed(*args):
            release.wait(2)
            return original(*args)
        bridge.admission_client.transport = delayed
        bridge.dispatch('exam.start', {})
        bridge.monitor.healthy = False
        release.set()
        bridge.admission_client._thread.join(2)
        bridge.tick()
        assert not bridge.controller.session.started
        assert bridge.admission_client.error == 'readiness_changed'
    finally: bridge.close()


def test_protected_teacher_policy_refused_by_safe_launch(tmp_path):
    bridge = connected_workflow(tmp_path)
    try:
        original = bridge.admission_client.transport
        def protected(*args):
            response = original(*args); response['exam']['protection_mode'] = 'protected'; return response
        bridge.admission_client.transport = protected
        bridge.dispatch('connected.admit', IDENTITY)
        bridge.admission_client._thread.join(2); bridge.tick()
        assert not bridge._admission_applied
        assert bridge.admission_client.error == 'protection_policy_mismatch'
        assert not bridge.controller.protection.blocking_enabled
    finally: bridge.close()


def test_delayed_start_approval_cannot_start_after_conservative_deadline(tmp_path):
    bridge = connected_workflow(tmp_path)
    try:
        admit(bridge); prepare(bridge)
        # Server time at response leaves 0.1 seconds; transport took a second.
        original = bridge.admission_client.transport
        def delayed(*args):
            result = original(*args)
            result['server_time'] = '2026-10-13T10:04:59.900000+00:00'
            bridge.clock.advance(1)
            return result
        bridge.admission_client.transport = delayed
        start(bridge)
        assert bridge.admission_client.start_authorized
        assert not bridge.controller.session.started
        assert bridge.admission_client.error == 'readiness_changed'
        assert not bridge.readiness()['ready']
    finally: bridge.close()


def test_refresh_does_not_replace_quiz_object_or_reorder_attempt(tmp_path):
    bridge = connected_workflow(tmp_path)
    try:
        admit(bridge)
        quiz = bridge.controller.quiz
        question_ids = [q.id for q in quiz.questions]
        option_ids = [q.option_ids for q in quiz.questions]
        bridge.dispatch('connected.refresh', {})
        bridge.admission_client._thread.join(2); bridge.tick()
        assert bridge.controller.quiz is quiz
        assert [q.id for q in quiz.questions] == question_ids
        assert [q.option_ids for q in quiz.questions] == option_ids
    finally: bridge.close()
