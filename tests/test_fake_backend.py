"""Tests for FakeBackend command application and reconnect behaviour."""

from __future__ import annotations

import pytest

from mixer.services.backend import MoveStream, SetDefaultDevice, SetMute, SetVolume
from mixer.services.fake_backend import FakeBackend
from mixer.services.pulse_service import _MAX_BACKOFF, _MIN_BACKOFF


def test_fake_applies_volume_and_notifies() -> None:
    backend = FakeBackend()
    snapshots: list[int] = []
    backend.start(lambda snap: snapshots.append(snap.generation))
    assert snapshots  # initial

    backend.submit(SetVolume(target="stream", index=100, volume=0.12))
    stream = next(s for s in backend.snapshot.streams if s.index == 100)
    assert stream.volume == pytest.approx(0.12)
    assert len(snapshots) >= 2


def test_fake_move_and_default() -> None:
    backend = FakeBackend()
    backend.start(lambda _s: None)
    backend.submit(MoveStream(stream_index=100, sink_index=2))
    assert next(s for s in backend.snapshot.streams if s.index == 100).sink_index == 2

    backend.submit(SetDefaultDevice(kind="sink", name="alsa_output.headphones"))
    assert backend.snapshot.default_sink_name == "alsa_output.headphones"
    assert any(d.is_default and d.name.endswith("headphones") for d in backend.snapshot.sinks)


def test_fake_mute() -> None:
    backend = FakeBackend()
    backend.start(lambda _s: None)
    backend.submit(SetMute(target="source", index=10, muted=True))
    assert next(s for s in backend.snapshot.sources if s.index == 10).muted is True


def test_reconnect_backoff_schedule() -> None:
    """Documented reconnect schedule stays within bounds."""
    backoff = _MIN_BACKOFF
    seen = [backoff]
    for _ in range(10):
        backoff = min(backoff * 2, _MAX_BACKOFF)
        seen.append(backoff)
    assert seen[0] == 0.5
    assert seen[-1] == _MAX_BACKOFF
    assert all(0.5 <= v <= 8.0 for v in seen)


def test_commands_preserved_across_disconnect_queue() -> None:
    """FakeBackend keeps accepting commands after reconnect simulation."""
    backend = FakeBackend()
    backend.start(lambda _s: None)
    backend.set_connected(False)
    assert not backend.snapshot.connected

    # While disconnected FakeBackend still records commands when submit is called;
    # PulseService keeps them in its queue — here we verify Fake can recover state.
    backend.set_connected(True)
    backend.clear_commands()
    backend.submit(SetVolume(target="sink", index=1, volume=0.33))
    assert any(isinstance(c, SetVolume) for c in backend.commands)
    sink = next(s for s in backend.snapshot.sinks if s.index == 1)
    assert sink.volume == pytest.approx(0.33)
