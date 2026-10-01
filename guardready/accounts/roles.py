"""
Roles and their permissions.

Each role is a Django Group. This dictionary is the only place that decides
what a role can do. seed_demo creates the groups from it.
"""

ADMIN = "Admin/HR"
COMMANDER = "Detachment Commander"
GUARD = "Guard"

ROLE_PERMISSIONS = {
    ADMIN: [
        "guards.view_dashboard",
        "guards.view_all_guards",
        "guards.step_up_sensitive",
        "guards.manage_credentials",
        "deployment.assign_guard",
        "reports.record_performance",
        "reports.view_summary_report",
        "audit.view_audit_log",
    ],
    COMMANDER: [
        "guards.view_dashboard",
        "guards.view_all_guards",
        "deployment.assign_guard",
        "reports.record_performance",
        "reports.view_summary_report",
    ],
    GUARD: [
        "guards.view_own_record",
        "guards.step_up_sensitive",
    ],
}


def role_name(user):
    """The role shown in the navbar and stored in every audit entry."""
    if not user.is_authenticated:
        return "Anonymous"
    if user.is_superuser:
        return "Superuser"
    group = user.groups.first()
    if group is None:
        return "No role"
    return group.name
