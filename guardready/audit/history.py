"""
Guard history: one timeline per guard, built from records that already exist.
Nothing here is saved. The History tab on the guard profile shows it.

OOP in this file
- ABSTRACTION: HistoryEvent is an abstract base class (ABC). It is never used
  on its own.
- INHERITANCE: AssignmentEvent, RefusedAssignmentEvent, CredentialEvent and
  NoticeEvent extend HistoryEvent.
- POLYMORPHISM: each event overrides records_for(), when(), describe() and
  _by(). row() is the shared step that calls them, and NoticeEvent extends
  row() with super(). history_for() asks every class in HISTORY_EVENTS for its
  events, so there is no if/elif on the kind, like ALERT_RULES in alerts.py.
- ASSOCIATION: each event wraps one record: an Assignment, a refused ASSIGN
  audit entry, a CredentialVersion, or a Notification.
- ENCAPSULATION: the record is kept in _record, with a read-only property.

Sensitive data never appears here: no medical results, no personal details,
and no government numbers.
"""

from abc import ABC, abstractmethod

from django.utils import timezone

from guards.dates import day_count, long_date, start_of_day
from guards.models import CredentialVersion

from .changes import shown
from .constants import SYSTEM_ROLE
from .models import AuditEntry

# A notice in the 7 day, 1 day or expired band shows in red, like on the banner.
URGENT_COLOR = "danger"


def display_name(user):
    """A user's full name, or the username if no name is on file."""
    return user.get_full_name().strip() or user.username


class HistoryEvent(ABC):
    """ABSTRACTION: one line in a guard's history. Each subclass wraps one kind of record."""

    # The Event column and its badge color. Each subclass sets its own.
    LABEL = ""
    COLOR = "secondary"

    def __init__(self, record):
        self._record = record

    def __str__(self):
        return f"{self.LABEL}: {self.describe()}"

    @property
    def record(self):
        """The record this event wraps. Read only."""
        return self._record

    # --- What every kind of event must answer (POLYMORPHISM) ---

    @classmethod
    @abstractmethod
    def records_for(cls, guard):
        """This kind of record, for one guard."""

    @abstractmethod
    def when(self):
        """When it happened, as a date and time in Philippine time. The history is sorted by this."""

    @abstractmethod
    def describe(self):
        """One plain sentence. Names, posts and dates only, never a medical result."""

    @abstractmethod
    def _by(self):
        """Who did it."""

    # --- Shared steps, the same for every event ---

    @classmethod
    def for_guard(cls, guard):
        """FACTORY: one event of this kind for each of the guard's records."""
        return [cls(record) for record in cls.records_for(guard)]

    def row(self):
        """The cells of one history table row. It calls the methods each subclass overrides."""
        return {
            "date": long_date(self.when().date()),
            "label": self.LABEL,
            "color": self.COLOR,
            "details": self.describe(),
            "by": self._by(),
        }


class AssignmentEvent(HistoryEvent):
    """A posting at a client site. Wraps one Assignment."""

    LABEL = "Posting"
    COLOR = "primary"

    @classmethod
    def records_for(cls, guard):
        return guard.assignments.select_related("post__site", "assigned_by")

    def when(self):
        """
        The day the posting started. When HR recorded it on that same day, the
        time it was recorded too, so it sorts after anything earlier that day.
        """
        posting = self._record
        recorded = timezone.localtime(posting.created_at)
        if recorded.date() == posting.start_date:
            return recorded
        return start_of_day(posting.start_date)

    def describe(self):
        posting = self._record
        days = day_count(posting.days_served())
        if posting.is_open():
            return (
                f"Posted at {posting.post} since {long_date(posting.start_date)}. "
                f"Still posted ({days} so far)."
            )
        return (
            f"Posted at {posting.post} from {long_date(posting.start_date)} "
            f"to {long_date(posting.end_date)} ({days})."
        )

    def _by(self):
        return display_name(self._record.assigned_by)


class RefusedAssignmentEvent(HistoryEvent):
    """A posting that GuardReady refused. Wraps the ASSIGN audit entry with outcome Denied."""

    LABEL = "Refused posting"
    COLOR = "danger"

    @classmethod
    def records_for(cls, guard):
        return AuditEntry.objects.filter(
            action=AuditEntry.ASSIGN,
            outcome=AuditEntry.DENIED,
            target_type="Guard",
            target_id=str(guard.pk),
        ).select_related("user")

    def when(self):
        return timezone.localtime(self._record.timestamp)

    def describe(self):
        """assign_guard() wrote the post and every reason in the entry's details."""
        return self._record.details

    def _by(self):
        entry = self._record
        return display_name(entry.user) if entry.user else entry.username


class CredentialEvent(HistoryEvent):
    """A renewal or correction of one document. Wraps one CredentialVersion (the old values)."""

    LABEL = "Document change"
    COLOR = "info"

    @classmethod
    def records_for(cls, guard):
        return CredentialVersion.objects.filter(credential__guard=guard).select_related(
            "credential", "changed_by"
        )

    def when(self):
        return timezone.localtime(self._record.changed_at)

    def describe(self):
        """What changed in the number and dates. The result is never read, even for a medical exam."""
        changes = [
            f'{label} from "{shown(old)}" to "{shown(new)}"'
            for label, old, new in self._pairs()
            if old != new
        ]
        what = "; ".join(changes) if changes else "the number and dates stayed the same"
        return f"{self._record.credential.doc_type} renewed or corrected: {what}."

    def _pairs(self):
        """(label, old value, new value) for the number and both dates."""
        version = self._record
        new = version.new_values()
        return [
            ("Number", version.old_number, new["number"]),
            ("Date issued", version.old_issued, new["issued"]),
            ("Expiry date", version.old_expires, new["expires"]),
        ]

    def _by(self):
        return display_name(self._record.changed_by)


class NoticeEvent(HistoryEvent):
    """An expiry notice about one of his documents. Wraps one Notification."""

    LABEL = "Expiry notice"
    COLOR = "warning"

    @classmethod
    def records_for(cls, guard):
        return guard.notifications.select_related("guard", "credential")

    def when(self):
        return start_of_day(self._record.created_date)

    def describe(self):
        """The notice's own message (document name and date only), and where it stands now."""
        return f"{self._record.message()} Notice status: {self._record.status}."

    def _by(self):
        """The daily expiry check makes every notice."""
        return SYSTEM_ROLE

    def row(self):
        """POLYMORPHISM: the shared row, in red for a 7 day, 1 day or expired notice."""
        row = super().row()
        if self._record.is_urgent():
            row["color"] = URGENT_COLOR
        return row


# Every kind of event the History tab shows. Each class finds its own records.
HISTORY_EVENTS = [AssignmentEvent, RefusedAssignmentEvent, CredentialEvent, NoticeEvent]


def history_for(guard):
    """Every event of one guard, newest first. POLYMORPHISM: no if/elif on the kind."""
    events = [event for event_class in HISTORY_EVENTS for event in event_class.for_guard(guard)]
    return sorted(events, key=lambda event: event.when(), reverse=True)
