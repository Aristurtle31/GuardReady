"""Small date helpers used by the models, the seed data, and the forms."""

import calendar
from datetime import date


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
