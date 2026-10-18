"""
Service functions for deployment. Business rules stay in the models.

Post.refusal_reasons() decides whether a guard can be posted, Assignment.start()
opens a posting, and Assignment.close() ends one. These functions only
coordinate: they call those methods and write the audit entries.
"""

from django.db import transaction

from audit.models import AuditEntry
from audit.services import log_event
from guards.dates import day_count, long_date
from guards.services import all_guards, filter_by_employment

from .models import Assignment


def guard_choices(post, show):
    """
    The guards the assign page lists: current guards by default, or the guards
    who left. Each comes with his open posting and the reasons he would be
    refused here, so HR can see them first. assign_guard() checks again on submit.
    """
    return [
        {
            "guard": guard,
            "posting": guard.current_assignment(),
            "reasons": post.refusal_reasons(guard),
        }
        for guard in filter_by_employment(all_guards(), show)
    ]


@transaction.atomic
def assign_guard(request, guard, post):
    """
    Post a guard here from today, or refuse. Post.refusal_reasons() decides.
    Every attempt writes one ASSIGN entry about the guard: Success, or Denied
    with every reason. A refused guard is never posted, and there is no override.
    Returns the new assignment (None if refused) and the reasons (empty if posted).
    """
    reasons = post.refusal_reasons(guard)
    if reasons:
        log_event(
            request,
            AuditEntry.ASSIGN,
            "Guard",
            guard.pk,
            outcome=AuditEntry.DENIED,
            details=f"Refused to post {guard.summary()} at {post}. Reasons: {'; '.join(reasons)}.",
        )
        return None, reasons

    assignment = Assignment.start(guard, post, request.user)
    log_event(
        request,
        AuditEntry.ASSIGN,
        "Guard",
        guard.pk,
        details=(
            f"Posted {guard.summary()} at {post}, starting {long_date(assignment.start_date)}. "
            f"Readiness: {guard.readiness()}."
        ),
    )
    return assignment, []


@transaction.atomic
def close_posting(request, assignment):
    """
    End a posting today through Assignment.close(), which works only once,
    and log an UPDATE. A closed posting raises RecordLockedError.
    """
    assignment.close()
    log_event(
        request,
        AuditEntry.UPDATE,
        "Assignment",
        assignment.pk,
        details=(
            f"Ended the posting of {assignment.guard.summary()} at {assignment.post} "
            f"on {long_date(assignment.end_date)}, after {day_count(assignment.days_served())}."
        ),
    )
