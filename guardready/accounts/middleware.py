"""
Zero Trust: idle timeout.

The time of the user's last request is kept in his session. If he comes
back after more than IDLE_TIMEOUT_SECONDS, this middleware logs a TIMEOUT
entry, logs him out, and sends him to the login page.
"""

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from audit.models import AuditEntry
from audit.services import is_static_request, log_event

LAST_ACTIVITY_KEY = "last_activity"


class IdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not is_static_request(request):
            now = time.time()
            idle_seconds = now - request.session.get(LAST_ACTIVITY_KEY, now)
            if idle_seconds > settings.IDLE_TIMEOUT_SECONDS:
                return self.time_out(request, idle_seconds)
            request.session[LAST_ACTIVITY_KEY] = now
        return self.get_response(request)

    def time_out(self, request, idle_seconds):
        log_event(
            request,
            AuditEntry.TIMEOUT,
            "User",
            request.user.pk,
            details=f"Logged out after {int(idle_seconds)} seconds idle.",
        )
        logout(request)
        messages.warning(request, "Your session ended because you were idle. Please log in again.")
        return redirect("login")
