"""
Guards app models.

INHERITANCE: Person (abstract) -> Employee (abstract) -> Guard (concrete).
Only Guard gets a database table. It has the fields of all three classes.

Credential is one table with four proxy subclasses: License, Clearance,
MedicalCert, and TrainingCert. A proxy shares the same table but has its
own Python methods (POLYMORPHISM).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from audit.models import AppendOnlyRecord, RecordLockedError

from . import constants as c
from .dates import add_months, nice_date


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
    }


# ---------------------------------------------------------------------------
# Credentials: one table, four proxy classes
# ---------------------------------------------------------------------------


class Credential(models.Model):
    """
    One document of one guard. The kind field says which proxy class
    (License, Clearance, MedicalCert, TrainingCert) the row belongs to.
    Credentials can be added and renewed. They can never be deleted.
    """

    guard = models.ForeignKey(Guard, on_delete=models.PROTECT, related_name="credentials")
    kind = models.CharField(max_length=20, choices=c.CREDENTIAL_KIND_CHOICES)
    doc_type = models.CharField(max_length=40, choices=c.DOCUMENT_CHOICES)
    number = models.CharField(max_length=50)
    issuer = models.CharField(max_length=100, blank=True)
    issued = models.DateField()
    expires = models.DateField()
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

    # --- Methods the proxy classes override (POLYMORPHISM) ---

    def validity_months(self):
        """Every proxy class must override this. Call typed() first."""
        raise NotImplementedError("Call typed() to get the proxy class first.")

    def notice_days(self):
        """Days before expiry when a notice is sent. One kind can override it later."""
        return list(c.NOTICE_DAYS)

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
        }

    # --- Status ---

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
        The notice band this credential is in today:
        60, 30, 14, 7, 1, 0 (expired), or None if no notice is due yet.
        """
        days = self.days_left()
        if days <= 0:
            return c.EXPIRED_BAND
        bands_reached = [band for band in self.notice_days() if days <= band]
        if not bands_reached:
            return None
        return min(bands_reached)

    def suggested_expiry(self, issued):
        """Pre-fill value for the expiry date: issue date + validity months."""
        return add_months(issued, self.validity_months())

    # --- Changes ---

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
        ENCAPSULATION: the only way to change a credential's number and dates.
        The old values are saved in a CredentialVersion first.
        changed_at is only passed by seed_demo to record a past renewal.
        """
        Credential.check_values(number, issued, expires)
        CredentialVersion.objects.create(
            credential=self,
            old_number=self.number,
            old_issued=self.issued,
            old_expires=self.expires,
            old_result=self.result,
            changed_by=by_user,
            changed_at=changed_at or timezone.now(),
        )
        self.number = number.strip()
        self.issued = issued
        self.expires = expires
        self.save()


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
        super().renew(number, issued, expires, by_user, changed_at)
        if result is not None:
            self.result = result
            self.save()


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


# ---------------------------------------------------------------------------
# Expiry notifications
# ---------------------------------------------------------------------------


class Notification(models.Model):
    """
    An in-app expiry notice for one credential in one band.
    The unique constraint makes sure a band is never sent twice.
    """

    NEW = "New"
    SEEN = "Seen"
    RESOLVED = "Resolved"
    STATUS_ORDER = [NEW, SEEN, RESOLVED]
    STATUS_CHOICES = [(status, status) for status in STATUS_ORDER]
    BAND_CHOICES = list(c.NOTICE_BAND_LABELS.items())

    guard = models.ForeignKey(Guard, on_delete=models.PROTECT, related_name="notifications")
    credential = models.ForeignKey(
        Credential, on_delete=models.PROTECT, related_name="notifications"
    )
    band = models.PositiveSmallIntegerField(choices=BAND_CHOICES)
    expiry_date = models.DateField()
    created_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=NEW)

    class Meta:
        ordering = ["-created_date", "band"]
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "band", "expiry_date"], name="one_notice_per_band"
            ),
        ]

    def __str__(self):
        return self.message()

    def delete(self, *args, **kwargs):
        raise RecordLockedError("Notices cannot be deleted.")

    def message(self):
        """Document name and date only. Never a result."""
        doc_type = self.credential.doc_type
        when = nice_date(self.expiry_date)
        if self.band == c.EXPIRED_BAND:
            return f"{self.guard.full_name}: {doc_type} has expired ({when})."
        days = (self.expiry_date - self.created_date).days
        unit = "day" if days == 1 else "days"
        return f"{self.guard.full_name}: {doc_type} expires in {days} {unit} ({when})."

    def is_urgent(self):
        """7 day, 1 day, and expired notices go in the dashboard banner."""
        return self.band in c.URGENT_BANDS

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
