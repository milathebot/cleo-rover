"""Tests for median ultrasonic filtering (rejects single-ping spikes)."""

from __future__ import annotations

from rover import peripherals


class FakeDistanceSensor:
    """gpiozero.DistanceSensor stand-in. `.distance` is meters, like the real one."""

    def __init__(self, meters_sequence):
        self._seq = list(meters_sequence)
        self._i = 0

    @property
    def distance(self):
        value = self._seq[min(self._i, len(self._seq) - 1)]
        self._i += 1
        return value


def _patch(monkeypatch, sensor):
    # Avoid importing real gpiozero and reuse the injected fake sensor singleton.
    monkeypatch.setattr(peripherals, "_import_gpiozero", lambda: (object, object))
    monkeypatch.setattr(peripherals, "_DISTANCE_SENSOR", sensor, raising=False)


def test_median_rejects_single_spike(monkeypatch):
    # cm reads: 50, 50, 5(spike), 50, 50 -> median 50, spike ignored.
    _patch(monkeypatch, FakeDistanceSensor([0.50, 0.50, 0.05, 0.50, 0.50]))
    reader = peripherals.FreenoveSensorReader(front_stop_distance_cm=18)
    assert reader.read_front_distance_cm(samples=5) == 50.0


def test_negative_reads_are_dropped(monkeypatch):
    # A negative (echo-timeout) read is dropped, not treated as a real distance.
    _patch(monkeypatch, FakeDistanceSensor([0.60, -0.01, 0.60]))
    reader = peripherals.FreenoveSensorReader(front_stop_distance_cm=18)
    assert reader.read_front_distance_cm(samples=3) == 60.0


def test_all_invalid_reads_return_none(monkeypatch):
    _patch(monkeypatch, FakeDistanceSensor([-0.01, -0.02, -0.03]))
    reader = peripherals.FreenoveSensorReader(front_stop_distance_cm=18)
    assert reader.read_front_distance_cm(samples=3) is None


def test_single_sample_is_the_fast_path(monkeypatch):
    # samples=1 (reflex path) returns the one read immediately.
    _patch(monkeypatch, FakeDistanceSensor([0.33]))
    reader = peripherals.FreenoveSensorReader(front_stop_distance_cm=18)
    assert reader.read_front_distance_cm() == 33.0
