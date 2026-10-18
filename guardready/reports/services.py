"""
Service functions for reports. Business rules stay in the models and the
report classes.

These functions only coordinate: they save attendance and evaluations through
AttendanceRecord.record() and Evaluation.record(), and write the audit
entries. log_report() writes the one REPORT entry of a report.
"""

from django.db import transaction

from audit.models import AuditEntry
from audit.services import log_event
from guards.dates import long_date

from .models import AttendanceRecord, Evaluation


@transaction.atomic
def save_attendance(request, guard, form):
    """Record one duty through AttendanceRecord.record(), and log a CREATE."""
    record = AttendanceRecord.record(guard, by_user=request.user, **form.values())
    log_event(
        request,
        AuditEntry.CREATE,
        "AttendanceRecord",
        record.pk,
        details=(
            f"Recorded the attendance of {guard.summary()} on {long_date(record.date)} "
            f"at {record.post}: {record.result_text()}."
        ),
    )
    return record


@transaction.atomic
def save_evaluation(request, guard, form):
    """Add one evaluation through Evaluation.record(), and log a CREATE with the scores."""
    evaluation = Evaluation.record(guard, by_user=request.user, **form.values())
    scores = ", ".join(f"{category} {score}" for category, score in evaluation.scores().items())
    remarks = "with remarks" if evaluation.remarks else "no remarks"
    log_event(
        request,
        AuditEntry.CREATE,
        "Evaluation",
        evaluation.pk,
        details=(
            f"Added an evaluation of {guard.summary()} dated {long_date(evaluation.date)}: "
            f"{scores}. Average {evaluation.average():.2f}, {remarks}."
        ),
    )
    return evaluation


def log_report(request, report, target_id):
    """
    Write the REPORT entry before the report is shown or downloaded. Its ID
    becomes the report number (assign_number() works only once).
    """
    entry = log_event(
        request,
        AuditEntry.REPORT,
        report.TARGET_TYPE,
        target_id,
        sensitive=report.SENSITIVE,
        details=report.log_details(),
    )
    report.assign_number(entry)
    return entry
