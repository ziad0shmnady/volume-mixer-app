"""Tests for volume conversion helpers."""

from __future__ import annotations

import pytest

from mixer.models.audio import VolumeMath


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-1.0, 0.0),
        (0.0, 0.0),
        (0.5, 0.5),
        (1.0, 1.0),
        (1.5, 1.5),
        (2.0, 1.5),
    ],
)
def test_clamp(value: float, expected: float) -> None:
    assert VolumeMath.clamp(value) == expected


@pytest.mark.parametrize(
    ("volume", "percent"),
    [
        (0.0, 0),
        (0.51, 51),
        (1.0, 100),
        (1.5, 150),
    ],
)
def test_to_percent(volume: float, percent: int) -> None:
    assert VolumeMath.to_percent(volume) == percent


def test_from_percent_respects_maximum() -> None:
    assert VolumeMath.from_percent(150, maximum=1.0) == 1.0
    assert VolumeMath.from_percent(150, maximum=1.5) == 1.5
    assert VolumeMath.from_percent(50) == pytest.approx(0.5)


def test_format_percent() -> None:
    assert VolumeMath.format_percent(0.82) == "82%"
