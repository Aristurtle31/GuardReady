from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("guards/", views.guard_list, name="guard_list"),
    path("guards/me/", views.my_record, name="my_record"),
    path("guards/<int:pk>/", views.guard_profile, name="guard_profile"),
]
