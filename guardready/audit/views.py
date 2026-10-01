"""The audit log screen. Admin/HR only. Read only: there is no edit or delete."""

from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils.dateparse import parse_date

from accounts.access import access_required

from .models import AuditEntry
from .services import filter_entries


@access_required("audit.view_audit_log")
def audit_log(request):
    username = request.GET.get("user", "")
    action = request.GET.get("action", "")
    day = read_date(request.GET.get("date", ""))
    sensitive_only = request.GET.get("sensitive") == "on"

    entries = filter_entries(username, action, day, sensitive_only)
    page = Paginator(entries, 50).get_page(request.GET.get("page"))

    # Keep the filters when moving between pages.
    filters = request.GET.copy()
    filters.pop("page", None)

    context = {
        "page": page,
        "usernames": AuditEntry.objects.order_by("username").values_list("username", flat=True).distinct(),
        "actions": AuditEntry.ACTIONS,
        "chosen_user": username,
        "chosen_action": action,
        "chosen_date": day.isoformat() if day else "",
        "sensitive_only": sensitive_only,
        "filter_query": filters.urlencode(),
    }
    return render(request, "audit/audit_log.html", context)


def read_date(text):
    """Turn "2026-10-01" into a date. Anything invalid becomes None."""
    try:
        return parse_date(text)
    except ValueError:
        return None
