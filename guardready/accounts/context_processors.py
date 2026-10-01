"""Adds the role name and the role's menu to every page."""

from django.conf import settings
from django.urls import reverse

from .roles import role_name

# Each menu item: (label, URL name, permissions that show it).
# An item shows only if the user has at least one of its permissions,
# so every role gets its own menu without any if/else on the role.
MENU_ITEMS = [
    ("Dashboard", "dashboard", ["guards.view_dashboard"]),
    ("Guards", "guard_list", ["guards.view_all_guards"]),
    ("My record", "my_record", ["guards.view_own_record"]),
    ("Audit log", "audit_log", ["audit.view_audit_log"]),
]


def navigation(request):
    user = request.user
    if not user.is_authenticated:
        return {}

    menu = []
    for label, url_name, permissions in MENU_ITEMS:
        if any(user.has_perm(p) for p in permissions):
            url = reverse(url_name)
            menu.append({"label": label, "url": url, "active": request.path.startswith(url)})

    return {
        "menu": menu,
        "role_name": role_name(user),
        "idle_timeout_seconds": settings.IDLE_TIMEOUT_SECONDS,
    }
