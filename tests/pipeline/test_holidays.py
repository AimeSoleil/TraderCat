"""Tests for market holiday detection."""
import pytest
from datetime import date

from tradercat.pipeline.holidays import is_market_day, get_next_market_day, get_previous_market_day


def test_weekend_detection():
    """Test that weekends are not market days."""
    # Saturday
    saturday = date(2026, 2, 7)
    assert not is_market_day(saturday)
    
    # Sunday
    sunday = date(2026, 2, 8)
    assert not is_market_day(sunday)


def test_weekday_detection():
    """Test that regular weekdays are market days."""
    # Monday
    monday = date(2026, 2, 9)
    assert is_market_day(monday)
    
    # Wednesday
    wednesday = date(2026, 2, 11)
    assert is_market_day(wednesday)


def test_holiday_detection():
    """Test that known holidays are not market days."""
    # New Year's Day 2026
    new_years = date(2026, 1, 1)
    assert not is_market_day(new_years)
    
    # Christmas 2026
    christmas = date(2026, 12, 25)
    assert not is_market_day(christmas)


def test_next_market_day():
    """Test getting next market day."""
    # Friday -> Monday (skip weekend)
    friday = date(2026, 2, 6)
    next_day = get_next_market_day(friday)
    assert next_day == date(2026, 2, 9)  # Monday
    
    # Thursday -> Friday (regular)
    thursday = date(2026, 2, 5)
    next_day = get_next_market_day(thursday)
    assert next_day == date(2026, 2, 6)  # Friday


def test_previous_market_day():
    """Test getting previous market day."""
    # Monday -> Friday (skip weekend)
    monday = date(2026, 2, 9)
    prev_day = get_previous_market_day(monday)
    assert prev_day == date(2026, 2, 6)  # Friday
    
    # Tuesday -> Monday (regular)
    tuesday = date(2026, 2, 10)
    prev_day = get_previous_market_day(tuesday)
    assert prev_day == date(2026, 2, 9)  # Monday
