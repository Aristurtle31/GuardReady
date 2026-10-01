"""
Audit app models.

AppendOnlyRecord is the abstract parent of every record that must never
change once it is saved. AuditEntry is the Zero Trust log itself.
"""

from django.conf import settings
from django.db import models


class RecordLockedError(Exception):
    """Raised when code tries to edit or delete a locked record."""


class AppendOnlyQuerySet(models.QuerySet):
    """Blocks bulk edits and bulk deletes, for example AuditEntry.objects.all().delete()."""

    def update(self, **kwargs):
        raise RecordLockedError("These records are append only. They cannot be edited.")

    def delete(self):
        raise RecordLockedError("These records are append only. They cannot be deleted.")


class AppendOnlyRecord(models.Model):
    """
    ABSTRACTION: an abstract model. It has no table of its own.
    Every child (AuditEntry, CredentialVersion, AttendanceRecord, Evaluation)
    can be created once and then never edited or deleted.
    """

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True
        # Django will not even create "change" and "delete" permissions.
        default_permissions = ("add", "view")

    def save(self, *args, **kwargs):
        # _state.adding is True only for a new row that is not saved yet.
        if not self._state.adding:
            raise RecordLockedError(
                f"{self.__class__.__name__} is append only. It cannot be edited."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RecordLockedError(
            f"{self.__class__.__name__} is append only. It cannot be deleted."
        )


class AuditEntry(AppendOnlyRecord):
    """One line in the audit log. Fields follow spec section 6."""

    # Actions
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    VIEW = "VIEW"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    ASSIGN = "ASSIGN"
    STEP_UP = "STEP_UP"
    DENY = "DENY"
    TIMEOUT = "TIMEOUT"
    REPORT = "REPORT"
    ACTIONS = [LOGIN, LOGOUT, VIEW, CREATE, UPDATE, ASSIGN, STEP_UP, DENY, TIMEOUT, REPORT]
    ACTION_CHOICES = [(action, action) for action in ACTIONS]

    # Outcomes
    SUCCESS = "Success"
    DENIED = "Denied"
    OUTCOME_CHOICES = [(SUCCESS, SUCCESS), (DENIED, DENIED)]

    # The entry ID is Django's automatic "id" field.
    timestamp = models.DateTimeField(auto_now_add=True)
    # PROTECT: a user who appears in the log can never be deleted.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )
    username = models.CharField(max_length=150)
    role = models.CharField(max_length=50)
    session_key = models.CharField(max_length=40, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.CharField(max_length=200, blank=True)
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES, default=SUCCESS)
    sensitive = models.BooleanField(default=False)
    details = models.TextField(blank=True)

    class Meta(AppendOnlyRecord.Meta):
        ordering = ["-timestamp", "-id"]
        verbose_name_plural = "audit entries"
        permissions = [("view_audit_log", "Can view the audit log")]

    def __str__(self):
        return f"#{self.pk} {self.username} {self.action} {self.outcome}"

    def target(self):
        """Target type and ID in one short string, for the log screen."""
        return f"{self.target_type} {self.target_id}".strip()

    def short_session(self):
        """Only the first 8 characters of the session key are shown on screen."""
        return self.session_key[:8]
