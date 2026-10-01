"""Login, logout, the home redirect, and the step-up page."""

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from audit.models import AuditEntry
from audit.services import log_event, mark_target
from guards.models import Guard

from .access import access_required, can_step_up, deny
from .forms import LoginForm, StepUpForm
from .middleware import LAST_ACTIVITY_KEY
from .stepup import start_step_up


def login_view(request):
    """The only page that does not need a login."""
    if request.user.is_authenticated:
        return redirect("home")

    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            request.session[LAST_ACTIVITY_KEY] = time.time()
            log_event(request, AuditEntry.LOGIN, "User", user.pk)
            return redirect(safe_next_url(request) or "home")
        # Failed logins are logged too, with the username that was typed.
        log_event(
            request,
            AuditEntry.LOGIN,
            outcome=AuditEntry.DENIED,
            username=request.POST.get("username", "")[:150],
            details="Wrong username or password.",
        )
    return render(request, "accounts/login.html", {"form": form})


def safe_next_url(request):
    """Only follow ?next= if it points back to this site."""
    next_url = request.GET.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return ""


@require_POST
@access_required()
def logout_view(request):
    log_event(request, AuditEntry.LOGOUT, "User", request.user.pk)
    logout(request)
    messages.info(request, "You have logged out.")
    return redirect("login")


def home(request):
    """
    Send each role to its start page. The site address itself just leads
    to the login page, so a visitor who is not logged in is not logged as
    a refused attempt here. Every other page uses @access_required.
    """
    if not request.user.is_authenticated:
        return redirect("login")
    if request.user.has_perm("guards.view_dashboard"):
        return redirect("dashboard")
    if request.user.has_perm("guards.view_own_record"):
        return redirect("my_record")
    deny(request, "This account has no role.")


@access_required("guards.step_up_sensitive")
def step_up(request, guard_id):
    """Re-enter the password plus a reason to unlock one guard's sensitive data."""
    guard = get_object_or_404(Guard, pk=guard_id)
    if not can_step_up(request.user, guard):
        deny(request, "You can only unlock your own records.", "Guard", guard.pk)
    mark_target(request, "Guard", guard.pk)

    form = StepUpForm(request.user, request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            start_step_up(request, guard)
            log_event(
                request,
                AuditEntry.STEP_UP,
                "Guard",
                guard.pk,
                sensitive=True,
                details=f"Reason: {form.cleaned_data['reason']}",
            )
            messages.success(
                request,
                f"Sensitive records unlocked for {settings.STEP_UP_SECONDS} seconds.",
            )
            return redirect("guard_profile", pk=guard.pk)

        log_event(
            request,
            AuditEntry.STEP_UP,
            "Guard",
            guard.pk,
            outcome=AuditEntry.DENIED,
            sensitive=True,
            details=f"Refused: {form.problems()} Reason given: {request.POST.get('reason', '')[:200]}",
        )
    return render(request, "accounts/step_up.html", {"form": form, "guard": guard})
