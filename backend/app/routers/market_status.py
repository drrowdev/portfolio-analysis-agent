from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

router = APIRouter(tags=["market-status"])

# Timezone definitions
ET = ZoneInfo("America/New_York")
HEL = ZoneInfo("Europe/Helsinki")
UTC = ZoneInfo("UTC")

# Trading hours
US_OPEN = time(9, 30)
US_CLOSE = time(16, 0)
HEL_OPEN = time(10, 0)
HEL_CLOSE = time(18, 30)

# Pre-load calendars at module level for performance
_us_cal = None
_hel_cal = None


def _get_calendars():
    global _us_cal, _hel_cal
    if _us_cal is None:
        import exchange_calendars as xcals
        _us_cal = xcals.get_calendar("XNYS")
        _hel_cal = xcals.get_calendar("XHEL")
    return _us_cal, _hel_cal


def _is_trading_session(cal, d: date) -> bool:
    """Check if a date is a valid trading session using exchange_calendars."""
    import pandas as pd
    ts = pd.Timestamp(d)
    if ts < cal.first_session or ts > cal.last_session:
        # Out of calendar range — fall back to weekday check
        return d.weekday() < 5
    return cal.is_session(ts)


def _next_trading_session(cal, d: date) -> date:
    """Find the next valid trading session on or after date d."""
    import pandas as pd
    candidate = d
    for _ in range(10):
        if _is_trading_session(cal, candidate):
            return candidate
        candidate += timedelta(days=1)
    # Fallback: next weekday
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _format_time(dt: datetime, tz_abbrev: str) -> str:
    """Format datetime as '10:30 AM ET'."""
    return f"{dt.strftime('%-I:%M %p')} {tz_abbrev}"


def _format_time_win(dt: datetime, tz_abbrev: str = "") -> str:
    """Format datetime as '20:30' — 24h format, no timezone label."""
    return dt.strftime('%H:%M')


def _exchange_status(
    cal, tz: ZoneInfo, tz_abbrev: str, open_time: time, close_time: time,
    display_tz: ZoneInfo | None = None, display_tz_abbrev: str | None = None,
) -> dict:
    """Compute exchange open/closed status.
    
    If display_tz is set, times shown to the user are converted to that timezone.
    """
    now_local = datetime.now(tz)
    today = now_local.date()

    disp_tz = display_tz or tz
    disp_abbrev = display_tz_abbrev or tz_abbrev
    now_disp = now_local.astimezone(disp_tz)
    current_time_str = _format_time_win(now_disp, disp_abbrev)

    is_session = _is_trading_session(cal, today)
    now_t = now_local.time()
    is_open = is_session and open_time <= now_t < close_time

    if is_open:
        close_dt = now_local.replace(
            hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0,
        ).astimezone(disp_tz)
        close_str = _format_time_win(close_dt, disp_abbrev)
        return {
            "status": "open",
            "current_time": current_time_str,
            "session_info": f"Open until {close_str}",
        }

    # Market is closed — find next open
    if is_session and now_t < open_time:
        next_session_date = today
    else:
        next_session_date = _next_trading_session(cal, today + timedelta(days=1))

    next_open_dt = datetime(
        next_session_date.year, next_session_date.month, next_session_date.day,
        open_time.hour, open_time.minute, tzinfo=tz,
    ).astimezone(disp_tz)
    day_name = next_open_dt.strftime("%A")
    open_str = _format_time_win(next_open_dt, disp_abbrev)

    if next_session_date == today:
        session_info = f"Opens today at {open_str}"
    elif next_session_date == today + timedelta(days=1):
        session_info = f"Opens tomorrow at {open_str}"
    else:
        session_info = f"Opens {day_name} at {open_str}"

    return {
        "status": "closed",
        "current_time": current_time_str,
        "session_info": session_info,
        "next_open": next_open_dt.isoformat(),
    }


@router.get("/market-status")
async def get_market_status():
    """Return current open/closed status for US and Finnish exchanges."""
    us_cal, hel_cal = _get_calendars()

    us_info = _exchange_status(us_cal, ET, "ET", US_OPEN, US_CLOSE, display_tz=HEL, display_tz_abbrev="FI")
    hel_info = _exchange_status(hel_cal, HEL, "EET", HEL_OPEN, HEL_CLOSE)

    return {
        "exchanges": [
            {"name": "US (NYSE/NASDAQ)", "code": "us", **us_info},
            {"name": "Helsinki (Nasdaq Nordic)", "code": "fi", **hel_info},
        ],
        "last_updated": datetime.now(UTC).isoformat(),
    }
