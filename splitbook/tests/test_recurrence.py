from datetime import date

import pytest

from splitbook.domain.recurrence import advance_due


def test_monthly_end_of_month_clamps_no_drift():
    d = advance_due(date(2024, 1, 31), "monthly", 31)
    assert d == date(2024, 2, 29)  # 2024 是閏年
    d2 = advance_due(d, "monthly", 31)
    assert d2 == date(2024, 3, 31)  # clamp 後仍以 cycle_day 為準，不漂移


def test_monthly_common_year_february():
    d = advance_due(date(2023, 1, 31), "monthly", 31)
    assert d == date(2023, 2, 28)
    d2 = advance_due(d, "monthly", 31)
    assert d2 == date(2023, 3, 31)


def test_monthly_regular_day():
    d = advance_due(date(2024, 3, 15), "monthly", 15)
    assert d == date(2024, 4, 15)


def test_bimonthly_year_boundary():
    d = advance_due(date(2024, 11, 15), "bimonthly", 15)
    assert d == date(2025, 1, 15)


def test_yearly_leap_day_to_common_year():
    d = advance_due(date(2024, 2, 29), "yearly", 31)
    assert d == date(2025, 2, 28)


def test_invalid_cycle_raises():
    with pytest.raises(ValueError):
        advance_due(date(2024, 1, 1), "weekly", 1)


def test_invalid_cycle_day_zero_raises():
    with pytest.raises(ValueError):
        advance_due(date(2024, 1, 1), "monthly", 0)


def test_invalid_cycle_day_32_raises():
    with pytest.raises(ValueError):
        advance_due(date(2024, 1, 1), "monthly", 32)
