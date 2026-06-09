"""Pure-function tests for HDD/CDD numerical integration (no hass fixture)."""

from datetime import datetime, timedelta

from custom_components.heating_cooling_degree_days.calculations import (
    calculate_cdd_from_readings,
    calculate_hdd_from_readings,
)

BASE = datetime(2026, 1, 1, 0, 0, 0)


def _series(temps: list[float], step_hours: float = 1.0):
    """Build (timestamp, temp) readings spaced step_hours apart."""
    return [(BASE + timedelta(hours=i * step_hours), t) for i, t in enumerate(temps)]


def test_hdd_empty_readings_returns_zero():
    """Empty readings list returns 0 for HDD."""
    assert calculate_hdd_from_readings([], base_temp=18.0) == 0


def test_cdd_empty_readings_returns_zero():
    """Empty readings list returns 0 for CDD."""
    assert calculate_cdd_from_readings([], base_temp=18.0) == 0


def test_hdd_constant_below_base_full_day():
    """25 hourly readings at 10°C = 24h span with 8°C deficit below base 18°C gives 8.0 HDD."""
    # 25 hourly readings = 24h span at a constant 8°C deficit below base 18°C.
    readings = _series([10.0] * 25)
    # 24h = 1.0 day at 8 deg deficit → 8.0 degree-days.
    assert calculate_hdd_from_readings(readings, base_temp=18.0) == 8.0


def test_hdd_constant_above_base_is_zero():
    """Temperatures constantly above base produce 0 HDD."""
    readings = _series([22.0] * 25)
    assert calculate_hdd_from_readings(readings, base_temp=18.0) == 0.0


def test_cdd_constant_above_base_full_day():
    """24h at constant 6°C excess above base 18°C gives 6.0 CDD."""
    # 24h at constant 6°C excess above base 18°C → 6.0 degree-days.
    readings = _series([24.0] * 25)
    assert calculate_cdd_from_readings(readings, base_temp=18.0) == 6.0


def test_cdd_constant_below_base_is_zero():
    """Temperatures constantly below base produce 0 CDD."""
    readings = _series([10.0] * 25)
    assert calculate_cdd_from_readings(readings, base_temp=18.0) == 0.0


def test_hdd_trapezoidal_crossing_base():
    """Trapezoidal rule: two points 24h apart at base and 12°C below gives 6.0 HDD."""
    # Two points 24h apart: 18°C (zero deficit) → 6°C (12°C deficit).
    # Trapezoid avg deficit = (0 + 12) / 2 = 6 over 1.0 day → 6.0.
    readings = [(BASE, 18.0), (BASE + timedelta(hours=24), 6.0)]
    assert calculate_hdd_from_readings(readings, base_temp=18.0) == 6.0


def test_readings_are_sorted_before_integration():
    """Reversed input produces the same HDD as forward-ordered input."""
    # Same data, reversed input order, must give the identical result.
    forward = _series([10.0] * 25)
    reversed_input = list(reversed(forward))
    assert calculate_hdd_from_readings(
        reversed_input, base_temp=18.0
    ) == calculate_hdd_from_readings(forward, base_temp=18.0)
