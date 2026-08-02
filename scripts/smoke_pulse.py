#!/usr/bin/env python3
"""Smoke-test PulseService against the live audio server (no GUI)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mixer.models.audio import AudioSnapshot  # noqa: E402
from mixer.services.backend import SetMute, SetVolume  # noqa: E402
from mixer.services.pulse_service import PulseService  # noqa: E402


def main() -> int:
    snapshots: list[AudioSnapshot] = []
    ready = threading.Event()

    def on_snap(snap: AudioSnapshot) -> None:
        snapshots.append(snap)
        if snap.connected:
            ready.set()

    svc = PulseService(client_name="mixer-smoke")
    svc.start(on_snap)
    if not ready.wait(timeout=5.0):
        print("FAIL: no connected snapshot within 5s")
        svc.stop()
        return 1

    snap = snapshots[-1]
    print(f"connected={snap.connected} sinks={len(snap.sinks)} "
          f"sources={len(snap.sources)} streams={len(snap.streams)}")
    print(f"default_sink={snap.default_sink_name}")
    for s in snap.sinks:
        mark = "*" if s.is_default else " "
        print(f"  {mark} sink#{s.index} {s.description!r} vol={s.volume:.2f} mute={s.muted}")
    for s in snap.streams:
        print(f"    stream#{s.index} {s.name!r} -> sink#{s.sink_index} vol={s.volume:.2f}")

    if not snap.sinks:
        print("FAIL: no sinks")
        svc.stop()
        return 1

    default = next((s for s in snap.sinks if s.is_default), snap.sinks[0])
    original = default.volume
    target = 0.37 if abs(original - 0.37) > 0.05 else 0.63

    before = len(snapshots)
    svc.submit(SetVolume(target="sink", index=default.index, volume=target))
    # Wait for echo snapshot
    deadline = time.time() + 3.0
    echoed = False
    while time.time() < deadline:
        if len(snapshots) > before:
            latest = snapshots[-1]
            cur = next((s for s in latest.sinks if s.index == default.index), None)
            if cur and abs(cur.volume - target) < 0.05:
                echoed = True
                print(f"OK: volume set {original:.2f} -> {cur.volume:.2f}")
                break
        time.sleep(0.05)

    # Restore
    svc.submit(SetVolume(target="sink", index=default.index, volume=original))
    time.sleep(0.3)

    if not echoed:
        print("FAIL: volume change not reflected in snapshot")
        svc.stop()
        return 1

    # Mute round-trip (restore after)
    svc.submit(SetMute(target="sink", index=default.index, muted=True))
    time.sleep(0.2)
    svc.submit(SetMute(target="sink", index=default.index, muted=default.muted))
    time.sleep(0.2)

    svc.stop()
    print("OK: PulseService smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
