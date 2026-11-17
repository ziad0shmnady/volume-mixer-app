"""Per-application rows: silent apps, grouping, and remembered volumes."""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from mixer.models.audio import AppPreference, StreamInfo
from mixer.services.backend import MoveStream, SetMute, SetVolume
from mixer.services.fake_backend import FakeBackend
from mixer.viewmodel.mixer_viewmodel import MixerViewModel, _VOLUME_DEBOUNCE_S


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def saves() -> list[int]:
    return []


@pytest.fixture
def vm(backend: FakeBackend, saves: list[int]) -> MixerViewModel:
    view = MixerViewModel(backend=backend, on_app_preferences_changed=lambda: saves.append(1))
    view.start()
    yield view
    view.stop()


def _stream(index: int, app_key: str, *, volume: float = 1.0, media: str = "") -> StreamInfo:
    return StreamInfo(
        index=index,
        name=app_key.split(":")[-1].title(),
        media_name=media,
        icon_name=None,
        volume=volume,
        muted=False,
        sink_index=1,
        app_key=app_key,
    )


def _add_streams(backend: FakeBackend, vm: MixerViewModel, *streams: StreamInfo) -> None:
    snap = backend.snapshot
    backend.push_snapshot(replace(snap, streams=snap.streams + streams))


def _app(vm: MixerViewModel, key: str):
    app = vm.app_by_key(key)
    assert app is not None, key
    return app


def test_silent_apps_are_listed(vm: MixerViewModel) -> None:
    apps = {app.key: app for app in vm.apps()}
    assert set(apps) == {"bin:chrome", "bin:firefox", "snap:discord", "bin:slack"}
    assert not apps["snap:discord"].active
    assert apps["snap:discord"].subtitle == "Not playing"
    assert apps["snap:discord"].volume == pytest.approx(1.0)
    # Playing app: client + stream merged into one row.
    assert apps["bin:chrome"].stream_indices == (100,)
    assert apps["bin:chrome"].subtitle == "YouTube"


def test_apps_sorted_by_name(vm: MixerViewModel) -> None:
    assert [app.name for app in vm.apps()] == ["Discord", "Firefox", "Google Chrome", "Slack"]


def test_streams_of_one_app_share_a_row(vm: MixerViewModel, backend: FakeBackend) -> None:
    _add_streams(backend, vm, _stream(102, "bin:chrome", volume=0.3, media="Meet"))
    chrome = _app(vm, "bin:chrome")
    assert chrome.stream_indices == (100, 102)
    assert chrome.subtitle == "2 streams"
    assert chrome.volume == pytest.approx(0.8)  # loudest stream
    assert len(vm.apps()) == 4


def test_set_app_volume_moves_every_stream(vm: MixerViewModel, backend: FakeBackend) -> None:
    _add_streams(backend, vm, _stream(102, "bin:chrome", volume=0.3))
    backend.clear_commands()
    vm.set_app_volume("bin:chrome", 0.5)
    time.sleep(_VOLUME_DEBOUNCE_S + 0.02)
    vm.flush_pending()
    targets = {c.index for c in backend.commands if isinstance(c, SetVolume)}
    assert targets == {100, 102}
    assert _app(vm, "bin:chrome").volume == pytest.approx(0.5)


def test_silent_app_volume_is_remembered(
    vm: MixerViewModel, backend: FakeBackend, saves: list[int]
) -> None:
    backend.clear_commands()
    vm.set_app_volume("snap:discord", 0.3)
    vm.set_app_mute("snap:discord", True)
    assert backend.commands == []  # nothing to send yet
    discord = _app(vm, "snap:discord")
    assert discord.volume == pytest.approx(0.3)
    assert discord.muted is True
    assert vm.app_preferences["snap:discord"] == AppPreference(volume=0.3, muted=True)
    assert saves


def test_remembered_volume_applied_when_app_starts_playing(
    vm: MixerViewModel, backend: FakeBackend
) -> None:
    vm.set_app_volume("snap:discord", 0.3)
    vm.set_app_mute("snap:discord", True)
    backend.clear_commands()

    _add_streams(backend, vm, _stream(200, "snap:discord", volume=1.0))

    assert any(
        isinstance(c, SetVolume) and c.index == 200 and c.volume == pytest.approx(0.3)
        for c in backend.commands
    )
    assert any(isinstance(c, SetMute) and c.index == 200 and c.muted for c in backend.commands)
    discord = _app(vm, "snap:discord")
    assert discord.active
    assert discord.volume == pytest.approx(0.3)
    assert discord.muted is True


def test_remembered_volume_respects_overamp_limit(
    vm: MixerViewModel, backend: FakeBackend
) -> None:
    vm.app_preferences["snap:discord"] = AppPreference(volume=1.4)
    backend.clear_commands()
    _add_streams(backend, vm, _stream(200, "snap:discord", volume=0.5))
    volumes = [c.volume for c in backend.commands if isinstance(c, SetVolume)]
    assert volumes == [pytest.approx(1.0)]


def test_streams_present_at_startup_are_not_overridden(backend: FakeBackend) -> None:
    view = MixerViewModel(
        backend=backend,
        app_preferences={"bin:chrome": AppPreference(volume=0.2)},
    )
    view.start()
    try:
        assert not any(isinstance(c, SetVolume) for c in backend.commands)
        # The remembered value follows what is actually playing.
        assert view.app_preferences["bin:chrome"].volume == pytest.approx(0.8)
    finally:
        view.stop()


def test_external_change_updates_remembered_volume(
    vm: MixerViewModel, backend: FakeBackend, saves: list[int]
) -> None:
    vm.app_preferences["bin:chrome"] = AppPreference(volume=0.8)
    saves.clear()
    snap = backend.snapshot
    backend.push_snapshot(
        replace(
            snap,
            streams=tuple(replace(s, volume=0.45) if s.index == 100 else s for s in snap.streams),
        )
    )
    assert vm.app_preferences["bin:chrome"].volume == pytest.approx(0.45)
    assert saves


def test_reconnect_does_not_reapply_to_existing_streams(
    vm: MixerViewModel, backend: FakeBackend
) -> None:
    vm.app_preferences["bin:firefox"] = AppPreference(volume=0.9)
    backend.set_connected(False)
    backend.clear_commands()
    backend.set_connected(True)
    assert not any(isinstance(c, SetVolume) for c in backend.commands)


def test_move_app_moves_every_stream(vm: MixerViewModel, backend: FakeBackend) -> None:
    _add_streams(backend, vm, _stream(102, "bin:chrome"))
    backend.clear_commands()
    vm.move_app("bin:chrome", 2)
    moved = {c.stream_index for c in backend.commands if isinstance(c, MoveStream)}
    assert moved == {100, 102}
    assert _app(vm, "bin:chrome").sink_index == 2


def test_app_goes_idle_and_keeps_its_row(vm: MixerViewModel, backend: FakeBackend) -> None:
    vm.set_app_volume("bin:firefox", 0.6)
    snap = backend.snapshot
    backend.push_snapshot(replace(snap, streams=tuple(s for s in snap.streams if s.index != 101)))
    firefox = _app(vm, "bin:firefox")
    assert not firefox.active
    assert firefox.volume == pytest.approx(0.6)
    assert firefox.subtitle == "Not playing"


def test_silent_app_shows_last_played_volume(vm: MixerViewModel, backend: FakeBackend) -> None:
    # Firefox plays at 40% (no preference set in the mixer), then stops.
    snap = backend.snapshot
    backend.push_snapshot(replace(snap, streams=tuple(s for s in snap.streams if s.index != 101)))
    firefox = _app(vm, "bin:firefox")
    assert not firefox.active
    assert firefox.volume == pytest.approx(0.4)
    assert "bin:firefox" not in vm.app_preferences  # display only, not enforced
