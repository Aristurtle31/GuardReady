"""
The audit log screen and the Security alerts page. Admin/HR only.
Read only: there is no edit or delete.
"""

from datetime import timedelta

from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.access import access_required
from guards.dates import long_datetime

from . import constants as c
from .alerts import ALERT_RULES
from .models import AuditEntry
from .services import filter_entries, mark_target


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


@access_required("audit.view_audit_log")
def security_alerts(request):
    """
    Alerts worked out just now from the last LOOKBACK_DAYS of the audit log.
    Nothing is saved. The page calls find() on each rule in ALERT_RULES, so
    there is no if/elif on the rule type. Opening it is logged as a VIEW.
    """
    mark_target(request, "SecurityAlerts", f"last {c.LOOKBACK_DAYS} days")
    since = timezone.now() - timedelta(days=c.LOOKBACK_DAYS)
    entries = list(AuditEntry.objects.filter(timestamp__gte=since))

    alerts = []
    checks = []
    for rule in ALERT_RULES:
        found = rule.find(entries)
        alerts.extend(found)
        checks.append((rule, len(found)))
    alerts.sort(key=lambda alert: alert.end, reverse=True)

    context = {
        "alerts": alerts,
        "checks": checks,
        "since": long_datetime(since, c.PH_TIME_ZONE),
        "lookback_days": c.LOOKBACK_DAYS,
    }
    return render(request, "audit/security_alerts.html", context)
