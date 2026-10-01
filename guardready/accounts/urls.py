from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("step-up/<int:guard_id>/", views.step_up, name="step_up"),
]
