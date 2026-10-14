"""
Employment status: Active, On leave, Resigned, Let go.

Each status is a plain Python class that answers the same questions in its
own way, like the account types in the bank activity.

OOP in this file
- ABSTRACTION: EmploymentStatus is an abstract base class (ABC).
- INHERITANCE: ActiveStatus and OnLeaveStatus extend EmploymentStatus.
  SeparatedStatus holds the shared rules for guards who left, and
  ResignedStatus and LetGoStatus extend it (3 levels).
- POLYMORPHISM: every status overrides can_be_assigned(), gets_notices(),
  counts_as_current(), allows_login(), next_statuses() and reasons().
- ENCAPSULATION: a status keeps the change it came from in _change, with
  read-only properties.
- FACTORY: STATUS_CLASSES picks the class for a status name, like
  ACCOUNT_TYPES and create_account().
"""

from abc import ABC, abstractmethod

from . import constants as c


class EmploymentStatus(ABC):
    """ABSTRACTION: what a guard's employment status allows. Each status answers for itself."""

    NAME = ""
    # Why an assignment is refused. Empty means he can be assigned.
    REFUSAL = ""

    def __init__(self, change=None):
        # The EmploymentStatusChange this status came from. None means no record yet.
        self._change = change

    def __str__(self):
        return self.NAME

    # --- What every status must answer (POLYMORPHISM) ---

    @abstractmethod
    def can_be_assigned(self):
        """True if he can be posted to a client site."""

    @abstractmethod
    def gets_notices(self):
        """True if check_expiry() should send him expiry notices."""

    @abstractmethod
    def counts_as_current(self):
        """True if he shows in lists, counts and rosters by default."""

    @abstractmethod
    def allows_login(self):
        """True if his login account (if he has one) may work."""

    @abstractmethod
    def next_statuses(self):
        """The status names he can change to from this one."""

    @abstractmethod
    def reasons(self):
        """The reasons that can be given for this status."""

    # --- Shared steps, the same for every status ---

    @property
    def name(self):
        return self.NAME

    @property
    def effective_date(self):
        """The day this status started, or None if he has no record (Active since hired)."""
        return self._change.effective_date if self._change else None

    @property
    def reason(self):
        return self._change.reason if self._change else ""

    def refusal_reason(self):
        """Why he cannot be posted, for the refusal and the audit log. Empty if he can be."""
        return self.REFUSAL

    def list_label(self):
        """The label beside his name in lists. Active guards need none."""
        return self.NAME

    def next_choices(self):
        """Every status he can change to, each with its reasons, for the form."""
        return [(name, STATUS_CLASSES[name]().reasons()) for name in self.next_statuses()]


class ActiveStatus(EmploymentStatus):
    """Working normally. A guard with no status record is Active."""

    NAME = c.ACTIVE

    def can_be_assigned(self):
        return True

    def gets_notices(self):
        return True

    def counts_as_current(self):
        return True

    def allows_login(self):
        return True

    def next_statuses(self):
        return [c.ON_LEAVE, c.RESIGNED, c.LET_GO]

    def reasons(self):
        return list(c.ACTIVE_REASONS)

    def list_label(self):
        """POLYMORPHISM: Active is the normal case, so lists show no label."""
        return ""


class OnLeaveStatus(EmploymentStatus):
    """Still employed and still counted, but cannot be posted until he is back."""

    NAME = c.ON_LEAVE
    REFUSAL = c.ON_LEAVE_REFUSAL

    def can_be_assigned(self):
        return False

    def gets_notices(self):
        return True

    def counts_as_current(self):
        return True

    def allows_login(self):
        return True

    def next_statuses(self):
        return [c.ACTIVE, c.RESIGNED, c.LET_GO]

    def reasons(self):
        return list(c.ON_LEAVE_REASONS)


class SeparatedStatus(EmploymentStatus):
    """The shared rules for a guard who left. Each way of leaving gives its own reasons()."""

    REFUSAL = c.SEPARATED_REFUSAL

    def can_be_assigned(self):
        return False

    def gets_notices(self):
        return False

    def counts_as_current(self):
        return False

    def allows_login(self):
        return False

    def next_statuses(self):
        """A guard who left can only come back as Active (rehired or a correction)."""
        return [c.ACTIVE]


class ResignedStatus(SeparatedStatus):
    """He left on his own. INHERITANCE level 3."""

    NAME = c.RESIGNED

    def reasons(self):
        return list(c.RESIGNED_REASONS)


class LetGoStatus(SeparatedStatus):
    """The agency ended his work. INHERITANCE level 3."""

    NAME = c.LET_GO

    def reasons(self):
        return list(c.LET_GO_REASONS)


# FACTORY: each status name maps to its class, like ACCOUNT_TYPES in the bank activity.
STATUS_CLASSES = {
    c.ACTIVE: ActiveStatus,
    c.ON_LEAVE: OnLeaveStatus,
    c.RESIGNED: ResignedStatus,
    c.LET_GO: LetGoStatus,
}
