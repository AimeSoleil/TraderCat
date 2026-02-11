"""US market holiday calendar for pipeline scheduling."""
from datetime import date
from typing import Set
import exchange_calendars as xcals


# NYSE holidays for 2025-2027 (hardcoded fallback)
HARDCODED_HOLIDAYS: Set[date] = {
    # 2025
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # Martin Luther King Jr. Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
    # 2026
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # Martin Luther King Jr. Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
    # 2027
    date(2027, 1, 1),   # New Year's Day
    date(2027, 1, 18),  # Martin Luther King Jr. Day
    date(2027, 2, 15),  # Presidents' Day
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),  # Memorial Day
    date(2027, 6, 18),  # Juneteenth (observed)
    date(2027, 7, 5),   # Independence Day (observed)
    date(2027, 9, 6),   # Labor Day
    date(2027, 11, 25), # Thanksgiving
    date(2027, 12, 24), # Christmas (observed)
}


def is_market_day(check_date: date) -> bool:
    """
    Check if a given date is a US market trading day.
    
    Args:
        check_date: Date to check
        
    Returns:
        True if market is open, False if weekend or holiday
    """
    # Check if weekend
    if check_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
    
    # Try using exchange_calendars first
    try:
        nyse = xcals.get_calendar("XNYS")
        return nyse.is_session(check_date)
    except Exception:
        # Fallback to hardcoded holidays
        return check_date not in HARDCODED_HOLIDAYS


def get_next_market_day(from_date: date) -> date:
    """
    Get the next market day after the given date.
    
    Args:
        from_date: Starting date
        
    Returns:
        Next market day
    """
    from datetime import timedelta
    
    next_date = from_date + timedelta(days=1)
    while not is_market_day(next_date):
        next_date += timedelta(days=1)
    
    return next_date


def get_previous_market_day(from_date: date) -> date:
    """
    Get the previous market day before the given date.
    
    Args:
        from_date: Starting date
        
    Returns:
        Previous market day
    """
    from datetime import timedelta
    
    prev_date = from_date - timedelta(days=1)
    while not is_market_day(prev_date):
        prev_date -= timedelta(days=1)
    
    return prev_date
