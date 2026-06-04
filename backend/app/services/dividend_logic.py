"""Pure decision logic for yfinance dividend auto-detection.

Database-free and stdlib-only so it can be unit-tested in isolation, mirroring
:mod:`app.services.capital_income`. The async detector
(:mod:`app.services.dividend_detector`) imports these helpers and constants.

Why this exists
---------------
``yfinance``'s ``Ticker.dividends`` series is indexed by the **ex-dividend
date** and carries **no pay date**. A dividend is only *received income* once it
is actually **paid**, which for US large caps is typically ~3 weeks after the
ex-date (e.g. MSFT: ex 2026-05-21 → pay 2026-06-11). The previous detector
recorded the dividend as soon as the ex-date was in the past, so a declared but
not-yet-paid dividend was booked as income weeks early.

These helpers gate recognition on an **estimated pay date**
(``ex_date + PAYMENT_DELAY_DAYS``) and only record a dividend once that
estimated pay date is on or before today. The estimated pay date is also used as
the stored transaction date, so the income lands in the correct tax year (Finnish
dividends are taxed in the year they are paid / available).
"""

from datetime import date, timedelta
from decimal import Decimal

# How far back (in ex-dividend-date terms) to scan yfinance history each run.
# Must comfortably exceed PAYMENT_DELAY_DAYS so the daily scheduler always has a
# wide window in which to recognise a dividend once its estimated pay date
# arrives.
LOOKBACK_DAYS = 60

# Approximate gap between ex-dividend date and pay date. yfinance does not expose
# the pay date, so we approximate it. ~21 days covers US large caps (MSFT is
# exactly 21); EUR/Nordic dividends pay sooner, so for those this delays
# recognition slightly but keeps it in the correct tax year.
PAYMENT_DELAY_DAYS = 21

# Treat an existing dividend within +/- this many days of the estimated pay date
# as the same payment. Absorbs both the pay-date approximation drift and small
# date differences against manually imported rows, preventing duplicates.
DEDUP_WINDOW_DAYS = 7


def estimate_pay_date(ex_date: date) -> date:
    """Estimate the pay date from the ex-dividend date."""
    return ex_date + timedelta(days=PAYMENT_DELAY_DAYS)


def recognition_decision(
    ex_date: date,
    today: date,
    amount_per_share: Decimal,
) -> date | None:
    """Decide whether a dividend should be recorded now.

    Returns the estimated pay date (to use as the transaction date) when the
    dividend should be recorded, or ``None`` when it should be skipped because:

    * the per-share amount is non-positive, or
    * the ex-date is older than ``LOOKBACK_DAYS`` (out of scan window), or
    * the estimated pay date is still in the future (declared but not yet paid).
    """
    if amount_per_share <= 0:
        return None

    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    if ex_date < cutoff:
        return None

    pay_date_est = estimate_pay_date(ex_date)
    if pay_date_est > today:
        return None

    return pay_date_est


def dedup_window(pay_date_est: date) -> tuple[date, date]:
    """Inclusive date range used to detect an already-recorded equivalent dividend."""
    return (
        pay_date_est - timedelta(days=DEDUP_WINDOW_DAYS),
        pay_date_est + timedelta(days=DEDUP_WINDOW_DAYS),
    )
