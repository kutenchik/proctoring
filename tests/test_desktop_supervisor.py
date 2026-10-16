import json
from types import SimpleNamespace

import pytest

from proctoring.desktop_bridge.supervisor import BackendOwner, IDENTITY_PREFIX, announce_backend_identity, backend_command


class Native:
    def __init__(self):
        self.closed = []
        self.terminated = []
        self.times = {100: '1000', 200: '2000'}
    def open_process(self, pid, terminate=False): return pid
    def creation(self, handle): return self.times[handle]
    def alive(self, handle): return handle not in self.terminated
    def terminate(self, handle, timeout=1.): self.terminated.append(handle)
    def close(self, handle): self.closed.append(handle)


def test_backend_owner_rejects_unrelated_pid_before_any_termination():
    native = Native()
    launcher = SimpleNamespace(pid=100, poll=lambda: None)
    with pytest.raises(ValueError, match='not owned'):
        BackendOwner(200, launcher, native=native, identity_reader=lambda pid: (pid, 1, "python.exe", "test-owner", ("backend",)), parent_chain=lambda _: [999])
    assert native.closed == [200]
    assert native.terminated == []


def test_backend_owner_keeps_native_handle_even_if_numeric_pid_is_reused():
    native = Native()
    launcher = SimpleNamespace(pid=100, poll=lambda: None)
    owner = BackendOwner(200, launcher, native=native, identity_reader=lambda pid: (pid, 1, "python.exe", "test-owner", ("backend",)), parent_chain=lambda _: [100])
    assert owner.created == '2000'
    owner.terminate()
    assert native.terminated == [200]
    assert not owner.alive()
    owner.close()
    assert native.closed == [100, 200]


def test_backend_owner_rejects_older_creation_time_and_dead_launcher():
    native = Native(); native.times[200] = '500'
    with pytest.raises(ValueError, match='stale'):
        BackendOwner(200, SimpleNamespace(pid=100, poll=lambda: None), native=native, identity_reader=lambda pid: (pid, 1, "python.exe", "test-owner", ("backend",)), parent_chain=lambda _: [100])
    with pytest.raises(ValueError, match='Invalid'):
        BackendOwner(200, SimpleNamespace(pid=100, poll=lambda: 0), native=native, identity_reader=lambda pid: (pid, 1, "python.exe", "test-owner", ("backend",)), parent_chain=lambda _: [100])
    assert native.terminated == []


def test_early_identity_requires_inherited_nonce(monkeypatch, capsys):
    monkeypatch.delenv('PROCTORING_BACKEND_NONCE', raising=False)
    announce_backend_identity()
    assert capsys.readouterr().err == ''
    monkeypatch.setenv('PROCTORING_BACKEND_NONCE', 'f' * 64)
    announce_backend_identity()
    output = capsys.readouterr()
    assert output.out == ''
    record = json.loads(output.err.removeprefix(IDENTITY_PREFIX))
    assert record['nonce'] == 'f' * 64 and record['pid'] > 0


def test_frozen_supervisor_invokes_backend_entrypoint_not_itself(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    command = backend_command('C:/путь с пробелами/config.toml', 'pipe', 'token')
    assert command[1] == '--desktop-bridge'
    assert '--desktop-supervisor' not in command
    assert command[3] == 'C:/путь с пробелами/config.toml'


@pytest.mark.parametrize('field', range(5))
def test_forced_cleanup_refuses_changed_pid_time_image_owner_or_command(field):
    native = Native()
    identity = [200, 1., 'python.exe', 'test-owner', ('backend',)]
    owner = BackendOwner(200, SimpleNamespace(pid=100, poll=lambda: None), native=native,
                         parent_chain=lambda _: [100], identity_reader=lambda _: tuple(identity))
    identity[field] = 'changed'
    assert owner.terminate() is False
    assert native.terminated == []
    owner.close()


def test_forced_cleanup_refuses_unreadable_identity():
    native = Native()
    owner = BackendOwner(200, SimpleNamespace(pid=100, poll=lambda: None), native=native,
                         parent_chain=lambda _: [100], identity_reader=lambda _: (200, 1, 'python', 'owner', ('backend',)))
    def denied(_): raise PermissionError('private path')
    owner.identity_reader = denied
    assert owner.terminate() is False
    assert native.terminated == []
    owner.close()
