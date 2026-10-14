"""
Service functions for guards. Business rules stay in the models.

The save functions below only coordinate: they call the model methods
(add_credential(), AgencyPermit.add(), renew(), save()) and write the audit
entries, all inside one transaction. If any step fails, nothing is saved, not
even the log entry.
"""

from django.db import transaction
from django.db.models import Q

from audit.changes import ChangeSummary
from audit.models import AuditEntry
from audit.services import log_event

from . import constants as c
from .dates import long_date
from .models import AgencyPermit, Guard


def all_guards():
    """Every guard, with credentials and status changes loaded in two extra queries."""
    return Guard.objects.prefetch_related("credentials", "status_changes")


def search_guards(query):
    """Every word must match a first name, last name, or employee number."""
    guards = all_guards()
    for word in query.split():
        guards = guards.filter(
            Q(first_name__icontains=word)
            | Q(last_name__icontains=word)
            | Q(employee_no__icontains=word)
        )
    return guards


def filter_by_readiness(guards, readiness):
    """Keep only guards with this readiness. An unknown value keeps everyone."""
    if readiness not in c.READINESS_LEVELS:
        return list(guards)
    return [guard for guard in guards if guard.readiness() == readiness]


# The guard list filter. The value says whether we want guards who still count
# as current (Active or On leave) or the guards who left.
WANTS_CURRENT = {c.SHOW_CURRENT: True, c.SHOW_LEFT: False}


def filter_by_employment(guards, show):
    """
    Current guards (Active or On leave) by default, or the guards who left
    (Resigned or Let go). Each guard's status object decides.
    """
    wants_current = WANTS_CURRENT.get(show, True)
    return [
        guard for guard in guards
        if guard.employment_status().counts_as_current() == wants_current
    ]


def current_guards(guards=None):
    """Guards still employed (Active or On leave). Lists, counts and rosters use these."""
    return filter_by_employment(all_guards() if guards is None else guards, c.SHOW_CURRENT)


def employment_counts(guards):
    """How many guards have each employment status."""
    counts = {status: 0 for status in c.EMPLOYMENT_STATUSES}
    for guard in guards:
        counts[guard.employment_status().name] += 1
    return counts


def readiness_counts(guards):
    """How many guards are Cleared, Expiring soon, and Not cleared."""
    counts = {level: 0 for level in c.READINESS_LEVELS}
    for guard in guards:
        counts[guard.readiness()] += 1
    return counts


# ---------------------------------------------------------------------------
# Saving guards and documents (Add Guard, Edit Guard, Add, Renew or correct)
# ---------------------------------------------------------------------------


@transaction.atomic
def save_new_guard(request, page):
    """
    Save a new guard and every document section that was filled in, in one
    transaction, so a failed save never leaves half a guard. Logs one CREATE
    for the guard and one for each document.
    check_expiry() does not exist yet (Stage 2), so no notices are made here.
    """
    guard = page.new_guard()
    guard.save()
    summary = page.describe_new_guard()
    log_event(
        request,
        AuditEntry.CREATE,
        "Guard",
        guard.pk,
        sensitive=summary.sensitive,
        details=f"Added {guard.summary()}. {summary}.",
    )
    for form in page.filled_documents():
        save_new_document(request, guard, form)
    return guard


@transaction.atomic
def save_new_document(request, guard, form):
    """Put one document on file through Guard.add_credential(), and log a CREATE."""
    credential = guard.add_credential(form.doc_type, **form.values())
    summary = form.describe_new(ChangeSummary())
    log_event(
        request,
        AuditEntry.CREATE,
        "Credential",
        credential.pk,
        sensitive=summary.sensitive,
        details=f"Added {credential.doc_type} for {guard.summary()}. {summary}.",
    )
    return credential


@transaction.atomic
def save_renewal(request, credential, form):
    """
    Renew or correct one document through renew() (MedicalCert.renew() when
    the form has a result). renew() saves the old values in a
    CredentialVersion first. Logs an UPDATE with the changed fields.
    """
    summary = form.describe_changes(ChangeSummary())
    credential.renew(by_user=request.user, **form.values())
    log_event(
        request,
        AuditEntry.UPDATE,
        "Credential",
        credential.pk,
        sensitive=summary.sensitive,
        details=(
            f"Renewed or corrected {credential.doc_type} of {credential.guard.summary()}. "
            f"{summary}. The old values are kept in the history."
        ),
    )
    return summary


@transaction.atomic
def save_guard_edit(request, guard, forms, what):
    """
    Apply an edit made with one or more section forms, then log one UPDATE
    that lists the changed fields. Sensitive fields are named without their
    values. If nothing changed, nothing is saved or logged.
    Returns the ChangeSummary, so the view can name the changed fields.
    """
    summary = ChangeSummary()
    for form in forms:
        form.describe_changes(summary)
    if not summary:
        return summary

    for form in forms:
        form.save(commit=False)  # puts the new values on this guard
    guard.save()
    log_event(
        request,
        AuditEntry.UPDATE,
        "Guard",
        guard.pk,
        sensitive=summary.sensitive,
        details=f"Edited the {what} of {guard.summary()}. {summary}.",
    )
    return summary


@transaction.atomic
def save_status_change(request, guard, form):
    """
    Change a guard's employment status through Guard.change_employment_status(),
    then log one UPDATE with the old status, new status, effective date and
    reason, plus a closed posting or a login change if there was one.
    """
    old = guard.employment_status()
    new, effects = guard.change_employment_status(
        form.cleaned_data["status"],
        form.cleaned_data["reason"],
        form.cleaned_data["effective_date"],
        request.user,
    )
    details = (
        f'Employment status of {guard.summary()} from "{old}" to "{new}", '
        f'effective {long_date(new.effective_date)}, reason "{new.reason}".'
    )
    details += "".join(f" {effect}." for effect in effects)
    log_event(request, AuditEntry.UPDATE, "Guard", guard.pk, details=details)
    return new, effects


# ---------------------------------------------------------------------------
# Agency permits (Add, and Renew or correct)
# ---------------------------------------------------------------------------


@transaction.atomic
def save_new_permit(request, kind, form):
    """Put an agency permit on file through AgencyPermit.add(), and log a CREATE."""
    permit = AgencyPermit.add(kind, **form.values())
    summary = form.describe_new(ChangeSummary())
    log_event(
        request,
        AuditEntry.CREATE,
        "AgencyPermit",
        permit.pk,
        details=f"Added the agency's {permit.name()}. {summary}.",
    )
    return permit


@transaction.atomic
def save_permit_renewal(request, permit, form):
    """
    Renew or correct an agency permit through renew(), which saves the old
    values in an AgencyPermitVersion first. Logs an UPDATE with the changes.
    """
    summary = form.describe_changes(ChangeSummary())
    permit.renew(by_user=request.user, **form.values())
    log_event(
        request,
        AuditEntry.UPDATE,
        "AgencyPermit",
        permit.pk,
        details=(
            f"Renewed or corrected the agency's {permit.name()}. {summary}. "
            "The old values are kept in the history."
        ),
    )
    return summary
