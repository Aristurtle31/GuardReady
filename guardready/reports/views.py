"""
Compliance reports: printable reports for a government office or a client.

Admin/HR only (audit.view_audit_log). These views check access, call the
report classes in compliance.py, write the REPORT audit entry, and render.
"""

from django.http import Http404
from django.shortcuts import render

from accounts.access import access_required, deny
from audit.models import AuditEntry
from audit.services import log_event, mark_target

from .compliance import GOVERNMENT_REPORTS, compliance_report_class


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
        entry = log_event(
            request,
            AuditEntry.REPORT,
            "ComplianceReport",
            kind,
            sensitive=True,
            details=report.log_details(),
        )
        report.assign_number(entry)
        return render(request, "reports/compliance_report.html", {"report": report})

    context = {
        "form": form,
        "report_info": report_class.describe(),
        # Shown when the header would print "LTO not on file".
        "lto_warning": report_class.lto_warning(),
    }
    return render(request, "reports/compliance_form.html", context)
