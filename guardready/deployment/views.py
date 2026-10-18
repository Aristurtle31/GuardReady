"""
Sites, posts, and the assign screen. Admin/HR only (the assign_guard permission).

Views only check access, call services and model methods, and render a
template. Post.refusal_reasons() decides who can be posted, and
deployment/services.py writes the audit entries.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import access_required
from audit.models import AuditEntry, RecordLockedError
from audit.services import log_event, mark_target
from guards import constants as gc

from .forms import AssignGuardForm
from .models import Assignment, ClientSite, Post
from .services import assign_guard, close_posting, guard_choices

# Admin/HR has it. The guard role does not.
ASSIGN_PERMISSION = "deployment.assign_guard"


@access_required(ASSIGN_PERMISSION)
def site_list(request):
    """Every client site with its posts, and how many guards each post has and needs."""
    mark_target(request, "ClientSite", "all")
    context = {"sites": ClientSite.objects.prefetch_related("posts")}
    return render(request, "deployment/site_list.html", context)


@access_required(ASSIGN_PERMISSION)
def post_detail(request, pk):
    """One post: who is posted there now (with End posting), and who was posted before."""
    post = get_object_or_404(Post.objects.select_related("site"), pk=pk)
    mark_target(request, "Post", post.pk)
    details = ("guard", "assigned_by")
    context = {
        "post": post,
        "current": post.active_assignments().select_related(*details),
        "past": post.past_assignments().select_related(*details),
    }
    return render(request, "deployment/post_detail.html", context)


@access_required(ASSIGN_PERMISSION)
def assign_to_post(request, pk):
    """
    Pick a guard for this post. Current guards are listed by default, and the
    "show" filter lists the guards who left. assign_guard() decides and logs
    every attempt. A refused one is shown with its reasons. There is no override.
    """
    post = get_object_or_404(Post.objects.select_related("site"), pk=pk)
    mark_target(request, "Post", post.pk)
    data = request.POST if request.method == "POST" else request.GET
    show = data.get("show", gc.SHOW_CURRENT)

    form = AssignGuardForm(request.POST or None)
    chosen, reasons = None, []
    if request.method == "POST":
        if form.is_valid():
            chosen = form.cleaned_data["guard"]
            assignment, reasons = assign_guard(request, chosen, post)
            if assignment is not None:
                messages.success(
                    request,
                    f"{chosen.full_name} is now posted at {post}, starting today. "
                    f"Readiness: {chosen.readiness()}.",
                )
                return redirect("post_detail", pk=post.pk)
        else:
            log_event(
                request,
                AuditEntry.ASSIGN,
                "Post",
                post.pk,
                outcome=AuditEntry.DENIED,
                details=f"Refused, nothing was saved. {form.problems()}",
            )

    context = {
        "post": post,
        "form": form,
        "rows": guard_choices(post, show),
        "chosen": chosen,
        "reasons": reasons,
        "show": show,
        "show_options": gc.EMPLOYMENT_FILTERS,
        "today": timezone.localdate(),
    }
    return render(request, "deployment/assign.html", context)


@access_required(ASSIGN_PERMISSION)
@require_POST
def end_posting(request, pk):
    """End a posting today through Assignment.close(). POST only, and it works only once."""
    posting = get_object_or_404(Assignment.objects.select_related("guard", "post__site"), pk=pk)
    try:
        close_posting(request, posting)
        messages.success(
            request, f"The posting of {posting.guard.full_name} at {posting.post} ended today."
        )
    except RecordLockedError as error:
        log_event(
            request,
            AuditEntry.UPDATE,
            "Assignment",
            posting.pk,
            outcome=AuditEntry.DENIED,
            details=f"Refused, nothing was changed. {error}",
        )
        messages.info(request, str(error))
    return redirect("post_detail", pk=posting.post_id)
