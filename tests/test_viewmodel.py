"""Tests for MixerViewModel sorting, diffing, debounce, and feedback guards."""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from mixer.models.audio import AudioSnapshot, DeviceInfo, StreamInfo
from mixer.services.backend import MoveStream, SetDefaultDevice, SetMute, SetVolume
from mixer.services.fake_backend import FakeBackend, default_snapshot
from mixer.viewmodel.mixer_viewmodel import MixerViewModel, _VOLUME_DEBOUNCE_S


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def vm(backend: FakeBackend) -> MixerViewModel:
    view = MixerViewModel(backend=backend)
    view.start()
    yield view
    view.stop()


def test_initial_snapshot_loaded(vm: MixerViewModel) -> None:
    assert vm.connected
    assert len(vm.sorted_streams()) == 2
    assert vm.default_sink() is not None
    assert vm.default_source() is not None


def test_streams_sorted_by_name(vm: MixerViewModel, backend: FakeBackend) -> None:
    snap = default_snapshot()
    streams = (
        StreamInfo(
            index=200,
            name="zeta",
            media_name="",
            icon_name=None,
            volume=0.5,
            muted=False,
            sink_index=1,
        ),
        StreamInfo(
            index=201,
            name="Alpha",
            media_name="",
            icon_name=None,
            volume=0.5,
            muted=False,
            sink_index=1,
        ),
        StreamInfo(
            index=202,
            name="alpha",
            media_name="",
            icon_name=None,
            volume=0.5,
            muted=False,
            sink_index=1,
        ),
    )
    backend.push_snapshot(replace(snap, streams=streams))
    names = [s.name for s in vm.sorted_streams()]
    assert names == ["Alpha", "alpha", "zeta"]


def test_stream_added_and_removed(vm: MixerViewModel, backend: FakeBackend) -> None:
    assert vm.stream_keys() == {100, 101}
    snap = vm.snapshot
    new_stream = StreamInfo(
        index=300,
        name="VLC",
        media_name="Movie",
        icon_name="vlc",
        volume=0.9,
        muted=False,
        sink_index=1,
    )
    backend.push_snapshot(replace(snap, streams=snap.streams + (new_stream,)))
    assert 300 in vm.stream_keys()

    backend.push_snapshot(replace(vm.snapshot, streams=snap.streams))
    assert 300 not in vm.stream_keys()
    assert vm.stream_keys() == {100, 101}


def test_set_mute_dispatches_command(vm: MixerViewModel, backend: FakeBackend) -> None:
    backend.clear_commands()
    vm.set_mute("stream", 100, True)
    assert vm.stream_by_index(100) is not None
    assert vm.stream_by_index(100).muted is True
    assert any(
        isinstance(c, SetMute) and c.target == "stream" and c.index == 100 and c.muted
        for c in backend.commands
    )


def test_move_stream_dispatches_command(vm: MixerViewModel, backend: FakeBackend) -> None:
    backend.clear_commands()
    vm.move_stream(100, 2)
    assert vm.stream_by_index(100).sink_index == 2
    assert any(
        isinstance(c, MoveStream) and c.stream_index == 100 and c.sink_index == 2
        for c in backend.commands
    )


def test_set_default_device(vm: MixerViewModel, backend: FakeBackend) -> None:
    backend.clear_commands()
    vm.set_default_device("sink", "alsa_output.headphones")
    assert vm.snapshot.default_sink_name == "alsa_output.headphones"
    assert vm.default_sink() is not None
    assert vm.default_sink().name == "alsa_output.headphones"
    assert any(
        isinstance(c, SetDefaultDevice)
        and c.kind == "sink"
        and c.name == "alsa_output.headphones"
        for c in backend.commands
    )


def test_volume_debounce_emits_single_command(
    vm: MixerViewModel, backend: FakeBackend
) -> None:
    backend.clear_commands()
    vm.set_volume("stream", 100, 0.1)
    vm.set_volume("stream", 100, 0.2)
    vm.set_volume("stream", 100, 0.3)
    # Not flushed yet
    assert not any(isinstance(c, SetVolume) for c in backend.commands)

    time.sleep(_VOLUME_DEBOUNCE_S + 0.02)
    flushed = vm.flush_pending()
    assert flushed == 1
    volume_cmds = [c for c in backend.commands if isinstance(c, SetVolume)]
    assert len(volume_cmds) == 1
    assert volume_cmds[0].volume == pytest.approx(0.3)


def test_immediate_volume_bypasses_debounce(
    vm: MixerViewModel, backend: FakeBackend
) -> None:
    backend.clear_commands()
    vm.set_volume("stream", 100, 0.55, immediate=True)
    volume_cmds = [c for c in backend.commands if isinstance(c, SetVolume)]
    assert len(volume_cmds) == 1
    assert volume_cmds[0].volume == pytest.approx(0.55)


def test_overamplification_clamp(vm: MixerViewModel) -> None:
    vm.set_overamplification(False)
    vm.set_volume("stream", 100, 1.4, immediate=True)
    assert vm.stream_by_index(100).volume == pytest.approx(1.0)

    vm.set_overamplification(True)
    vm.set_volume("stream", 100, 1.4, immediate=True)
    assert vm.stream_by_index(100).volume == pytest.approx(1.4)


def test_feedback_guard_keeps_local_volume_during_drag(
    vm: MixerViewModel, backend: FakeBackend
) -> None:
    backend.clear_commands()
    vm.set_volume("stream", 100, 0.25)
    # Incoming snapshot with different volume should be ignored while guard active.
    incoming = replace(
        vm.snapshot,
        streams=tuple(
            replace(s, volume=0.99) if s.index == 100 else s for s in vm.snapshot.streams
        ),
        generation=vm.snapshot.generation + 1,
    )
    # Simulate backend pushing without going through FakeBackend.apply
    vm._on_snapshot(incoming)  # noqa: SLF001
    assert vm.stream_by_index(100).volume == pytest.approx(0.25)


def test_disconnect_and_reconnect(vm: MixerViewModel, backend: FakeBackend) -> None:
    assert vm.connected
    backend.set_connected(False)
    assert not vm.connected
    assert vm.sorted_streams() == ()

    backend.set_connected(True)
    assert vm.connected
    assert len(vm.sorted_streams()) >= 1


def test_listener_notified(vm: MixerViewModel) -> None:
    calls: list[int] = []
    vm.add_listener(lambda _vm: calls.append(1))
    vm.set_mute("sink", 1, True)
    assert calls
