"""
Reports. Admin/HR only.

Compliance reports (Stage 5, audit.view_audit_log): printable reports for a
government office or a client. Guard reports (Stage 4): the summary of every
guard and the report of one guard (reports.view_summary_report), and the
attendance and evaluation forms (reports.record_performance).

These views check access, call the forms, the report classes and the
services, and render. Each report's REPORT entry is written by log_report().
"""

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.access import access_required, can_view_guard, deny
from audit.models import AuditEntry
from audit.services import log_event, mark_target
from guards.dates import long_date
from guards.models import Guard

from .compliance import GOVERNMENT_REPORTS, compliance_report_class
from .constants import LATE_GRACE_MINUTES
from .forms import AttendanceForm, EvaluationForm, ReportPeriodForm, SummaryFilterForm
from .guard_reports import GuardReport, SummaryReport
from .services import log_report, save_attendance, save_evaluation

# ---------------------------------------------------------------------------
# Compliance reports (Stage 5)
# ---------------------------------------------------------------------------


@access_required("audit.view_audit_log")
def choose_office(request):
    """Print Government Report, step 1: pick the office. Its own page, since there is no JavaScript."""
    mark_target(request, "ComplianceReport", "government")
    offices = [report_class.describe() for report_class in GOVERNMENT_REPORTS]
    return render(request, "reports/compliance_offices.html", {"offices": offices})


@access_required("audit.view_audit_log")
def compliance_request(request, kind):
    """
    The request form. Once it is valid and the password is right, build the
    report, write ONE REPORT audit entry, then show the print-ready page.
    """
    report_class = compliance_report_class(kind)
    if report_class is None:
        raise Http404("There is no compliance report of that kind.")
    mark_target(request, "ComplianceReport", kind)

    form = report_class.make_form(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        # Zero Trust: being logged in is not enough to release personal data.
        if not form.password_ok():
            deny(
                request,
                "Wrong password. The compliance report was not generated.",
                "ComplianceReport",
                kind,
            )

        report = report_class.from_form(form, request.user).build()
        # Written before the page renders. Its ID becomes the report number.
        log_report(request, report, kind)
        return render(request, "reports/compliance_report.html", {"report": report})

    context = {
        "form": form,
        "report_info": report_class.describe(),
        # Shown when the header would print "LTO not on file".
        "lto_warning": report_class.lto_warning(),
    }
    return render(request, "reports/compliance_form.html", context)


# ---------------------------------------------------------------------------
# Guard reports (Stage 4)
# ---------------------------------------------------------------------------


def report_guard(request, pk):
    """The guard from the URL, checked on the object itself (Zero Trust)."""
    guard = get_object_or_404(Guard, pk=pk)
    if not can_view_guard(request.user, guard):
        deny(request, "You cannot open this guard's records.", "Guard", guard.pk)
    return guard


def csv_download(report):
    """The built and numbered report as a CSV file. Report.write_csv() writes it."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{report.csv_file_name()}"'
    report.write_csv(response)
    return response


def refuse_csv(request, target_type, target_id, form):
    """A CSV request with a bad period is refused and logged. Nothing is made."""
    log_event(
        request,
        AuditEntry.REPORT,
        target_type,
        target_id,
        outcome=AuditEntry.DENIED,
        details=f"Refused, no file was made. {form.problems()}",
    )
    messages.error(request, f"The CSV file was not made. {form.problems()}")


@access_required("reports.view_summary_report")
def summary_report(request):
    """Every current guard (or every guard who left), one row each, for the period."""
    mark_target(request, "SummaryReport", "page")
    form = SummaryFilterForm(request.GET or None)
    filters = form.filters()
    report = SummaryReport.from_filters(filters, request.user).build()
    context = {"form": form, "filters": filters, "report": report}
    return render(request, "reports/summary_report.html", context)


@access_required("reports.view_summary_report")
@require_POST
def summary_report_csv(request):
    """The summary as a CSV file. Each download writes one REPORT entry with a new number."""
    form = SummaryFilterForm(request.POST)
    if not form.is_valid():
        refuse_csv(request, SummaryReport.TARGET_TYPE, "csv", form)
        return redirect("summary_report")
    filters = form.filters()
    report = SummaryReport.from_filters(filters, request.user).build()
    log_report(request, report, filters["show"])
    return csv_download(report)


@access_required("reports.view_summary_report")
def guard_report(request, pk):
    """One guard's punctuality and evaluations for the period (the Report tab)."""
    guard = report_guard(request, pk)
    mark_target(request, GuardReport.TARGET_TYPE, guard.pk)
    form = ReportPeriodForm(request.GET or None)
    filters = form.filters()
    context = {
        "guard": guard,
        "readiness": guard.readiness(),
        "employment": guard.employment_status(),
        "form": form,
        "filters": filters,
        "report": GuardReport.from_filters(guard, filters, request.user).build(),
    }
    return render(request, "reports/guard_report.html", context)


@access_required("reports.view_summary_report")
@require_POST
def guard_report_csv(request, pk):
    """One guard's report as a CSV file. Each download writes one REPORT entry."""
    guard = report_guard(request, pk)
    form = ReportPeriodForm(request.POST)
    if not form.is_valid():
        refuse_csv(request, GuardReport.TARGET_TYPE, guard.pk, form)
        return redirect("guard_report", pk=guard.pk)
    report = GuardReport.from_filters(guard, form.filters(), request.user).build()
    log_report(request, report, guard.pk)
    return csv_download(report)


@access_required("reports.record_performance")
def record_attendance(request, pk):
    """Record one duty. AttendanceRecord.check_duty() decides, and a refusal is logged."""
    guard = report_guard(request, pk)
    mark_target(request, "Guard", guard.pk)
    form = AttendanceForm(guard, request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            record = save_attendance(request, guard, form)
            messages.success(
                request, f"Attendance on {long_date(record.date)} was saved: {record.result_text()}."
            )
            return redirect("guard_report", pk=guard.pk)
        log_event(
            request,
            AuditEntry.CREATE,
            "Guard",
            guard.pk,
            outcome=AuditEntry.DENIED,
            details=f"Refused, nothing was saved. {form.problems()}",
        )
    context = {
        "guard": guard,
        "form": form,
        "posting": guard.current_assignment(),
        "grace_minutes": LATE_GRACE_MINUTES,
    }
    return render(request, "reports/attendance_form.html", context)


@access_required("reports.record_performance")
def add_evaluation(request, pk):
    """Add one character evaluation. Evaluation.check_values() decides, and a refusal is logged."""
    guard = report_guard(request, pk)
    mark_target(request, "Guard", guard.pk)
    form = EvaluationForm(guard, request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            evaluation = save_evaluation(request, guard, form)
            messages.success(
                request,
                f"The evaluation dated {long_date(evaluation.date)} was saved. "
                f"Average score: {evaluation.average():.2f}.",
            )
            return redirect("guard_report", pk=guard.pk)
        log_event(
            request,
            AuditEntry.CREATE,
            "Guard",
            guard.pk,
            outcome=AuditEntry.DENIED,
            details=f"Refused, nothing was saved. {form.problems()}",
        )
    return render(request, "reports/evaluation_form.html", {"guard": guard, "form": form})
