"""Small helper functions for writing and reading the audit log."""

import ipaddress

from django.conf import settings

from accounts.roles import role_name

from .models import AuditEntry


def client_ip(request):
    """
    The user's IP address. Codespaces sits behind a proxy, so the real
    address is the first one in X-Forwarded-For when that header exists.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        candidate = forwarded.split(",")[0].strip()
    else:
        candidate = request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def is_static_request(request):
    """Static files (CSS) are not logged."""
    static_prefix = "/" + settings.STATIC_URL.lstrip("/")
    return request.path.startswith(static_prefix) or request.path == "/favicon.ico"


def mark_target(request, target_type, target_id, sensitive=False):
    """Views call this so the page view entry says what was opened."""
    request.audit_target = (target_type, str(target_id))
    request.audit_sensitive = sensitive


def log_event(
    request,
    action,
    target_type="",
    target_id="",
    outcome=AuditEntry.SUCCESS,
    sensitive=False,
    details="",
    username=None,
):
    """Write one audit entry. Who, role, session, and IP come from the request."""
    user = request.user if request.user.is_authenticated else None
    if username is None:
        username = user.username if user else "anonymous"
    return AuditEntry.objects.create(
        user=user,
        username=username,
        role=role_name(request.user),
        session_key=request.session.session_key or "",
        ip_address=client_ip(request),
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        outcome=outcome,
        sensitive=sensitive,
        details=details,
    )


def filter_entries(username="", action="", day=None, sensitive_only=False):
    """The audit log screen filters: user, action, date, sensitive only."""
    entries = AuditEntry.objects.all()
    if username:
        entries = entries.filter(username=username)
    if action:
        entries = entries.filter(action=action)
    if day:
        entries = entries.filter(timestamp__date=day)
    if sensitive_only:
        entries = entries.filter(sensitive=True)
    return entries
