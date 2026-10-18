"""
Guards app models.

INHERITANCE: Person (abstract) -> Employee (abstract) -> Guard (concrete).
Only Guard gets a database table. It has the fields of all three classes.

ExpiringDocument is an abstract model (no table) for any paper with a
number, an issue date and an expiry date. It holds the shared expiry rules
(days left, status, notice days, the notice band) and the shared steps of
renew() and make_notice(). Credential (a guard's document) and AgencyPermit
(the agency's own permit, like its License to Operate) both extend it.

ExpiryNotice is the abstract base of the two notice models: Notification (a
guard's document) and AgencyNotice (an agency permit). They share the fields,
message(), move_to() and the rest. Each one only says whose document it is,
which page it links to, and whether its owner still gets notices.
NOTICE_TYPES picks the notice class from its kind, like ACCOUNT_TYPES.

Credential is one table with four proxy subclasses: License, Clearance,
MedicalCert, and TrainingCert. A proxy shares the same table but has its
own Python methods (POLYMORPHISM).

EmploymentStatusChange is the append-only history of a guard's employment
status. The rules for each status live in guards/status.py.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from audit.models import AppendOnlyRecord, RecordLockedError

from . import constants as c
from .dates import add_months, long_date, nice_date
from .status import STATUS_CLASSES, ActiveStatus


# ---------------------------------------------------------------------------
# People: Person -> Employee -> Guard
# ---------------------------------------------------------------------------


class Person(models.Model):
    """
    ABSTRACTION: an abstract model for any person.
    Birth date, contact number, and home address are sensitive (RA 10173).
    """

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    birth_date = models.DateField(null=True, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    home_address = models.CharField(max_length=200, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def masked_contact(self):
        """Show only the last 4 digits, for example *******4567."""
        if len(self.contact_number) <= 4:
            return "****"
        hidden = len(self.contact_number) - 4
        return "*" * hidden + self.contact_number[-4:]

    def personal_details(self):
        """Sensitive details. Views call this only while a step-up is active."""
        return {
            "Date of birth": nice_date(self.birth_date),
            "Home address": self.home_address,
            "Contact number": self.contact_number,
        }

    def summary(self):
        return self.full_name


class Employee(Person):
    """INHERITANCE level 2: an abstract employee of the agency."""

    employee_no = models.CharField(max_length=20, unique=True)
    date_hired = models.DateField()
    position = models.CharField(max_length=50, default="Security Guard")
    # Government numbers are sensitive too.
    sss_number = models.CharField(max_length=20, blank=True)
    tin_number = models.CharField(max_length=20, blank=True)
    philhealth_number = models.CharField(max_length=20, blank=True)

    class Meta:
        abstract = True

    def personal_details(self):
        """POLYMORPHISM: Person's details plus the government numbers."""
        details = super().personal_details()
        details["SSS number"] = self.sss_number
        details["TIN"] = self.tin_number
        details["PhilHealth number"] = self.philhealth_number
        return details

    def summary(self):
        """POLYMORPHISM: adds the employee number."""
        return f"{self.employee_no} {self.full_name}"


class Guard(Employee):
    """INHERITANCE level 3: the only concrete class, with its own table."""

    rank = models.CharField(max_length=50, default="Security Guard")
    guard_type = models.CharField(max_length=40, choices=c.GUARD_TYPE_CHOICES)
    # A guard may have a login account. guard1 is linked to Juan Dela Cruz.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="guard_profile",
    )

    class Meta:
        ordering = ["last_name", "first_name"]
        # Custom permissions. The groups in accounts/roles.py get these.
        permissions = [
            ("view_dashboard", "Can view the dashboard"),
            ("view_all_guards", "Can view and search all guards"),
            ("view_own_record", "Can view own guard record"),
            ("step_up_sensitive", "Can unlock sensitive data with a step-up"),
            ("manage_credentials", "Can add or renew credentials"),
        ]

    def summary(self):
        """POLYMORPHISM: adds the guard type."""
        return f"{super().summary()} ({self.guard_type})"

    # --- Credentials (COMPOSITION: a guard owns his credentials) ---

    def credential_list(self):
        """All credentials of this guard, each one as its proxy class."""
        return [credential.typed() for credential in self.credentials.all()]

    def get_credential(self, doc_type):
        """The credential for one document, or None if it is not on file."""
        for credential in self.credential_list():
            if credential.doc_type == doc_type:
                return credential
        return None

    def add_credential(self, doc_type, number, issued, expires, issuer="", result=""):
        """The only way to add a credential. Returns the new credential."""
        if doc_type not in c.REQUIRED_DOCUMENTS:
            raise ValidationError(f"{doc_type} is not a required document.")
        if self.credentials.filter(doc_type=doc_type).exists():
            raise ValidationError(f"{doc_type} is already on file. Renew it instead.")
        Credential.check_values(number, issued, expires)

        credential = Credential(
            guard=self,
            kind=c.DOCUMENT_KINDS[doc_type],
            doc_type=doc_type,
            number=number.strip(),
            issuer=issuer,
            issued=issued,
            expires=expires,
        ).typed()
        if credential.uses_result():
            credential.result = result
        credential.save()
        return credential

    def credential_rows(self, unlocked=False):
        """One row per required document, for the profile table."""
        rows = []
        for doc_type in c.REQUIRED_DOCUMENTS:
            credential = self.get_credential(doc_type)
            if credential is None:
                rows.append(missing_row(doc_type))
            else:
                rows.append(credential.row(unlocked))
        return rows

    # --- Readiness ---

    def missing(self):
        """Required documents that are not on file."""
        on_file = [credential.doc_type for credential in self.credential_list()]
        return [doc for doc in c.REQUIRED_DOCUMENTS if doc not in on_file]

    def expired(self):
        """Credentials that have expired."""
        return [cr for cr in self.credential_list() if cr.status() == c.EXPIRED]

    def expiring(self):
        """Credentials inside the first notice band (60 days)."""
        return [cr for cr in self.credential_list() if cr.status() == c.EXPIRING_SOON]

    def readiness(self):
        """Cleared, Expiring soon, or Not cleared."""
        if self.missing() or self.expired():
            return c.NOT_CLEARED
        if self.expiring():
            return c.EXPIRING_SOON
        return c.CLEARED

    def is_deployable(self):
        """Cleared and Expiring soon guards can be posted. Not cleared cannot."""
        return self.readiness() != c.NOT_CLEARED

    def block_reasons(self):
        """Why the guard cannot be posted. Document names and dates only."""
        reasons = [f"{doc} is not on file" for doc in self.missing()]
        for credential in self.expired():
            reasons.append(f"{credential.doc_type} expired on {nice_date(credential.expires)}")
        return reasons

    def earliest_expiry(self):
        """The credential that expires first, or None if he has none."""
        credentials = self.credential_list()
        if not credentials:
            return None
        return min(credentials, key=lambda credential: credential.expires)

    # --- Deployment ---

    def current_assignment(self):
        """The open assignment (no end date yet), or None."""
        open_assignments = self.assignments.filter(end_date__isnull=True)
        return open_assignments.select_related("post__site").first()

    def posting_on(self, day):
        """
        The posting he worked on this day, or None. A posting covers its start
        date up to the day before its end date, because the end date is the day
        he left (or moved to his next post).
        """
        covering = self.assignments.filter(start_date__lte=day).filter(
            Q(end_date__isnull=True) | Q(end_date__gt=day)
        )
        return covering.select_related("post__site").first()

    # --- Employment status (the rules for each status are in guards/status.py) ---

    def status_history(self):
        """Every status change, newest first: by effective date, then by the time it was recorded."""
        return sorted(
            self.status_changes.all(),
            key=lambda change: (change.effective_date, change.recorded_at, change.pk),
            reverse=True,
        )

    def employment_status(self):
        """The status object for his latest change. A guard with no record is Active."""
        history = self.status_history()
        if not history:
            return ActiveStatus()
        return history[0].as_status()

    def check_status_change(self, status, reason, effective_date):
        """The rules for a status change. Raises ValidationError with every problem found."""
        if status not in STATUS_CLASSES:
            raise ValidationError(f"{status} is not an employment status.")
        current = self.employment_status()
        new = STATUS_CLASSES[status]()
        errors = []
        if status not in current.next_statuses():
            errors.append(f"A guard who is {current} cannot change to {status}.")
        if reason not in new.reasons():
            errors.append(f'"{reason}" is not a reason for {status}.')
        if effective_date > timezone.localdate():
            errors.append("The effective date cannot be in the future.")
        if effective_date < self.date_hired:
            errors.append(
                f"The effective date cannot be before the hire date ({long_date(self.date_hired)})."
            )
        if current.effective_date and effective_date < current.effective_date:
            errors.append(
                "The effective date cannot be before the last status change "
                f"({long_date(current.effective_date)})."
            )
        posting = self.current_assignment()
        if posting and not new.can_be_assigned() and effective_date < posting.start_date:
            errors.append(
                "The effective date is before the current posting started "
                f"({long_date(posting.start_date)}). Use that date or a later one."
            )
        if errors:
            raise ValidationError(errors)

    def change_employment_status(self, status, reason, effective_date, by_user):
        """
        ENCAPSULATION: the only way to change a guard's employment status.
        It checks the rules, saves an EmploymentStatusChange, closes his open
        posting if he can no longer be posted, and turns his login off (or back
        on) to match the new status. Returns the new status and a list of what
        else changed, for the audit log.
        """
        self.check_status_change(status, reason, effective_date)
        change = EmploymentStatusChange.objects.create(
            guard=self,
            status=status,
            reason=reason,
            effective_date=effective_date,
            recorded_by=by_user,
        )
        new = change.as_status()

        effects = []
        posting = self.current_assignment()
        if posting is not None and not new.can_be_assigned():
            posting.close(effective_date)
            effects.append(
                f"The open posting at {posting.post} was closed on {long_date(effective_date)}"
            )
        if self.user is not None and self.user.is_active != new.allows_login():
            # Django refuses an inactive user on his next click, so he is logged out.
            self.user.is_active = new.allows_login()
            self.user.save(update_fields=["is_active"])
            effects.append(
                f"Login {c.LOGIN_CHANGE_NOTES[new.allows_login()]} for user {self.user.username}"
            )
        return new, effects


def missing_row(doc_type):
    """A profile table row for a document that is not on file."""
    return {
        "document": doc_type,
        "number": "",
        "issuer": "",
        "issued": "",
        "expires": "",
        "days_left": "",
        "status": c.NOT_ON_FILE,
        "result": "",
        "on_file": False,
    }


# ---------------------------------------------------------------------------
# Expiring documents: the shared abstract base
# ---------------------------------------------------------------------------


class ExpiringDocument(models.Model):
    """ABSTRACTION: a paper with a number, an issue date and an expiry date. It has no table."""

    number = models.CharField(max_length=50)
    issued = models.DateField()
    expires = models.DateField()

    class Meta:
        abstract = True

    def __str__(self):
        return self.number

    # --- What every kind of document must answer (POLYMORPHISM) ---

    def validity_months(self):
        """Every proxy class must override this. Call typed() first."""
        raise NotImplementedError("Call typed() to get the proxy class first.")

    def notice_days(self):
        """Days before expiry when a notice is sent. One kind can override it later."""
        return list(c.NOTICE_DAYS)

    # --- Status, the same for every document ---

    def days_left(self):
        return (self.expires - timezone.localdate()).days

    def status(self):
        """
        Expired, Expiring soon, or Valid.
        A document counts as expired on its expiry date, so the status and
        the "Expired" notice always agree.
        """
        days = self.days_left()
        if days <= 0:
            return c.EXPIRED
        if days <= max(self.notice_days()):
            return c.EXPIRING_SOON
        return c.VALID

    def notice_band(self):
        """
        The notice band this document is in today:
        60, 30, 14, 7, 1, 0 (expired), or None if no notice is due yet.
        """
        days = self.days_left()
        if days <= 0:
            return c.EXPIRED_BAND
        bands_reached = [band for band in self.notice_days() if days <= band]
        if not bands_reached:
            return None
        return min(bands_reached)

    def expiry_text(self):
        """One short line, like "valid until October 18, 2028" or "expired on October 8, 2026"."""
        days = self.days_left()
        unit = "day" if days == 1 else "days"
        return c.EXPIRY_TEXTS[self.status()].format(
            date=long_date(self.expires), days=f"{days} {unit}"
        )

    # --- Changes, the same steps for every document ---

    @staticmethod
    def check_values(number, issued, expires):
        """Validation rules for adding and renewing."""
        errors = []
        if not number or not number.strip():
            errors.append("The document number cannot be blank.")
        if issued > timezone.localdate():
            errors.append("The issue date cannot be in the future.")
        if expires <= issued:
            errors.append("The expiry date must be after the issue date.")
        if errors:
            raise ValidationError(errors)

    def renew(self, number, issued, expires, by_user, changed_at=None):
        """
        ENCAPSULATION: the only way to change a document's number and dates.
        The old values are saved in a version record first. Then the open
        notices about an expiry date the document no longer has are resolved.
        Returns how many notices were resolved.
        changed_at is only passed by seed_demo to record a past renewal.
        """
        self.check_values(number, issued, expires)
        self._save_version(by_user, changed_at or timezone.now())
        self.number = number.strip()
        self.issued = issued
        self.expires = expires
        self.save()
        return self._resolve_old_notices()

    def _resolve_old_notices(self):
        """
        Resolve the open notices about any other expiry date. A correction that
        keeps the same expiry date keeps its notices open, because the
        document still expires then.
        """
        old_notices = list(
            self._notices()
            .filter(status__in=ExpiryNotice.OPEN)
            .exclude(expiry_date=self.expires)
        )
        for notice in old_notices:
            notice.resolve()
        return len(old_notices)

    def _save_version(self, by_user, changed_at):
        """Keep the values on file now in a version record. Each child has its own model."""
        raise NotImplementedError("Each kind of document saves its own version record.")

    # --- Expiry notices. Stage 2's check_expiry() calls make_notice() ---

    def make_notice(self):
        """
        Make the notice for the band this document is in today, once.
        Each notice model is unique on (document, band, expiry date), so a
        band is never sent twice, and a renewal with a new expiry starts again.
        Returns the new notice, or None if no notice is due or it was made before.
        """
        band = self.notice_band()
        if band is None:
            return None
        notice, created = self._notices().get_or_create(
            band=band, expiry_date=self.expires, defaults=self._notice_extra()
        )
        return notice if created else None

    def _notices(self):
        """This document's notices (a related manager). Each child names its own."""
        raise NotImplementedError("Each kind of document has its own notices.")

    def _notice_extra(self):
        """Other fields a new notice needs. None, unless a child adds some."""
        return {}


# ---------------------------------------------------------------------------
# Credentials: one table, four proxy classes
# ---------------------------------------------------------------------------


class Credential(ExpiringDocument):
    """
    One document of one guard. The kind field says which proxy class
    (License, Clearance, MedicalCert, TrainingCert) the row belongs to.
    Credentials can be added and renewed. They can never be deleted.
    number, issued and expires come from ExpiringDocument.
    """

    guard = models.ForeignKey(Guard, on_delete=models.PROTECT, related_name="credentials")
    kind = models.CharField(max_length=20, choices=c.CREDENTIAL_KIND_CHOICES)
    doc_type = models.CharField(max_length=40, choices=c.DOCUMENT_CHOICES)
    issuer = models.CharField(max_length=100, blank=True)
    # Only medical certificates use this field. It is sensitive.
    result = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["guard", "doc_type"]
        # No "change" or "delete" permission. Changes go through renew().
        default_permissions = ("add", "view")
        constraints = [
            models.UniqueConstraint(fields=["guard", "doc_type"], name="one_document_per_guard"),
        ]

    def __str__(self):
        return f"{self.doc_type} {self.number}"

    def delete(self, *args, **kwargs):
        raise RecordLockedError("Credentials cannot be deleted. Renew them instead.")

    def typed(self):
        """
        Return this row as its proxy class (License, Clearance, ...).
        A proxy uses the same table and fields, so we only switch the
        Python class. No extra database query is needed.
        """
        self.__class__ = CREDENTIAL_CLASSES[self.kind]
        return self

    @classmethod
    def for_document(cls, doc_type):
        """
        FACTORY: an unsaved credential of the right proxy class for this
        document. Forms use it to ask questions like uses_result() before the
        document is on file. It is never saved.
        """
        return cls(kind=c.DOCUMENT_KINDS[doc_type], doc_type=doc_type).typed()

    # --- Methods the proxy classes override (POLYMORPHISM) ---
    # validity_months() and notice_days() come from ExpiringDocument.

    def is_sensitive(self):
        return False

    def uses_result(self):
        return False

    def row(self, unlocked=False):
        """One row for the profile table. MedicalCert adds the result."""
        return {
            "document": self.doc_type,
            "number": self.number,
            "issuer": self.issuer,
            "issued": nice_date(self.issued),
            "expires": nice_date(self.expires),
            "days_left": self.days_left(),
            "status": self.status(),
            "result": "Not applicable",
            "on_file": True,
        }

    # --- Status: days_left(), status() and notice_band() come from ExpiringDocument ---

    def suggested_expiry(self, issued):
        """Pre-fill value for the expiry date: issue date + validity months."""
        return add_months(issued, self.validity_months())

    # --- Changes: check_values() and renew() come from ExpiringDocument ---

    def _save_version(self, by_user, changed_at):
        """renew() calls this first. The old values and the old result go in a CredentialVersion."""
        CredentialVersion.objects.create(
            credential=self,
            old_number=self.number,
            old_issued=self.issued,
            old_expires=self.expires,
            old_result=self.result,
            changed_by=by_user,
            changed_at=changed_at,
        )

    # --- Notices: make_notice() comes from ExpiringDocument ---

    def _notices(self):
        return self.notifications

    def _notice_extra(self):
        """A guard's notice also names the guard, for the notifications page."""
        return {"guard": self.guard}


class License(Credential):
    """LESP license."""

    class Meta:
        proxy = True
        default_permissions = ()

    def validity_months(self):
        return c.LICENSE_VALIDITY_MONTHS


class Clearance(Credential):
    """NBI clearance and police clearance."""

    class Meta:
        proxy = True
        default_permissions = ()

    def validity_months(self):
        return c.CLEARANCE_VALIDITY_MONTHS


class MedicalCert(Credential):
    """Drug test and neuro-psychiatric exam. The only sensitive kind."""

    class Meta:
        proxy = True
        default_permissions = ()

    def validity_months(self):
        if self.doc_type == c.NEURO_EXAM:
            return c.NEURO_EXAM_VALIDITY_MONTHS
        return c.DRUG_TEST_VALIDITY_MONTHS

    def is_sensitive(self):
        return True

    def uses_result(self):
        return True

    def row(self, unlocked=False):
        """POLYMORPHISM: the parent row plus the result, hidden until a step-up."""
        row = super().row(unlocked)
        row["result"] = self.result if unlocked else "Locked"
        return row

    def renew(self, number, issued, expires, by_user, changed_at=None, result=None):
        """POLYMORPHISM: a new medical exam also has a new result."""
        resolved = super().renew(number, issued, expires, by_user, changed_at)
        if result is not None:
            self.result = result
            self.save()
        return resolved


class TrainingCert(Credential):
    """Basic Security Guard Course certificate."""

    class Meta:
        proxy = True
        default_permissions = ()

    def validity_months(self):
        return c.TRAINING_VALIDITY_MONTHS


# typed() uses this to pick the right proxy class for a row.
CREDENTIAL_CLASSES = {
    c.LICENSE: License,
    c.CLEARANCE: Clearance,
    c.MEDICAL: MedicalCert,
    c.TRAINING: TrainingCert,
}


class CredentialVersion(AppendOnlyRecord):
    """The old values of a credential, saved by renew(). Never changes."""

    credential = models.ForeignKey(Credential, on_delete=models.PROTECT, related_name="versions")
    old_number = models.CharField(max_length=50)
    old_issued = models.DateField()
    old_expires = models.DateField()
    # Only medical certificates have a result. Sensitive.
    old_result = models.CharField(max_length=100, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="credential_changes"
    )
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.credential.doc_type} before {self.changed_at:%Y-%m-%d}"

    def new_values(self):
        """
        The number and dates that replaced these old values: the old values of
        the next version, or the values on file now if this is the newest one.
        Never the result. The guard history and the SOSIA report both use this.
        """
        later = (
            self.credential.versions.filter(
                Q(changed_at__gt=self.changed_at) | Q(changed_at=self.changed_at, id__gt=self.id)
            )
            .order_by("changed_at", "id")
            .first()
        )
        if later is None:
            now = self.credential
            return {"number": now.number, "issued": now.issued, "expires": now.expires}
        return {"number": later.old_number, "issued": later.old_issued, "expires": later.old_expires}


class EmploymentStatusChange(AppendOnlyRecord):
    """One change of a guard's employment status. Never edited or deleted."""

    guard = models.ForeignKey(Guard, on_delete=models.PROTECT, related_name="status_changes")
    status = models.CharField(max_length=20, choices=c.EMPLOYMENT_STATUS_CHOICES)
    effective_date = models.DateField()
    reason = models.CharField(max_length=40, choices=c.STATUS_REASON_CHOICES)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="status_changes_recorded"
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["-effective_date", "-recorded_at", "-id"]

    def __str__(self):
        return f"{self.guard.full_name}: {self.status} from {long_date(self.effective_date)}"

    def as_status(self):
        """FACTORY: this change as its status object (ActiveStatus, OnLeaveStatus, ...)."""
        return STATUS_CLASSES[self.status](self)


# ---------------------------------------------------------------------------
# Expiry notices: an abstract base, then one model per kind of document
# ---------------------------------------------------------------------------


class ExpiryNotice(models.Model):
    """ABSTRACTION: an in-app expiry notice for one document in one band. It has no table."""

    NEW = "New"
    SEEN = "Seen"
    RESOLVED = "Resolved"
    STATUS_ORDER = [NEW, SEEN, RESOLVED]
    STATUS_CHOICES = [(status, status) for status in STATUS_ORDER]
    BAND_CHOICES = list(c.NOTICE_BAND_LABELS.items())
    # A notice is open until its document is renewed with a new expiry date.
    OPEN = [NEW, SEEN]
    # The status filter of the notifications page: key -> (label, statuses).
    STATUS_FILTERS = {
        "open": ("Open (new and seen)", OPEN),
        "new": ("New", [NEW]),
        "seen": ("Seen", [SEEN]),
        "resolved": ("Resolved", [RESOLVED]),
        "all": ("All", STATUS_ORDER),
    }
    DEFAULT_FILTER = "open"

    # Each kind of notice sets these: its name in a URL, and what it is about.
    KIND = ""
    ABOUT = ""

    band = models.PositiveSmallIntegerField(choices=BAND_CHOICES)
    expiry_date = models.DateField()
    created_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=NEW)

    class Meta:
        abstract = True

    def __str__(self):
        return self.message()

    def delete(self, *args, **kwargs):
        raise RecordLockedError("Notices cannot be deleted.")

    # --- What every kind of notice must answer (POLYMORPHISM) ---

    def _who(self):
        """Whose document it is: a guard's name, or the agency."""
        raise NotImplementedError("Each kind of notice says whose document it is.")

    def _document_name(self):
        """The name of the document, like "NBI Clearance"."""
        raise NotImplementedError("Each kind of notice names its document.")

    def get_absolute_url(self):
        """The page where HR acts on this notice."""
        raise NotImplementedError("Each kind of notice has its own page.")

    def _owner_gets_notices(self):
        """True if whoever owns the document still gets notices. A child can say no."""
        return True

    @classmethod
    def with_details(cls, rows):
        """These rows, with what message() and is_shown() read loaded in a few queries."""
        return rows

    # --- Shared steps, the same for every notice ---

    def message(self):
        """Document name and date only. Never a result."""
        who, document = self._who(), self._document_name()
        when = nice_date(self.expiry_date)
        if self.band == c.EXPIRED_BAND:
            return f"{who}: {document} has expired ({when})."
        days = (self.expiry_date - self.created_date).days
        unit = "day" if days == 1 else "days"
        return f"{who}: {document} expires in {days} {unit} ({when})."

    def is_urgent(self):
        """7 day, 1 day, and expired notices go in the dashboard banner."""
        return self.band in c.URGENT_BANDS

    def is_open(self):
        return self.status in self.OPEN

    def is_shown(self):
        """
        Open notices of an owner who no longer gets notices (a guard who left)
        are hidden from the notifications page, the navbar count and the
        banner. The notice itself does not change.
        """
        return not self.is_open() or self._owner_gets_notices()

    def move_to(self, new_status):
        """
        ENCAPSULATION: the status only moves forward (New, Seen, Resolved).
        Returns the old status so the caller can log the change.
        """
        if self.STATUS_ORDER.index(new_status) <= self.STATUS_ORDER.index(self.status):
            raise ValidationError(f"A notice cannot go from {self.status} to {new_status}.")
        old_status = self.status
        self.status = new_status
        self.save()
        return old_status

    def mark_seen(self):
        return self.move_to(self.SEEN)

    def resolve(self):
        return self.move_to(self.RESOLVED)


class Notification(ExpiryNotice):
    """
    An in-app expiry notice for one guard's credential in one band.
    The unique constraint makes sure a band is never sent twice.
    """

    guard = models.ForeignKey(Guard, on_delete=models.PROTECT, related_name="notifications")
    credential = models.ForeignKey(
        Credential, on_delete=models.PROTECT, related_name="notifications"
    )

    class Meta:
        ordering = ["-created_date", "band"]
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "band", "expiry_date"], name="one_notice_per_band"
            ),
        ]

    KIND = "guard"
    ABOUT = "Guard document"

    def _who(self):
        return self.guard.full_name

    def _document_name(self):
        return self.credential.doc_type

    def get_absolute_url(self):
        return reverse("guard_profile", args=[self.guard_id])

    def _owner_gets_notices(self):
        """POLYMORPHISM: a guard who left (Resigned, Let go) gets no notices."""
        return self.guard.employment_status().gets_notices()

    @classmethod
    def with_details(cls, rows):
        return rows.select_related("guard", "credential").prefetch_related("guard__status_changes")


# ---------------------------------------------------------------------------
# Agency permits: the agency's own papers, like its License to Operate
# ---------------------------------------------------------------------------


class AgencyPermit(ExpiringDocument):
    """
    One permit of the agency itself. The kind field says which proxy class
    (only LicenseToOperate for now) the row belongs to. One row per kind.
    Permits can be added and renewed. They can never be deleted.
    number, issued and expires come from ExpiringDocument.
    """

    kind = models.CharField(max_length=20, choices=c.PERMIT_KIND_CHOICES)
    issuer = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["kind"]
        # No "change" or "delete" permission. Changes go through renew().
        default_permissions = ("add", "view")
        constraints = [
            models.UniqueConstraint(fields=["kind"], name="one_permit_per_kind"),
        ]

    def __str__(self):
        return f"{self.name()} {self.number}"

    def delete(self, *args, **kwargs):
        raise RecordLockedError("Agency permits cannot be deleted. Renew them instead.")

    def name(self):
        """Like "License to Operate (LTO)"."""
        return self.get_kind_display()

    def typed(self):
        """Return this row as its proxy class, like typed() on Credential. No extra query."""
        self.__class__ = PERMIT_TYPES[self.kind]
        return self

    @classmethod
    def for_kind(cls, kind):
        """FACTORY: an unsaved permit of the right proxy class, like create_account()."""
        return cls(kind=kind).typed()

    @classmethod
    def on_file(cls, kind):
        """The permit of this kind as its proxy class, or None if it is not on file."""
        permit = cls.objects.filter(kind=kind).first()
        return permit.typed() if permit else None

    @classmethod
    def usable(cls, kind):
        """The permit of this kind if it is on file and not expired, or None."""
        permit = cls.on_file(kind)
        if permit is None or permit.status() == c.EXPIRED:
            return None
        return permit

    @classmethod
    def add(cls, kind, number, issued, expires, issuer=""):
        """The only way to put a permit on file. Returns the new permit."""
        if kind not in PERMIT_TYPES:
            raise ValidationError(f"{kind} is not an agency permit GuardReady tracks.")
        if cls.objects.filter(kind=kind).exists():
            name = cls.for_kind(kind).name()
            raise ValidationError(f"{name} is already on file. Renew it instead.")
        cls.check_values(number, issued, expires)
        permit = cls(
            kind=kind, number=number.strip(), issuer=issuer, issued=issued, expires=expires
        ).typed()
        permit.save()
        return permit

    @classmethod
    def overview(cls, kind):
        """
        A short status for the dashboard and the compliance request form, even
        when the permit is not on file: its name, the permit, status, text, color.
        """
        permit = cls.on_file(kind)
        status = permit.status() if permit else c.NOT_ON_FILE
        return {
            "name": cls.for_kind(kind).name(),
            "slug": slugify(kind),
            "permit": permit,
            "status": status,
            "text": permit.expiry_text() if permit else c.PERMIT_MISSING_TEXT,
            "color": c.PERMIT_ALERT_COLORS[status],
        }

    # --- renew() comes from ExpiringDocument ---

    def _save_version(self, by_user, changed_at):
        """renew() calls this first. The old values go in an AgencyPermitVersion."""
        AgencyPermitVersion.objects.create(
            permit=self,
            old_number=self.number,
            old_issued=self.issued,
            old_expires=self.expires,
            changed_by=by_user,
            changed_at=changed_at,
        )

    # --- make_notice() comes from ExpiringDocument ---

    def _notices(self):
        return self.notices


class LicenseToOperate(AgencyPermit):
    """The agency's License to Operate (LTO), a PNP permit."""

    class Meta:
        proxy = True
        default_permissions = ()

    def validity_months(self):
        """The longest period by law (RA 11917, Sec. 7). HR always types the real expiry date."""
        return c.LTO_VALIDITY_MONTHS


# typed() uses this to pick the right proxy class, like ACCOUNT_TYPES in the bank activity.
PERMIT_TYPES = {
    c.LTO: LicenseToOperate,
}


class AgencyPermitVersion(AppendOnlyRecord):
    """The old values of an agency permit, saved by renew(). Never changes."""

    permit = models.ForeignKey(AgencyPermit, on_delete=models.PROTECT, related_name="versions")
    old_number = models.CharField(max_length=50)
    old_issued = models.DateField()
    old_expires = models.DateField()
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="permit_changes"
    )
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.permit.name()} before {self.changed_at:%Y-%m-%d}"


class AgencyNotice(ExpiryNotice):
    """An in-app expiry notice for one agency permit in one band. Never sent twice."""

    permit = models.ForeignKey(AgencyPermit, on_delete=models.PROTECT, related_name="notices")

    class Meta:
        ordering = ["-created_date", "band"]
        constraints = [
            models.UniqueConstraint(
                fields=["permit", "band", "expiry_date"], name="one_agency_notice_per_band"
            ),
        ]

    KIND = "agency"
    ABOUT = "Agency permit"

    def _who(self):
        return c.AGENCY_NOTICE_NAME

    def _document_name(self):
        return self.permit.name()

    def get_absolute_url(self):
        return reverse("agency_permits")

    @classmethod
    def with_details(cls, rows):
        return rows.select_related("permit")


# The notifications page and its URLs pick the notice class from its KIND,
# like ACCOUNT_TYPES in the bank activity.
NOTICE_TYPES = {
    Notification.KIND: Notification,
    AgencyNotice.KIND: AgencyNotice,
}
