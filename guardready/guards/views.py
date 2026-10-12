"""
Dashboard, guard list, add guard, and guard profile.

Views only check access, call model methods, and render a template.
"""

from datetime import timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.access import access_required, can_step_up, can_view_guard, deny, own_guard
from accounts.stepup import is_unlocked, seconds_left
from audit.models import AuditEntry
from audit.services import log_event, mark_target

from . import constants as c
from .forms import GuardForm
from .models import Guard
from .services import all_guards, filter_by_readiness, readiness_counts, search_guards


@access_required("guards.view_dashboard")
def dashboard(request):
    guards = list(all_guards())
    counts = readiness_counts(guards)
    cards = [
        {"label": level, "count": counts[level], "color": c.STATUS_COLORS[level]}
        for level in c.READINESS_LEVELS
    ]
    return render(request, "guards/dashboard.html", {"total": len(guards), "cards": cards})


@access_required("guards.view_all_guards")
def guard_list(request):
    query = request.GET.get("q", "").strip()
    readiness = request.GET.get("status", "")
    guards = filter_by_readiness(search_guards(query), readiness)
    context = {
        "guards": guards,
        "query": query,
        "readiness": readiness,
        "levels": c.READINESS_LEVELS,
    }
    return render(request, "guards/guard_list.html", context)


@access_required("guards.add_guard")
def add_guard(request):
    """
    Add a new guard. Admin/HR only.

    The form collects the sensitive fields, so a successful save is logged as
    a sensitive CREATE entry. A refused save is logged too, with the reasons.
    """
    form = GuardForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            guard = form.save()
            log_event(
                request,
                AuditEntry.CREATE,
                "Guard",
                guard.pk,
                sensitive=True,
                details=f"Added {guard.summary()}. No documents on file yet.",
            )
            messages.success(
                request,
                f"{guard.full_name} was added. Readiness: {guard.readiness()}. "
                f"The next step is to put his documents on file.",
            )
            return redirect("guard_profile", pk=guard.pk)

        log_event(
            request,
            AuditEntry.CREATE,
            "Guard",
            "",
            outcome=AuditEntry.DENIED,
            sensitive=True,
            details=f"Refused: {form.problems()}",
        )
    return render(request, "guards/guard_form.html", {"form": form})


@access_required("guards.view_own_record")
def my_record(request):
    """The guard's menu link. Sends him to his own profile."""
    guard = own_guard(request.user)
    if guard is None:
        deny(request, "No guard record is linked to this account.")
    return redirect("guard_profile", pk=guard.pk)


@access_required("guards.view_all_guards", "guards.view_own_record")
def guard_profile(request, pk):
    guard = get_object_or_404(Guard.objects.prefetch_related("credentials"), pk=pk)
    # Zero Trust: checked on the object itself, not just hidden from the menu.
    if not can_view_guard(request.user, guard):
        deny(request, "A guard can only open his own records.", "Guard", guard.pk)

    unlocked = is_unlocked(request, guard)
    mark_target(request, "Guard", guard.pk, sensitive=unlocked)

    left = seconds_left(request, guard) if unlocked else 0
    context = {
        "guard": guard,
        "readiness": guard.readiness(),
        "block_reasons": guard.block_reasons(),
        "earliest": guard.earliest_expiry(),
        "assignment": guard.current_assignment(),
        "rows": guard.credential_rows(unlocked),
        "unlocked": unlocked,
        "can_unlock": can_step_up(request.user, guard),
        "personal": guard.personal_details() if unlocked else None,
        "seconds_left": left,
        "locks_at": timezone.localtime() + timedelta(seconds=left),
    }
    return render(request, "guards/guard_profile.html", context)
