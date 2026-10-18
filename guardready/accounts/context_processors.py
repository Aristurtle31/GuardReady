"""Adds the role name and the role's menu to every page."""

from django.conf import settings
from django.urls import reverse

from guards.services import unread_notice_count

from .roles import role_name


def no_count():
    """Most menu items show no number."""
    return 0


# Each menu item: (label, URL name, permissions that show it, the number it shows).
# An item shows only if the user has at least one of its permissions,
# so every role gets its own menu without any if/else on the role.
MENU_ITEMS = [
    ("Dashboard", "dashboard", ["guards.view_dashboard"], no_count),
    ("Guards", "guard_list", ["guards.view_all_guards"], no_count),
    # Stage 3: client sites, their posts, and the assign screen.
    ("Sites", "site_list", ["deployment.assign_guard"], no_count),
    # Stage 4: punctuality, guard type and character evaluation of every guard.
    ("Guard reports", "summary_report", ["reports.view_summary_report"], no_count),
    ("Agency permits", "agency_permits", ["guards.manage_credentials"], no_count),
    # Stage 2: the number of new (unread) expiry notices.
    ("Notifications", "notifications", ["guards.manage_credentials"], unread_notice_count),
    ("My record", "my_record", ["guards.view_own_record"], no_count),
    ("Audit log", "audit_log", ["audit.view_audit_log"], no_count),
]


def navigation(request):
    user = request.user
    if not user.is_authenticated:
        return {}

    menu = []
    for label, url_name, permissions, count in MENU_ITEMS:
        if any(user.has_perm(p) for p in permissions):
            url = reverse(url_name)
            menu.append(
                {
                    "label": label,
                    "url": url,
                    "active": request.path.startswith(url),
                    "count": count(),
                }
            )

    return {
        "menu": menu,
        "role_name": role_name(user),
        "idle_timeout_seconds": settings.IDLE_TIMEOUT_SECONDS,
    }
