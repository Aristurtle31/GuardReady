"""
Dashboard, guard list, add and edit guard, documents, guard profile, and the
agency's own permits.

Views only check access, call forms, services and model methods, and render
a template. Saving lives in guards/services.py.
"""

from datetime import timedelta

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.access import (
    access_required,
    can_step_up,
    can_view_guard,
    deny,
    deny_until_step_up,
    own_guard,
)
from accounts.stepup import is_unlocked, seconds_left
from audit.models import AuditEntry
from audit.services import log_event, mark_target

from . import constants as c
from .forms import (
    AddGuardForms,
    GuardBasicForm,
    GuardGovernmentForm,
    GuardPersonalForm,
    PermitForm,
    RenewPermitForm,
    StatusChangeForm,
    add_form_class,
    renew_form_class,
)
from .models import PERMIT_TYPES, AgencyPermit, AgencyPermitVersion, Credential, Guard
from .services import (
    all_guards,
    current_guards,
    employment_counts,
    filter_by_employment,
    filter_by_readiness,
    readiness_counts,
    save_guard_edit,
    save_new_document,
    save_new_guard,
    save_new_permit,
    save_permit_renewal,
    save_renewal,
    save_status_change,
    search_guards,
)


@access_required("guards.view_dashboard")
def dashboard(request):
    """Counts cover current guards only (Active or On leave). Guards who left are not counted."""
    guards = list(all_guards())
    current = current_guards(guards)
    counts = readiness_counts(current)
    cards = [
        {"label": level, "count": counts[level], "color": c.STATUS_COLORS[level]}
        for level in c.READINESS_LEVELS
    ]
    context = {
        "total": len(current),
        "cards": cards,
        "on_leave": employment_counts(current)[c.ON_LEAVE],
        "left": len(guards) - len(current),
        "show_left": c.SHOW_LEFT,
        # The agency's own License to Operate: valid until a date, or a warning.
        "lto": AgencyPermit.overview(c.LTO),
    }
    return render(request, "guards/dashboard.html", context)


@access_required("guards.view_all_guards")
def guard_list(request):
    """Current guards by default. The "show" filter lists the guards who left instead."""
    query = request.GET.get("q", "").strip()
    readiness = request.GET.get("status", "")
    show = request.GET.get("show", c.SHOW_CURRENT)
    guards = filter_by_readiness(filter_by_employment(search_guards(query), show), readiness)
    context = {
        "guards": guards,
        "query": query,
        "readiness": readiness,
        "levels": c.READINESS_LEVELS,
        "show": show,
        "show_options": c.EMPLOYMENT_FILTERS,
    }
    return render(request, "guards/guard_list.html", context)


# ---------------------------------------------------------------------------
# Add Guard and Edit Guard
# ---------------------------------------------------------------------------


@access_required("guards.add_guard")
def add_guard(request):
    """
    The full Add Guard page: basic details, personal details, government
    numbers, and the 6 documents, saved together in one transaction.
    A refused save is logged too, with the reasons but never the values.
    """
    page = AddGuardForms(request.POST or None)
    if request.method == "POST":
        if page.is_valid():
            guard = save_new_guard(request, page)
            on_file = len(page.filled_documents())
            messages.success(
                request,
                f"{guard.full_name} was added with {on_file} of "
                f"{len(c.REQUIRED_DOCUMENTS)} documents on file. "
                f"Readiness: {guard.readiness()}.",
            )
            return redirect("guard_profile", pk=guard.pk)

        log_event(
            request,
            AuditEntry.CREATE,
            "Guard",
            "",
            outcome=AuditEntry.DENIED,
            sensitive=page.has_sensitive_fields(),
            details=f"Refused, nothing was saved. {page.problems()}",
        )
    return render(request, "guards/guard_form.html", {"page": page})


def editable_guard(request, pk):
    """The guard from the URL, checked on the object itself (Zero Trust)."""
    guard = get_object_or_404(Guard, pk=pk)
    if not can_view_guard(request.user, guard):
        deny(request, "You cannot open this guard's records.", "Guard", guard.pk)
    return guard


@access_required("guards.change_guard")
def edit_guard(request, pk):
    """Edit the basic details. None of them is sensitive, so no step-up is needed."""
    guard = editable_guard(request, pk)
    mark_target(request, "Guard", guard.pk)
    title = guard.summary()  # read before the form puts new values on the guard

    form = GuardBasicForm(request.POST or None, instance=guard)
    if request.method == "POST":
        if form.is_valid():
            summary = save_guard_edit(request, guard, [form], "basic details")
            report_saved(request, summary)
            return redirect("guard_profile", pk=guard.pk)
        log_refused_edit(request, guard, [form])

    context = {
        "guard_pk": guard.pk,
        "title": title,
        "form": form,
        "unlocked": is_unlocked(request, guard),
        "can_unlock": can_step_up(request.user, guard),
    }
    return render(request, "guards/guard_edit.html", context)


@access_required("guards.change_guard")
def edit_guard_sensitive(request, pk):
    """
    Edit the personal details and government numbers. They are sensitive, so
    the page opens only while step-up is active for this guard. Without it,
    deny_until_step_up() refuses (logged as DENY) and offers the step-up link.
    """
    guard = editable_guard(request, pk)
    if not is_unlocked(request, guard):
        deny_until_step_up(request, guard)
    # The form shows the current values, so this page view is a sensitive one.
    mark_target(request, "Guard", guard.pk, sensitive=True)
    title = guard.summary()

    data = request.POST or None
    forms = [
        GuardPersonalForm(data, instance=guard, prefix="personal"),
        GuardGovernmentForm(data, instance=guard, prefix="government"),
    ]
    if request.method == "POST":
        if all([form.is_valid() for form in forms]):
            summary = save_guard_edit(request, guard, forms, "personal and government details")
            report_saved(request, summary)
            return redirect("guard_profile", pk=guard.pk)
        log_refused_edit(request, guard, forms)

    left = seconds_left(request, guard)
    context = {
        "guard_pk": guard.pk,
        "title": title,
        "forms": forms,
        "seconds_left": left,
        "locks_at": timezone.localtime() + timedelta(seconds=left),
    }
    return render(request, "guards/guard_edit_sensitive.html", context)


def report_saved(request, summary):
    """A success message with the changed field names only, never the values."""
    if summary:
        messages.success(request, f"Saved. Changed: {', '.join(summary.labels)}.")
    else:
        messages.info(request, "Nothing was changed, so nothing was saved.")


def log_refused_edit(request, guard, forms):
    """A refused edit is logged with the reasons. Error messages never repeat a value."""
    problems = " ".join(form.problems() for form in forms if form.problems())
    log_event(
        request,
        AuditEntry.UPDATE,
        "Guard",
        guard.pk,
        outcome=AuditEntry.DENIED,
        sensitive=any(form.has_sensitive_fields() for form in forms),
        details=f"Refused, nothing was saved. {problems}",
    )


# ---------------------------------------------------------------------------
# Employment status
# ---------------------------------------------------------------------------


@access_required("guards.change_guard")
def change_status(request, pk):
    """
    Change a guard's employment status. Same permission as Edit Guard. The
    form lists only the statuses his current status allows.
    """
    guard = editable_guard(request, pk)
    mark_target(request, "Guard", guard.pk)

    form = StatusChangeForm(guard, request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            new, effects = save_status_change(request, guard, form)
            extra = "".join(f" {effect}." for effect in effects)
            messages.success(request, f"{guard.full_name} is now {new}.{extra}")
            return redirect("guard_profile", pk=guard.pk)
        log_event(
            request,
            AuditEntry.UPDATE,
            "Guard",
            guard.pk,
            outcome=AuditEntry.DENIED,
            details=f"Status change refused, nothing was saved. {form.problems()}",
        )

    context = {
        "guard": guard,
        "current": guard.employment_status(),
        "history": guard.status_history(),
        "form": form,
    }
    return render(request, "guards/status_form.html", context)


# ---------------------------------------------------------------------------
# Documents: Add, and Renew or correct
# ---------------------------------------------------------------------------


def document_page(request, pk, doc):
    """The guard and the document name from the URL. An unknown document is a 404."""
    guard = editable_guard(request, pk)
    doc_type = c.DOCUMENT_SLUGS.get(doc)
    if doc_type is None:
        raise Http404("There is no required document with that name.")
    return guard, doc_type


@access_required("guards.manage_credentials")
def add_document(request, pk, doc):
    """
    Put a missing document on file. The result field of a medical exam shows
    only while step-up is active, because it is sensitive.
    """
    guard, doc_type = document_page(request, pk, doc)
    if guard.get_credential(doc_type) is not None:
        messages.info(request, f"{doc_type} is already on file. Renew or correct it instead.")
        return redirect("renew_document", pk=guard.pk, doc=doc)
    mark_target(request, "Guard", guard.pk)

    unlocked = is_unlocked(request, guard)
    sample = Credential.for_document(doc_type)
    form_class = add_form_class(sample, show_result=unlocked)
    form = form_class(request.POST or None, doc_type=doc_type)
    if request.method == "POST":
        if form.is_valid():
            save_new_document(request, guard, form)
            messages.success(request, f"{doc_type} is now on file. Readiness: {guard.readiness()}.")
            return redirect("guard_profile", pk=guard.pk)
        log_event(
            request,
            AuditEntry.CREATE,
            "Guard",
            guard.pk,
            outcome=AuditEntry.DENIED,
            sensitive=form.has_sensitive_fields(),
            details=f"Refused, nothing was saved. {form.problems()}",
        )

    context = {
        "guard": guard,
        "form": form,
        "result_hidden": sample.uses_result() and not unlocked,
        "can_unlock": can_step_up(request.user, guard),
    }
    return render(request, "guards/document_add.html", context)


@access_required("guards.manage_credentials")
def renew_document(request, pk, doc):
    """
    Renew or correct a document on file. It always goes through renew(), so
    the old values are saved in the history first. There is no delete.
    """
    guard, doc_type = document_page(request, pk, doc)
    credential = guard.get_credential(doc_type)
    if credential is None:
        messages.info(request, f"{doc_type} is not on file yet. Add it first.")
        return redirect("add_document", pk=guard.pk, doc=doc)

    unlocked = is_unlocked(request, guard)
    shows_result = credential.uses_result() and unlocked
    # With step-up, the form shows the current result, so the view is sensitive.
    mark_target(request, "Credential", credential.pk, sensitive=shows_result)

    form_class = renew_form_class(credential, show_result=unlocked)
    form = form_class(request.POST or None, credential=credential)
    if request.method == "POST":
        if form.is_valid():
            save_renewal(request, credential, form)
            messages.success(request, f"{doc_type} was saved. The old values are kept in the history.")
            return redirect("guard_profile", pk=guard.pk)
        log_event(
            request,
            AuditEntry.UPDATE,
            "Credential",
            credential.pk,
            outcome=AuditEntry.DENIED,
            sensitive=form.has_sensitive_fields(),
            details=f"Refused, nothing was saved. {form.problems()}",
        )

    context = {
        "guard": guard,
        "credential": credential,
        "form": form,
        "validity_months": credential.validity_months(),
        "result_hidden": credential.uses_result() and not unlocked,
        "can_unlock": can_step_up(request.user, guard),
    }
    return render(request, "guards/document_renew.html", context)


# ---------------------------------------------------------------------------
# Agency permits: the agency's own papers, like its License to Operate
# ---------------------------------------------------------------------------


def kind_from_slug(slug):
    """The permit kind from the URL, like "lto". An unknown permit is a 404."""
    kind = c.PERMIT_SLUGS.get(slug)
    if kind is None:
        raise Http404("There is no agency permit with that name.")
    return kind


@access_required("guards.manage_credentials")
def agency_permits(request):
    """One row per kind of permit, with Add or Renew or correct, and the change history."""
    mark_target(request, "AgencyPermit", "all")
    context = {
        "permits": [AgencyPermit.overview(kind) for kind in PERMIT_TYPES],
        "versions": AgencyPermitVersion.objects.select_related("permit", "changed_by"),
    }
    return render(request, "guards/agency_permits.html", context)


@access_required("guards.manage_credentials")
def add_permit(request, kind):
    """Put a missing permit on file. HR types every value from the permit, even the expiry date."""
    permit_kind = kind_from_slug(kind)
    sample = AgencyPermit.for_kind(permit_kind)
    if AgencyPermit.on_file(permit_kind) is not None:
        messages.info(request, f"{sample.name()} is already on file. Renew or correct it instead.")
        return redirect("renew_permit", kind=kind)
    mark_target(request, "AgencyPermit", permit_kind)

    form = PermitForm(request.POST or None, permit=sample)
    if request.method == "POST":
        if form.is_valid():
            permit = save_new_permit(request, permit_kind, form)
            messages.success(
                request, f"{permit.name()} is now on file. It is {permit.expiry_text()}."
            )
            return redirect("agency_permits")
        log_event(
            request,
            AuditEntry.CREATE,
            "AgencyPermit",
            permit_kind,
            outcome=AuditEntry.DENIED,
            details=f"Refused, nothing was saved. {form.problems()}",
        )
    return render(request, "guards/permit_add.html", {"form": form})


@access_required("guards.manage_credentials")
def renew_permit(request, kind):
    """
    Renew or correct a permit on file. It always goes through renew(), so the
    old values are saved in the history first. There is no delete.
    """
    permit_kind = kind_from_slug(kind)
    permit = AgencyPermit.on_file(permit_kind)
    if permit is None:
        name = AgencyPermit.for_kind(permit_kind).name()
        messages.info(request, f"{name} is not on file yet. Add it first.")
        return redirect("add_permit", kind=kind)
    mark_target(request, "AgencyPermit", permit.pk)

    form = RenewPermitForm(request.POST or None, permit=permit)
    if request.method == "POST":
        if form.is_valid():
            save_permit_renewal(request, permit, form)
            messages.success(
                request,
                f"{permit.name()} was saved. It is {permit.expiry_text()}. "
                "The old values are kept in the history.",
            )
            return redirect("agency_permits")
        log_event(
            request,
            AuditEntry.UPDATE,
            "AgencyPermit",
            permit.pk,
            outcome=AuditEntry.DENIED,
            details=f"Refused, nothing was saved. {form.problems()}",
        )
    return render(request, "guards/permit_renew.html", {"form": form, "permit": permit})


# ---------------------------------------------------------------------------
# My record and the guard profile
# ---------------------------------------------------------------------------


@access_required("guards.view_own_record")
def my_record(request):
    """The guard's menu link. Sends him to his own profile."""
    guard = own_guard(request.user)
    if guard is None:
        deny(request, "No guard record is linked to this account.")
    return redirect("guard_profile", pk=guard.pk)


@access_required("guards.view_all_guards", "guards.view_own_record")
def guard_profile(request, pk):
    guard = get_object_or_404(
        Guard.objects.prefetch_related("credentials", "status_changes__recorded_by"), pk=pk
    )
    # Zero Trust: checked on the object itself, not just hidden from the menu.
    if not can_view_guard(request.user, guard):
        deny(request, "A guard can only open his own records.", "Guard", guard.pk)

    unlocked = is_unlocked(request, guard)
    mark_target(request, "Guard", guard.pk, sensitive=unlocked)

    left = seconds_left(request, guard) if unlocked else 0
    context = {
        "guard": guard,
        "employment": guard.employment_status(),
        "status_history": guard.status_history(),
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
