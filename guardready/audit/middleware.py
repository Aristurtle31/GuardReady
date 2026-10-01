"""
Zero Trust: the audit middleware.

It runs after every request and writes one AuditEntry for:
- every page view (a GET that returned a page), and
- every refused request (a 403, or a view that refused and redirected).
Changes (POST requests) write their own entries inside the views.
Static files are skipped.
"""

from .models import AuditEntry
from .services import is_static_request, log_event


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if is_static_request(request):
            return response

        # Views say what was opened with mark_target(). Otherwise log the page.
        target_type, target_id = getattr(request, "audit_target", ("Page", request.path))
        page = f"{request.method} {request.get_full_path()}"
        refused_reason = getattr(request, "deny_reason", "")

        if response.status_code == 403 or refused_reason:
            reason = refused_reason or "Refused with status 403"
            log_event(
                request,
                AuditEntry.DENY,
                target_type,
                target_id,
                outcome=AuditEntry.DENIED,
                details=f"{reason}. ({page})",
            )
        elif request.method == "GET" and response.status_code == 200:
            log_event(
                request,
                AuditEntry.VIEW,
                target_type,
                target_id,
                sensitive=getattr(request, "audit_sensitive", False),
                details=page,
            )
        return response
