"""Pure domain logic for Heating and Cooling Degree Days.

This package contains only pure functions with no external dependencies.
It can be tested independently and reused outside of Home Assistant.
"""

from .calculations import (
    calculate_cdd_from_readings,
    calculate_hdd_from_readings,
)

__all__ = [
    "calculate_hdd_from_readings",
    "calculate_cdd_from_readings",
]
