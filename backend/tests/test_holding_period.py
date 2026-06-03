"""Tests for the calendar-based 10-year hankintameno-olettama boundary.

The deemed acquisition cost is 40 % of proceeds once a lot has been held at
least ten years, otherwise 20 %. The legal boundary is calendar-based, so a
365.25-day approximation must NOT be used (it can misclassify by ~1 day).
"""

from datetime import date

from app.services.tax import held_at_least_10_years, ten_year_anniversary


def test_anniversary_is_same_calendar_date_plus_ten_years():
    assert ten_year_anniversary(date(2014, 3, 15)) == date(2024, 3, 15)


def test_exact_anniversary_counts_as_ten_years_held():
    lot = date(2014, 6, 3)
    # Sold exactly on the anniversary -> held >= 10 years -> 40 % applies.
    assert held_at_least_10_years(lot, date(2024, 6, 3)) is True
    # One day before -> still < 10 years -> 20 % applies.
    assert held_at_least_10_years(lot, date(2024, 6, 2)) is False


def test_leap_day_lot_falls_back_to_feb_28_in_non_leap_year():
    # 2016-02-29 + 10y -> 2026 is not a leap year, so Feb 28.
    assert ten_year_anniversary(date(2016, 2, 29)) == date(2026, 2, 28)
    assert held_at_least_10_years(date(2016, 2, 29), date(2026, 2, 28)) is True


def test_day_count_approximation_would_misclassify_but_calendar_does_not():
    # A lot held a hair under 10 calendar years can be near the 3652.5-day
    # (10 * 365.25) mark yet still be < 10 calendar years. The calendar test
    # must classify it as NOT yet 10 years.
    lot = date(2014, 1, 1)
    sell = date(2023, 12, 31)  # < 10 calendar years
    assert (sell - lot).days / 365.25 >= 9.99  # close to the boundary
    assert held_at_least_10_years(lot, sell) is False
