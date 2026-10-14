"""
Security alerts, worked out from the audit log each time the page opens.

Nothing here is saved, so there is no model. The Security alerts page reads
the last LOOKBACK_DAYS of AuditEntry rows and calls find() on every rule in
ALERT_RULES. An alert shows a username, a time window and a count, never what
a record contains. Every window and the office hours use Philippine time.

OOP in this file
- ABSTRACTION: AlertRule is an abstract base class (ABC) with abstract title()
  and find(). ThresholdRule stays abstract too, because matches() is abstract.
- INHERITANCE: ThresholdRule holds the shared counting logic, and
  FailedLoginRule, RepeatedDenialRule, ManyUnlocksRule and BulkViewingRule
  extend it (3 levels). AfterHoursRule extends AlertRule directly.
- POLYMORPHISM: each counting rule overrides matches() and sets its own
  constants. AfterHoursRule overrides find() with its own way of looking.
  The page calls find() on each rule in ALERT_RULES, with no if/elif on type.
- ENCAPSULATION: an Alert keeps its data in _attributes, with read-only
  properties.
"""

import calendar
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from django.urls import Resolver404, resolve
from django.utils import timezone

from accounts.roles import ROLE_PERMISSIONS
from guards.dates import clock_time, long_date, long_datetime

from . import constants as c
from .models import AuditEntry

MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 24 * 60


def philippine_time(moment):
    """The same moment in Philippine time, even if it was stored in UTC."""
    return timezone.localtime(moment, c.PH_TIME_ZONE)


def staff_roles():
    """
    The roles that have STAFF_PERMISSION in ROLE_PERMISSIONS (Admin/HR today).
    It checks the permission, never a role name.
    """
    return {
        role
        for role, permissions in ROLE_PERMISSIONS.items()
        if c.STAFF_PERMISSION in permissions
    }


def page_name(entry):
    """
    The URL name of the page a VIEW entry opened, like "guard_profile".
    The audit middleware writes details like "GET /guards/3/". Returns ""
    when the details do not point to a page of this site.
    """
    path = urlsplit(entry.details.partition(" ")[2]).path
    try:
        return resolve(path).url_name or ""
    except Resolver404:
        return ""


def _window_text(minutes):
    """Say a window in words, like 15 minutes, 1 hour or 1 day."""
    if minutes % MINUTES_PER_DAY == 0:
        amount, unit = minutes // MINUTES_PER_DAY, "day"
    elif minutes % MINUTES_PER_HOUR == 0:
        amount, unit = minutes // MINUTES_PER_HOUR, "hour"
    else:
        amount, unit = minutes, "minute"
    return f"{amount} {unit}" if amount == 1 else f"{amount} {unit}s"


class Alert:
    """ENCAPSULATION: one alert: the rule that found it, a username, a time window and a count."""

    def __init__(self, rule, username, start, end, count):
        self._attributes = {
            "rule": rule,
            "username": username,
            "start": philippine_time(start),
            "end": philippine_time(end),
            "count": count,
        }

    def __str__(self):
        return f"{self.title}: {self.username}, {self.count} entries, {self.window_text}"

    @property
    def rule(self):
        return self._attributes["rule"]

    @property
    def title(self):
        return self.rule.title()

    @property
    def username(self):
        return self._attributes["username"]

    @property
    def start(self):
        """The time of the first entry, in Philippine time."""
        return self._attributes["start"]

    @property
    def end(self):
        """The time of the last entry, in Philippine time."""
        return self._attributes["end"]

    @property
    def count(self):
        return self._attributes["count"]

    @property
    def window_text(self):
        """Like "October 12, 2026, 2:01:05 AM to 2:09:40 AM", in Philippine time."""
        start = long_datetime(self.start, c.PH_TIME_ZONE)
        if self.start.date() != self.end.date():
            return f"{start} to {long_datetime(self.end, c.PH_TIME_ZONE)}"
        end = clock_time(self.end)
        # Entries in the same second show one time, not "2:01:05 AM to 2:01:05 AM".
        return start if end == clock_time(self.start) else f"{start} to {end}"

    def audit_log_links(self):
        """
        Links to the audit log with the filters it already has: user, action
        and date. Returns (day, query) pairs, one for each day in the window,
        so a window that crosses midnight gets two links.
        """
        links = []
        day = self.start.date()
        while day <= self.end.date():
            filters = {
                "user": self.username,
                "action": self.rule.LOG_ACTION,
                "date": day.isoformat(),
            }
            query = urlencode({name: value for name, value in filters.items() if value})
            links.append((long_date(day), query))
            day += timedelta(days=1)
        return links


class AlertRule(ABC):
    """ABSTRACTION: one security rule that reads audit entries and finds alerts."""

    # The action filter for this rule's audit log links. "" means every action.
    LOG_ACTION = ""

    def __str__(self):
        return self.title()

    # --- What every rule must answer (POLYMORPHISM) ---

    @abstractmethod
    def title(self):
        """The rule's name on the Security alerts page."""

    @abstractmethod
    def find(self, entries):
        """Return a list of Alert objects found in these audit entries."""

    # --- Shared default, children give more detail ---

    def describe(self):
        """What the rule looks for, for the "What this page checks" list."""
        return self.title()


class ThresholdRule(AlertRule):
    """INHERITANCE: N or more matching entries for one username within W minutes make an alert."""

    # Each child sets these constants and overrides matches(). Nothing else.
    TITLE = ""
    COUNTED = ""  # what is counted, in words, for describe()
    THRESHOLD = 0
    WINDOW_MINUTES = 0

    def title(self):
        return self.TITLE

    def describe(self):
        return (
            f"{self.THRESHOLD} or more {self.COUNTED} under one username "
            f"within {_window_text(self.WINDOW_MINUTES)}."
        )

    @abstractmethod
    def matches(self, entry):
        """True if this audit entry counts toward the rule."""

    def find(self, entries):
        alerts = []
        for username, times in self._times_by_username(entries).items():
            alerts.extend(self._alerts_for(username, times))
        return alerts

    def _times_by_username(self, entries):
        """The times of the matching entries, grouped by username, oldest first."""
        times = defaultdict(list)
        for entry in entries:
            if self.matches(entry):
                times[entry.username].append(entry.timestamp)
        return {username: sorted(found) for username, found in times.items()}

    def _alerts_for(self, username, times):
        """
        Start at the earliest time and count the times that fall within the
        window from it. THRESHOLD or more make one alert, and counting starts
        again after them, so alerts never overlap. Fewer, and the next time
        becomes the start.
        """
        window = timedelta(minutes=self.WINDOW_MINUTES)
        alerts = []
        first = 0
        while first < len(times):
            last = first
            while last + 1 < len(times) and times[last + 1] - times[first] <= window:
                last += 1
            count = last - first + 1
            if count >= self.THRESHOLD:
                alerts.append(Alert(self, username, times[first], times[last], count))
                first = last + 1
            else:
                first += 1
        return alerts


class FailedLoginRule(ThresholdRule):
    """POLYMORPHISM: many failed logins for one typed username."""

    TITLE = "Failed logins"
    COUNTED = "failed logins"
    THRESHOLD = c.FAILED_LOGIN_THRESHOLD
    WINDOW_MINUTES = c.FAILED_LOGIN_WINDOW_MINUTES
    LOG_ACTION = AuditEntry.LOGIN

    def matches(self, entry):
        # login_view logs a failed login as LOGIN, Denied, with the typed username.
        return entry.action == AuditEntry.LOGIN and entry.outcome == AuditEntry.DENIED


class RepeatedDenialRule(ThresholdRule):
    """POLYMORPHISM: many refused requests for one logged-in user."""

    TITLE = "Repeated refusals"
    COUNTED = "refusals (DENY entries)"
    THRESHOLD = c.DENIAL_THRESHOLD
    WINDOW_MINUTES = c.DENIAL_WINDOW_MINUTES
    LOG_ACTION = AuditEntry.DENY

    def matches(self, entry):
        # Visitors who are not logged in have no user, so they are left out.
        return entry.action == AuditEntry.DENY and entry.user_id is not None


class ManyUnlocksRule(ThresholdRule):
    """POLYMORPHISM: many step-ups (unlocks of sensitive records) by one user."""

    TITLE = "Many unlocks"
    COUNTED = "unlock tries (STEP_UP entries)"
    THRESHOLD = c.UNLOCK_THRESHOLD
    WINDOW_MINUTES = c.UNLOCK_WINDOW_MINUTES
    LOG_ACTION = AuditEntry.STEP_UP

    def matches(self, entry):
        # A wrong password at step-up is a STEP_UP entry too, so it counts.
        return entry.action == AuditEntry.STEP_UP


class BulkViewingRule(ThresholdRule):
    """POLYMORPHISM: many guard profiles opened by one user."""

    TITLE = "Bulk viewing"
    COUNTED = "guard profiles opened"
    THRESHOLD = c.BULK_VIEW_THRESHOLD
    WINDOW_MINUTES = c.BULK_VIEW_WINDOW_MINUTES
    LOG_ACTION = AuditEntry.VIEW

    def matches(self, entry):
        # Opening a profile is a VIEW entry with details like "GET /guards/3/".
        # The edit, status and document pages are other URL names, so they do not count.
        return entry.action == AuditEntry.VIEW and page_name(entry) == c.PROFILE_URL_NAME


class AfterHoursRule(AlertRule):
    """POLYMORPHISM: staff activity outside office hours. Guards are never checked."""

    def title(self):
        return "After-hours activity"

    def describe(self):
        days = ", ".join(self._office_day_names())
        return (
            f"Any activity by {', '.join(sorted(staff_roles()))} outside office hours "
            f"({clock_time(c.OFFICE_OPENS, seconds=False)} to "
            f"{clock_time(c.OFFICE_CLOSES, seconds=False)}, {days}). Guards are not "
            "checked, because they work night shifts."
        )

    def find(self, entries):
        roles = staff_roles()
        groups = defaultdict(list)
        for entry in entries:
            moment = philippine_time(entry.timestamp)
            if entry.role in roles and not self._in_office_hours(moment):
                # One alert per user per day. Early morning and evening are kept
                # apart, so one alert never spans the office day.
                early = moment.time() < c.OFFICE_OPENS
                groups[(entry.username, moment.date(), early)].append(moment)
        return [
            Alert(self, username, min(times), max(times), len(times))
            for (username, _day, _early), times in groups.items()
        ]

    def _in_office_hours(self, moment):
        """True from OFFICE_OPENS up to (not including) OFFICE_CLOSES on an office day."""
        open_day = moment.weekday() in c.OFFICE_DAYS
        return open_day and c.OFFICE_OPENS <= moment.time() < c.OFFICE_CLOSES

    def _office_day_names(self):
        """Mon, Tue, ... for the days in OFFICE_DAYS."""
        return [calendar.day_abbr[day] for day in c.OFFICE_DAYS]


# The page calls find() on each of these. Add a rule by adding a class and an object here.
ALERT_RULES = [
    FailedLoginRule(),
    RepeatedDenialRule(),
    ManyUnlocksRule(),
    BulkViewingRule(),
    AfterHoursRule(),
]
