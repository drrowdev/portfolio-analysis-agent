"""Tests for the pure yfinance dividend-recognition decision logic."""

from datetime import date, timedelta
from decimal import Decimal

from app.services.dividend_logic import (
    DEDUP_WINDOW_DAYS,
    LOOKBACK_DAYS,
    PAYMENT_DELAY_DAYS,
    dedup_window,
    estimate_pay_date,
    recognition_decision,
)


def test_estimate_pay_date_adds_payment_delay():
    # 2026-05-21 + 21 days = 2026-06-11
    assert estimate_pay_date(date(2026, 5, 21)) == date(2026, 6, 11)
    assert PAYMENT_DELAY_DAYS == 21


def test_declared_but_unpaid_dividend_is_not_recognized():
    # MSFT 2026 Q2: ex-date 2026-05-21, pay date 2026-06-11.
    # On 2026-06-04 it has NOT been paid yet -> must be skipped.
    ex = date(2026, 5, 21)
    today = date(2026, 6, 4)
    assert recognition_decision(ex, today, Decimal("0.91")) is None


def test_dividend_recognized_on_or_after_estimated_pay_date():
    # The same dividend, checked on 2026-06-12 (the daily run after pay date),
    # should now be recognized and dated at the estimated pay date 2026-06-11.
    ex = date(2026, 5, 21)
    today = date(2026, 6, 12)
    result = recognition_decision(ex, today, Decimal("0.91"))
    assert result == date(2026, 6, 11)


def test_dividend_recognized_exactly_on_estimated_pay_date():
    ex = date(2026, 5, 21)
    today = date(2026, 6, 11)  # == estimated pay date
    assert recognition_decision(ex, today, Decimal("0.91")) == date(2026, 6, 11)


def test_zero_or_negative_amount_is_skipped():
    ex = date(2026, 5, 1)
    today = date(2026, 6, 12)
    assert recognition_decision(ex, today, Decimal("0")) is None
    assert recognition_decision(ex, today, Decimal("-1.5")) is None


def test_old_dividend_outside_lookback_is_skipped():
    today = date(2026, 6, 12)
    # ex-date well beyond the lookback window -> skipped even though long paid.
    old_ex = date(2026, 1, 1)  # > LOOKBACK_DAYS before today
    assert (today - old_ex).days > LOOKBACK_DAYS
    assert recognition_decision(old_ex, today, Decimal("0.91")) is None


def test_recent_dividend_just_inside_lookback_is_recognized():
    today = date(2026, 6, 12)
    # ex-date just inside the lookback window and pay date already passed.
    ex = today - timedelta(days=LOOKBACK_DAYS - 1)
    result = recognition_decision(ex, today, Decimal("1.00"))
    assert result == estimate_pay_date(ex)


def test_dedup_window_brackets_estimated_pay_date():
    pay = date(2026, 6, 11)
    start, end = dedup_window(pay)
    assert (pay - start).days == DEDUP_WINDOW_DAYS
    assert (end - pay).days == DEDUP_WINDOW_DAYS
