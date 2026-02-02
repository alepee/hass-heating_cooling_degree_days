"""Tests for degree days calculation functions (domain logic)."""

import pytest
from datetime import datetime, timedelta

from degree_days import (
    calculate_hdd_from_readings,
    calculate_cdd_from_readings,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def base_time() -> datetime:
    """Return a base datetime for test readings."""
    return datetime(2024, 1, 15, 0, 0, 0)


def make_constant_readings(
    base_time: datetime, temperature: float, hours: int = 24
) -> list[tuple[datetime, float]]:
    """Generate readings with constant temperature over a period."""
    return [
        (base_time + timedelta(hours=h), temperature)
        for h in range(hours + 1)
    ]


def make_readings_from_hourly_temps(
    base_time: datetime, hourly_temps: list[float]
) -> list[tuple[datetime, float]]:
    """Generate readings from a list of hourly temperatures."""
    return [
        (base_time + timedelta(hours=h), temp)
        for h, temp in enumerate(hourly_temps)
    ]


# =============================================================================
# Tests: calculate_hdd_from_readings - Basic Cases
# =============================================================================


class TestHDDBasicCases:
    """Basic test cases for HDD calculation."""

    def test_empty_readings_returns_zero(self):
        """Empty readings should return 0 HDD."""
        assert calculate_hdd_from_readings([], base_temp=18.0) == 0

    def test_single_reading_returns_zero(self):
        """A single reading cannot form an interval, should return 0."""
        readings = [(datetime(2024, 1, 1, 0, 0), 10.0)]
        assert calculate_hdd_from_readings(readings, base_temp=18.0) == 0

    def test_two_readings_same_temperature(self, base_time):
        """Two readings at same temp should calculate correctly."""
        readings = [
            (base_time, 10.0),
            (base_time + timedelta(hours=24), 10.0),
        ]
        # 1 day at 10°C with base 18°C = 8 HDD
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        assert result == pytest.approx(8.0, abs=0.1)


class TestHDDConstantTemperature:
    """Test HDD with constant temperatures."""

    def test_constant_temp_below_base(self, base_time):
        """Constant temperature below base should accumulate HDD."""
        readings = make_constant_readings(base_time, temperature=15.0)
        # 1 day at 15°C with base 18°C = 3 HDD
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        assert result == pytest.approx(3.0, abs=0.1)

    def test_constant_temp_above_base(self, base_time):
        """Constant temperature above base should return 0 HDD."""
        readings = make_constant_readings(base_time, temperature=25.0)
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        assert result == 0

    def test_constant_temp_at_base(self, base_time):
        """Temperature exactly at base should return 0 HDD."""
        readings = make_constant_readings(base_time, temperature=18.0)
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        assert result == 0

    def test_constant_negative_temperature(self, base_time):
        """Negative temperatures should be handled correctly."""
        readings = make_constant_readings(base_time, temperature=-5.0)
        # 1 day at -5°C with base 18°C = 23 HDD
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        assert result == pytest.approx(23.0, abs=0.1)

    def test_extreme_cold(self, base_time):
        """Extreme cold temperatures should calculate large HDD."""
        readings = make_constant_readings(base_time, temperature=-20.0)
        # 1 day at -20°C with base 18°C = 38 HDD
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        assert result == pytest.approx(38.0, abs=0.1)


class TestHDDVaryingTemperature:
    """Test HDD with varying temperatures."""

    def test_temperature_crosses_base_once(self, base_time):
        """Temperature crossing base once during the day."""
        # 12h at 10°C, then 12h at 25°C
        readings = [
            (base_time, 10.0),
            (base_time + timedelta(hours=12), 10.0),
            (base_time + timedelta(hours=12, minutes=1), 25.0),
            (base_time + timedelta(hours=24), 25.0),
        ]
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # ~0.5 day at 8°C deficit = ~4 HDD
        assert result == pytest.approx(4.0, abs=0.3)

    def test_linear_temperature_decrease(self, base_time):
        """Linear temperature decrease throughout the day."""
        # From 18°C to 8°C over 24 hours
        readings = [
            (base_time + timedelta(hours=h), 18.0 - (h * 10 / 24))
            for h in range(25)
        ]
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # Average deficit over the day: ~5°C -> ~5 HDD
        assert result == pytest.approx(5.0, abs=0.3)

    def test_diurnal_cycle(self, base_time):
        """Simulate a typical day/night temperature cycle."""
        # Night: cold, Day: warmer
        hourly_temps = [
            5, 4, 3, 3, 4, 5,       # 00:00-05:00 (cold night)
            7, 9, 12, 15, 17, 19,   # 06:00-11:00 (warming up)
            20, 21, 21, 20, 18, 16, # 12:00-17:00 (warm afternoon)
            14, 12, 10, 8, 7, 6, 5  # 18:00-24:00 (cooling down)
        ]
        readings = make_readings_from_hourly_temps(base_time, hourly_temps)
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # Most of the day below 18°C, expect significant HDD
        assert result > 5.0
        assert result < 15.0


# =============================================================================
# Tests: calculate_cdd_from_readings - Basic Cases
# =============================================================================


class TestCDDBasicCases:
    """Basic test cases for CDD calculation."""

    def test_empty_readings_returns_zero(self):
        """Empty readings should return 0 CDD."""
        assert calculate_cdd_from_readings([], base_temp=18.0) == 0

    def test_single_reading_returns_zero(self):
        """A single reading cannot form an interval, should return 0."""
        readings = [(datetime(2024, 1, 1, 0, 0), 30.0)]
        assert calculate_cdd_from_readings(readings, base_temp=18.0) == 0


class TestCDDConstantTemperature:
    """Test CDD with constant temperatures."""

    def test_constant_temp_above_base(self, base_time):
        """Constant temperature above base should accumulate CDD."""
        readings = make_constant_readings(base_time, temperature=25.0)
        # 1 day at 25°C with base 18°C = 7 CDD
        result = calculate_cdd_from_readings(readings, base_temp=18.0)
        assert result == pytest.approx(7.0, abs=0.1)

    def test_constant_temp_below_base(self, base_time):
        """Constant temperature below base should return 0 CDD."""
        readings = make_constant_readings(base_time, temperature=10.0)
        result = calculate_cdd_from_readings(readings, base_temp=18.0)
        assert result == 0

    def test_constant_temp_at_base(self, base_time):
        """Temperature exactly at base should return 0 CDD."""
        readings = make_constant_readings(base_time, temperature=18.0)
        result = calculate_cdd_from_readings(readings, base_temp=18.0)
        assert result == 0

    def test_extreme_heat(self, base_time):
        """Extreme heat should calculate large CDD."""
        readings = make_constant_readings(base_time, temperature=40.0)
        # 1 day at 40°C with base 18°C = 22 CDD
        result = calculate_cdd_from_readings(readings, base_temp=18.0)
        assert result == pytest.approx(22.0, abs=0.1)

    def test_negative_temp_returns_zero_cdd(self, base_time):
        """Negative temperatures should return 0 CDD."""
        readings = make_constant_readings(base_time, temperature=-10.0)
        result = calculate_cdd_from_readings(readings, base_temp=18.0)
        assert result == 0


class TestCDDVaryingTemperature:
    """Test CDD with varying temperatures."""

    def test_hot_summer_day_cycle(self, base_time):
        """Simulate a hot summer day with diurnal cycle."""
        # Night: warm, Day: hot
        hourly_temps = [
            22, 21, 20, 19, 19, 20,  # 00:00-05:00 (warm night)
            22, 25, 28, 31, 33, 35,  # 06:00-11:00 (heating up)
            36, 37, 37, 36, 34, 32,  # 12:00-17:00 (hot afternoon)
            30, 28, 26, 24, 23, 22, 22  # 18:00-24:00 (cooling)
        ]
        readings = make_readings_from_hourly_temps(base_time, hourly_temps)
        result = calculate_cdd_from_readings(readings, base_temp=18.0)
        # All day above 18°C, expect significant CDD
        assert result > 8.0
        assert result < 20.0


# =============================================================================
# Tests: Edge Cases and Data Quality
# =============================================================================


class TestEdgeCases:
    """Test edge cases for both HDD and CDD."""

    def test_very_short_interval_skipped(self, base_time):
        """Intervals shorter than 1 minute should be skipped."""
        readings = [
            (base_time, 10.0),
            (base_time + timedelta(seconds=30), 10.0),  # Too short
            (base_time + timedelta(seconds=45), 10.0),  # Too short
            (base_time + timedelta(hours=24), 10.0),
        ]
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # Should still calculate correctly, ignoring short intervals
        assert result == pytest.approx(8.0, abs=0.1)

    def test_unsorted_readings_are_sorted(self, base_time):
        """Readings provided out of order should be sorted."""
        readings = [
            (base_time + timedelta(hours=24), 10.0),
            (base_time, 10.0),
            (base_time + timedelta(hours=12), 10.0),
        ]
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        assert result == pytest.approx(8.0, abs=0.1)

    def test_result_rounded_to_one_decimal(self, base_time):
        """Results should be rounded to 1 decimal place."""
        readings = [
            (base_time, 15.333),
            (base_time + timedelta(hours=24), 15.333),
        ]
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # Check that result has at most 1 decimal place
        assert result == round(result, 1)

    def test_partial_day_readings(self, base_time):
        """Readings covering less than 24 hours."""
        # Only 12 hours of data
        readings = make_constant_readings(base_time, temperature=10.0, hours=12)
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # 0.5 day at 10°C with base 18°C = 4 HDD
        assert result == pytest.approx(4.0, abs=0.1)

    def test_sparse_readings(self, base_time):
        """Readings with large gaps (e.g., every 6 hours)."""
        readings = [
            (base_time, 10.0),
            (base_time + timedelta(hours=6), 12.0),
            (base_time + timedelta(hours=12), 14.0),
            (base_time + timedelta(hours=18), 12.0),
            (base_time + timedelta(hours=24), 10.0),
        ]
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # Average around 6-8°C deficit over the day
        assert result > 5.0
        assert result < 10.0


class TestFahrenheitSupport:
    """Test calculations work correctly with Fahrenheit values."""

    def test_hdd_fahrenheit_mild_day(self, base_time):
        """HDD calculation with typical Fahrenheit values."""
        readings = make_constant_readings(base_time, temperature=50.0)
        # 1 day at 50°F with base 65°F = 15 HDD
        result = calculate_hdd_from_readings(readings, base_temp=65.0)
        assert result == pytest.approx(15.0, abs=0.1)

    def test_cdd_fahrenheit_hot_day(self, base_time):
        """CDD calculation with typical Fahrenheit values."""
        readings = make_constant_readings(base_time, temperature=85.0)
        # 1 day at 85°F with base 65°F = 20 CDD
        result = calculate_cdd_from_readings(readings, base_temp=65.0)
        assert result == pytest.approx(20.0, abs=0.1)

    def test_hdd_fahrenheit_freezing(self, base_time):
        """HDD calculation with freezing Fahrenheit values."""
        readings = make_constant_readings(base_time, temperature=20.0)
        # 1 day at 20°F with base 65°F = 45 HDD
        result = calculate_hdd_from_readings(readings, base_temp=65.0)
        assert result == pytest.approx(45.0, abs=0.1)


# =============================================================================
# Tests: Trapezoidal Integration Accuracy
# =============================================================================


class TestTrapezoidalIntegration:
    """Test the accuracy of trapezoidal numerical integration."""

    def test_linear_increase_integration(self, base_time):
        """Linear temperature increase should integrate correctly."""
        # Temperature increases linearly from 10°C to 20°C over 24h
        readings = [
            (base_time + timedelta(hours=h), 10.0 + (h * 10 / 24))
            for h in range(25)
        ]
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # Average temp = 15°C, but only part below 18°C contributes
        # First ~19.2 hours below base, with decreasing deficit
        assert result > 2.0
        assert result < 5.0

    def test_symmetric_temperature_curve(self, base_time):
        """Symmetric temperature curve (parabola-like)."""
        # Coldest at midnight and noon, warmest at 6am and 6pm
        import math
        readings = [
            (base_time + timedelta(hours=h), 15.0 + 5 * math.sin(h * math.pi / 12))
            for h in range(25)
        ]
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # Temperature oscillates 10-20°C, averaging 15°C
        # Significant time below 18°C
        assert result > 1.0
        assert result < 5.0


# =============================================================================
# Tests: Real-World Scenarios
# =============================================================================


class TestRealWorldScenarios:
    """Test with realistic temperature patterns."""

    def test_winter_day_france(self, base_time):
        """Typical winter day in France (January)."""
        hourly_temps = [
            2, 1, 0, 0, -1, 0,      # 00:00-05:00
            1, 2, 4, 6, 8, 9,       # 06:00-11:00
            10, 10, 9, 8, 6, 4,     # 12:00-17:00
            3, 2, 2, 1, 1, 1, 2     # 18:00-24:00
        ]
        readings = make_readings_from_hourly_temps(base_time, hourly_temps)
        result = calculate_hdd_from_readings(readings, base_temp=18.0)
        # Cold day, expect high HDD (around 14-15)
        assert result > 12.0
        assert result < 18.0

    def test_summer_day_france(self, base_time):
        """Typical summer day in France (July)."""
        hourly_temps = [
            18, 17, 16, 16, 17, 18,  # 00:00-05:00
            20, 23, 26, 28, 30, 32,  # 06:00-11:00
            33, 34, 34, 33, 31, 29,  # 12:00-17:00
            27, 25, 23, 21, 20, 19, 18  # 18:00-24:00
        ]
        readings = make_readings_from_hourly_temps(base_time, hourly_temps)

        hdd = calculate_hdd_from_readings(readings, base_temp=18.0)
        cdd = calculate_cdd_from_readings(readings, base_temp=18.0)

        # Hot day: low HDD, significant CDD
        assert hdd < 1.0
        assert cdd > 5.0

    def test_spring_transition_day(self, base_time):
        """Spring day with temperature crossing base multiple times."""
        hourly_temps = [
            12, 11, 10, 10, 11, 12,  # 00:00-05:00 (below base)
            14, 16, 18, 20, 21, 22,  # 06:00-11:00 (crossing base)
            23, 23, 22, 21, 19, 17,  # 12:00-17:00 (above then crossing)
            15, 14, 13, 12, 12, 12, 12  # 18:00-24:00 (below base)
        ]
        readings = make_readings_from_hourly_temps(base_time, hourly_temps)

        hdd = calculate_hdd_from_readings(readings, base_temp=18.0)
        cdd = calculate_cdd_from_readings(readings, base_temp=18.0)

        # Both HDD and CDD should have some value
        assert hdd > 2.0
        assert cdd > 1.0
