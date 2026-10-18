"""Small date helpers for the models, the seed data, the forms, the reports, and the guard history."""

import calendar
from datetime import date, datetime, time

from django.utils import timezone


def add_months(start, months):
    """
    Add (or subtract) whole months to a date.
    Jan 31 + 1 month becomes Feb 28 (or 29), the last day of that month.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def nice_date(value):
    """Format a date like Oct 31, 2026. Returns an empty string for None."""
    if value is None:
        return ""
    return value.strftime("%b %d, %Y")


def long_date(value):
    """
    Format a date like October 12, 2026, for printed reports.
    Built by hand because "%-d" (day without a leading zero) fails on Windows.
    Returns an empty string for None.
    """
    if value is None:
        return ""
    return f"{value:%B} {value.day}, {value.year}"


def clock_time(value, seconds=True):
    """
    Format the time of a datetime or time like 3:05:09 PM, or 3:05 PM with
    seconds=False. The hour has no leading zero.
    """
    hour = value.hour % 12 or 12
    half_of_day = "AM" if value.hour < 12 else "PM"
    shown = f"{hour}:{value:%M:%S}" if seconds else f"{hour}:{value:%M}"
    return f"{shown} {half_of_day}"


def long_datetime(value, zone=None):
    """
    Format a date and time in Philippine time (settings.TIME_ZONE), like
    October 12, 2026, 3:05:09 PM. Pass zone to name the time zone yourself.
    Returns an empty string for None.
    """
    if value is None:
        return ""
    local = timezone.localtime(value, zone)
    return f"{long_date(local.date())}, {clock_time(local)}"


def start_of_day(value):
    """Midnight at the start of a date, in Philippine time, so dates and times can be sorted together."""
    return timezone.make_aware(datetime.combine(value, time.min))


def day_count(days):
    """Like "1 day" or "21 days"."""
    unit = "day" if days == 1 else "days"
    return f"{days} {unit}"
