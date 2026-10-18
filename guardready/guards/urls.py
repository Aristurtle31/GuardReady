from django.urls import path

from . import views

# There is no delete URL for a guard, a document or an agency permit, on
# purpose. A guard's history, attendance, evaluations and audit trail must stay.
urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("guards/", views.guard_list, name="guard_list"),
    path("guards/new/", views.add_guard, name="add_guard"),
    path("guards/me/", views.my_record, name="my_record"),
    path("guards/<int:pk>/", views.guard_profile, name="guard_profile"),
    path("guards/<int:pk>/history/", views.guard_history, name="guard_history"),
    path("guards/<int:pk>/edit/", views.edit_guard, name="edit_guard"),
    path("guards/<int:pk>/status/", views.change_status, name="change_status"),
    path(
        "guards/<int:pk>/edit/sensitive/",
        views.edit_guard_sensitive,
        name="edit_guard_sensitive",
    ),
    path(
        "guards/<int:pk>/documents/<slug:doc>/add/",
        views.add_document,
        name="add_document",
    ),
    path(
        "guards/<int:pk>/documents/<slug:doc>/renew/",
        views.renew_document,
        name="renew_document",
    ),
    # The agency's own permits. kind is a PERMIT_SLUGS key like "lto".
    path("agency/permits/", views.agency_permits, name="agency_permits"),
    path("agency/permits/<slug:kind>/add/", views.add_permit, name="add_permit"),
    path("agency/permits/<slug:kind>/renew/", views.renew_permit, name="renew_permit"),
    # Expiry notices. kind is a NOTICE_TYPES key: "guard" or "agency".
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/seen/", views.all_notices_seen, name="all_notices_seen"),
    path("notifications/<slug:kind>/<int:pk>/seen/", views.notice_seen, name="notice_seen"),
]
