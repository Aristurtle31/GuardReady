"""
Zero Trust access checks.

Every view is wrapped in @access_required. The check runs on every request,
so a role change takes effect on the very next click.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def deny(request, reason, target_type="", target_id=""):
    """
    Refuse the request. The note on the request tells the audit middleware
    why it was refused. Django turns PermissionDenied into the 403 page.
    """
    request.deny_reason = reason
    if target_type:
        request.audit_target = (target_type, str(target_id))
    raise PermissionDenied(reason)


def access_required(*permissions):
    """
    Decorator for every view.
    1. The user must be logged in.
    2. If permissions are listed, the user must have at least one of them.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                request.deny_reason = "Not logged in"
                return redirect_to_login(request.get_full_path())
            if permissions and not any(request.user.has_perm(p) for p in permissions):
                deny(request, "Your role is missing the permission: " + " or ".join(permissions))
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def own_guard(user):
    """The Guard record linked to this login, or None."""
    return getattr(user, "guard_profile", None)


def can_view_guard(user, guard):
    """Checked on the guard object itself. A guard can see only his own record."""
    if user.has_perm("guards.view_all_guards"):
        return True
    return user.has_perm("guards.view_own_record") and guard.user_id == user.id


def can_step_up(user, guard):
    """Who may unlock this guard's sensitive data. Commanders never can."""
    if not user.has_perm("guards.step_up_sensitive"):
        return False
    return can_view_guard(user, guard)
