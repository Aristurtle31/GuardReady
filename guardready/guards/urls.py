from django.urls import path

from . import views

# There is no delete URL for a guard or a document, on purpose. A guard's
# history, attendance, evaluations and audit trail must stay.
urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("guards/", views.guard_list, name="guard_list"),
    path("guards/new/", views.add_guard, name="add_guard"),
    path("guards/me/", views.my_record, name="my_record"),
    path("guards/<int:pk>/", views.guard_profile, name="guard_profile"),
    path("guards/<int:pk>/edit/", views.edit_guard, name="edit_guard"),
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
]
